"""Product tables: accounts, conversations, jobs and operations.

The Recognition tables live in ``ros.persistence.models`` — they are the Sway-owned
part of the system. Both share one metadata (``ros.persistence.base.Base``) so a
single Alembic history covers the whole database.

Conventions (CLAUDE.md → Data rules):
* every user-owned table has ``user_id`` and every query filters by it;
* status/kind columns are text + CHECK, never Postgres enums, so later phases can
  add values with a plain migration;
* every foreign key spells out its ON DELETE behaviour.
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
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ros.persistence.base import Base, TimestampMixin, created_at_col, ts, uuid_pk

EMBEDDING_DIM = 1536

USER_ROLES = ("user", "admin")
USER_STATUS = ("active", "deleting", "deleted")
CONVERSATION_KINDS = ("chat", "onboarding")
MESSAGE_ROLES = ("user", "assistant")
MESSAGE_STATUS = ("complete", "streaming", "partial", "failed")
JOB_STATUS = ("queued", "running", "done", "failed", "dead")
JOB_LANES = ("fast", "slow")


def _check(column: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    values = ", ".join(f"'{value}'" for value in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)


# --------------------------------------------------------------------------- accounts


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # What KnoRI calls the person in conversation; set during onboarding.
    preferred_name: Mapped[str | None] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    email_verified_at: Mapped[datetime | None] = ts()
    onboarding_completed_at: Mapped[datetime | None] = ts()
    last_seen_at: Mapped[datetime | None] = ts()
    deleted_at: Mapped[datetime | None] = ts()
    purge_after: Mapped[datetime | None] = ts()

    __table_args__ = (
        _check("role", USER_ROLES, "role"),
        _check("status", USER_STATUS, "status"),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = ts()
    revoked_at: Mapped[datetime | None] = ts()
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = ts()
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (_check("purpose", ("verify_email", "reset_password"), "purpose"),)


class UserSettings(Base):
    """One row per user, created with defaults at signup."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    recognition_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_recognitions_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    chat_style: Mapped[str] = mapped_column(Text, nullable=False, default="warm")
    # One-time UI flags, e.g. {"first_card_explainer_seen": true}
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        _check("chat_style", ("warm", "direct"), "chat_style"),
        CheckConstraint("max_recognitions_per_day BETWEEN 0 AND 5", name="max_per_day"),
    )


class LegalAcceptance(Base):
    __tablename__ = "legal_acceptances"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tos_version: Mapped[str] = mapped_column(String(32), nullable=False)
    privacy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = created_at_col()


class InviteCode(Base):
    """Invite-only signup keeps strangers off the API bill during beta (plan §2.4)."""

    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    note: Mapped[str | None] = mapped_column(Text)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = ts()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Kept when the account is purged, so the trail survives (plan §4.7).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (_check("actor", ("user", "admin", "system"), "actor"),)


# ----------------------------------------------------------------------- conversation


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="chat")
    title: Mapped[str | None] = mapped_column(String(120))
    is_incognito: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # seq allocation happens under a row lock on this table (plan §5.1).
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = ts()
    archived_at: Mapped[datetime | None] = ts()
    # Rolling summary of everything up to summary_upto_seq.
    summary: Mapped[str | None] = mapped_column(Text)
    summary_upto_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_threads: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    summarised_at: Mapped[datetime | None] = ts()
    ended_at: Mapped[datetime | None] = ts()

    __table_args__ = (
        _check("kind", CONVERSATION_KINDS, "kind"),
        Index("ix_conversations_user_recent", "user_id", "last_message_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="complete")
    # Set by the client so a retry after a dropped stream does not duplicate the turn.
    client_message_id: Mapped[str | None] = mapped_column(String(64))
    # user rows only: when extraction ran (NULL = still to do)
    extracted_at: Mapped[datetime | None] = ts()
    # assistant rows only: which memories/recognitions went into the prompt
    context_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    # user rows only: used for cross-conversation retrieval
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
        _check("role", MESSAGE_ROLES, "role"),
        _check("status", MESSAGE_STATUS, "status"),
        Index("ix_messages_user_created", "user_id", "created_at"),
        Index(
            "ix_messages_unextracted",
            "conversation_id",
            postgresql_where=text("role = 'user' AND extracted_at IS NULL"),
        ),
    )


class ConversationEvent(Base):
    """Places a Recognition card inside a thread without pretending it is a message."""

    __tablename__ = "conversation_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="recognition")
    after_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recognition_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recognitions.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("kind", ("recognition",), "kind"),
        Index("ix_conversation_events_thread", "conversation_id", "after_seq"),
    )


# ------------------------------------------------------------------------------ jobs


class Job(Base):
    """Postgres is the queue (plan §3.4). Enqueue happens in the caller's transaction."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    lane: Mapped[str] = mapped_column(Text, nullable=False, default="fast")
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    locked_at: Mapped[datetime | None] = ts()
    locked_by: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = ts()
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # One queued job per key (a *running* job does not block a new queued one).
    dedupe_key: Mapped[str | None] = mapped_column(String(128))
    # One running job per key: serialises interpret/feedback per user.
    lock_key: Mapped[str | None] = mapped_column(String(128))
    finished_at: Mapped[datetime | None] = ts()
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        _check("status", JOB_STATUS, "status"),
        _check("lane", JOB_LANES, "lane"),
        Index(
            "ix_jobs_claim",
            "lane",
            "priority",
            "run_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "uq_jobs_dedupe_queued",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "uq_jobs_lock_running",
            "lock_key",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_beat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[str | None] = mapped_column(String(64))


class SystemStatus(Base):
    """Small key/value table for things ops needs to see: backup age, last eval run."""

    __tablename__ = "system_status"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserDailyUsage(Base):
    """Cheap per-user spend counter so caps can be enforced without scanning llm_calls."""

    __tablename__ = "user_daily_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD, UTC
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chat_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
