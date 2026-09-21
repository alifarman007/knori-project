"""Everything the chat prompt needs, loaded from the database.

Kept apart from ``knori.services.chat`` so the turn itself reads as one story and
this reads as one list. The split matters in practice: the builder in
``ros.memory.context_builder`` is pure and this is the only place that decides
*what* to give it, so a change to retrieval never touches streaming.

Retrieval degrades rather than fails. If the query embedding does not come back
in two seconds the previous message's vector is used, and if there is none the
user still gets their pinned memories — a slow embedding must never cost someone
their reply (plan §5.4).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now, today_in
from knori.core.logging import get_logger
from knori.db.models import Conversation, User, UserSettings
from ros.engine.types import SimilarityCutoffs, load_thresholds
from ros.llm.base import Effort, ProviderError
from ros.llm.cost import spent_today
from ros.llm.router import Router
from ros.memory.context_builder import (
    AssertionLine,
    ChatContextInputs,
    ContextLimits,
    HistoryMessage,
    RecognitionRef,
    make_estimator,
)
from ros.memory.selection import Candidate, SectionBudget
from ros.memory.selection import select as select_candidates
from ros.persistence import repositories
from ros.persistence.models import EMBEDDING_DIM
from ros.persistence.pg_memory import PgRetriever

log = get_logger("knori.chat.context")

HISTORY_WINDOW = 60
#: The query embedding is on the critical path, so it gets one short try.
EMBED_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class SpendDecision:
    """What today's spend means for this turn (plan §6.6)."""

    blocked: bool = False
    effort: Effort | None = None


# ------------------------------------------------------------------- the context


async def load_context_inputs(
    session: AsyncSession,
    user: User,
    conversation: Conversation,
    *,
    content: str,
    router: Router,
    limits: ContextLimits,
    model: str | None,
    message_id: uuid.UUID | None = None,
) -> ChatContextInputs:
    """Gather everything the builder needs. All of it filtered by ``user_id``."""
    estimate = make_estimator(model)
    profile = await repositories.latest_profile(session, user.id)
    cards = await repositories.list_open_recognitions(session, user.id, limit=10)
    assertions = await repositories.list_active_assertions(session, user.id, limit=50)
    history = await repositories.list_messages(
        session, user.id, conversation.id, limit=HISTORY_WINDOW, include_failed=False
    )

    embedding = await _query_embedding(session, user.id, content, router)
    if embedding is not None and message_id is not None and not conversation.is_incognito:
        await _store_embedding(session, message_id, embedding, router.embedder.model_id)
    memory_hits, message_hits = await _retrieve(
        session, user.id, conversation.id, embedding, limits=limits
    )
    memory = select_candidates(
        memory_hits,
        now=now(),
        budget=SectionBudget("memory", limits.memory_tokens, limits.max_memory_items, True),
        tokens=estimate,
    )
    past = select_candidates(
        message_hits,
        now=now(),
        budget=SectionBudget("past_messages", limits.past_message_tokens, limits.max_past_messages),
        tokens=estimate,
    )
    settings = await session.get(UserSettings, user.id)
    return ChatContextInputs(
        user_name=user.preferred_name or user.display_name,
        current_message=content,
        today=today_in(user.timezone),
        chat_style=settings.chat_style if settings else "warm",
        profile_text=profile.profile_text if profile else "",
        profile_version=profile.version if profile else None,
        open_recognitions=tuple(
            RecognitionRef(
                id=card.id, title=card.title, label=card.confidence_label, state=card.state
            )
            for card in cards
        ),
        assertions=tuple(AssertionLine(id=row.id, statement=row.statement) for row in assertions),
        summary=conversation.summary,
        summary_upto_seq=conversation.summary_upto_seq,
        history=tuple(
            HistoryMessage(
                seq=row.seq, role=row.role, content=row.content, status=row.status, id=row.id
            )
            for row in history
        ),
        memory=memory,
        past_messages=past,
        days_since_last_visit=await _days_since_last_visit(session, user.id, conversation.id),
        model=model,
    )


async def _query_embedding(
    session: AsyncSession, user_id: uuid.UUID, content: str, router: Router
) -> list[float] | None:
    """One short attempt; then the previous message's vector; then nothing.

    Retrieval failing must never cost the user their reply, so this degrades
    instead of raising: without a vector they get their pinned memories only.
    """
    try:
        async with asyncio.timeout(EMBED_TIMEOUT_SECONDS):
            vectors = await router.embed([content], user_id=user_id, session=session)
        if vectors:
            return list(vectors[0])
    except (TimeoutError, ProviderError, OSError) as exc:
        log.warning("chat.embed_failed", error=str(exc))
    previous = await session.scalar(
        text(
            "SELECT embedding FROM messages WHERE user_id = :user_id AND role = 'user' "
            "AND embedding IS NOT NULL ORDER BY created_at DESC LIMIT 1"
        ),
        {"user_id": user_id},
    )
    return list(previous) if previous is not None else None


async def _store_embedding(
    session: AsyncSession, message_id: uuid.UUID, embedding: list[float], model: str
) -> None:
    """Keep the vector we already paid for (plan §5.4).

    Written here rather than in a job so retrieval works from the very first
    turn; ``embed_pending`` only ever has to catch up on what this missed.
    """
    statement = text(
        "UPDATE messages SET embedding = :embedding, embedding_model = :model "
        "WHERE id = :id AND embedding IS NULL"
    ).bindparams(bindparam("embedding", type_=Vector(EMBEDDING_DIM)))
    await session.execute(statement, {"embedding": embedding, "model": model, "id": message_id})


async def _retrieve(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    embedding: Sequence[float] | None,
    *,
    limits: ContextLimits,
) -> tuple[list[Candidate], list[Candidate]]:
    """Memory items and past user messages, both through the ``Retriever`` protocol."""
    pinned = await _pinned_candidates(session, user_id)
    if embedding is None:
        return pinned, []

    retriever = PgRetriever(session)
    cutoffs = _cutoffs()
    memory_hits = await retriever.search(
        user_id,
        query_embedding=embedding,
        kinds=("memory_item",),
        k=limits.max_memory_items,
    )
    message_hits = await retriever.search(
        user_id,
        query_embedding=embedding,
        kinds=("message",),
        k=limits.max_past_messages,
        min_score=cutoffs.retrieval,
        exclude_conversation_id=conversation_id,
    )
    memory = [Candidate.from_hit(hit) for hit in memory_hits]
    known = {item.id for item in memory}
    memory.extend(item for item in pinned if item.id not in known)
    return memory, [Candidate.from_hit(hit) for hit in message_hits]


def _cutoffs() -> SimilarityCutoffs:
    thresholds = load_thresholds()
    return thresholds.cutoffs(thresholds.default_embedding_model)


async def _pinned_candidates(session: AsyncSession, user_id: uuid.UUID) -> list[Candidate]:
    """Pinned memories go in every turn, vector or no vector — they asked for that."""
    rows = (
        await session.execute(
            text(
                "SELECT id, kind, statement, confirmations, "
                "COALESCE(last_confirmed_at, first_seen_at, created_at) AS at "
                "FROM memory_items WHERE user_id = :user_id AND status = 'active' AND pinned "
                "ORDER BY at DESC LIMIT 20"
            ),
            {"user_id": user_id},
        )
    ).all()
    return [
        Candidate(
            id=row.id,
            kind="memory_item",
            text=row.statement,
            cosine=0.0,
            created_at=row.at,
            confirmations=int(row.confirmations or 0),
            pinned=True,
            item_kind=row.kind,
        )
        for row in rows
    ]


async def _days_since_last_visit(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> int | None:
    last = await session.scalar(
        text(
            "SELECT max(last_message_at) FROM conversations "
            "WHERE user_id = :user_id AND id <> :conversation_id AND is_incognito = FALSE"
        ),
        {"user_id": user_id, "conversation_id": conversation_id},
    )
    if last is None:
        return None
    return max(0, int((now() - last).total_seconds() // 86_400))


async def spend_decision(
    session: AsyncSession, router: Router, user_id: uuid.UUID
) -> SpendDecision:
    """Cheaper thinking near the cap, nothing at all past it (plan §6.6)."""
    try:
        spent = await spent_today(session, user_id, occurred_at=now())
    except Exception as exc:  # a missing counter must never stop a conversation
        log.warning("chat.spend_lookup_failed", error=str(exc))
        return SpendDecision()
    cap = router.limits.user_cap()
    if cap > 0 and spent >= cap:
        return SpendDecision(blocked=True)
    if router.limits.should_downgrade_effort(spent):
        return SpendDecision(effort="low")
    return SpendDecision()


__all__ = [
    "EMBED_TIMEOUT_SECONDS",
    "HISTORY_WINDOW",
    "SpendDecision",
    "load_context_inputs",
    "spend_decision",
]
