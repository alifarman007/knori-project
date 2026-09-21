"""The background worker: claim a job, run its handler, record what happened.

One process, ``WORKER_CONCURRENCY`` jobs at a time, two lanes. The ``slow`` lane
(interpret, which can sit inside Opus for a minute) is capped at 2 so a burst of
long runs can never starve extraction, compose or feedback (plan.md §3.4).

Shutdown is graceful: the worker stops claiming, lets running jobs finish, and
only then exits. Anything still running when the grace period ends stays marked
``running`` and is picked up by the boot reset or the reaper — never silently
dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import time
from collections import Counter
from datetime import timedelta
from typing import Any, cast

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from knori.core.clock import now
from knori.core.config import settings
from knori.core.logging import clear_context, configure_logging, get_logger, log_context
from knori.db.models import WorkerHeartbeat
from knori.jobs import queue
from knori.jobs.registry import (
    JobContext,
    JobFailure,
    SessionFactory,
    get_spec,
    load_handlers,
    registered_kinds,
)
from knori.jobs.scheduler import Scheduler
from ros.llm.base import ProviderError

log = get_logger("knori.worker")

SLOW_LANE_LIMIT = 2
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 30.0
REAP_EVERY = timedelta(minutes=5)
SHUTDOWN_GRACE_SECONDS = 30.0


def default_worker_id() -> str:
    """Stable enough to recognise across a restart, unique enough for two workers."""
    return f"{socket.gethostname()}-{os.getpid()}"


def app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("knori")
    except PackageNotFoundError:
        return "0.0.0"


def resolve_session_factory() -> SessionFactory:
    """Find the async session factory the db slice exposes."""
    import importlib

    try:
        db_session = importlib.import_module("knori.db.session")
    except ModuleNotFoundError as exc:
        raise RuntimeError("the worker needs knori.db.session to open database sessions") from exc

    for name in (
        "async_session_factory",
        "AsyncSessionLocal",
        "SessionLocal",
        "session_factory",
        "async_session",
    ):
        candidate = getattr(db_session, name, None)
        if candidate is not None:
            return cast(SessionFactory, candidate)
    raise RuntimeError(
        "knori.db.session has no async session factory "
        "(expected one of: async_session_factory, AsyncSessionLocal, SessionLocal)"
    )


class Worker:
    def __init__(
        self,
        session_factory: SessionFactory | None = None,
        *,
        worker_id: str | None = None,
        concurrency: int | None = None,
        slow_limit: int = SLOW_LANE_LIMIT,
        poll_seconds: float = POLL_SECONDS,
        run_scheduler: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self.worker_id = worker_id or default_worker_id()
        self.concurrency = max(1, concurrency or settings.worker_concurrency)
        self.slow_limit = max(1, slow_limit)
        self.poll_seconds = poll_seconds
        self.run_scheduler = run_scheduler
        self.stop_event = asyncio.Event()
        self._running: dict[asyncio.Task[None], queue.ClaimedJob] = {}
        self._lane_counts: Counter[str] = Counter()

    # -- plumbing ---------------------------------------------------------------

    @property
    def sessions(self) -> SessionFactory:
        if self._session_factory is None:
            self._session_factory = resolve_session_factory()
        return self._session_factory

    def request_stop(self, reason: str = "signal") -> None:
        if not self.stop_event.is_set():
            log.info("worker_stopping", reason=reason, in_flight=len(self._running))
            self.stop_event.set()

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_stop, sig.name)
            except (NotImplementedError, AttributeError, ValueError):
                # Windows has no add_signal_handler on the Proactor loop.
                with contextlib.suppress(ValueError, OSError):
                    signal.signal(sig, lambda *_: self.request_stop("signal"))

    def _lanes_with_capacity(self) -> tuple[str, ...]:
        lanes = ["fast"]
        if self._lane_counts["slow"] < self.slow_limit:
            lanes.append("slow")
        return tuple(lanes)

    # -- main loop --------------------------------------------------------------

    async def run(self) -> None:
        self._install_signal_handlers()
        loaded = load_handlers()
        log.info(
            "worker_started",
            worker_id=self.worker_id,
            concurrency=self.concurrency,
            slow_limit=self.slow_limit,
            handler_modules=loaded,
            kinds=list(registered_kinds()),
        )

        async with self.sessions() as session:
            requeued = await queue.reset_running_on_boot(session, self.worker_id)
            await session.commit()
        if requeued:
            log.info("worker_requeued_own_jobs", count=requeued)

        tasks = [asyncio.create_task(self._heartbeat_loop(), name="worker-heartbeat")]
        if self.run_scheduler:
            scheduler = Scheduler(self.sessions)
            tasks.append(asyncio.create_task(scheduler.run(self.stop_event), name="scheduler"))

        try:
            await self._claim_loop()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._drain()
            log.info("worker_stopped", worker_id=self.worker_id)

    async def _claim_loop(self) -> None:
        while not self.stop_event.is_set():
            # Drain what is runnable right now, then wait a poll interval.
            while len(self._running) < self.concurrency and not self.stop_event.is_set():
                claimed = await self._claim(self._lanes_with_capacity())
                if claimed is None:
                    break
                self._start(claimed)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll_seconds)

    async def _claim(self, lanes: tuple[str, ...]) -> queue.ClaimedJob | None:
        try:
            async with self.sessions() as session:
                claimed = await queue.claim_one(session, lanes, self.worker_id)
                await session.commit()
                return claimed
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("job_claim_failed", error=str(exc))
            await asyncio.sleep(self.poll_seconds)
            return None

    def _start(self, claimed: queue.ClaimedJob) -> None:
        self._lane_counts[claimed.lane] += 1
        task = asyncio.create_task(self._execute(claimed), name=f"job-{claimed.kind}")
        self._running[task] = claimed
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        claimed = self._running.pop(task, None)
        if claimed is not None:
            self._lane_counts[claimed.lane] -= 1
        if not task.cancelled() and task.exception() is not None:
            log.error("job_task_crashed", error=str(task.exception()))

    async def _drain(self) -> None:
        if not self._running:
            return
        log.info("worker_draining", in_flight=len(self._running))
        pending = list(self._running)
        _, still_running = await asyncio.wait(pending, timeout=SHUTDOWN_GRACE_SECONDS)
        for task in still_running:
            task.cancel()
        if still_running:
            # Their rows stay 'running'; the next boot reset or the reaper takes them.
            log.warning("worker_drain_timeout", abandoned=len(still_running))
            await asyncio.gather(*still_running, return_exceptions=True)

    # -- running one job --------------------------------------------------------

    async def _execute(self, claimed: queue.ClaimedJob) -> None:
        spec = get_spec(claimed.kind)
        started = time.monotonic()
        clear_context()
        with log_context(
            job_id=str(claimed.id),
            job_kind=claimed.kind,
            lane=claimed.lane,
            attempt=claimed.attempts,
            **({"user_id": str(claimed.user_id)} if claimed.user_id else {}),
        ):
            if spec is None:
                await self._fail(claimed, f"no handler registered for {claimed.kind!r}", False)
                log.error("job_no_handler", kind=claimed.kind)
                return

            ctx = JobContext(
                job_id=claimed.id,
                kind=claimed.kind,
                lane=claimed.lane,
                payload=claimed.payload,
                user_id=claimed.user_id,
                attempt=claimed.attempts,
                worker_id=self.worker_id,
                session_factory=self.sessions,
                log=log,
            )

            try:
                result = await asyncio.wait_for(spec.handler(ctx), timeout=spec.timeout_seconds)
            except asyncio.CancelledError:
                # Shutdown. Leave the row 'running' so it is requeued on boot.
                log.warning("job_cancelled", duration_ms=_ms(started))
                raise
            except JobFailure as exc:
                await self._fail(claimed, str(exc), exc.retryable)
                log.warning("job_failed", error=str(exc), duration_ms=_ms(started))
                return
            except ProviderError as exc:
                # Refusals and truncation are typed failures: retrying burns money.
                await self._fail(claimed, f"{type(exc).__name__}: {exc}", exc.retryable)
                log.warning(
                    "job_failed_llm",
                    error=str(exc),
                    request_id=exc.request_id,
                    retryable=exc.retryable,
                    duration_ms=_ms(started),
                )
                return
            except IntegrityError as exc:
                await self._fail(claimed, f"IntegrityError: {exc}", False)
                log.warning("job_failed_integrity", duration_ms=_ms(started))
                return
            except TimeoutError:
                await self._fail(claimed, f"timed out after {spec.timeout_seconds}s", True)
                log.warning("job_timeout", duration_ms=_ms(started))
                return
            except Exception as exc:
                await self._fail(claimed, f"{type(exc).__name__}: {exc}", True)
                log.exception("job_error", error=str(exc), duration_ms=_ms(started))
                return

            await self._complete(claimed, result)
            log.info("job_done", duration_ms=_ms(started))

    async def _complete(self, claimed: queue.ClaimedJob, result: Any) -> None:
        payload = result if isinstance(result, dict) else None
        try:
            async with self.sessions() as session:
                await queue.complete(session, claimed.id, payload)
                await session.commit()
        except Exception as exc:
            log.error("job_complete_write_failed", error=str(exc))

    async def _fail(self, claimed: queue.ClaimedJob, error: str, retryable: bool) -> None:
        try:
            async with self.sessions() as session:
                status = await queue.fail(session, claimed.id, error, retryable=retryable)
                await session.commit()
            if status == "dead":
                log.error("job_dead", attempts=claimed.attempts, error=error)
        except Exception as exc:
            log.error("job_fail_write_failed", error=str(exc))

    # -- heartbeats -------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        last_reap = time.monotonic()
        while not self.stop_event.is_set():
            job_ids = [job.id for job in self._running.values()]
            due_reap = time.monotonic() - last_reap >= REAP_EVERY.total_seconds()
            try:
                async with self.sessions() as session:
                    await queue.heartbeat(session, job_ids, self.worker_id)
                    await self._write_worker_heartbeat(session)
                    if due_reap:
                        reaped = await queue.reap_stale(session)
                        last_reap = time.monotonic()
                        if reaped:
                            log.warning("jobs_reaped", count=reaped)
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("heartbeat_failed", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=HEARTBEAT_SECONDS)

    async def _write_worker_heartbeat(self, session: Any) -> None:
        stmt = pg_insert(WorkerHeartbeat).values(
            worker_id=self.worker_id, last_beat_at=now(), version=app_version()
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[WorkerHeartbeat.worker_id],
                set_={"last_beat_at": stmt.excluded.last_beat_at, "version": stmt.excluded.version},
            )
        )


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def main() -> int:
    configure_logging()
    worker = Worker()
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        return 0
    return 0


__all__ = [
    "HEARTBEAT_SECONDS",
    "POLL_SECONDS",
    "SLOW_LANE_LIMIT",
    "Worker",
    "default_worker_id",
    "main",
    "resolve_session_factory",
]
