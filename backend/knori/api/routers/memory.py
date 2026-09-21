"""``/memory`` — what you told KnoRI, and what you corrected (plan.md §7, §8).

This is the screen that makes the product honest on day one, before any
Recognition exists: every line KnoRI holds about someone, where it came from,
and a way to change or remove it.

Two rules run through the whole file:

* **an edited memory is theirs.** Editing sets ``source = 'user_edited'`` and
  extraction is never allowed to overwrite it again (plan §5.2). The user gets
  the last word about their own life.
* **retracting anything re-scores the engine.** A memory or a correction that no
  longer stands must change what KnoRI concludes next, not just what it shows —
  otherwise "correct me" is a checkbox (CLAUDE.md engine rule 7).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.deps import CurrentUser, DbSession
from knori.api.schemas.memory import (
    AssertionOut,
    AssertionsOut,
    CreateMemoryItemIn,
    MemoryItemOut,
    MemoryItemsOut,
    MemorySourceOut,
    MemorySourcesOut,
    ProfileOut,
    UpdateMemoryItemIn,
)
from knori.core.clock import now
from knori.core.errors import NotFound
from knori.jobs import queue
from knori.jobs.handlers.chat import EMBED_JOB
from knori.services.feedback import reasoning_lock_key
from ros.memory.protocols import MemoryItemIn
from ros.persistence import repositories
from ros.persistence.models import MemoryItem
from ros.persistence.pg_memory import PgMemoryStore

router = APIRouter(prefix="/memory", tags=["memory"])


# ------------------------------------------------------------------ the items


@router.get("/items", response_model=MemoryItemsOut, summary="What KnoRI remembers")
async def list_items(
    user: CurrentUser,
    session: DbSession,
    kind: Annotated[str | None, Query(description="One memory kind, or all of them.")] = None,
    status_filter: Annotated[str, Query(alias="status")] = "active",
) -> MemoryItemsOut:
    rows = await repositories.list_memory_items(
        session,
        user.id,
        kinds=(kind,) if kind else (),
        status=None if status_filter == "all" else status_filter,
    )
    counts = await _source_counts(session, [row.id for row in rows])
    return MemoryItemsOut(items=[_view(row, counts.get(row.id, 0)) for row in rows])


@router.post(
    "/items",
    response_model=MemoryItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a memory yourself",
)
async def create_item(
    user: CurrentUser, session: DbSession, payload: CreateMemoryItemIn
) -> MemoryItemOut:
    """A memory the user typed. It has no quote, because nobody said it in a chat."""
    store = PgMemoryStore(session, clock=now)
    result = await store.upsert_item(
        user.id,
        MemoryItemIn(
            kind=payload.kind,
            statement=payload.statement,
            key=payload.key,
            source="user_added",
            pinned=payload.pinned,
        ),
    )
    await _queue_embedding(session, user.id)
    await session.commit()
    row = await repositories.get_memory_item(session, user.id, result.item_id)
    if row is None:  # pragma: no cover - only if the row vanished mid-request
        raise NotFound("That memory could not be saved.")
    return _view(row, 0)


@router.patch("/items/{item_id}", response_model=MemoryItemOut, summary="Edit a memory")
async def update_item(
    user: CurrentUser, session: DbSession, item_id: uuid.UUID, payload: UpdateMemoryItemIn
) -> MemoryItemOut:
    row = await repositories.get_memory_item(session, user.id, item_id)
    if row is None:
        raise NotFound("That memory does not exist.")

    if payload.statement is not None and payload.statement != row.statement:
        row.statement = payload.statement
        row.source = "user_edited"
        # The words changed, so the old vector is wrong: drop it and re-embed.
        row.embedding = None
        row.embedding_model = None
        await _queue_embedding(session, user.id)
    if payload.kind is not None:
        row.kind = payload.kind
    if payload.pinned is not None:
        row.pinned = payload.pinned
    await session.commit()
    counts = await _source_counts(session, [row.id])
    return _view(row, counts.get(row.id, 0))


@router.delete(
    "/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Retract a memory"
)
async def retract_item(user: CurrentUser, session: DbSession, item_id: uuid.UUID) -> Response:
    store = PgMemoryStore(session, clock=now)
    if not await store.retract(user.id, item_id, reason="user_retracted"):
        raise NotFound("That memory does not exist.")
    await _queue_rescore(session, user.id, "memory_retracted")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/items/{item_id}/sources",
    response_model=MemorySourcesOut,
    summary="Where a memory came from",
)
async def item_sources(
    user: CurrentUser, session: DbSession, item_id: uuid.UUID
) -> MemorySourcesOut:
    """The exact words, and enough to link back to the message that holds them."""
    if await repositories.get_memory_item(session, user.id, item_id) is None:
        raise NotFound("That memory does not exist.")
    sources = await repositories.list_memory_sources(session, user.id, item_id)
    metas = {
        meta.message_id: meta
        for meta in await repositories.message_metas(
            session, user.id, [source.message_id for source in sources]
        )
    }
    out: list[MemorySourceOut] = []
    for source in sources:
        meta = metas.get(str(source.message_id))
        out.append(
            MemorySourceOut(
                message_id=source.message_id,
                conversation_id=uuid.UUID(meta.conversation_id)
                if meta and meta.conversation_id
                else None,
                conversation_title=meta.conversation_title if meta else None,
                seq=meta.seq if meta else None,
                quote_text=source.quote_text,
                quote_start=source.quote_start,
                quote_end=source.quote_end,
                message_created_at=meta.created_at if meta else None,
            )
        )
    return MemorySourcesOut(sources=out)


# ---------------------------------------------------------------- the profile


@router.get("/profile", response_model=ProfileOut, summary="How KnoRI sees you")
async def profile(user: CurrentUser, session: DbSession) -> ProfileOut:
    row = await repositories.latest_profile(session, user.id)
    if row is None:
        return ProfileOut(profile_text="")
    sections = row.profile_json.get("sections") if isinstance(row.profile_json, dict) else None
    return ProfileOut(
        version=row.version,
        profile_text=row.profile_text,
        sections=list(sections or []),
        trigger=row.trigger,
        created_at=row.created_at,
    )


# ------------------------------------------------------------- your corrections


@router.get("/assertions", response_model=AssertionsOut, summary="Your corrections")
async def list_assertions(user: CurrentUser, session: DbSession) -> AssertionsOut:
    rows = await repositories.list_active_assertions(session, user.id)
    return AssertionsOut(assertions=[AssertionOut.model_validate(row) for row in rows])


@router.delete(
    "/assertions/{assertion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Take back a correction",
)
async def retract_assertion(
    user: CurrentUser, session: DbSession, assertion_id: uuid.UUID
) -> Response:
    """Retracting a ``deny`` is what lets a rejected claim be reconsidered (R7)."""
    row = await repositories.get_assertion(session, user.id, assertion_id)
    if row is None or row.status != "active":
        raise NotFound("That correction does not exist.")
    row.status = "retracted"
    row.retracted_at = now()
    await _queue_rescore(session, user.id, "assertion_retracted")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- internals


def _view(row: MemoryItem, source_count: int) -> MemoryItemOut:
    return MemoryItemOut(
        id=row.id,
        kind=row.kind,
        statement=row.statement,
        key=row.key,
        status=row.status,
        source=row.source,
        pinned=row.pinned,
        confirmations=row.confirmations,
        sensitive_category=row.sensitive_category,
        first_seen_at=row.first_seen_at,
        last_confirmed_at=row.last_confirmed_at,
        source_count=source_count,
    )


async def _source_counts(session: AsyncSession, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not item_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT memory_item_id AS id, count(*) AS n FROM memory_sources "
                "WHERE memory_item_id = ANY(:ids) GROUP BY memory_item_id"
            ),
            {"ids": item_ids},
        )
    ).all()
    return {row.id: int(row.n) for row in rows}


async def _queue_embedding(session: AsyncSession, user_id: uuid.UUID) -> Any:
    """New or edited text needs a vector before it can be retrieved again."""
    return await queue.enqueue(
        session,
        EMBED_JOB,
        {"reason": "memory_changed"},
        lane="fast",
        user_id=user_id,
        priority=7,
        dedupe_key=queue.dedupe_key_for(EMBED_JOB, user_id),
    )


async def _queue_rescore(session: AsyncSession, user_id: uuid.UUID, reason: str) -> Any:
    """Enqueued in the same transaction as the change it follows."""
    return await queue.enqueue(
        session,
        "rescore_user",
        {"reason": reason},
        lane="slow",
        user_id=user_id,
        priority=6,
        dedupe_key=queue.dedupe_key_for("rescore_user", user_id, reason),
        lock_key=reasoning_lock_key(user_id),
    )


__all__ = ["router"]
