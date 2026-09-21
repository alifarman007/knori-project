"""Every read and write the Recognition pipeline needs, and nothing else.

One repository, one user: :class:`EngineRepo` is constructed with a ``user_id``
and every statement in this file filters by it. There is no method that can see
another person's rows, so "did we remember to scope that query?" is answered once,
here, instead of at forty call sites.

Two kinds of table are reached from this file:

* **ROS tables** (``signals``, ``interpretations``, …) through their SQLAlchemy
  models — they belong to this package;
* **product tables** (``messages``, ``conversations``, ``users``,
  ``user_settings``) through plain SQL. ``ros`` must never import ``knori``
  (CLAUDE.md → repo layout), and a hand-written ``SELECT`` is the honest way to
  read a table another package owns.

Similarity search is *not* here. It goes through the ``Retriever`` protocol from
``ros.memory`` (plan §5.6), so swapping pgvector for something else in Phase 5 is
one implementation, not forty queries.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ros.engine.provenance import MessageMeta, ProvenanceRow
from ros.engine.types import (
    AssertionIn,
    ClaimMatchIn,
    EvidenceIn,
    InterpretationIn,
    SignalIn,
    UserPolicy,
)
from ros.persistence.models import (
    ClaimMatch,
    CorrectionEffect,
    Evidence,
    Interpretation,
    MemoryItem,
    Recognition,
    RecognitionEvent,
    RecognitionFeedback,
    RecognitionProvenance,
    Signal,
    ThresholdEvaluation,
    UserAssertion,
    UserProfile,
)

if TYPE_CHECKING:  # the memory slice owns this protocol; ros.engine never needs it
    from ros.memory.protocols import Retriever

OPEN_LIFECYCLE = ("candidate", "recognized")
OPEN_CARD_STATES = ("pending", "presented")


@dataclass(frozen=True, slots=True)
class MessageRow:
    """A row of ``messages``, read without importing the product package."""

    id: str
    conversation_id: str
    seq: int
    role: str
    content: str
    created_at: datetime
    status: str = "complete"


@dataclass(frozen=True, slots=True)
class ConversationRow:
    id: str
    title: str | None
    is_incognito: bool
    archived_at: datetime | None
    last_seq: int


@dataclass(frozen=True, slots=True)
class UserContext:
    """What the engine needs to know about the person, outside the ROS tables."""

    policy: UserPolicy
    display_name: str = "you"
    memory_enabled: bool = True
    chat_style: str = "warm"


@dataclass(frozen=True, slots=True)
class CardBudget:
    open_cards: int = 0
    created_today: int = 0
    has_card_for_version: frozenset[tuple[str, int]] = frozenset()


def _f(value: Any, default: float = 0.0) -> float:
    return default if value is None else float(value)


def _vector(value: Any) -> list[float] | None:
    """pgvector hands back a numpy array; the engine only ever wants floats."""
    if value is None:
        return None
    return [float(x) for x in value]


def signal_in(row: Signal) -> SignalIn:
    return SignalIn(
        id=str(row.id),
        subject=row.subject,
        topic=row.topic,
        strength=_f(row.strength, 0.6),
        polarity=int(row.polarity or 0),
        sensitive_category=row.sensitive_category,
        observed_at=row.observed_at,
        message_id=str(row.message_id),
        quote_text=row.quote_text,
        quote_start=int(row.quote_start),
        quote_end=int(row.quote_end),
    )


def assertion_in(row: UserAssertion) -> AssertionIn:
    return AssertionIn(
        id=str(row.id),
        kind=row.kind,
        statement=row.statement,
        topic=row.topic,
        applies_to_interpretation_id=(
            str(row.applies_to_interpretation_id) if row.applies_to_interpretation_id else None
        ),
        weight=_f(row.weight, 1.0),
        status=row.status,
        created_at=row.created_at,
    )


def assertion_support(row: UserAssertion) -> EvidenceIn:
    """An amended claim's own assertion, as the dated support R3 counts (plan §4.6).

    ``evidence.signal_id`` is NOT NULL, so this support exists in memory and in the
    provenance snapshot (``kind='assertion'``), never as an ``evidence`` row.
    """
    return EvidenceIn(
        signal=SignalIn(
            id=str(row.id),
            subject="self",
            topic=row.topic or "",
            strength=1.0,
            observed_at=row.created_at,
            message_id=None,
            quote_text=row.statement,
        ),
        role="supports",
        weight=_f(row.weight, 1.0),
        id=f"assertion:{row.id}",
        note="The user's own correction.",
    )


class EngineRepo:
    """Scoped to one user for its whole lifetime."""

    def __init__(self, session: AsyncSession, user_id: uuid.UUID | str) -> None:
        self.session = session
        self.user_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

    # -- product tables ---------------------------------------------------------

    async def user_context(self) -> UserContext:
        row = (
            await self.session.execute(
                text(
                    """
                    SELECT u.display_name, u.preferred_name, u.timezone,
                           COALESCE(s.recognition_enabled, TRUE)   AS recognition_enabled,
                           COALESCE(s.memory_enabled, TRUE)        AS memory_enabled,
                           COALESCE(s.max_recognitions_per_day, 2) AS max_per_day,
                           COALESCE(s.chat_style, 'warm')          AS chat_style
                      FROM users u
                      LEFT JOIN user_settings s ON s.user_id = u.id
                     WHERE u.id = :user_id
                    """
                ),
                {"user_id": self.user_id},
            )
        ).first()
        if row is None:
            return UserContext(policy=UserPolicy())
        return UserContext(
            policy=UserPolicy(
                recognition_enabled=bool(row.recognition_enabled),
                max_recognitions_per_day=int(row.max_per_day),
                timezone=row.timezone or "UTC",
            ),
            display_name=row.preferred_name or row.display_name or "you",
            memory_enabled=bool(row.memory_enabled),
            chat_style=row.chat_style,
        )

    async def conversation(self, conversation_id: uuid.UUID | str) -> ConversationRow | None:
        row = (
            await self.session.execute(
                text(
                    "SELECT id, title, is_incognito, archived_at, last_seq FROM conversations "
                    "WHERE id = :id AND user_id = :user_id"
                ),
                {"id": _as_uuid(conversation_id), "user_id": self.user_id},
            )
        ).first()
        if row is None:
            return None
        return ConversationRow(
            id=str(row.id),
            title=row.title,
            is_incognito=bool(row.is_incognito),
            archived_at=row.archived_at,
            last_seq=int(row.last_seq or 0),
        )

    async def unextracted_messages(
        self, conversation_id: uuid.UUID | str, *, limit: int = 20
    ) -> list[MessageRow]:
        return await self._messages(
            "conversation_id = :conversation_id AND role = 'user' AND extracted_at IS NULL "
            "AND status IN ('complete','partial') ORDER BY seq ASC LIMIT :limit",
            {"conversation_id": _as_uuid(conversation_id), "limit": limit},
        )

    async def messages_by_id(self, message_ids: Sequence[uuid.UUID | str]) -> list[MessageRow]:
        if not message_ids:
            return []
        return await self._messages(
            "id = ANY(:ids) ORDER BY created_at ASC, seq ASC",
            {"ids": [_as_uuid(m) for m in message_ids]},
        )

    async def context_messages(
        self, conversation_id: uuid.UUID | str, *, before_seq: int, limit: int = 6
    ) -> list[MessageRow]:
        """The few turns before the new ones — context for extraction, never extracted."""
        rows = await self._messages(
            "conversation_id = :conversation_id AND seq < :before_seq "
            "AND status IN ('complete','partial') ORDER BY seq DESC LIMIT :limit",
            {
                "conversation_id": _as_uuid(conversation_id),
                "before_seq": before_seq,
                "limit": limit,
            },
        )
        return list(reversed(rows))

    async def _messages(self, tail: str, params: dict[str, Any]) -> list[MessageRow]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT id, conversation_id, seq, role, content, created_at, status "
                    f"FROM messages WHERE user_id = :user_id AND {tail}"
                ),
                {**params, "user_id": self.user_id},
            )
        ).all()
        return [
            MessageRow(
                id=str(r.id),
                conversation_id=str(r.conversation_id),
                seq=int(r.seq),
                role=r.role,
                content=r.content or "",
                created_at=r.created_at,
                status=r.status,
            )
            for r in rows
        ]

    async def message_metas(self, message_ids: Iterable[uuid.UUID | str]) -> dict[str, MessageMeta]:
        ids = [_as_uuid(m) for m in dict.fromkeys(str(m) for m in message_ids)]
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                text(
                    "SELECT m.id, m.conversation_id, m.seq, m.created_at, c.title "
                    "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                    "WHERE m.user_id = :user_id AND m.id = ANY(:ids)"
                ),
                {"user_id": self.user_id, "ids": ids},
            )
        ).all()
        return {
            str(r.id): MessageMeta(
                message_id=str(r.id),
                conversation_id=str(r.conversation_id),
                conversation_title=r.title,
                seq=int(r.seq),
                created_at=r.created_at,
            )
            for r in rows
        }

    async def mark_extracted(self, message_ids: Sequence[uuid.UUID | str], at: datetime) -> int:
        if not message_ids:
            return 0
        result = await self.session.execute(
            text(
                "UPDATE messages SET extracted_at = :at "
                "WHERE user_id = :user_id AND id = ANY(:ids) AND extracted_at IS NULL"
            ),
            {"at": at, "user_id": self.user_id, "ids": [_as_uuid(m) for m in message_ids]},
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def placement_target(
        self, preferred_conversation_id: uuid.UUID | str | None
    ) -> tuple[str, int] | None:
        """Where a card goes: never an incognito or archived thread (plan §5.1)."""
        if preferred_conversation_id is not None:
            found = await self.conversation(preferred_conversation_id)
            if found is not None and not found.is_incognito and found.archived_at is None:
                return found.id, found.last_seq
        row = (
            await self.session.execute(
                text(
                    "SELECT id, last_seq FROM conversations "
                    "WHERE user_id = :user_id AND is_incognito = FALSE AND archived_at IS NULL "
                    "ORDER BY last_message_at DESC NULLS LAST LIMIT 1"
                ),
                {"user_id": self.user_id},
            )
        ).first()
        return (str(row.id), int(row.last_seq or 0)) if row is not None else None

    async def place_card(
        self, conversation_id: str, after_seq: int, recognition_id: uuid.UUID
    ) -> None:
        await self.session.execute(
            text(
                "INSERT INTO conversation_events "
                "(conversation_id, user_id, kind, after_seq, recognition_id) "
                "VALUES (:conversation_id, :user_id, 'recognition', :after_seq, :recognition_id)"
            ),
            {
                "conversation_id": _as_uuid(conversation_id),
                "user_id": self.user_id,
                "after_seq": after_seq,
                "recognition_id": recognition_id,
            },
        )

    # -- signals ----------------------------------------------------------------

    async def add_signal(self, **values: Any) -> Signal:
        row = Signal(user_id=self.user_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def new_signals(self, *, limit: int = 40) -> list[Signal]:
        """Uninterpreted signals the interpreter is allowed to see (plan §4.3)."""
        rows = await self.session.scalars(
            select(Signal)
            .where(
                Signal.user_id == self.user_id,
                Signal.interpreted_at.is_(None),
                Signal.subject == "self",
                Signal.sensitive_category.is_(None),
            )
            .order_by(Signal.observed_at.asc())
            .limit(limit)
        )
        return list(rows.all())

    async def count_uninterpreted(self) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(Signal)
            .where(
                Signal.user_id == self.user_id,
                Signal.interpreted_at.is_(None),
                Signal.subject == "self",
                Signal.sensitive_category.is_(None),
            )
        )
        return int(value or 0)

    async def signals_by_id(self, signal_ids: Iterable[uuid.UUID | str]) -> list[Signal]:
        ids = [_as_uuid(s) for s in dict.fromkeys(str(s) for s in signal_ids)]
        if not ids:
            return []
        rows = await self.session.scalars(
            select(Signal).where(Signal.user_id == self.user_id, Signal.id.in_(ids))
        )
        return list(rows.all())

    async def mark_interpreted(self, signal_ids: Sequence[uuid.UUID | str], at: datetime) -> None:
        if not signal_ids:
            return
        await self.session.execute(
            update(Signal)
            .where(
                Signal.user_id == self.user_id,
                Signal.id.in_([_as_uuid(s) for s in signal_ids]),
            )
            .values(interpreted_at=at)
        )

    async def neighbourhood(
        self,
        seeds: Sequence[Signal],
        *,
        retriever: Retriever | None = None,
        per_seed: int = 8,
        limit: int = 60,
    ) -> list[Signal]:
        """Older signals worth showing beside the new ones (plan §4.3).

        Same topic, plus the nearest by cosine — and the cosine half goes through
        the ``Retriever`` protocol, never through SQL written here.
        """
        seed_ids = {str(s.id) for s in seeds}
        topics = sorted({s.topic for s in seeds if s.topic})
        found: dict[str, Signal] = {}

        if topics:
            rows = await self.session.scalars(
                select(Signal)
                .where(
                    Signal.user_id == self.user_id,
                    Signal.topic.in_(topics),
                    Signal.subject == "self",
                    Signal.sensitive_category.is_(None),
                    Signal.id.notin_([_as_uuid(i) for i in seed_ids] or [uuid.uuid4()]),
                )
                .order_by(Signal.observed_at.desc())
                .limit(limit)
            )
            found.update({str(r.id): r for r in rows.all()})

        if retriever is not None:
            nearby_ids: list[str] = []
            for seed in seeds:
                vector = _vector(seed.embedding)
                if vector is None:
                    continue
                hits = await retriever.search(
                    self.user_id,
                    query_embedding=vector,
                    kinds=("signal",),
                    k=per_seed,
                    exclude_ids=[uuid.UUID(i) for i in sorted(seed_ids)],
                )
                nearby_ids.extend(str(hit.id) for hit in hits)
            missing = [
                i for i in dict.fromkeys(nearby_ids) if i and i not in found and i not in seed_ids
            ]
            for row in await self.signals_by_id(missing):
                if row.subject == "self" and not row.sensitive_category:
                    found[str(row.id)] = row

        ordered = sorted(found.values(), key=lambda s: s.observed_at)
        return ordered[-limit:]

    # -- interpretations, evidence, ledger --------------------------------------

    async def open_interpretations(self, *, limit: int = 60) -> list[Interpretation]:
        rows = await self.session.scalars(
            select(Interpretation)
            .where(
                Interpretation.user_id == self.user_id,
                Interpretation.lifecycle_status.in_(OPEN_LIFECYCLE),
            )
            .order_by(Interpretation.created_at.asc())
            .limit(limit)
        )
        return list(rows.all())

    async def interpretations_by_id(
        self, interpretation_ids: Iterable[uuid.UUID | str]
    ) -> list[Interpretation]:
        ids = [_as_uuid(i) for i in dict.fromkeys(str(i) for i in interpretation_ids)]
        if not ids:
            return []
        rows = await self.session.scalars(
            select(Interpretation).where(
                Interpretation.user_id == self.user_id, Interpretation.id.in_(ids)
            )
        )
        return list(rows.all())

    async def evidence_for(
        self, interpretation_ids: Iterable[uuid.UUID | str]
    ) -> dict[str, list[tuple[Evidence, Signal]]]:
        ids = [_as_uuid(i) for i in dict.fromkeys(str(i) for i in interpretation_ids)]
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(Evidence, Signal)
                .join(Signal, Signal.id == Evidence.signal_id)
                .join(Interpretation, Interpretation.id == Evidence.interpretation_id)
                .where(Interpretation.user_id == self.user_id, Evidence.interpretation_id.in_(ids))
                .order_by(Signal.observed_at.asc())
            )
        ).all()
        out: dict[str, list[tuple[Evidence, Signal]]] = {str(i): [] for i in ids}
        for evidence, signal in rows:
            out[str(evidence.interpretation_id)].append((evidence, signal))
        return out

    async def load_interpretations(
        self, interpretation_ids: Iterable[uuid.UUID | str] | None = None
    ) -> tuple[list[Interpretation], dict[str, InterpretationIn]]:
        """Rows plus the engine's view of them, evidence and assertions included."""
        rows = (
            await self.open_interpretations()
            if interpretation_ids is None
            else await self.interpretations_by_id(interpretation_ids)
        )
        evidence = await self.evidence_for([r.id for r in rows])
        supports = await self.assertion_supports([r.id for r in rows])
        views = {
            str(row.id): interpretation_in(
                row, evidence.get(str(row.id), []), supports.get(str(row.id), [])
            )
            for row in rows
        }
        return rows, views

    async def assertion_supports(
        self, interpretation_ids: Iterable[uuid.UUID | str]
    ) -> dict[str, list[EvidenceIn]]:
        """``amend`` assertions act as dated supports on the row they authored."""
        ids = [_as_uuid(i) for i in dict.fromkeys(str(i) for i in interpretation_ids)]
        if not ids:
            return {}
        rows = await self.session.scalars(
            select(UserAssertion).where(
                UserAssertion.user_id == self.user_id,
                UserAssertion.status == "active",
                UserAssertion.kind == "amend",
                UserAssertion.applies_to_interpretation_id.in_(ids),
            )
        )
        out: dict[str, list[EvidenceIn]] = {}
        for row in rows.all():
            out.setdefault(str(row.applies_to_interpretation_id), []).append(assertion_support(row))
        return out

    async def create_interpretation(self, **values: Any) -> Interpretation:
        row = Interpretation(user_id=self.user_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_evidence(
        self,
        interpretation_id: uuid.UUID | str,
        signal_id: uuid.UUID | str,
        *,
        role: str = "supports",
        weight: float = 1.0,
        note: str | None = None,
        job_id: uuid.UUID | None = None,
    ) -> Evidence | None:
        """Add a link, unless an active one already exists (the partial unique index)."""
        existing = await self.session.scalar(
            select(Evidence).where(
                Evidence.interpretation_id == _as_uuid(interpretation_id),
                Evidence.signal_id == _as_uuid(signal_id),
                Evidence.removed_at.is_(None),
            )
        )
        if existing is not None:
            return None
        row = Evidence(
            interpretation_id=_as_uuid(interpretation_id),
            signal_id=_as_uuid(signal_id),
            role=role,
            weight=weight,
            note=note,
            added_job_id=job_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def remove_evidence(
        self,
        interpretation_id: uuid.UUID | str,
        signal_ids: Sequence[uuid.UUID | str],
        *,
        at: datetime,
        reason: str,
    ) -> int:
        if not signal_ids:
            return 0
        result = await self.session.execute(
            update(Evidence)
            .where(
                Evidence.interpretation_id == _as_uuid(interpretation_id),
                Evidence.signal_id.in_([_as_uuid(s) for s in signal_ids]),
                Evidence.removed_at.is_(None),
            )
            .values(removed_at=at, removed_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def write_event(
        self,
        event: str,
        *,
        interpretation_id: uuid.UUID | str | None = None,
        recognition_id: uuid.UUID | str | None = None,
        payload: Mapping[str, Any] | None = None,
        actor: str = "system",
        feedback_id: uuid.UUID | str | None = None,
    ) -> RecognitionEvent:
        row = RecognitionEvent(
            user_id=self.user_id,
            interpretation_id=_as_uuid(interpretation_id) if interpretation_id else None,
            recognition_id=_as_uuid(recognition_id) if recognition_id else None,
            event=event,
            payload=dict(payload or {}),
            actor=actor,
            feedback_id=_as_uuid(feedback_id) if feedback_id else None,
        )
        self.session.add(row)
        return row

    async def last_evaluation(
        self, interpretation_id: uuid.UUID | str
    ) -> ThresholdEvaluation | None:
        return await self.session.scalar(
            select(ThresholdEvaluation)
            .where(
                ThresholdEvaluation.user_id == self.user_id,
                ThresholdEvaluation.interpretation_id == _as_uuid(interpretation_id),
            )
            .order_by(ThresholdEvaluation.created_at.desc())
            .limit(1)
        )

    async def write_evaluation(
        self,
        *,
        outcome: str,
        reason: str | None,
        rules: list[dict[str, Any]],
        interpretation_id: uuid.UUID | str | None = None,
        candidate_text: str | None = None,
        confidence: float | None = None,
        timezone_used: str = "UTC",
        policy_version: str = "thr-v1",
    ) -> ThresholdEvaluation:
        row = ThresholdEvaluation(
            user_id=self.user_id,
            interpretation_id=_as_uuid(interpretation_id) if interpretation_id else None,
            candidate_text=candidate_text,
            policy_version=policy_version,
            timezone_used=timezone_used,
            outcome=outcome,
            reason=reason,
            rules=rules,
            confidence_at_eval=confidence,
        )
        self.session.add(row)
        return row

    # -- claim matches ----------------------------------------------------------

    async def claim_matches(
        self, interpretation_ids: Iterable[uuid.UUID | str]
    ) -> list[ClaimMatchIn]:
        ids = [_as_uuid(i) for i in dict.fromkeys(str(i) for i in interpretation_ids)]
        if not ids:
            return []
        rows = await self.session.scalars(
            select(ClaimMatch).where(
                ClaimMatch.user_id == self.user_id, ClaimMatch.interpretation_id.in_(ids)
            )
        )
        return [
            ClaimMatchIn(
                interpretation_id=str(r.interpretation_id),
                target_kind=r.target_kind,
                target_id=str(r.target_id),
                same=bool(r.same),
                cosine=_f(r.cosine),
                decided_by=r.decided_by,
            )
            for r in rows.all()
        ]

    async def save_claim_match(self, match: ClaimMatchIn, *, why: str | None = None) -> None:
        """Decided once per pair — the unique index is what "once" means."""
        stmt = pg_insert(ClaimMatch).values(
            user_id=self.user_id,
            interpretation_id=_as_uuid(match.interpretation_id),
            target_kind=match.target_kind,
            target_id=_as_uuid(match.target_id),
            cosine=match.cosine,
            decided_by=match.decided_by,
            same=match.same,
            why=why,
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    ClaimMatch.interpretation_id,
                    ClaimMatch.target_kind,
                    ClaimMatch.target_id,
                ],
                set_={
                    "cosine": stmt.excluded.cosine,
                    "decided_by": stmt.excluded.decided_by,
                    "same": stmt.excluded.same,
                    "why": stmt.excluded.why,
                },
            )
        )

    # -- assertions, memory, profile --------------------------------------------

    async def assertions(self, *, kind: str | None = None) -> list[UserAssertion]:
        where = [UserAssertion.user_id == self.user_id, UserAssertion.status == "active"]
        if kind is not None:
            where.append(UserAssertion.kind == kind)
        rows = await self.session.scalars(
            select(UserAssertion).where(*where).order_by(UserAssertion.created_at.asc())
        )
        return list(rows.all())

    async def create_assertion(self, **values: Any) -> UserAssertion:
        row = UserAssertion(user_id=self.user_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def denied_statements(self, *, limit: int = 40) -> list[str]:
        """The do-not-repropose list: what the user has already said is wrong."""
        denials = await self.assertions(kind="deny")
        retired = await self.session.scalars(
            select(Interpretation.statement)
            .where(
                Interpretation.user_id == self.user_id,
                Interpretation.lifecycle_status == "retired",
                Interpretation.gate_reason == "user_denied",
            )
            .limit(limit)
        )
        seen = [a.statement for a in denials] + list(retired.all())
        return list(dict.fromkeys(s for s in seen if s))[:limit]

    async def active_memory(self, *, limit: int = 200) -> list[MemoryItem]:
        rows = await self.session.scalars(
            select(MemoryItem)
            .where(MemoryItem.user_id == self.user_id, MemoryItem.status == "active")
            .order_by(MemoryItem.pinned.desc(), MemoryItem.last_confirmed_at.desc().nullslast())
            .limit(limit)
        )
        return list(rows.all())

    async def latest_profile(self) -> UserProfile | None:
        return await self.session.scalar(
            select(UserProfile)
            .where(UserProfile.user_id == self.user_id)
            .order_by(UserProfile.version.desc())
            .limit(1)
        )

    async def add_profile(self, **values: Any) -> UserProfile:
        row = UserProfile(user_id=self.user_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    # -- recognitions -----------------------------------------------------------

    async def card_budget(self, *, today: str, timezone: str) -> CardBudget:
        rows = await self.session.scalars(
            select(Recognition).where(
                Recognition.user_id == self.user_id, Recognition.state != "withdrawn"
            )
        )
        cards = list(rows.all())
        pending = sum(1 for c in cards if c.state in OPEN_CARD_STATES)
        created = sum(1 for c in cards if _local_day(c.created_at, timezone) == today)
        waiting = await self.session.scalar(
            select(func.count())
            .select_from(Interpretation)
            .where(
                Interpretation.user_id == self.user_id,
                Interpretation.gate_outcome == "recognize",
                Interpretation.lifecycle_status == "candidate",
            )
        )
        return CardBudget(
            open_cards=pending + int(waiting or 0),
            created_today=created,
            has_card_for_version=frozenset(
                (str(c.interpretation_id), int(c.interpretation_version)) for c in cards
            ),
        )

    async def card_for_version(
        self, interpretation_id: uuid.UUID | str, version: int
    ) -> Recognition | None:
        return await self.session.scalar(
            select(Recognition).where(
                Recognition.user_id == self.user_id,
                Recognition.interpretation_id == _as_uuid(interpretation_id),
                Recognition.interpretation_version == version,
                Recognition.state != "withdrawn",
            )
        )

    async def cards_for(
        self, interpretation_ids: Iterable[uuid.UUID | str], *, states: Sequence[str]
    ) -> list[Recognition]:
        ids = [_as_uuid(i) for i in dict.fromkeys(str(i) for i in interpretation_ids)]
        if not ids:
            return []
        rows = await self.session.scalars(
            select(Recognition).where(
                Recognition.user_id == self.user_id,
                Recognition.interpretation_id.in_(ids),
                Recognition.state.in_(list(states)),
            )
        )
        return list(rows.all())

    async def recognition(self, recognition_id: uuid.UUID | str) -> Recognition | None:
        return await self.session.scalar(
            select(Recognition).where(
                Recognition.user_id == self.user_id, Recognition.id == _as_uuid(recognition_id)
            )
        )

    async def create_recognition(self, **values: Any) -> Recognition:
        row = Recognition(user_id=self.user_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_provenance(self, recognition_id: uuid.UUID, rows: Sequence[ProvenanceRow]) -> int:
        for row in rows:
            self.session.add(
                RecognitionProvenance(
                    recognition_id=recognition_id,
                    kind=row.kind,
                    signal_id=_as_uuid(row.signal_id) if row.kind == "signal" else None,
                    message_id=_as_uuid(row.message_id) if row.message_id else None,
                    conversation_id=(
                        _as_uuid(row.conversation_id) if row.conversation_id else None
                    ),
                    conversation_title=row.conversation_title,
                    seq=row.seq,
                    quote_text=row.quote_text,
                    quote_start=row.quote_start,
                    quote_end=row.quote_end,
                    message_created_at=row.message_created_at,
                    feedback_id=_as_uuid(row.feedback_id) if row.feedback_id else None,
                    role=row.role,
                    weight=row.weight,
                    display_order=row.display_order,
                    note=row.note,
                )
            )
        return len(rows)

    # -- feedback ---------------------------------------------------------------

    async def feedback(self, feedback_id: uuid.UUID | str) -> RecognitionFeedback | None:
        return await self.session.scalar(
            select(RecognitionFeedback).where(
                RecognitionFeedback.user_id == self.user_id,
                RecognitionFeedback.id == _as_uuid(feedback_id),
            )
        )

    async def correction_effect(self, feedback_id: uuid.UUID | str) -> CorrectionEffect | None:
        return await self.session.scalar(
            select(CorrectionEffect).where(
                CorrectionEffect.user_id == self.user_id,
                CorrectionEffect.feedback_id == _as_uuid(feedback_id),
            )
        )

    async def write_correction_effect(
        self, feedback_id: uuid.UUID | str, **values: Any
    ) -> CorrectionEffect:
        row = await self.correction_effect(feedback_id)
        if row is None:
            row = CorrectionEffect(user_id=self.user_id, feedback_id=_as_uuid(feedback_id))
            self.session.add(row)
        for name, value in values.items():
            setattr(row, name, value)
        await self.session.flush()
        return row

    async def cascade_candidates(self, *, topic: str | None, limit: int = 50) -> list[str]:
        """Which claims a correction might have moved: same topic, then the rest.

        Cosine-based widening is applied by the caller through the ``Retriever``;
        this is the cheap half that needs no vector at all.
        """
        rows = await self.session.scalars(
            select(Interpretation.id)
            .where(
                Interpretation.user_id == self.user_id,
                Interpretation.lifecycle_status.in_(OPEN_LIFECYCLE),
                *([Interpretation.topic == topic] if topic else []),
            )
            .order_by(Interpretation.last_evaluated_at.asc().nullsfirst())
            .limit(limit)
        )
        return [str(i) for i in rows.all()]


def interpretation_in(
    row: Interpretation,
    evidence: Sequence[tuple[Evidence, Signal]],
    extra_supports: Sequence[EvidenceIn] = (),
) -> InterpretationIn:
    """The engine's read-only view of one interpretation row."""
    items = [
        EvidenceIn(
            signal=signal_in(signal),
            role=ev.role,  # type: ignore[arg-type]
            weight=_f(ev.weight, 1.0),
            id=str(ev.id),
            note=ev.note,
            removed_at=ev.removed_at,
        )
        for ev, signal in evidence
    ]
    return InterpretationIn(
        id=str(row.id),
        kind=row.kind,
        topic=row.topic,
        statement=row.statement,
        source=row.source,
        model_confidence=_f(row.model_confidence),
        version=int(row.version),
        lifecycle_status=row.lifecycle_status,
        cooldown_until=row.cooldown_until,
        dismiss_count=int(row.dismiss_count or 0),
        sensitive_category=row.sensitive_category,
        evidence=(*items, *extra_supports),
        created_at=row.created_at,
    )


def _as_uuid(value: uuid.UUID | str | None) -> Any:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _local_day(moment: datetime | None, timezone: str) -> str:
    from ros.engine.confidence import local_day

    return "" if moment is None else local_day(moment, timezone)


__all__ = [
    "OPEN_CARD_STATES",
    "OPEN_LIFECYCLE",
    "CardBudget",
    "ConversationRow",
    "EngineRepo",
    "MessageRow",
    "UserContext",
    "assertion_in",
    "assertion_support",
    "interpretation_in",
    "signal_in",
]
