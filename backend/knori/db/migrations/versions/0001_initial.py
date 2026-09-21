"""baseline: every Phase 1 table, index and check constraint

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-21

Hand-maintained baseline for KnoRI Phase 1. It creates the product tables
(``knori.db.models``) and the ROS tables (``ros.persistence.models``) as one schema,
in foreign-key order, exactly as the two model modules declare them.

Two things are easy to miss when reading it:

* the ``vector`` extension is created first — every embedding column needs it;
* several CHECK constraints are named ``ck_<table>_ck_<table>_<rule>``. That double
  prefix comes from the naming convention in ``ros/persistence/base.py`` being applied
  to a constraint that was already given an explicit ``ck_...`` name. The names here
  match the models on purpose, so ``alembic check`` stays quiet.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "system_status",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_status")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("preferred_name", sa.String(length=80), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'admin')", name=op.f("ck_users_role")),
        sa.CheckConstraint(
            "status IN ('active', 'deleting', 'deleted')", name=op.f("ck_users_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_created_at"), "users", ["created_at"], unique=False)
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column(
            "last_beat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_heartbeats")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("actor IN ('user', 'admin', 'system')", name=op.f("ck_audit_log_actor")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_index(
        op.f("ix_auth_sessions_created_at"), "auth_sessions", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("is_incognito", sa.Boolean(), nullable=False),
        sa.Column("last_seq", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_upto_seq", sa.Integer(), nullable=False),
        sa.Column("open_threads", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summarised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('chat', 'onboarding')", name=op.f("ck_conversations_kind")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_conversations_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index(
        op.f("ix_conversations_created_at"), "conversations", ["created_at"], unique=False
    )
    op.create_index(
        "ix_conversations_user_recent",
        "conversations",
        ["user_id", "last_message_at"],
        unique=False,
    )
    op.create_table(
        "email_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')", name=op.f("ck_email_tokens_purpose")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_email_tokens_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_email_tokens_created_at"), "email_tokens", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_email_tokens_user_id"), "email_tokens", ["user_id"], unique=False)
    op.create_table(
        "interpretations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("lifecycle_status", sa.Text(), nullable=False),
        sa.Column("gate_outcome", sa.Text(), nullable=True),
        sa.Column("gate_reason", sa.String(length=48), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("confidence_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_version", sa.String(length=16), nullable=False),
        sa.Column("model_confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("sensitive_category", sa.String(length=32), nullable=True),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismiss_count", sa.Integer(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "gate_outcome IS NULL OR gate_outcome IN ('recognize','hold','suppress','decline','merge')",
            name=op.f("ck_interpretations_ck_interpretations_gate_outcome"),
        ),
        sa.CheckConstraint(
            "kind IN ('pattern', 'preference', 'value', 'tension')",
            name=op.f("ck_interpretations_kind"),
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('candidate', 'recognized', 'superseded', 'retired')",
            name=op.f("ck_interpretations_lifecycle_status"),
        ),
        sa.CheckConstraint(
            "source IN ('model', 'user_correction')", name=op.f("ck_interpretations_source")
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["interpretations.id"],
            name=op.f("fk_interpretations_supersedes_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_interpretations_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interpretations")),
    )
    op.create_index(
        op.f("ix_interpretations_created_at"), "interpretations", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_interpretations_user_id"), "interpretations", ["user_id"], unique=False
    )
    op.create_index(
        "ix_interpretations_user_status",
        "interpretations",
        ["user_id", "lifecycle_status"],
        unique=False,
    )
    op.create_index(
        "ix_interpretations_user_topic", "interpretations", ["user_id", "topic"], unique=False
    )
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_invite_codes_created_by"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invite_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_invite_codes_code")),
    )
    op.create_index(
        op.f("ix_invite_codes_created_at"), "invite_codes", ["created_at"], unique=False
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column("lock_key", sa.String(length=128), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("lane IN ('fast', 'slow')", name=op.f("ck_jobs_lane")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'dead')", name=op.f("ck_jobs_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_jobs_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["lane", "priority", "run_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(op.f("ix_jobs_created_at"), "jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)
    op.create_index(
        "uq_jobs_dedupe_queued",
        "jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "uq_jobs_lock_running",
        "jobs",
        ["lock_key"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_table(
        "legal_acceptances",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("tos_version", sa.String(length=32), nullable=False),
        sa.Column("privacy_version", sa.String(length=32), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_legal_acceptances_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_acceptances")),
    )
    op.create_index(
        op.f("ix_legal_acceptances_created_at"), "legal_acceptances", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_legal_acceptances_user_id"), "legal_acceptances", ["user_id"], unique=False
    )
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("task", sa.String(length=48), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_name", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=16), nullable=True),
        sa.Column("prompt_hash", sa.String(length=16), nullable=True),
        sa.Column("effort", sa.String(length=16), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), nullable=False, server_default="0"
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'error', 'refused', 'truncated')", name=op.f("ck_llm_calls_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_llm_calls_user_id"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(op.f("ix_llm_calls_created_at"), "llm_calls", ["created_at"], unique=False)
    op.create_index("ix_llm_calls_task_created", "llm_calls", ["task", "created_at"], unique=False)
    op.create_index(op.f("ix_llm_calls_user_id"), "llm_calls", ["user_id"], unique=False)
    op.create_table(
        "memory_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("confirmations", sa.Integer(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("sensitive_category", sa.String(length=32), nullable=True),
        sa.Column("retracted_reason", sa.String(length=48), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('fact', 'preference', 'goal', 'event', 'routine', 'constraint', 'relationship')",
            name=op.f("ck_memory_items_kind"),
        ),
        sa.CheckConstraint(
            "source IN ('extracted', 'onboarding', 'user_added', 'user_edited', 'correction')",
            name=op.f("ck_memory_items_source"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')", name=op.f("ck_memory_items_status")
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["memory_items.id"],
            name=op.f("fk_memory_items_superseded_by_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memory_items_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_items")),
    )
    op.create_index(
        op.f("ix_memory_items_created_at"), "memory_items", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_memory_items_user_id"), "memory_items", ["user_id"], unique=False)
    op.create_index(
        "ix_memory_items_user_status", "memory_items", ["user_id", "status"], unique=False
    )
    op.create_index(
        "uq_memory_items_active_key",
        "memory_items",
        ["user_id", "key"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND key IS NOT NULL"),
    )
    op.create_table(
        "user_daily_usage",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), nullable=False, server_default="0"
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chat_messages", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_daily_usage_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "day", name=op.f("pk_user_daily_usage")),
    )
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile_text", sa.Text(), nullable=False),
        sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("built_from", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inputs_hash", sa.String(length=64), nullable=True),
        sa.Column("trigger", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_profiles_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profiles")),
        sa.UniqueConstraint("user_id", "version", name="uq_user_profiles_user_id_version"),
    )
    op.create_index(
        op.f("ix_user_profiles_created_at"), "user_profiles", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_user_profiles_user_id"), "user_profiles", ["user_id"], unique=False)
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("recognition_enabled", sa.Boolean(), nullable=False),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False),
        sa.Column("max_recognitions_per_day", sa.Integer(), nullable=False),
        sa.Column("chat_style", sa.Text(), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chat_style IN ('warm', 'direct')", name=op.f("ck_user_settings_chat_style")
        ),
        sa.CheckConstraint(
            "max_recognitions_per_day BETWEEN 0 AND 5",
            name=op.f("ck_user_settings_max_per_day"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_settings_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
    )
    op.create_table(
        "claim_matches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("interpretation_id", sa.UUID(), nullable=False),
        sa.Column("target_kind", sa.Text(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("cosine", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("same", sa.Boolean(), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decided_by IN ('cosine', 'judge')", name=op.f("ck_claim_matches_decided_by")
        ),
        sa.CheckConstraint(
            "target_kind IN ('assertion', 'memory_item', 'interpretation')",
            name=op.f("ck_claim_matches_target_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["interpretation_id"],
            ["interpretations.id"],
            name=op.f("fk_claim_matches_interpretation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_claim_matches_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_matches")),
        sa.UniqueConstraint(
            "interpretation_id",
            "target_kind",
            "target_id",
            name="uq_claim_matches_interpretation_id_target_kind_target_id",
        ),
    )
    op.create_index(
        op.f("ix_claim_matches_created_at"), "claim_matches", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_claim_matches_user_id"), "claim_matches", ["user_id"], unique=False)
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_call_id", sa.UUID(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_messages_role")),
        sa.CheckConstraint(
            "status IN ('complete', 'streaming', 'partial', 'failed')",
            name=op.f("ck_messages_status"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_messages_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
    )
    op.create_index(op.f("ix_messages_created_at"), "messages", ["created_at"], unique=False)
    op.create_index(
        "ix_messages_unextracted",
        "messages",
        ["conversation_id"],
        unique=False,
        postgresql_where=sa.text("role = 'user' AND extracted_at IS NULL"),
    )
    op.create_index("ix_messages_user_created", "messages", ["user_id", "created_at"], unique=False)
    op.create_index(op.f("ix_messages_user_id"), "messages", ["user_id"], unique=False)
    op.create_table(
        "recognitions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("interpretation_id", sa.UUID(), nullable=False),
        sa.Column("interpretation_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("body", sa.String(length=400), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("confidence_label", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("withdrawn_reason", sa.String(length=48), nullable=True),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_version", sa.String(length=16), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence_label IN ('likely', 'strong')",
            name=op.f("ck_recognitions_confidence_label"),
        ),
        sa.CheckConstraint(
            "kind IN ('pattern', 'preference', 'value', 'tension')",
            name=op.f("ck_recognitions_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'presented', 'accepted', 'corrected', 'rejected', 'dismissed', 'withdrawn')",
            name=op.f("ck_recognitions_state"),
        ),
        sa.ForeignKeyConstraint(
            ["interpretation_id"],
            ["interpretations.id"],
            name=op.f("fk_recognitions_interpretation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["recognitions.id"],
            name=op.f("fk_recognitions_supersedes_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_recognitions_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recognitions")),
    )
    op.create_index(
        op.f("ix_recognitions_created_at"), "recognitions", ["created_at"], unique=False
    )
    op.create_index(
        "ix_recognitions_user_created", "recognitions", ["user_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_recognitions_user_id"), "recognitions", ["user_id"], unique=False)
    op.create_index(
        "ix_recognitions_user_state", "recognitions", ["user_id", "state"], unique=False
    )
    op.create_index(
        "uq_recognitions_interpretation_version",
        "recognitions",
        ["interpretation_id", "interpretation_version"],
        unique=True,
        postgresql_where=sa.text("state <> 'withdrawn'"),
    )
    op.create_table(
        "threshold_evaluations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("interpretation_id", sa.UUID(), nullable=True),
        sa.Column("candidate_text", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.String(length=16), nullable=False),
        sa.Column("timezone_used", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=True),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_at_eval", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('recognize', 'hold', 'suppress', 'decline', 'merge')",
            name=op.f("ck_threshold_evaluations_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["interpretation_id"],
            ["interpretations.id"],
            name=op.f("fk_threshold_evaluations_interpretation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_threshold_evaluations_user_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threshold_evaluations")),
    )
    op.create_index(
        op.f("ix_threshold_evaluations_created_at"),
        "threshold_evaluations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_threshold_evaluations_interpretation",
        "threshold_evaluations",
        ["interpretation_id"],
        unique=False,
    )
    op.create_index(
        "ix_threshold_evaluations_user_created",
        "threshold_evaluations",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_threshold_evaluations_user_id"), "threshold_evaluations", ["user_id"], unique=False
    )
    op.create_table(
        "conversation_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("after_seq", sa.Integer(), nullable=False),
        sa.Column("recognition_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('recognition')", name=op.f("ck_conversation_events_kind")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_events_conversation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recognition_id"],
            ["recognitions.id"],
            name=op.f("fk_conversation_events_recognition_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_conversation_events_user_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_events")),
    )
    op.create_index(
        op.f("ix_conversation_events_created_at"),
        "conversation_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_events_thread",
        "conversation_events",
        ["conversation_id", "after_seq"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_events_user_id"), "conversation_events", ["user_id"], unique=False
    )
    op.create_table(
        "memory_sources",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("memory_item_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("quote_end", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["memory_item_id"],
            ["memory_items.id"],
            name=op.f("fk_memory_sources_memory_item_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_memory_sources_message_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_sources")),
        sa.UniqueConstraint(
            "memory_item_id", "message_id", name="uq_memory_sources_memory_item_id_message_id"
        ),
    )
    op.create_index(
        op.f("ix_memory_sources_created_at"), "memory_sources", ["created_at"], unique=False
    )
    op.create_table(
        "recognition_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("interpretation_id", sa.UUID(), nullable=True),
        sa.Column("recognition_id", sa.UUID(), nullable=True),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("actor IN ('user', 'system')", name=op.f("ck_recognition_events_actor")),
        sa.ForeignKeyConstraint(
            ["interpretation_id"],
            ["interpretations.id"],
            name=op.f("fk_recognition_events_interpretation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recognition_id"],
            ["recognitions.id"],
            name=op.f("fk_recognition_events_recognition_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_recognition_events_user_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recognition_events")),
    )
    op.create_index(
        op.f("ix_recognition_events_created_at"), "recognition_events", ["created_at"], unique=False
    )
    op.create_index(
        "ix_recognition_events_interpretation",
        "recognition_events",
        ["interpretation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_recognition_events_recognition",
        "recognition_events",
        ["recognition_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recognition_events_user_id"), "recognition_events", ["user_id"], unique=False
    )
    op.create_table(
        "recognition_feedback",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("recognition_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("correction_text", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.String(length=32), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('accept', 'correct', 'reject', 'dismiss')",
            name=op.f("ck_recognition_feedback_action"),
        ),
        sa.ForeignKeyConstraint(
            ["recognition_id"],
            ["recognitions.id"],
            name=op.f("fk_recognition_feedback_recognition_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_recognition_feedback_user_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recognition_feedback")),
    )
    op.create_index(
        op.f("ix_recognition_feedback_created_at"),
        "recognition_feedback",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_recognition_feedback_recognition",
        "recognition_feedback",
        ["recognition_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recognition_feedback_user_id"), "recognition_feedback", ["user_id"], unique=False
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=False),
        sa.Column("quote_end", sa.Integer(), nullable=False),
        sa.Column("polarity", sa.Integer(), nullable=False),
        sa.Column("strength", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("sensitive_category", sa.String(length=32), nullable=True),
        sa.Column("context_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extraction_job_id", sa.UUID(), nullable=True),
        sa.Column("interpreted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('statement', 'behavior', 'preference', 'value', 'goal', 'emotion', 'situation', 'reflection')",
            name=op.f("ck_signals_kind"),
        ),
        sa.CheckConstraint(
            "subject IN ('self', 'other', 'hypothetical', 'unclear')",
            name=op.f("ck_signals_subject"),
        ),
        sa.CheckConstraint("polarity BETWEEN -1 AND 1", name=op.f("ck_signals_polarity")),
        sa.CheckConstraint("quote_end > quote_start", name=op.f("ck_signals_quote_span")),
        sa.CheckConstraint("strength > 0 AND strength <= 1", name=op.f("ck_signals_strength")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_signals_conversation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name=op.f("fk_signals_message_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_signals_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    op.create_index(op.f("ix_signals_created_at"), "signals", ["created_at"], unique=False)
    op.create_index("ix_signals_message", "signals", ["message_id"], unique=False)
    op.create_index(
        "ix_signals_uninterpreted",
        "signals",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("interpreted_at IS NULL"),
    )
    op.create_index(op.f("ix_signals_user_id"), "signals", ["user_id"], unique=False)
    op.create_index("ix_signals_user_observed", "signals", ["user_id", "observed_at"], unique=False)
    op.create_index("ix_signals_user_topic", "signals", ["user_id", "topic"], unique=False)
    op.create_table(
        "correction_effects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("effects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recognitions_withdrawn", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("recognitions_created", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assertions_created", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("profile_before_text", sa.Text(), nullable=True),
        sa.Column("profile_after_text", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'ready')", name=op.f("ck_correction_effects_status")
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["recognition_feedback.id"],
            name=op.f("fk_correction_effects_feedback_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_correction_effects_user_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correction_effects")),
        sa.UniqueConstraint("feedback_id", name=op.f("uq_correction_effects_feedback_id")),
    )
    op.create_index(
        op.f("ix_correction_effects_created_at"), "correction_effects", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_correction_effects_user_id"), "correction_effects", ["user_id"], unique=False
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("interpretation_id", sa.UUID(), nullable=False),
        sa.Column("signal_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("added_job_id", sa.UUID(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_reason", sa.String(length=48), nullable=True),
        sa.Column("temporal_weight", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("context_weight", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('supports', 'contradicts', 'context')", name=op.f("ck_evidence_role")
        ),
        sa.CheckConstraint("weight >= 0 AND weight <= 1", name=op.f("ck_evidence_weight")),
        sa.ForeignKeyConstraint(
            ["interpretation_id"],
            ["interpretations.id"],
            name=op.f("fk_evidence_interpretation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["signals.id"], name=op.f("fk_evidence_signal_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    op.create_index(op.f("ix_evidence_created_at"), "evidence", ["created_at"], unique=False)
    op.create_index("ix_evidence_signal", "evidence", ["signal_id"], unique=False)
    op.create_index(
        "uq_evidence_active",
        "evidence",
        ["interpretation_id", "signal_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_table(
        "recognition_provenance",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("recognition_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("signal_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("conversation_title", sa.String(length=120), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("quote_end", sa.Integer(), nullable=True),
        sa.Column("message_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("scrubbed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('signal', 'assertion')", name=op.f("ck_recognition_provenance_kind")
        ),
        sa.CheckConstraint(
            "role IN ('supports', 'contradicts', 'context')",
            name=op.f("ck_recognition_provenance_role"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_recognition_provenance_conversation_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_recognition_provenance_message_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recognition_id"],
            ["recognitions.id"],
            name=op.f("fk_recognition_provenance_recognition_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_recognition_provenance_signal_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recognition_provenance")),
    )
    op.create_index(
        op.f("ix_recognition_provenance_created_at"),
        "recognition_provenance",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_recognition_provenance_message", "recognition_provenance", ["message_id"], unique=False
    )
    op.create_index(
        "ix_recognition_provenance_recognition",
        "recognition_provenance",
        ["recognition_id", "display_order"],
        unique=False,
    )
    op.create_table(
        "user_assertions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=True),
        sa.Column("applies_to_interpretation_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_feedback_id", sa.UUID(), nullable=True),
        sa.Column("source_message_id", sa.UUID(), nullable=True),
        sa.Column("weight", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('affirm', 'deny', 'amend', 'scope')", name=op.f("ck_user_assertions_kind")
        ),
        sa.CheckConstraint(
            "source IN ('feedback', 'onboarding', 'memory_ui')",
            name=op.f("ck_user_assertions_source"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retracted')", name=op.f("ck_user_assertions_status")
        ),
        sa.ForeignKeyConstraint(
            ["applies_to_interpretation_id"],
            ["interpretations.id"],
            name=op.f("fk_user_assertions_applies_to_interpretation_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_feedback_id"],
            ["recognition_feedback.id"],
            name=op.f("fk_user_assertions_source_feedback_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("fk_user_assertions_source_message_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_assertions_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_assertions")),
    )
    op.create_index(
        op.f("ix_user_assertions_created_at"), "user_assertions", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_user_assertions_user_id"), "user_assertions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_user_assertions_user_status", "user_assertions", ["user_id", "status"], unique=False
    )


def downgrade() -> None:
    """Drop everything this revision created. Indexes go with their table."""
    op.drop_table("user_assertions")
    op.drop_table("recognition_provenance")
    op.drop_table("evidence")
    op.drop_table("correction_effects")
    op.drop_table("signals")
    op.drop_table("recognition_feedback")
    op.drop_table("recognition_events")
    op.drop_table("memory_sources")
    op.drop_table("conversation_events")
    op.drop_table("threshold_evaluations")
    op.drop_table("recognitions")
    op.drop_table("messages")
    op.drop_table("claim_matches")
    op.drop_table("user_settings")
    op.drop_table("user_profiles")
    op.drop_table("user_daily_usage")
    op.drop_table("memory_items")
    op.drop_table("llm_calls")
    op.drop_table("legal_acceptances")
    op.drop_table("jobs")
    op.drop_table("invite_codes")
    op.drop_table("interpretations")
    op.drop_table("email_tokens")
    op.drop_table("conversations")
    op.drop_table("auth_sessions")
    op.drop_table("audit_log")
    op.drop_table("worker_heartbeats")
    op.drop_table("users")
    op.drop_table("system_status")
    # The `vector` extension is left in place: other databases on the same cluster
    # may use it, and re-creating it is cheap.
