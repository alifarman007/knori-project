"""The job queue, which is a table in Postgres (plan.md §3.4).

Enqueue is an ``INSERT`` in the caller's transaction, so a job can never exist
for a write that rolled back, and a write can never commit without its job. That
one property is why there is no Redis and no Celery here.

Claiming uses ``FOR UPDATE SKIP LOCKED``: several workers can take from the same
table without blocking each other. Two keys shape what may run:

* ``dedupe_key`` — unique among **queued** rows. A second "extract this
  conversation" while one is already waiting is pointless; a second one while
  the first is *running* is not, because it covers newer messages.
* ``lock_key``  — unique among **running** rows. Interpret and feedback are
  serialised per user so two of them cannot score the same evidence at once.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.db.models import Job

BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600
STALE_AFTER = timedelta(minutes=15)
HEARTBEAT_EVERY = timedelta(seconds=30)
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_PRIORITY = 5


# ------------------------------------------------------------------- pure helpers


def backoff_seconds(attempts: int) -> int:
    """``30 s · attempts²``, capped at an hour so a stuck job does not drift away."""
    if attempts <= 0:
        return BACKOFF_BASE_SECONDS
    return min(BACKOFF_BASE_SECONDS * attempts * attempts, BACKOFF_CAP_SECONDS)


def next_run_at(attempts: int, *, at: datetime | None = None) -> datetime:
    return (at or now()) + timedelta(seconds=backoff_seconds(attempts))


def is_dead(attempts: int, max_attempts: int, *, retryable: bool = True) -> bool:
    """A typed failure (refusal, truncation, bad payload) never gets a second try."""
    if not retryable:
        return True
    return attempts >= max_attempts


def dedupe_key_for(kind: str, *parts: object) -> str:
    """``kind:part:part`` — readable in the admin table, stable across processes."""
    return ":".join([kind, *(str(p) for p in parts if p is not None)])


def lock_key_for(kind: str, user_id: uuid.UUID | str) -> str:
    """One running job of this kind per user."""
    return f"{kind}:user:{user_id}"


@dataclass(frozen=True, slots=True)
class LaneDepth:
    lane: str
    queued: int
    running: int
    dead: int
    oldest_queued_seconds: float


# ------------------------------------------------------------------------ enqueue


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    lane: str = "fast",
    user_id: uuid.UUID | None = None,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    lock_key: str | None = None,
    priority: int = DEFAULT_PRIORITY,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Job | None:
    """Insert a job in the caller's transaction.

    Returns the row, or ``None`` when an identical job was already queued.
    """
    values = {
        "kind": kind,
        "lane": lane,
        "user_id": user_id,
        "payload": payload or {},
        "status": "queued",
        "priority": priority,
        "run_at": run_at or now(),
        "attempts": 0,
        "max_attempts": max_attempts,
        "dedupe_key": dedupe_key,
        "lock_key": lock_key,
    }
    stmt = pg_insert(Job).values(**values)
    if dedupe_key is not None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[Job.dedupe_key],
            index_where=text("status = 'queued'"),
        )
    result = await session.execute(stmt.returning(Job))
    return result.scalars().first()


# -------------------------------------------------------------------------- claim

_CLAIM_SQL = text(
    """
    WITH candidate AS (
        SELECT j.id
        FROM jobs j
        WHERE j.status = 'queued'
          AND j.lane = ANY(:lanes)
          AND j.run_at <= :now
          AND (
                j.lock_key IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM jobs r
                    WHERE r.lock_key = j.lock_key AND r.status = 'running'
                )
          )
        ORDER BY j.priority ASC, j.run_at ASC
        FOR UPDATE OF j SKIP LOCKED
        LIMIT :limit
    )
    UPDATE jobs
       SET status = 'running',
           attempts = jobs.attempts + 1,
           locked_at = :now,
           locked_by = :worker_id,
           heartbeat_at = :now,
           last_error = NULL
     WHERE jobs.id IN (SELECT id FROM candidate)
    RETURNING jobs.id, jobs.kind, jobs.lane, jobs.user_id, jobs.payload,
              jobs.attempts, jobs.max_attempts, jobs.lock_key, jobs.dedupe_key
    """
)


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """Just enough of the row to run it; the worker never holds the ORM object."""

    id: uuid.UUID
    kind: str
    lane: str
    user_id: uuid.UUID | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    lock_key: str | None
    dedupe_key: str | None

    @classmethod
    def from_row(cls, row: Row[Any]) -> ClaimedJob:
        return cls(
            id=row.id,
            kind=row.kind,
            lane=row.lane,
            user_id=row.user_id,
            payload=row.payload or {},
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            lock_key=row.lock_key,
            dedupe_key=row.dedupe_key,
        )


async def claim_one(
    session: AsyncSession,
    lanes: tuple[str, ...] | list[str],
    worker_id: str,
    *,
    at: datetime | None = None,
) -> ClaimedJob | None:
    """Take the next runnable job from ``lanes``, or return None."""
    jobs = await claim_many(session, lanes, worker_id, limit=1, at=at)
    return jobs[0] if jobs else None


async def claim_many(
    session: AsyncSession,
    lanes: tuple[str, ...] | list[str],
    worker_id: str,
    *,
    limit: int = 1,
    at: datetime | None = None,
) -> list[ClaimedJob]:
    if not lanes or limit <= 0:
        return []
    result = await session.execute(
        _CLAIM_SQL,
        {"lanes": list(lanes), "now": at or now(), "worker_id": worker_id, "limit": limit},
    )
    return [ClaimedJob.from_row(row) for row in result.all()]


# ------------------------------------------------------------------ finishing up


async def complete(
    session: AsyncSession,
    job_id: uuid.UUID,
    result: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            """
            UPDATE jobs
               SET status = 'done', finished_at = :now, heartbeat_at = NULL,
                   result = CAST(:result AS jsonb), last_error = NULL
             WHERE id = :id
            """
        ),
        {"id": job_id, "now": now(), "result": _as_json(result)},
    )


async def fail(
    session: AsyncSession,
    job_id: uuid.UUID,
    error: str,
    *,
    retryable: bool = True,
    at: datetime | None = None,
) -> str:
    """Mark a failed attempt. Returns the new status: ``queued`` or ``dead``."""
    moment = at or now()
    row = (
        await session.execute(
            text("SELECT attempts, max_attempts FROM jobs WHERE id = :id"),
            {"id": job_id},
        )
    ).first()
    if row is None:
        return "missing"

    attempts, max_attempts = int(row.attempts), int(row.max_attempts)
    if is_dead(attempts, max_attempts, retryable=retryable):
        await session.execute(
            text(
                """
                UPDATE jobs
                   SET status = 'dead', finished_at = :now, heartbeat_at = NULL,
                       last_error = :error
                 WHERE id = :id
                """
            ),
            {"id": job_id, "now": moment, "error": _trim(error)},
        )
        return "dead"

    await session.execute(
        text(
            """
            UPDATE jobs
               SET status = 'queued', run_at = :run_at, last_error = :error,
                   locked_at = NULL, locked_by = NULL, heartbeat_at = NULL
             WHERE id = :id
            """
        ),
        {
            "id": job_id,
            "run_at": next_run_at(attempts, at=moment),
            "error": _trim(error),
        },
    )
    return "queued"


async def heartbeat(
    session: AsyncSession,
    job_ids: list[uuid.UUID] | tuple[uuid.UUID, ...],
    worker_id: str,
) -> int:
    """Say a job is still alive. Without this the reaper takes it back."""
    if not job_ids:
        return 0
    result = await session.execute(
        text(
            """
            UPDATE jobs SET heartbeat_at = :now
             WHERE id = ANY(:ids) AND status = 'running' AND locked_by = :worker_id
            """
        ),
        {"ids": list(job_ids), "now": now(), "worker_id": worker_id},
    )
    return _rowcount(result)


async def reap_stale(
    session: AsyncSession,
    *,
    stale_after: timedelta = STALE_AFTER,
) -> int:
    """Put back jobs whose worker died mid-run. Long LLM calls make 15 min the floor."""
    result = await session.execute(
        text(
            """
            UPDATE jobs
               SET status = 'queued', locked_at = NULL, locked_by = NULL,
                   heartbeat_at = NULL, last_error = 'reaped: worker heartbeat went stale'
             WHERE status = 'running'
               AND (heartbeat_at IS NULL OR heartbeat_at < :cutoff)
            """
        ),
        {"cutoff": now() - stale_after},
    )
    return _rowcount(result)


async def reset_running_on_boot(session: AsyncSession, worker_id: str) -> int:
    """This worker's own leftovers from a crash or a redeploy go back to queued."""
    result = await session.execute(
        text(
            """
            UPDATE jobs
               SET status = 'queued', locked_at = NULL, locked_by = NULL,
                   heartbeat_at = NULL, last_error = 'requeued: worker restarted'
             WHERE status = 'running' AND locked_by = :worker_id
            """
        ),
        {"worker_id": worker_id},
    )
    return _rowcount(result)


async def retry_dead(session: AsyncSession, job_id: uuid.UUID) -> bool:
    """Admin action: put a dead job back with a fresh attempt budget."""
    result = await session.execute(
        text(
            """
            UPDATE jobs
               SET status = 'queued', run_at = :now, attempts = 0,
                   locked_at = NULL, locked_by = NULL, heartbeat_at = NULL,
                   finished_at = NULL
             WHERE id = :id AND status IN ('dead', 'failed')
            """
        ),
        {"id": job_id, "now": now()},
    )
    return _rowcount(result) > 0


async def purge_finished(session: AsyncSession, *, older_than: timedelta) -> int:
    """``job_gc``: done rows are only kept for a while; dead rows stay for the admin."""
    result = await session.execute(
        text("DELETE FROM jobs WHERE status = 'done' AND finished_at < :cutoff"),
        {"cutoff": now() - older_than},
    )
    return _rowcount(result)


async def lane_depths(session: AsyncSession) -> list[LaneDepth]:
    """Queue health for ``/admin/ops`` and the alerts job."""
    rows = (
        await session.execute(
            text(
                """
                SELECT lane,
                       count(*) FILTER (WHERE status = 'queued')  AS queued,
                       count(*) FILTER (WHERE status = 'running') AS running,
                       count(*) FILTER (WHERE status = 'dead')    AS dead,
                       COALESCE(EXTRACT(EPOCH FROM (CAST(:now AS timestamptz)
                                - min(run_at) FILTER (WHERE status = 'queued'))), 0) AS oldest
                  FROM jobs
                 GROUP BY lane
                """
            ),
            {"now": now()},
        )
    ).all()
    return [
        LaneDepth(
            lane=row.lane,
            queued=int(row.queued),
            running=int(row.running),
            dead=int(row.dead),
            oldest_queued_seconds=float(row.oldest or 0.0),
        )
        for row in rows
    ]


# ------------------------------------------------------------------------ private


def _rowcount(result: Any) -> int:
    """``execute`` is typed as Result; UPDATE/DELETE always give a CursorResult."""
    return int(getattr(result, "rowcount", 0) or 0)


def _trim(message: str, limit: int = 2000) -> str:
    text_value = message.strip()
    return text_value if len(text_value) <= limit else text_value[: limit - 1] + "…"


def _as_json(value: dict[str, Any] | None) -> str | None:
    return None if value is None else json.dumps(value, default=str)


__all__ = [
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_CAP_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "HEARTBEAT_EVERY",
    "STALE_AFTER",
    "ClaimedJob",
    "LaneDepth",
    "backoff_seconds",
    "claim_many",
    "claim_one",
    "complete",
    "dedupe_key_for",
    "enqueue",
    "fail",
    "heartbeat",
    "is_dead",
    "lane_depths",
    "lock_key_for",
    "next_run_at",
    "purge_finished",
    "reap_stale",
    "reset_running_on_boot",
    "retry_dead",
]
