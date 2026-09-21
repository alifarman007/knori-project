"""Periodic work, ticked from inside the worker.

The scheduler never does work itself: it only enqueues jobs, so a periodic task
is an ordinary job with an ordinary handler, retried and audited like any other
(plan.md §3.4). Each task carries a fixed ``dedupe_key``, which is unique among
*queued* rows — so a slow sweep can still be running while the next one waits.

Kinds with no registered handler are skipped, which keeps the worker usable
while the rest of Phase 1 is still being built.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from knori.core.clock import now
from knori.core.logging import get_logger
from knori.jobs import queue
from knori.jobs.registry import SessionFactory, get_spec

log = get_logger("knori.scheduler")

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


@dataclass(frozen=True, slots=True)
class PeriodicTask:
    name: str
    interval_seconds: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str = ""
    lane: str = "fast"
    # Periodic work yields to anything a person is waiting for.
    priority: int = 8

    def key(self) -> str:
        return self.dedupe_key or f"sched:{self.name}"


# plan.md §3.4. Intervals are deliberately coarse; nothing here is user-facing latency.
PERIODIC_TASKS: tuple[PeriodicTask, ...] = (
    PeriodicTask("extract_sweep", 2 * MINUTE, "extract_sweep"),
    PeriodicTask("idle_conversation_check", 5 * MINUTE, "idle_conversation_check"),
    PeriodicTask("alerts", 5 * MINUTE, "alerts"),
    PeriodicTask("release_held", 6 * HOUR, "release_held", lane="slow"),
    PeriodicTask("expire_sessions", 1 * HOUR, "expire_sessions"),
    PeriodicTask("purge_deleted_users", 1 * DAY, "purge_deleted_users"),
    PeriodicTask("job_gc", 1 * DAY, "job_gc"),
    PeriodicTask("backup_verify", 1 * DAY, "backup_verify"),
)


def due_tasks(
    tasks: Sequence[PeriodicTask],
    last_run: dict[str, datetime],
    at: datetime,
) -> list[PeriodicTask]:
    """Pure: which tasks are due at ``at``. A task with no recorded run is due."""
    out: list[PeriodicTask] = []
    for task in tasks:
        previous = last_run.get(task.name)
        if previous is None or at - previous >= timedelta(seconds=task.interval_seconds):
            out.append(task)
    return out


class Scheduler:
    """Ticks once a second and enqueues whatever is due."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        tasks: Sequence[PeriodicTask] = PERIODIC_TASKS,
        tick_seconds: float = 1.0,
        skip_unregistered: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._tasks = tuple(tasks)
        self._tick_seconds = tick_seconds
        self._skip_unregistered = skip_unregistered
        # Seeded at construction so a restart loop cannot fire everything repeatedly.
        start = now()
        self._last_run: dict[str, datetime] = {task.name: start for task in self._tasks}

    @property
    def tasks(self) -> tuple[PeriodicTask, ...]:
        return self._tasks

    def due(self, at: datetime | None = None) -> list[PeriodicTask]:
        return due_tasks(self._tasks, self._last_run, at or now())

    async def tick(self, at: datetime | None = None) -> int:
        """Enqueue every due task. Returns how many rows were actually inserted."""
        moment = at or now()
        due = self.due(moment)
        if not due:
            return 0

        enqueued = 0
        async with self._session_factory() as session:
            for task in due:
                self._last_run[task.name] = moment
                spec = get_spec(task.kind)
                if spec is None and self._skip_unregistered:
                    log.debug("scheduler_skip_unregistered", task=task.name, kind=task.kind)
                    continue
                created = await queue.enqueue(
                    session,
                    task.kind,
                    task.payload,
                    lane=spec.lane if spec else task.lane,
                    priority=task.priority,
                    dedupe_key=task.key(),
                    run_at=moment,
                    max_attempts=spec.max_attempts if spec else queue.DEFAULT_MAX_ATTEMPTS,
                )
                if created is not None:
                    enqueued += 1
            await session.commit()
        if enqueued:
            log.info("scheduler_enqueued", count=enqueued)
        return enqueued

    async def run(self, stop: asyncio.Event) -> None:
        """Tick until ``stop`` is set. A failed tick is logged and retried next time."""
        while not stop.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("scheduler_tick_failed", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._tick_seconds)


__all__ = [
    "DAY",
    "HOUR",
    "MINUTE",
    "PERIODIC_TASKS",
    "PeriodicTask",
    "Scheduler",
    "due_tasks",
]
