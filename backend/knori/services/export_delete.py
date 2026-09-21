"""Take everything with you, or leave and take nothing.

Two promises the privacy page makes, implemented here:

* **Export** — one JSON document with every conversation, message, memory item,
  Recognition with its provenance and feedback, and every correction.
* **Purge** — after the 24-hour grace period, every row that belongs to the user is
  deleted. The two exceptions are ``llm_calls`` and ``audit_log``, where ``user_id``
  is set to NULL instead so cost history and the security trail survive (plan.md §4.7).

The purge does not carry a hand-written list of tables. It reads the schema: any
table with a ``user_id`` column is emptied for that user, in reverse foreign-key
order. A table added next month is covered the day it is added, and the integration
test derives its check from the same place.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import knori.db.models  # noqa: F401  (registers the product tables on the metadata)
import ros.persistence.models  # noqa: F401  (registers the ROS tables)
from knori.core.clock import now
from knori.core.logging import get_logger
from knori.db.models import User
from ros.persistence.base import Base

log = get_logger("knori.privacy")

EXPORT_VERSION = 1

# Kept after a purge, with the owner forgotten.
ANONYMISED_TABLES: tuple[str, ...] = ("llm_calls", "audit_log")

_IDENTIFIER = re.compile(r"\A[a-z_][a-z0-9_]*\Z")


def user_owned_tables() -> tuple[str, ...]:
    """Every table with a ``user_id`` column, children first, minus the kept ones.

    ``sorted_tables`` is in dependency order (parents first), so reversing it deletes
    children before the rows they point at.
    """
    return tuple(
        table.name
        for table in reversed(Base.metadata.sorted_tables)
        if "user_id" in table.c and table.name not in ANONYMISED_TABLES
    )


@dataclass(frozen=True, slots=True)
class PurgeReport:
    user_id: str
    deleted: dict[str, int]
    anonymised: dict[str, int]

    @property
    def rows_deleted(self) -> int:
        return sum(self.deleted.values())


# ---------------------------------------------------------------------------- export


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


async def _rows(session: AsyncSession, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await session.execute(text(sql), params)
    return [_jsonable(dict(row)) for row in result.mappings().all()]


async def build_export(session: AsyncSession, user: User) -> dict[str, Any]:
    """Everything KnoRI holds about one person, as one plain dict.

    Every statement filters by ``user_id``; nothing is reached through a join from a
    row that was not already checked to belong to this user.
    """
    params = {"user_id": user.id}
    export: dict[str, Any] = {
        "export_version": EXPORT_VERSION,
        "generated_at": now().isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "preferred_name": user.preferred_name,
            "timezone": user.timezone,
            "status": user.status,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "email_verified_at": (
                user.email_verified_at.isoformat() if user.email_verified_at else None
            ),
            "onboarding_completed_at": (
                user.onboarding_completed_at.isoformat() if user.onboarding_completed_at else None
            ),
        },
    }

    export["settings"] = await _rows(
        session,
        """
        SELECT recognition_enabled, memory_enabled, max_recognitions_per_day,
               chat_style, flags, updated_at
          FROM user_settings WHERE user_id = :user_id
        """,
        params,
    )
    export["legal_acceptances"] = await _rows(
        session,
        """
        SELECT tos_version, privacy_version, created_at
          FROM legal_acceptances WHERE user_id = :user_id ORDER BY created_at
        """,
        params,
    )
    export["conversations"] = await _rows(
        session,
        """
        SELECT id, kind, title, is_incognito, message_count, summary,
               created_at, last_message_at, ended_at
          FROM conversations WHERE user_id = :user_id ORDER BY created_at
        """,
        params,
    )
    export["messages"] = await _rows(
        session,
        """
        SELECT id, conversation_id, seq, role, content, status, created_at
          FROM messages WHERE user_id = :user_id ORDER BY conversation_id, seq
        """,
        params,
    )
    export["memory_items"] = await _rows(
        session,
        """
        SELECT id, kind, key, statement, status, source, pinned, confirmations,
               first_seen_at, last_confirmed_at, sensitive_category
          FROM memory_items WHERE user_id = :user_id ORDER BY first_seen_at
        """,
        params,
    )
    export["memory_sources"] = await _rows(
        session,
        """
        SELECT s.memory_item_id, s.message_id, s.quote_text, s.quote_start, s.quote_end
          FROM memory_sources s
          JOIN memory_items m ON m.id = s.memory_item_id
         WHERE m.user_id = :user_id
         ORDER BY s.created_at
        """,
        params,
    )
    export["recognitions"] = await _rows(
        session,
        """
        SELECT r.id, r.kind, r.title, r.body, r.explanation, r.confidence,
               r.confidence_label, r.state, r.withdrawn_reason, r.created_at,
               r.presented_at, r.resolved_at, i.statement AS interpretation_statement,
               i.topic AS interpretation_topic
          FROM recognitions r
          LEFT JOIN interpretations i ON i.id = r.interpretation_id
         WHERE r.user_id = :user_id
         ORDER BY r.created_at
        """,
        params,
    )
    export["recognition_provenance"] = await _rows(
        session,
        """
        SELECT p.recognition_id, p.kind, p.conversation_id, p.conversation_title, p.seq,
               p.quote_text, p.quote_start, p.quote_end, p.message_created_at,
               p.role, p.display_order, p.scrubbed_at
          FROM recognition_provenance p
          JOIN recognitions r ON r.id = p.recognition_id
         WHERE r.user_id = :user_id
         ORDER BY p.recognition_id, p.display_order
        """,
        params,
    )
    export["recognition_feedback"] = await _rows(
        session,
        """
        SELECT id, recognition_id, action, correction_text, reason_code, created_at
          FROM recognition_feedback WHERE user_id = :user_id ORDER BY created_at
        """,
        params,
    )
    export["assertions"] = await _rows(
        session,
        """
        SELECT id, kind, statement, topic, source, status, created_at, retracted_at
          FROM user_assertions WHERE user_id = :user_id ORDER BY created_at
        """,
        params,
    )
    export["profile"] = await _rows(
        session,
        """
        SELECT version, profile_text, profile_json, trigger, created_at
          FROM user_profiles WHERE user_id = :user_id ORDER BY version
        """,
        params,
    )
    export["counts"] = {key: len(value) for key, value in export.items() if isinstance(value, list)}
    return export


def export_filename(user: User) -> str:
    return f"knori-export-{user.id}-{now().date().isoformat()}.json"


# ----------------------------------------------------------------------------- purge


async def purge_user(session: AsyncSession, user_id: uuid.UUID) -> PurgeReport:
    """Delete every row that belongs to this user. The caller owns the transaction.

    ``llm_calls`` and ``audit_log`` keep their rows with ``user_id`` set to NULL: the
    first so cost history stays honest, the second so the security trail is not a
    record someone can erase by leaving.
    """
    anonymised: dict[str, int] = {}
    for table in ANONYMISED_TABLES:
        result = await session.execute(
            text(f"UPDATE {_safe(table)} SET user_id = NULL WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        anonymised[table] = _rowcount(result)

    deleted: dict[str, int] = {}
    for table in user_owned_tables():
        result = await session.execute(
            text(f"DELETE FROM {_safe(table)} WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        deleted[table] = _rowcount(result)

    result = await session.execute(
        text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id}
    )
    deleted["users"] = _rowcount(result)

    report = PurgeReport(user_id=str(user_id), deleted=deleted, anonymised=anonymised)
    log.info(
        "user_purged",
        purged_user=str(user_id),
        rows=report.rows_deleted,
        anonymised=sum(anonymised.values()),
    )
    return report


def _rowcount(result: Any) -> int:
    """``execute`` is typed as Result; an UPDATE or DELETE always gives a CursorResult."""
    return int(getattr(result, "rowcount", 0) or 0)


def _safe(table: str) -> str:
    """Table names come from the schema, never from input — this is the belt and braces."""
    if not _IDENTIFIER.match(table):
        raise ValueError(f"refusing to build SQL for table name {table!r}")
    return table


__all__ = [
    "ANONYMISED_TABLES",
    "EXPORT_VERSION",
    "PurgeReport",
    "build_export",
    "export_filename",
    "purge_user",
    "user_owned_tables",
]
