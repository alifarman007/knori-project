"""The two doors between the engine and stored memory.

Everything that stores what a user told KnoRI goes through :class:`MemoryStore`,
and **every similarity lookup in the system goes through :class:`Retriever`** —
the chat context builder, the interpret neighbourhood query, dedup, claim
matches and the rescoring cascade alike.

That single rule is what makes the Phase 5 promise ("swap the retrieval system")
a swap rather than a rewrite: today the implementation is exact cosine over the
user's rows in Postgres (``ros/persistence/pg_memory.py``); tomorrow it can be
anything that answers :meth:`Retriever.search` with the same ``Hit`` list.

Nothing here touches a database, a model or ``knori``: these are protocols and
plain data, so the engine can be tested with a list-backed fake.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

#: What a retrieval hit can be. Each maps to one table with an ``embedding`` column.
HIT_KINDS: tuple[str, ...] = (
    "memory_item",
    "message",
    "assertion",
    "signal",
    "interpretation",
)


@dataclass(frozen=True, slots=True)
class Hit:
    """One row that came back from a similarity search, with its score.

    ``score`` is cosine similarity in ``[-1, 1]`` — never a raw pgvector distance,
    so a caller can compare hits from two different retrievers.
    """

    id: uuid.UUID
    kind: str
    text: str
    score: float
    created_at: datetime | None = None
    #: The ``kind`` column of the underlying row (memory item kind, signal kind…).
    item_kind: str | None = None
    conversation_id: uuid.UUID | None = None
    seq: int | None = None
    pinned: bool = False
    confirmations: int = 0
    embedding: tuple[float, ...] | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemorySourceIn:
    """Where a memory item came from: the message, and the words in it.

    The quote is verified against the message before insert, exactly as a signal's
    is — a memory the user can click through to nothing is worse than no memory.
    """

    message_id: uuid.UUID
    quote_text: str
    quote_start: int | None = None
    quote_end: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryItemIn:
    """A memory to write: what was said, not what was inferred."""

    kind: str
    statement: str
    key: str | None = None
    source: str = "extracted"
    sensitive_category: str | None = None
    pinned: bool = False
    embedding: Sequence[float] | None = None
    embedding_model: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A stored memory item, as the product and the engine read it back."""

    id: uuid.UUID
    kind: str
    statement: str
    key: str | None = None
    status: str = "active"
    source: str = "extracted"
    pinned: bool = False
    confirmations: int = 1
    sensitive_category: str | None = None
    first_seen_at: datetime | None = None
    last_confirmed_at: datetime | None = None
    superseded_by_id: uuid.UUID | None = None

    @property
    def usable_as_evidence(self) -> bool:
        """Sensitive items are stored (they said it) but never back a Recognition."""
        return self.status == "active" and self.sensitive_category is None


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """What an upsert actually did, so the caller can report it honestly."""

    item_id: uuid.UUID
    created: bool = False
    confirmed: bool = False
    superseded_id: uuid.UUID | None = None
    skipped_reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.created or self.confirmed or self.superseded_id is not None


@runtime_checkable
class MemoryStore(Protocol):
    """Writing and reading "what you told KnoRI"."""

    async def upsert_item(
        self,
        user_id: uuid.UUID,
        item: MemoryItemIn,
        *,
        sources: Sequence[MemorySourceIn] = (),
        similarity_cutoff: float | None = None,
    ) -> UpsertResult:
        """Add a memory, or confirm/supersede the one it duplicates.

        A user-edited or pinned row is never overwritten by extraction: the user's
        own words win over anything a model proposes later (plan §5.2).
        """
        ...

    async def retract(
        self, user_id: uuid.UUID, item_id: uuid.UUID, *, reason: str | None = None
    ) -> bool:
        """Mark an item retracted. Returns False when it is not this user's row."""
        ...

    async def list_active(
        self,
        user_id: uuid.UUID,
        *,
        kinds: Sequence[str] = (),
        limit: int = 200,
    ) -> list[MemoryRecord]: ...

    async def add_source(
        self, user_id: uuid.UUID, item_id: uuid.UUID, source: MemorySourceIn
    ) -> bool:
        """Attach another message as evidence for an existing memory."""
        ...


@runtime_checkable
class Retriever(Protocol):
    """The one way to ask "what of this user's is close to this?".

    ``query_embedding`` is preferred; ``query_text`` is a convenience for callers
    that have no vector yet and is only usable by an implementation that was given
    an embedder. Passing neither is an error, not an empty result — silently
    returning nothing would look like "this user has no memory".
    """

    async def search(
        self,
        user_id: uuid.UUID,
        *,
        query_embedding: Sequence[float] | None = None,
        query_text: str | None = None,
        kinds: Sequence[str] = (),
        k: int = 10,
        min_score: float = 0.0,
        embedding_model: str | None = None,
        exclude_conversation_id: uuid.UUID | None = None,
        exclude_ids: Sequence[uuid.UUID] = (),
    ) -> list[Hit]: ...


__all__ = [
    "HIT_KINDS",
    "Hit",
    "MemoryItemIn",
    "MemoryRecord",
    "MemorySourceIn",
    "MemoryStore",
    "Retriever",
    "UpsertResult",
]
