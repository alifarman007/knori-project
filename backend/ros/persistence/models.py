"""ROS tables — the Recognition Operating System's data model (Sway-owned).

One table per step of the canonical loop, so that every Recognition can be traced
back to the exact words the user typed, and every decision *not* to recognise
something is written down too:

    Signal → Evidence → Interpretation → Confidence → Threshold → Recognition
          → Provenance → Correction → Updated understanding

Memory (what the user told KnoRI) is deliberately separate from Recognition
(what KnoRI noticed). See plan.md §4.1 and §5.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ros.persistence.base import Base, TimestampMixin, created_at_col, ts, uuid_pk

EMBEDDING_DIM = 1536

SIGNAL_KINDS = (
    "statement",
    "behavior",
    "preference",
    "value",
    "goal",
    "emotion",
    "situation",
    "reflection",
)
SIGNAL_SUBJECTS = ("self", "other", "hypothetical", "unclear")
INTERPRETATION_KINDS = ("pattern", "preference", "value", "tension")
LIFECYCLE_STATUS = ("candidate", "recognized", "superseded", "retired")
GATE_OUTCOMES = ("recognize", "hold", "suppress", "decline", "merge")
EVIDENCE_ROLES = ("supports", "contradicts", "context")
RECOGNITION_STATES = (
    "pending",
    "presented",
    "accepted",
    "corrected",
    "rejected",
    "dismissed",
    "withdrawn",
)
FEEDBACK_ACTIONS = ("accept", "correct", "reject", "dismiss")
ASSERTION_KINDS = ("affirm", "deny", "amend", "scope")
MEMORY_KINDS = (
    "fact",
    "preference",
    "goal",
    "event",
    "routine",
    "constraint",
    "relationship",
)
# Categories KnoRI never infers a Recognition from (plan §4.5 R6).
SENSITIVE_CATEGORIES = (
    "health",
    "mental_health",
    "sexual_orientation",
    "religion",
    "ethnicity",
    "immigration",
    "criminal",
    "politics",
    "financial_distress",
)


def _check(column: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    values = ", ".join(f"'{value}'" for value in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _embedding() -> Mapped[Any | None]:
    return mapped_column(Vector(EMBEDDING_DIM))


# ---------------------------------------------------------------------------- signal


class Signal(Base):
    """One observation taken from one user message. Immutable once written.

    ``quote_text``/``quote_start``/``quote_end`` are verified against the stored
    message before insert: if the quote cannot be found the signal is dropped and
    counted. Nothing downstream can invent evidence.
    """

    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Only `self` signals may support a Recognition (enforced in code, rule V1).
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="self")
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_end: Mapped[int] = mapped_column(Integer, nullable=False)
    polarity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strength: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0.6)
    sensitive_category: Mapped[str | None] = mapped_column(String(32))
    context_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extraction_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    interpreted_at: Mapped[datetime | None] = ts()
    embedding: Mapped[Any | None] = _embedding()
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("kind", SIGNAL_KINDS, "kind"),
        _check("subject", SIGNAL_SUBJECTS, "subject"),
        CheckConstraint("quote_end > quote_start", name="quote_span"),
        CheckConstraint("polarity BETWEEN -1 AND 1", name="polarity"),
        CheckConstraint("strength > 0 AND strength <= 1", name="strength"),
        Index("ix_signals_user_topic", "user_id", "topic"),
        Index("ix_signals_user_observed", "user_id", "observed_at"),
        Index("ix_signals_message", "message_id"),
        Index(
            "ix_signals_uninterpreted",
            "user_id",
            postgresql_where=text("interpreted_at IS NULL"),
        ),
    )


# -------------------------------------------------------------------- interpretation


class Interpretation(Base, TimestampMixin):
    """A claim about the user that the engine is considering."""

    __tablename__ = "interpretations"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    lifecycle_status: Mapped[str] = mapped_column(Text, nullable=False, default="candidate")
    gate_outcome: Mapped[str | None] = mapped_column(Text)
    gate_reason: Mapped[str | None] = mapped_column(String(48))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    confidence_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    confidence_version: Mapped[str] = mapped_column(String(16), nullable=False, default="conf-v1")
    # 1.0 for rows the user wrote themselves (an amended claim).
    model_confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="model")
    sensitive_category: Mapped[str | None] = mapped_column(String(32))
    # Phase 2 keeps competing readings of the same evidence in one group.
    group_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("interpretations.id", ondelete="SET NULL")
    )
    cooldown_until: Mapped[datetime | None] = ts()
    dismiss_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_evaluated_at: Mapped[datetime | None] = ts()
    embedding: Mapped[Any | None] = _embedding()
    embedding_model: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        _check("kind", INTERPRETATION_KINDS, "kind"),
        _check("lifecycle_status", LIFECYCLE_STATUS, "lifecycle_status"),
        _check("source", ("model", "user_correction"), "source"),
        CheckConstraint(
            "gate_outcome IS NULL OR gate_outcome IN "
            "('recognize','hold','suppress','decline','merge')",
            name="ck_interpretations_gate_outcome",
        ),
        Index("ix_interpretations_user_status", "user_id", "lifecycle_status"),
        Index("ix_interpretations_user_topic", "user_id", "topic"),
    )


class Evidence(Base):
    """Links a signal to an interpretation. Removal is soft, so history survives."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    interpretation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("interpretations.id", ondelete="CASCADE"), nullable=False
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, default="supports")
    weight: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=1.0)
    note: Mapped[str | None] = mapped_column(Text)
    added_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    removed_at: Mapped[datetime | None] = ts()
    removed_reason: Mapped[str | None] = mapped_column(String(48))
    # Phase 2 hooks: unused in Phase 1, present so no rebuild is needed.
    temporal_weight: Mapped[float | None] = mapped_column(Numeric(3, 2))
    context_weight: Mapped[float | None] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("role", EVIDENCE_ROLES, "role"),
        CheckConstraint("weight >= 0 AND weight <= 1", name="weight"),
        Index(
            "uq_evidence_active",
            "interpretation_id",
            "signal_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_evidence_signal", "signal_id"),
    )


class ClaimMatch(Base):
    """ "Is this the same claim?" decided once per pair, before the threshold runs.

    Keeping the judge out of ``thr-v1`` is what lets the threshold stay a pure,
    table-tested function (CLAUDE.md engine rule 3).
    """

    __tablename__ = "claim_matches"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    interpretation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("interpretations.id", ondelete="CASCADE"), nullable=False
    )
    target_kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    cosine: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False, default="cosine")
    same: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    why: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("target_kind", ("assertion", "memory_item", "interpretation"), "target_kind"),
        _check("decided_by", ("cosine", "judge"), "decided_by"),
        UniqueConstraint(
            "interpretation_id",
            "target_kind",
            "target_id",
            name="uq_claim_matches_interpretation_id_target_kind_target_id",
        ),
    )


class ThresholdEvaluation(Base):
    """The ledger of every decision, including every decision *not* to recognise."""

    __tablename__ = "threshold_evaluations"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    interpretation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("interpretations.id", ondelete="CASCADE")
    )
    # Set when the model itself declined and no interpretation row was ever created.
    candidate_text: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(16), nullable=False, default="thr-v1")
    timezone_used: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(48))
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    confidence_at_eval: Mapped[float | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("outcome", GATE_OUTCOMES, "outcome"),
        Index("ix_threshold_evaluations_user_created", "user_id", "created_at"),
        Index("ix_threshold_evaluations_interpretation", "interpretation_id"),
    )


# ----------------------------------------------------------------------- recognition


class Recognition(Base, TimestampMixin):
    """The card the user sees. One per interpretation version, ever."""

    __tablename__ = "recognitions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    interpretation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("interpretations.id", ondelete="CASCADE"), nullable=False
    )
    interpretation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    body: Mapped[str] = mapped_column(String(400), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    confidence_label: Mapped[str] = mapped_column(Text, nullable=False, default="likely")
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recognitions.id", ondelete="SET NULL")
    )
    withdrawn_reason: Mapped[str | None] = mapped_column(String(48))
    presented_at: Mapped[datetime | None] = ts()
    resolved_at: Mapped[datetime | None] = ts()
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        _check("kind", INTERPRETATION_KINDS, "kind"),
        _check("state", RECOGNITION_STATES, "state"),
        _check("confidence_label", ("likely", "strong"), "confidence_label"),
        Index("ix_recognitions_user_state", "user_id", "state"),
        Index("ix_recognitions_user_created", "user_id", "created_at"),
        Index(
            "uq_recognitions_interpretation_version",
            "interpretation_id",
            "interpretation_version",
            unique=True,
            postgresql_where=text("state <> 'withdrawn'"),
        ),
    )


class RecognitionProvenance(Base):
    """Frozen copy of the evidence at the moment the card was written.

    The quote is scrubbed (not deleted) if the user deletes the source message, so a
    card can still show *that* it had evidence without keeping text the user removed.
    """

    __tablename__ = "recognition_provenance"

    id: Mapped[uuid.UUID] = uuid_pk()
    recognition_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recognitions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="signal")
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("signals.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    conversation_title: Mapped[str | None] = mapped_column(String(120))
    seq: Mapped[int | None] = mapped_column(Integer)
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    message_created_at: Mapped[datetime | None] = ts()
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    role: Mapped[str] = mapped_column(Text, nullable=False, default="supports")
    weight: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=1.0)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    scrubbed_at: Mapped[datetime | None] = ts()
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("kind", ("signal", "assertion"), "kind"),
        _check("role", EVIDENCE_ROLES, "role"),
        Index("ix_recognition_provenance_recognition", "recognition_id", "display_order"),
        Index("ix_recognition_provenance_message", "message_id"),
    )


class RecognitionEvent(Base):
    """Append-only history. Phase 3 reads this table as-is."""

    __tablename__ = "recognition_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    interpretation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("interpretations.id", ondelete="CASCADE")
    )
    recognition_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recognitions.id", ondelete="CASCADE")
    )
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    actor: Mapped[str] = mapped_column(Text, nullable=False, default="system")
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("actor", ("user", "system"), "actor"),
        Index("ix_recognition_events_recognition", "recognition_id", "created_at"),
        Index("ix_recognition_events_interpretation", "interpretation_id", "created_at"),
    )


class RecognitionFeedback(Base):
    """What the user did with a card."""

    __tablename__ = "recognition_feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    recognition_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recognitions.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    correction_text: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(String(32))
    processed_at: Mapped[datetime | None] = ts()
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("action", FEEDBACK_ACTIONS, "action"),
        Index("ix_recognition_feedback_recognition", "recognition_id"),
    )


class UserAssertion(Base):
    """A correction, stored as a durable claim the engine must respect from now on."""

    __tablename__ = "user_assertions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # The bare claim in the third person — no "the user says it is not true that…".
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str | None] = mapped_column(String(64))
    applies_to_interpretation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("interpretations.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, default="feedback")
    source_feedback_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recognition_feedback.id", ondelete="SET NULL")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    weight: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    retracted_at: Mapped[datetime | None] = ts()
    embedding: Mapped[Any | None] = _embedding()
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("kind", ASSERTION_KINDS, "kind"),
        _check("status", ("active", "retracted"), "status"),
        _check("source", ("feedback", "onboarding", "memory_ui"), "source"),
        Index("ix_user_assertions_user_status", "user_id", "status"),
    )


class CorrectionEffect(Base):
    """What a single piece of feedback actually changed — the "what changed" panel."""

    __tablename__ = "correction_effects"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recognition_feedback.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    recognitions_withdrawn: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    recognitions_created: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    assertions_created: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Inline snapshots so the before/after diff survives profile pruning.
    profile_before_text: Mapped[str | None] = mapped_column(Text)
    profile_after_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = created_at_col()
    ready_at: Mapped[datetime | None] = ts()

    __table_args__ = (_check("status", ("pending", "ready"), "status"),)


# --------------------------------------------------------------------------- memory


class MemoryItem(Base, TimestampMixin):
    """What the user told KnoRI. Visible from the first conversation, always editable."""

    __tablename__ = "memory_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str | None] = mapped_column(String(64))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="extracted")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_confirmed_at: Mapped[datetime | None] = ts()
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="SET NULL")
    )
    sensitive_category: Mapped[str | None] = mapped_column(String(32))
    retracted_reason: Mapped[str | None] = mapped_column(String(48))
    embedding: Mapped[Any | None] = _embedding()
    embedding_model: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        _check("kind", MEMORY_KINDS, "kind"),
        _check("status", ("active", "superseded", "retracted"), "status"),
        _check(
            "source",
            ("extracted", "onboarding", "user_added", "user_edited", "correction"),
            "source",
        ),
        Index("ix_memory_items_user_status", "user_id", "status"),
        Index(
            "uq_memory_items_active_key",
            "user_id",
            "key",
            unique=True,
            postgresql_where=text("status = 'active' AND key IS NOT NULL"),
        ),
    )


class MemorySource(Base):
    """Where a memory came from: the message and the words in it."""

    __tablename__ = "memory_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    memory_item_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint(
            "memory_item_id", "message_id", name="uq_memory_sources_memory_item_id_message_id"
        ),
    )


class UserProfile(Base):
    """ "How KnoRI sees you" — regenerated from memory, accepted cards and corrections."""

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    profile_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    built_from: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    inputs_hash: Mapped[str | None] = mapped_column(String(64))
    trigger: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_user_profiles_user_id_version"),
    )


# ------------------------------------------------------------------------- llm calls


class LlmCall(Base):
    """Every model call, with its cost. Feeds the cost caps and /admin/costs."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    # SET NULL on purge so cost history survives account deletion.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    task: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    prompt_hash: Mapped[str | None] = mapped_column(String(16))
    effort: Mapped[str | None] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cache_read_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cache_write_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0, server_default="0"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("status", ("ok", "error", "refused", "truncated"), "status"),
        Index("ix_llm_calls_task_created", "task", "created_at"),
    )
