"""Background jobs: a table in Postgres, a worker that polls it, a scheduler that
enqueues the periodic ones.

Other slices need only two things from here::

    from knori.jobs import enqueue, job

``enqueue`` inserts in the caller's transaction; ``job`` registers a handler.
"""

from __future__ import annotations

from knori.jobs.queue import (
    ClaimedJob,
    claim_one,
    complete,
    dedupe_key_for,
    enqueue,
    fail,
    lock_key_for,
)
from knori.jobs.registry import JobContext, JobFailure, JobSpec, get_spec, job, registered_kinds
from knori.jobs.scheduler import PERIODIC_TASKS, PeriodicTask, Scheduler

__all__ = [
    "PERIODIC_TASKS",
    "ClaimedJob",
    "JobContext",
    "JobFailure",
    "JobSpec",
    "PeriodicTask",
    "Scheduler",
    "claim_one",
    "complete",
    "dedupe_key_for",
    "enqueue",
    "fail",
    "get_spec",
    "job",
    "lock_key_for",
    "registered_kinds",
]
