"""Background work for conversations: summaries, openers, titles, embeddings.

All of it is Sonnet 5 work (plan §6.2) — cheap, thinking off, and none of it on
the path of a person waiting for a reply. Each handler is thin: load, call one
model, write. The decisions about *whether* to run live in
``knori.services.summaries`` so they can be tested without a model.

``write_opener`` is also called inline by ``POST /conversations``: a returning
user should see the first line immediately, not after a queue round-trip. It is
the same function either way, so the words never depend on how it was invoked.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.core.config import settings
from knori.core.logging import get_logger
from knori.db.models import User, UserSettings
from knori.jobs import queue
from knori.jobs.registry import JobContext, job
from knori.services import chat as chat_service
from knori.services import summaries
from ros.llm.base import ProviderError
from ros.llm.router import Router, build_router
from ros.persistence import repositories
from ros.persistence.models import EMBEDDING_DIM
from ros.schemas.llm_io import ChatTitle, ConversationSummary

log = get_logger("knori.jobs.chat")

SUMMARIZE_JOB = "summarize_conversation"
OPENER_JOB = "generate_opener"
TITLE_JOB = "generate_title"
EMBED_JOB = "embed_pending"

#: plan §6.2 — the embedding route's batch size. One call, 64 texts.
EMBED_BATCH = 64
EMBED_PER_RUN = 512
OPENER_MAX_WORDS = 120

_router: Router | None = None


def get_router() -> Router:
    """One router per process, built from the product's settings so ``.env`` counts."""
    global _router
    if _router is None:
        _router = build_router(settings, clock=now)
    return _router


# ------------------------------------------------------------------- summaries


async def write_summary(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    router: Router,
    job_id: uuid.UUID | None = None,
) -> str | None:
    """Summarise a conversation and move ``summary_upto_seq``. Returns the summary."""
    conversation = await repositories.get_conversation(session, user_id, conversation_id)
    if conversation is None or conversation.is_incognito:
        return None
    decision = summaries.decide_for(conversation, at=now())
    if not decision:
        log.info("chat.summary_skipped", reason=decision.reason)
        return None

    messages = await summaries.messages_to_summarise(
        session, user_id, conversation_id, after_seq=conversation.summary_upto_seq
    )
    if not messages:
        return None

    result = await router.run(
        "summarize.conversation",
        prompt="summarize/conversation",
        vars={
            "messages": messages,
            "previous_summary": conversation.summary or "",
            "user_name": await _user_name(session, user_id),
        },
        schema=ConversationSummary,
        user_id=user_id,
        job_id=job_id,
        session=session,
    )
    parsed = result.parsed
    if not isinstance(parsed, ConversationSummary) or not parsed.summary.strip():
        return None

    await summaries.apply_summary(
        session,
        user_id,
        conversation_id,
        summary=parsed.summary,
        open_threads=list(parsed.open_threads),
        upto_seq=conversation.last_seq,
    )
    return parsed.summary


@job(SUMMARIZE_JOB, lane="fast", timeout_seconds=300.0, priority=6)
async def summarize_conversation(ctx: JobContext) -> dict[str, Any]:
    conversation_id = ctx.require_uuid("conversation_id")
    user_id = ctx.require_user_id()
    async with ctx.session_factory() as session:
        summary = await write_summary(
            session, user_id, conversation_id, router=get_router(), job_id=ctx.job_id
        )
        await session.commit()
    return {"summarised": summary is not None}


@job("idle_conversation_check", lane="fast", priority=8)
async def idle_conversation_check(ctx: JobContext) -> dict[str, Any]:
    """Every 5 minutes: queue a summary for each conversation that has gone quiet."""
    async with ctx.session_factory() as session:
        ids = await summaries.find_idle_conversations(session, at=now())
        queued = 0
        for conversation_id in ids:
            owner = await session.scalar(
                text("SELECT user_id FROM conversations WHERE id = :id"), {"id": conversation_id}
            )
            if owner is None:
                continue
            created = await queue.enqueue(
                session,
                SUMMARIZE_JOB,
                {"conversation_id": str(conversation_id)},
                lane="fast",
                user_id=owner,
                priority=6,
                dedupe_key=queue.dedupe_key_for(SUMMARIZE_JOB, conversation_id),
            )
            queued += 1 if created is not None else 0
        await session.commit()
    return {"idle": len(ids), "queued": queued}


# --------------------------------------------------------------------- opener


async def write_opener(
    session: AsyncSession,
    user: User,
    conversation_id: uuid.UUID,
    *,
    router: Router,
    job_id: uuid.UUID | None = None,
) -> str | None:
    """KnoRI's first line of a returning visit (plan §5.5).

    Returns ``None`` — and writes nothing — when there is no record of a previous
    visit or the model call fails. A missing opener is a blank thread; a made-up
    one is a lie about remembering.
    """
    conversation = await repositories.get_conversation(session, user.id, conversation_id)
    if conversation is None or conversation.is_incognito or conversation.last_seq > 0:
        return None

    previous = await repositories.latest_conversation(session, user.id, exclude_id=conversation_id)
    welcome = await summaries.welcome_back(session, user.id, since=None)
    if welcome.days_since_last_visit is None:
        return None

    settings_row = await session.get(UserSettings, user.id)
    result = await router.run(
        "chat.opener",
        prompt="chat/opener",
        vars={
            "user_name": user.preferred_name or user.display_name,
            "chat_style": settings_row.chat_style if settings_row else "warm",
            "days_away": summaries.days_away_phrase(welcome.days_since_last_visit),
            "last_summary": (previous.summary or "") if previous else "",
            "open_threads": list(previous.open_threads) if previous else [],
            "new_recognitions_count": welcome.new_recognitions,
        },
        user_id=user.id,
        job_id=job_id,
        session=session,
    )
    line = " ".join(result.text.split())
    if not line:
        return None

    locked = await chat_service.lock_conversation(session, user.id, conversation_id)
    await chat_service.append_message(session, locked, role="assistant", content=line)
    return line


@job(OPENER_JOB, lane="fast", timeout_seconds=120.0, priority=5)
async def generate_opener(ctx: JobContext) -> dict[str, Any]:
    conversation_id = ctx.require_uuid("conversation_id")
    async with ctx.session_factory() as session:
        user = await session.get(User, ctx.require_user_id())
        if user is None:
            return {"skipped": "no_user"}
        line = await write_opener(
            session, user, conversation_id, router=get_router(), job_id=ctx.job_id
        )
        await session.commit()
    return {"opener": bool(line)}


# ---------------------------------------------------------------------- title


@job(TITLE_JOB, lane="fast", timeout_seconds=120.0, priority=7)
async def generate_title(ctx: JobContext) -> dict[str, Any]:
    """Name a conversation so it can be found again months later."""
    conversation_id = ctx.require_uuid("conversation_id")
    user_id = ctx.require_user_id()
    async with ctx.session_factory() as session:
        conversation = await repositories.get_conversation(session, user_id, conversation_id)
        if conversation is None or conversation.title:
            return {"skipped": "already_named"}
        messages = await summaries.messages_to_summarise(
            session, user_id, conversation_id, after_seq=0, limit=20
        )
        if len(messages) < 2:
            return {"skipped": "too_short"}

        result = await get_router().run(
            "chat.title",
            prompt="chat/title",
            vars={"messages": messages},
            schema=ChatTitle,
            user_id=user_id,
            job_id=ctx.job_id,
            session=session,
        )
        parsed = result.parsed
        title = " ".join(parsed.title.split())[:120] if isinstance(parsed, ChatTitle) else ""
        if title:
            await session.execute(
                text("UPDATE conversations SET title = :title WHERE id = :id AND user_id = :user"),
                {"title": title, "id": conversation_id, "user": user_id},
            )
        await session.commit()
    return {"title": title}


# ----------------------------------------------------------------- embeddings


@job(EMBED_JOB, lane="fast", timeout_seconds=300.0, priority=7)
async def embed_pending(ctx: JobContext) -> dict[str, Any]:
    """Fill in missing vectors, in batches of 64.

    The chat route embeds the current message itself so retrieval is live from
    the first turn; this catches everything else — a message whose embedding call
    timed out, a memory the user typed, an assertion a correction created.
    """
    router = get_router()
    counts: dict[str, int] = {}
    async with ctx.session_factory() as session:
        for table, column, extra in (
            ("messages", "content", "role = 'user' AND status <> 'failed'"),
            ("memory_items", "statement", "status = 'active'"),
            ("user_assertions", "statement", "status = 'active'"),
        ):
            counts[table] = await _embed_table(
                session, router, table, column, extra, user_id=ctx.user_id, job_id=ctx.job_id
            )
        await session.commit()
    return counts


async def _embed_table(
    session: AsyncSession,
    router: Router,
    table: str,
    column: str,
    extra: str,
    *,
    user_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
) -> int:
    clauses = [f"{column} <> ''", "embedding IS NULL", extra]
    params: dict[str, Any] = {"limit": EMBED_PER_RUN}
    if user_id is not None:
        clauses.append("user_id = :user_id")
        params["user_id"] = user_id
    rows = (
        await session.execute(
            text(
                f"SELECT id, {column} AS body FROM {table} WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at ASC LIMIT :limit"
            ),
            params,
        )
    ).all()
    if not rows:
        return 0

    model = router.embedder.model_id
    written = 0
    for start in range(0, len(rows), EMBED_BATCH):
        batch = rows[start : start + EMBED_BATCH]
        try:
            vectors = await router.embed(
                [row.body for row in batch], user_id=user_id, job_id=job_id, session=session
            )
        except ProviderError as exc:
            log.warning("chat.embed_batch_failed", table=table, error=str(exc))
            break
        written += await _write_vectors(session, table, batch, vectors, model)
    return written


async def _write_vectors(
    session: AsyncSession,
    table: str,
    rows: Sequence[Any],
    vectors: Sequence[Sequence[float]],
    model: str,
) -> int:
    statement = text(
        f"UPDATE {table} SET embedding = :embedding, embedding_model = :model WHERE id = :id"
    ).bindparams(bindparam("embedding", type_=Vector(EMBEDDING_DIM)))
    written = 0
    for row, vector in zip(rows, vectors, strict=False):
        await session.execute(statement, {"embedding": list(vector), "model": model, "id": row.id})
        written += 1
    return written


async def _user_name(session: AsyncSession, user_id: uuid.UUID) -> str:
    user = await session.get(User, user_id)
    if user is None:
        return "them"
    return user.preferred_name or user.display_name


__all__ = [
    "EMBED_BATCH",
    "EMBED_JOB",
    "OPENER_JOB",
    "SUMMARIZE_JOB",
    "TITLE_JOB",
    "embed_pending",
    "generate_opener",
    "generate_title",
    "idle_conversation_check",
    "summarize_conversation",
    "write_opener",
    "write_summary",
]
