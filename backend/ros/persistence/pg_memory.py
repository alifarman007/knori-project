"""Memory in Postgres: exact cosine over one user's rows, and nothing clever.

**No HNSW.** An approximate index answers a filtered query by searching the graph
and then throwing away everyone else's rows, which can return the wrong ones — and
at beta size a sequential scan of a few thousand vectors is milliseconds. The
btree on ``user_id`` does the only filtering that matters. plan §4.1, §2.3.

Every statement here starts from ``WHERE user_id = :user_id``. The vector operator
is pgvector's cosine distance ``<=>``; the score handed back is ``1 - distance``,
so callers compare similarities, never raw distances, and a different retriever
can answer the same way.

Cutoffs are read from ``config/thresholds.yaml`` **keyed by embedding model** —
a new model means new calibration, never these numbers reused.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ros.engine.quotes import locate_quote, verify_quote
from ros.engine.types import load_thresholds
from ros.memory.protocols import Hit, MemoryItemIn, MemoryRecord, MemorySourceIn, UpsertResult
from ros.persistence.models import EMBEDDING_DIM, MemoryItem, MemorySource

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _KindSpec:
    """How one embedded table answers a search. Values are constants, never input."""

    table: str
    text_column: str
    created_column: str
    item_kind_column: str = "NULL"
    conversation_column: str = "NULL"
    seq_column: str = "NULL"
    pinned_column: str = "FALSE"
    confirmations_column: str = "0"
    filters: tuple[str, ...] = ()


KIND_SPECS: dict[str, _KindSpec] = {
    "memory_item": _KindSpec(
        table="memory_items",
        text_column="statement",
        created_column="COALESCE(last_confirmed_at, first_seen_at, created_at)",
        item_kind_column="kind",
        pinned_column="pinned",
        confirmations_column="confirmations",
        filters=("status = 'active'",),
    ),
    "message": _KindSpec(
        table="messages",
        text_column="content",
        created_column="created_at",
        item_kind_column="role",
        conversation_column="conversation_id",
        seq_column="seq",
        filters=(
            "role = 'user'",
            "status <> 'failed'",
            # An incognito conversation leaves no trace anywhere else.
            "NOT EXISTS (SELECT 1 FROM conversations c "
            "WHERE c.id = messages.conversation_id AND c.is_incognito)",
        ),
    ),
    "assertion": _KindSpec(
        table="user_assertions",
        text_column="statement",
        created_column="created_at",
        item_kind_column="kind",
        filters=("status = 'active'",),
    ),
    "signal": _KindSpec(
        table="signals",
        text_column="content",
        created_column="observed_at",
        item_kind_column="kind",
        conversation_column="conversation_id",
    ),
    "interpretation": _KindSpec(
        table="interpretations",
        text_column="statement",
        created_column="created_at",
        item_kind_column="kind",
        filters=("lifecycle_status IN ('candidate', 'recognized')",),
    ),
}

DEFAULT_KINDS: tuple[str, ...] = ("memory_item", "message")


class PgRetriever:
    """The ``Retriever`` protocol, in Postgres.

    ``embed`` is optional and only used for ``query_text``; without it a caller
    must bring its own vector, which is the normal path (the chat route computes
    the query embedding once and reuses it).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        embedding_model: str | None = None,
        embed: Callable[[str], Any] | None = None,
    ) -> None:
        self.session = session
        self.embedding_model = embedding_model or load_thresholds().default_embedding_model
        self._embed = embed

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
    ) -> list[Hit]:
        vector = await self._vector(query_embedding, query_text)
        model = embedding_model or self.embedding_model
        wanted = tuple(kinds) or DEFAULT_KINDS

        hits: list[Hit] = []
        for kind in wanted:
            spec = KIND_SPECS.get(kind)
            if spec is None:
                raise ValueError(f"unknown retrieval kind {kind!r}")
            hits.extend(
                await self._search_one(
                    spec,
                    kind,
                    user_id,
                    vector,
                    model=model,
                    k=k,
                    exclude_conversation_id=exclude_conversation_id,
                    exclude_ids=exclude_ids,
                )
            )
        hits = [hit for hit in hits if hit.score >= min_score]
        hits.sort(key=lambda hit: (-hit.score, str(hit.id)))
        return hits[:k]

    async def _vector(
        self, query_embedding: Sequence[float] | None, query_text: str | None
    ) -> list[float]:
        if query_embedding is not None:
            return [float(value) for value in query_embedding]
        if query_text is not None and self._embed is not None:
            produced = await self._embed(query_text)
            return [float(value) for value in produced]
        raise ValueError(
            "search needs a query_embedding, or a query_text and a retriever built with an embedder"
        )

    async def _search_one(
        self,
        spec: _KindSpec,
        kind: str,
        user_id: uuid.UUID,
        vector: list[float],
        *,
        model: str,
        k: int,
        exclude_conversation_id: uuid.UUID | None,
        exclude_ids: Sequence[uuid.UUID],
    ) -> list[Hit]:
        clauses = ["user_id = :user_id", "embedding IS NOT NULL", *spec.filters]
        params: dict[str, Any] = {"user_id": user_id, "k": max(1, k), "model": model}
        clauses.append("(embedding_model IS NULL OR embedding_model = :model)")
        if exclude_conversation_id is not None and spec.conversation_column != "NULL":
            clauses.append(f"{spec.conversation_column} <> :exclude_conversation")
            params["exclude_conversation"] = exclude_conversation_id
        if exclude_ids:
            clauses.append("id <> ALL(:exclude_ids)")
            params["exclude_ids"] = list(exclude_ids)

        statement = text(
            f"SELECT id, {spec.text_column} AS text, {spec.created_column} AS created_at, "
            f"{spec.item_kind_column} AS item_kind, {spec.conversation_column} AS conversation_id, "
            f"{spec.seq_column} AS seq, {spec.pinned_column} AS pinned, "
            f"{spec.confirmations_column} AS confirmations, "
            "1 - (embedding <=> :query) AS score "
            f"FROM {spec.table} WHERE {' AND '.join(clauses)} "
            "ORDER BY embedding <=> :query LIMIT :k"
        ).bindparams(bindparam("query", value=vector, type_=Vector(EMBEDDING_DIM)))

        rows = (await self.session.execute(statement, params)).all()
        return [
            Hit(
                id=row.id,
                kind=kind,
                text=row.text or "",
                score=float(row.score),
                created_at=row.created_at,
                item_kind=row.item_kind,
                conversation_id=row.conversation_id,
                seq=row.seq,
                pinned=bool(row.pinned),
                confirmations=int(row.confirmations or 0),
            )
            for row in rows
        ]


class PgMemoryStore:
    """The ``MemoryStore`` protocol, in Postgres.

    Upsert follows plan §5.2: the same ``key`` supersedes, unless the existing row
    is user-edited or pinned — **the user's own words are never overwritten by
    extraction**. Otherwise a close enough match (cosine at the configured cutoff)
    counts as a confirmation rather than a second copy of the same fact.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock = _utc_now,
        embedding_model: str | None = None,
    ) -> None:
        self.session = session
        self.clock = clock
        thresholds = load_thresholds()
        self.embedding_model = embedding_model or thresholds.default_embedding_model
        self.memory_cutoff = thresholds.cutoffs(self.embedding_model).memory

    # ---------------------------------------------------------------- reading

    async def list_active(
        self,
        user_id: uuid.UUID,
        *,
        kinds: Sequence[str] = (),
        limit: int = 200,
    ) -> list[MemoryRecord]:
        clauses = ["user_id = :user_id", "status = 'active'"]
        params: dict[str, Any] = {"user_id": user_id, "limit": max(1, min(limit, 500))}
        if kinds:
            clauses.append("kind = ANY(:kinds)")
            params["kinds"] = list(kinds)
        rows = (
            await self.session.execute(
                text(
                    "SELECT id, kind, statement, key, status, source, pinned, confirmations, "
                    "sensitive_category, first_seen_at, last_confirmed_at, superseded_by_id "
                    f"FROM memory_items WHERE {' AND '.join(clauses)} "
                    "ORDER BY pinned DESC, COALESCE(last_confirmed_at, first_seen_at) DESC "
                    "LIMIT :limit"
                ),
                params,
            )
        ).all()
        return [_record(row) for row in rows]

    # ---------------------------------------------------------------- writing

    async def upsert_item(
        self,
        user_id: uuid.UUID,
        item: MemoryItemIn,
        *,
        sources: Sequence[MemorySourceIn] = (),
        similarity_cutoff: float | None = None,
    ) -> UpsertResult:
        existing = await self._match(user_id, item, similarity_cutoff)
        if existing is not None:
            return await self._resolve_existing(user_id, item, existing, sources)
        return await self._insert(user_id, item, sources)

    async def _resolve_existing(
        self,
        user_id: uuid.UUID,
        item: MemoryItemIn,
        existing: MemoryItem,
        sources: Sequence[MemorySourceIn],
    ) -> UpsertResult:
        protected = existing.source in ("user_edited", "user_added") or existing.pinned
        from_model = item.source in ("extracted", "onboarding")
        same_words = existing.statement.strip().casefold() == item.statement.strip().casefold()

        if same_words or (protected and from_model):
            existing.confirmations += 1
            existing.last_confirmed_at = self.clock()
            await self.session.flush()
            await self._add_sources(user_id, existing.id, sources)
            reason = None if same_words else "protected_by_user"
            return UpsertResult(item_id=existing.id, confirmed=True, skipped_reason=reason)

        # Free the key before the replacement takes it: `uq_memory_items_active_key` is a
        # partial unique index on (user_id, key) WHERE status = 'active', and Postgres
        # enforces it per statement, not at commit.
        existing.status = "superseded"
        await self.session.flush()

        result = await self._insert(user_id, item, sources)
        existing.superseded_by_id = result.item_id
        await self.session.flush()
        return UpsertResult(item_id=result.item_id, created=True, superseded_id=existing.id)

    async def _insert(
        self, user_id: uuid.UUID, item: MemoryItemIn, sources: Sequence[MemorySourceIn]
    ) -> UpsertResult:
        moment = self.clock()
        row = MemoryItem(
            user_id=user_id,
            kind=item.kind,
            key=item.key,
            statement=item.statement.strip(),
            status="active",
            source=item.source,
            pinned=item.pinned,
            confirmations=1,
            first_seen_at=moment,
            last_confirmed_at=moment,
            sensitive_category=item.sensitive_category,
            embedding=list(item.embedding) if item.embedding is not None else None,
            embedding_model=item.embedding_model if item.embedding is not None else None,
        )
        self.session.add(row)
        await self.session.flush()
        await self._add_sources(user_id, row.id, sources)
        return UpsertResult(item_id=row.id, created=True)

    async def retract(
        self, user_id: uuid.UUID, item_id: uuid.UUID, *, reason: str | None = None
    ) -> bool:
        result = await self.session.execute(
            text(
                "UPDATE memory_items SET status = 'retracted', retracted_reason = :reason, "
                "updated_at = :now WHERE id = :id AND user_id = :user_id AND status <> 'retracted'"
            ),
            {"id": item_id, "user_id": user_id, "reason": reason, "now": self.clock()},
        )
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def add_source(
        self, user_id: uuid.UUID, item_id: uuid.UUID, source: MemorySourceIn
    ) -> bool:
        added = await self._add_sources(user_id, item_id, [source])
        return added > 0

    async def _add_sources(
        self, user_id: uuid.UUID, item_id: uuid.UUID, sources: Sequence[MemorySourceIn]
    ) -> int:
        """Quotes are checked against the message before insert, like a signal's.

        A quote that cannot be found is dropped, never stored: a source chip that
        highlights nothing is a lie about where a memory came from.
        """
        added = 0
        for source in sources:
            content = await self.session.scalar(
                text("SELECT content FROM messages WHERE id = :id AND user_id = :user_id"),
                {"id": source.message_id, "user_id": user_id},
            )
            if content is None:
                continue
            span = _verified_span(str(content), source)
            if span is None:
                continue
            start, end = span
            result = await self.session.execute(
                text(
                    "INSERT INTO memory_sources "
                    "(memory_item_id, message_id, quote_text, quote_start, quote_end) "
                    "VALUES (:item_id, :message_id, :quote, :start, :end) "
                    "ON CONFLICT (memory_item_id, message_id) DO NOTHING"
                ),
                {
                    "item_id": item_id,
                    "message_id": source.message_id,
                    "quote": source.quote_text,
                    "start": start,
                    "end": end,
                },
            )
            added += int(getattr(result, "rowcount", 0) or 0)
        return added

    # --------------------------------------------------------------- matching

    async def _match(
        self, user_id: uuid.UUID, item: MemoryItemIn, similarity_cutoff: float | None
    ) -> MemoryItem | None:
        """The row this memory would duplicate: same key first, then close enough."""
        if item.key:
            found = await self.session.scalar(
                select(MemoryItem)
                .where(
                    MemoryItem.user_id == user_id,
                    MemoryItem.key == item.key,
                    MemoryItem.status == "active",
                )
                .limit(1)
            )
            if found is not None:
                return found

        if item.embedding is None:
            return None
        cutoff = self.memory_cutoff if similarity_cutoff is None else similarity_cutoff
        statement = text(
            "SELECT id FROM memory_items WHERE user_id = :user_id AND status = 'active' "
            "AND kind = :kind AND embedding IS NOT NULL "
            "AND (embedding_model IS NULL OR embedding_model = :model) "
            "AND 1 - (embedding <=> :query) >= :cutoff "
            "ORDER BY embedding <=> :query LIMIT 1"
        ).bindparams(
            bindparam(
                "query", value=[float(v) for v in item.embedding], type_=Vector(EMBEDDING_DIM)
            )
        )
        found_id = await self.session.scalar(
            statement,
            {
                "user_id": user_id,
                "kind": item.kind,
                "model": item.embedding_model or self.embedding_model,
                "cutoff": cutoff,
            },
        )
        if found_id is None:
            return None
        return await self.session.get(MemoryItem, found_id)


def _verified_span(content: str, source: MemorySourceIn) -> tuple[int, int] | None:
    offsets_given = source.quote_start is not None and source.quote_end is not None
    if offsets_given and verify_quote(
        content, source.quote_text, int(source.quote_start or 0), int(source.quote_end or 0)
    ):
        return int(source.quote_start or 0), int(source.quote_end or 0)
    return locate_quote(content, source.quote_text)


def _record(row: Any) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        kind=row.kind,
        statement=row.statement,
        key=row.key,
        status=row.status,
        source=row.source,
        pinned=bool(row.pinned),
        confirmations=int(row.confirmations or 0),
        sensitive_category=row.sensitive_category,
        first_seen_at=row.first_seen_at,
        last_confirmed_at=row.last_confirmed_at,
        superseded_by_id=row.superseded_by_id,
    )


def memory_record(item: MemoryItem) -> MemoryRecord:
    """ORM row → the protocol's plain record, for callers holding a model object."""
    return MemoryRecord(
        id=item.id,
        kind=item.kind,
        statement=item.statement,
        key=item.key,
        status=item.status,
        source=item.source,
        pinned=item.pinned,
        confirmations=item.confirmations,
        sensitive_category=item.sensitive_category,
        first_seen_at=item.first_seen_at,
        last_confirmed_at=item.last_confirmed_at,
        superseded_by_id=item.superseded_by_id,
    )


def source_record(row: MemorySource) -> MemorySourceIn:
    return MemorySourceIn(
        message_id=row.message_id,
        quote_text=row.quote_text,
        quote_start=row.quote_start,
        quote_end=row.quote_end,
    )


__all__ = [
    "DEFAULT_KINDS",
    "KIND_SPECS",
    "PgMemoryStore",
    "PgRetriever",
    "memory_record",
    "source_record",
]
