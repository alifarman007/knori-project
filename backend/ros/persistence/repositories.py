"""Small, typed reads that more than one slice needs.

Two rules shape this file.

**Every query filters by ``user_id``.** Not "should" — the parameter is required
on every function here, and there is no overload without it. A row that belongs
to someone else is simply not returned, which is how a cross-user read becomes a
404 instead of a leak.

**``ros`` never imports ``knori``.** The Recognition tables are ROS models and are
queried through the ORM. ``conversations``, ``messages`` and ``conversation_events``
are *product* tables, so they are read with parameterised SQL against the table
name and returned as plain frozen rows — the same approach ``ros/llm/cost.py``
already takes for ``user_daily_usage``. The engine gets the data it needs without
the package boundary bending.

Writes to conversations and messages stay in ``knori.services.chat``: this file
is for reading.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ros.engine.provenance import MessageMeta
from ros.persistence.models import (
    Interpretation,
    MemoryItem,
    MemorySource,
    Recognition,
    Signal,
    UserAssertion,
    UserProfile,
)

DEFAULT_PAGE = 50
MAX_PAGE = 200


# ------------------------------------------------------------------ product rows


@dataclass(frozen=True, slots=True)
class ConversationRow:
    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    title: str | None
    is_incognito: bool
    last_seq: int
    message_count: int
    last_message_at: datetime | None
    archived_at: datetime | None
    summary: str | None
    summary_upto_seq: int
    open_threads: list[str]
    summarised_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MessageRow:
    id: uuid.UUID
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    seq: int
    role: str
    content: str
    status: str
    created_at: datetime
    token_estimate: int = 0
    client_message_id: str | None = None
    extracted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConversationEventRow:
    """A card placed in a thread. Not a message — it is not something anyone said."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    kind: str
    after_seq: int
    recognition_id: uuid.UUID | None
    created_at: datetime


_CONVERSATION_COLUMNS = (
    "id, user_id, kind, title, is_incognito, last_seq, message_count, last_message_at, "
    "archived_at, summary, summary_upto_seq, open_threads, summarised_at, ended_at, created_at"
)
_MESSAGE_COLUMNS = (
    "id, conversation_id, user_id, seq, role, content, status, created_at, token_estimate, "
    "client_message_id, extracted_at"
)


def _conversation(row: Any) -> ConversationRow:
    return ConversationRow(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        title=row.title,
        is_incognito=row.is_incognito,
        last_seq=row.last_seq,
        message_count=row.message_count,
        last_message_at=row.last_message_at,
        archived_at=row.archived_at,
        summary=row.summary,
        summary_upto_seq=row.summary_upto_seq,
        open_threads=list(row.open_threads or []),
        summarised_at=row.summarised_at,
        ended_at=row.ended_at,
        created_at=row.created_at,
    )


def _message(row: Any) -> MessageRow:
    return MessageRow(
        id=row.id,
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        seq=row.seq,
        role=row.role,
        content=row.content,
        status=row.status,
        created_at=row.created_at,
        token_estimate=row.token_estimate,
        client_message_id=row.client_message_id,
        extracted_at=row.extracted_at,
    )


def _page(limit: int) -> int:
    return max(1, min(int(limit), MAX_PAGE))


# --------------------------------------------------------------- conversations


async def get_conversation(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> ConversationRow | None:
    """This user's conversation, or None — never someone else's."""
    row = (
        await session.execute(
            text(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations "
                "WHERE id = :id AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id},
        )
    ).first()
    return _conversation(row) if row is not None else None


async def list_conversations(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE,
    include_archived: bool = False,
    before: datetime | None = None,
) -> list[ConversationRow]:
    """Newest activity first. Cursor is ``last_message_at``, falling back to creation."""
    clauses = ["user_id = :user_id"]
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if before is not None:
        clauses.append("COALESCE(last_message_at, created_at) < :before")
    rows = (
        await session.execute(
            text(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE {' AND '.join(clauses)} "
                "ORDER BY COALESCE(last_message_at, created_at) DESC, id DESC LIMIT :limit"
            ),
            {"user_id": user_id, "limit": _page(limit), "before": before},
        )
    ).all()
    return [_conversation(row) for row in rows]


async def latest_conversation(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    kind: str = "chat",
    exclude_id: uuid.UUID | None = None,
) -> ConversationRow | None:
    """The thread ``/app`` reopens when it is fresh enough (plan §5.5).

    ``exclude_id`` is how the opener finds the *previous* conversation: the one it
    is writing the opener for already exists and would otherwise sort first.
    """
    clauses = ["user_id = :user_id", "kind = :kind", "archived_at IS NULL"]
    params: dict[str, Any] = {"user_id": user_id, "kind": kind}
    if exclude_id is not None:
        clauses.append("id <> :exclude_id")
        params["exclude_id"] = exclude_id
    rows = (
        await session.execute(
            text(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY COALESCE(last_message_at, created_at) DESC LIMIT 1"
            ),
            params,
        )
    ).all()
    return _conversation(rows[0]) if rows else None


# -------------------------------------------------------------------- messages


async def list_messages(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    before_seq: int | None = None,
    around_seq: int | None = None,
    limit: int = DEFAULT_PAGE,
    include_failed: bool = True,
) -> list[MessageRow]:
    """A page of a thread, oldest first.

    ``before_seq`` pages backwards for infinite scroll; ``around_seq`` centres a
    window on one message, which is what a Recognition's "open in chat" link needs.
    """
    size = _page(limit)
    clauses = ["conversation_id = :conversation_id", "user_id = :user_id"]
    params: dict[str, Any] = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "limit": size,
    }
    if not include_failed:
        clauses.append("status <> 'failed'")

    if around_seq is not None:
        half = max(1, size // 2)
        clauses.append("seq BETWEEN :low AND :high")
        params["low"] = max(0, around_seq - half)
        params["high"] = around_seq + half
        order = "seq ASC"
    elif before_seq is not None:
        clauses.append("seq < :before_seq")
        params["before_seq"] = before_seq
        order = "seq DESC"
    else:
        order = "seq DESC"

    rows = (
        await session.execute(
            text(
                f"SELECT {_MESSAGE_COLUMNS} FROM messages WHERE {' AND '.join(clauses)} "
                f"ORDER BY {order} LIMIT :limit"
            ),
            params,
        )
    ).all()
    messages = [_message(row) for row in rows]
    messages.sort(key=lambda message: message.seq)
    return messages


async def get_message_by_seq(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, seq: int
) -> MessageRow | None:
    rows = (
        await session.execute(
            text(
                f"SELECT {_MESSAGE_COLUMNS} FROM messages "
                "WHERE conversation_id = :conversation_id AND user_id = :user_id AND seq = :seq"
            ),
            {"conversation_id": conversation_id, "user_id": user_id, "seq": seq},
        )
    ).all()
    return _message(rows[0]) if rows else None


async def message_metas(
    session: AsyncSession, user_id: uuid.UUID, message_ids: Sequence[uuid.UUID]
) -> list[MessageMeta]:
    """Where each quote sits, for the provenance snapshot and its deep link."""
    if not message_ids:
        return []
    rows = (
        await session.execute(
            text(
                "SELECT m.id, m.conversation_id, m.seq, m.created_at, c.title "
                "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.user_id = :user_id AND m.id = ANY(:ids)"
            ),
            {"user_id": user_id, "ids": list(message_ids)},
        )
    ).all()
    return [
        MessageMeta(
            message_id=str(row.id),
            conversation_id=str(row.conversation_id),
            conversation_title=row.title,
            seq=row.seq,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def list_conversation_events(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    after_seq: int | None = None,
    before_seq: int | None = None,
) -> list[ConversationEventRow]:
    """Card placements inside one thread, in the order they appear."""
    clauses = ["conversation_id = :conversation_id", "user_id = :user_id"]
    params: dict[str, Any] = {"conversation_id": conversation_id, "user_id": user_id}
    if after_seq is not None:
        clauses.append("after_seq >= :after_seq")
        params["after_seq"] = after_seq
    if before_seq is not None:
        clauses.append("after_seq <= :before_seq")
        params["before_seq"] = before_seq
    rows = (
        await session.execute(
            text(
                "SELECT id, conversation_id, kind, after_seq, recognition_id, created_at "
                f"FROM conversation_events WHERE {' AND '.join(clauses)} "
                "ORDER BY after_seq ASC, created_at ASC"
            ),
            params,
        )
    ).all()
    return [
        ConversationEventRow(
            id=row.id,
            conversation_id=row.conversation_id,
            kind=row.kind,
            after_seq=row.after_seq,
            recognition_id=row.recognition_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ------------------------------------------------------------------- ROS tables


def _owned(stmt: Select[Any], model: Any, user_id: uuid.UUID) -> Select[Any]:
    return stmt.where(model.user_id == user_id)


async def get_signals_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    uninterpreted_only: bool = False,
    since: datetime | None = None,
    topics: Sequence[str] = (),
    limit: int = MAX_PAGE,
) -> list[Signal]:
    """Signals, oldest first — the order ``interpret`` wants them in."""
    stmt = _owned(select(Signal), Signal, user_id)
    if uninterpreted_only:
        stmt = stmt.where(Signal.interpreted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Signal.observed_at >= since)
    if topics:
        stmt = stmt.where(Signal.topic.in_(list(topics)))
    stmt = stmt.order_by(Signal.observed_at.asc()).limit(_page(limit))
    return list((await session.scalars(stmt)).all())


async def list_memory_items(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    kinds: Sequence[str] = (),
    status: str | None = "active",
    limit: int = MAX_PAGE,
) -> list[MemoryItem]:
    stmt = _owned(select(MemoryItem), MemoryItem, user_id)
    if status is not None:
        stmt = stmt.where(MemoryItem.status == status)
    if kinds:
        stmt = stmt.where(MemoryItem.kind.in_(list(kinds)))
    stmt = stmt.order_by(
        MemoryItem.pinned.desc(), MemoryItem.last_confirmed_at.desc().nullslast()
    ).limit(_page(limit))
    return list((await session.scalars(stmt)).all())


async def get_memory_item(
    session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID
) -> MemoryItem | None:
    stmt = _owned(select(MemoryItem), MemoryItem, user_id).where(MemoryItem.id == item_id)
    return await session.scalar(stmt)


async def list_memory_sources(
    session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID
) -> list[MemorySource]:
    """Sources for one item — filtered through the item, so ownership still holds."""
    stmt = (
        select(MemorySource)
        .join(MemoryItem, MemoryItem.id == MemorySource.memory_item_id)
        .where(MemoryItem.user_id == user_id, MemorySource.memory_item_id == item_id)
        .order_by(MemorySource.created_at.asc())
    )
    return list((await session.scalars(stmt)).all())


async def list_active_assertions(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = MAX_PAGE
) -> list[UserAssertion]:
    stmt = (
        _owned(select(UserAssertion), UserAssertion, user_id)
        .where(UserAssertion.status == "active")
        .order_by(UserAssertion.created_at.desc())
        .limit(_page(limit))
    )
    return list((await session.scalars(stmt)).all())


async def get_assertion(
    session: AsyncSession, user_id: uuid.UUID, assertion_id: uuid.UUID
) -> UserAssertion | None:
    stmt = _owned(select(UserAssertion), UserAssertion, user_id).where(
        UserAssertion.id == assertion_id
    )
    return await session.scalar(stmt)


async def latest_profile(session: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    stmt = (
        _owned(select(UserProfile), UserProfile, user_id)
        .order_by(UserProfile.version.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def list_open_recognitions(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 20
) -> list[Recognition]:
    """Cards the user has not resolved yet. Chat may name these, never invent one."""
    stmt = (
        _owned(select(Recognition), Recognition, user_id)
        .where(Recognition.state.in_(("pending", "presented")))
        .order_by(Recognition.created_at.desc())
        .limit(_page(limit))
    )
    return list((await session.scalars(stmt)).all())


async def get_interpretation(
    session: AsyncSession, user_id: uuid.UUID, interpretation_id: uuid.UUID
) -> Interpretation | None:
    stmt = _owned(select(Interpretation), Interpretation, user_id).where(
        Interpretation.id == interpretation_id
    )
    return await session.scalar(stmt)


__all__ = [
    "DEFAULT_PAGE",
    "MAX_PAGE",
    "ConversationEventRow",
    "ConversationRow",
    "MessageRow",
    "get_assertion",
    "get_conversation",
    "get_interpretation",
    "get_memory_item",
    "get_message_by_seq",
    "get_signals_for_user",
    "latest_conversation",
    "latest_profile",
    "list_active_assertions",
    "list_conversation_events",
    "list_conversations",
    "list_memory_items",
    "list_memory_sources",
    "list_messages",
    "list_open_recognitions",
    "message_metas",
]
