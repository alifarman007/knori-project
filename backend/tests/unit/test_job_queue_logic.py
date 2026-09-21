"""Queue rules that hold without a database: backoff, death, keys, registry, schedule.

The SQL itself (claim, dedupe index, reaping) is covered by the integration tests,
which need a real Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from knori.jobs.queue import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    STALE_AFTER,
    ClaimedJob,
    backoff_seconds,
    dedupe_key_for,
    is_dead,
    lock_key_for,
    next_run_at,
)
from knori.jobs.registry import (
    JobContext,
    JobFailure,
    JobSpec,
    clear_registry,
    get_spec,
    job,
    register,
    registered_kinds,
)
from knori.jobs.scheduler import PERIODIC_TASKS, PeriodicTask, due_tasks

AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_registry()
    yield
    clear_registry()


# ------------------------------------------------------------------------ backoff


@pytest.mark.parametrize(
    ("attempts", "seconds"),
    [(1, 30), (2, 120), (3, 270), (4, 480), (5, 750)],
)
def test_backoff_is_thirty_seconds_times_attempts_squared(attempts: int, seconds: int) -> None:
    assert backoff_seconds(attempts) == seconds


def test_backoff_grows_and_is_capped() -> None:
    assert backoff_seconds(0) == BACKOFF_BASE_SECONDS
    assert backoff_seconds(100) == BACKOFF_CAP_SECONDS
    values = [backoff_seconds(n) for n in range(1, 8)]
    assert values == sorted(values)


def test_next_run_at_pushes_the_job_into_the_future() -> None:
    assert next_run_at(2, at=AT) == AT + timedelta(seconds=120)


# --------------------------------------------------------------------------- death


def test_a_job_dies_after_the_attempt_budget() -> None:
    assert is_dead(1, DEFAULT_MAX_ATTEMPTS) is False
    assert is_dead(4, 5) is False
    assert is_dead(5, 5) is True
    assert is_dead(6, 5) is True


def test_a_typed_failure_never_gets_a_second_try() -> None:
    """A refusal or a bad payload would fail the same way five times over."""
    assert is_dead(1, 5, retryable=False) is True


def test_one_attempt_jobs_die_immediately() -> None:
    assert is_dead(1, 1) is True


# ---------------------------------------------------------------------------- keys


def test_dedupe_key_is_readable_and_stable() -> None:
    conversation = uuid.uuid4()
    assert dedupe_key_for("extract_signals", conversation) == f"extract_signals:{conversation}"
    assert dedupe_key_for("extract_signals", conversation) == dedupe_key_for(
        "extract_signals", conversation
    )


def test_dedupe_key_skips_missing_parts() -> None:
    assert dedupe_key_for("job_gc") == "job_gc"
    assert dedupe_key_for("sweep", None, 7) == "sweep:7"


def test_different_kinds_never_share_a_dedupe_key() -> None:
    target = uuid.uuid4()
    assert dedupe_key_for("interpret", target) != dedupe_key_for("apply_feedback", target)


def test_lock_key_serialises_per_user_not_globally() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    assert lock_key_for("interpret", a) != lock_key_for("interpret", b)
    assert lock_key_for("interpret", a) == f"interpret:user:{a}"


def test_stale_window_is_fifteen_minutes() -> None:
    """Interpret can legitimately run for minutes; reaping earlier would duplicate work."""
    assert timedelta(minutes=15) == STALE_AFTER


def test_claimed_job_reads_a_row() -> None:
    job_id, user_id = uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(
        id=job_id,
        kind="interpret",
        lane="slow",
        user_id=user_id,
        payload=None,
        attempts=1,
        max_attempts=5,
        lock_key="interpret:user:x",
        dedupe_key=None,
    )
    claimed = ClaimedJob.from_row(row)  # type: ignore[arg-type]
    assert claimed.id == job_id
    assert claimed.payload == {}
    assert claimed.lane == "slow"


# ------------------------------------------------------------------------ registry


async def _handler(ctx: JobContext) -> dict[str, str]:
    return {"kind": ctx.kind}


def test_decorator_registers_a_handler() -> None:
    job("demo", lane="slow", max_attempts=2)(_handler)
    spec = get_spec("demo")
    assert spec is not None
    assert spec.lane == "slow"
    assert spec.max_attempts == 2
    assert "demo" in registered_kinds()


def test_registering_the_same_kind_twice_is_an_error() -> None:
    job("demo")(_handler)
    with pytest.raises(ValueError, match="already registered"):
        job("demo")(_handler)


def test_an_unknown_lane_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown lane"):
        job("demo", lane="express")(_handler)


def test_noop_is_always_available_for_smoke_tests() -> None:
    assert get_spec("noop") is not None


def test_unregistered_kind_has_no_spec() -> None:
    assert get_spec("does_not_exist") is None


def test_register_replace_allows_test_doubles() -> None:
    job("demo", lane="slow")(_handler)
    register(JobSpec(kind="demo", handler=_handler, lane="fast"), replace=True)
    spec = get_spec("demo")
    assert spec is not None and spec.lane == "fast"


# ------------------------------------------------------------------- job context


def _context(payload: dict[str, Any]) -> JobContext:
    return JobContext(
        job_id=uuid.uuid4(),
        kind="demo",
        lane="fast",
        payload=payload,
        user_id=None,
        attempt=1,
        worker_id="test",
        session_factory=lambda: None,  # type: ignore[arg-type,return-value]
    )


def test_missing_payload_field_is_a_permanent_failure() -> None:
    with pytest.raises(JobFailure) as caught:
        _context({}).require("conversation_id")
    assert caught.value.retryable is False


def test_bad_uuid_in_payload_is_a_permanent_failure() -> None:
    with pytest.raises(JobFailure) as caught:
        _context({"conversation_id": "not-a-uuid"}).require_uuid("conversation_id")
    assert caught.value.retryable is False


def test_good_uuid_is_parsed() -> None:
    value = uuid.uuid4()
    assert _context({"id": str(value)}).require_uuid("id") == value


def test_a_job_without_a_user_cannot_pretend_to_have_one() -> None:
    with pytest.raises(JobFailure):
        _context({}).require_user_id()


# ------------------------------------------------------------------- scheduler


def test_a_task_that_never_ran_is_due() -> None:
    tasks = [PeriodicTask("sweep", 120, "extract_sweep")]
    assert due_tasks(tasks, {}, AT) == tasks


def test_a_task_is_due_only_after_its_interval() -> None:
    tasks = [PeriodicTask("sweep", 120, "extract_sweep")]
    last = {"sweep": AT}
    assert due_tasks(tasks, last, AT + timedelta(seconds=119)) == []
    assert due_tasks(tasks, last, AT + timedelta(seconds=120)) == tasks


def test_only_the_due_tasks_come_back() -> None:
    tasks = [
        PeriodicTask("fast_one", 60, "a"),
        PeriodicTask("slow_one", 86400, "b"),
    ]
    last = {"fast_one": AT, "slow_one": AT}
    due = due_tasks(tasks, last, AT + timedelta(minutes=5))
    assert [t.name for t in due] == ["fast_one"]


def test_periodic_task_dedupe_keys_are_unique_and_namespaced() -> None:
    keys = [task.key() for task in PERIODIC_TASKS]
    assert len(keys) == len(set(keys))
    assert all(key.startswith("sched:") for key in keys)


def test_the_plan_s_schedule_is_what_is_configured() -> None:
    by_name = {task.name: task.interval_seconds for task in PERIODIC_TASKS}
    assert by_name["extract_sweep"] == 120
    assert by_name["idle_conversation_check"] == 300
    assert by_name["release_held"] == 6 * 3600
    assert by_name["expire_sessions"] == 3600
    assert by_name["purge_deleted_users"] == 86400
    assert by_name["job_gc"] == 86400


def test_periodic_work_never_outranks_a_person_waiting() -> None:
    assert all(task.priority > 5 for task in PERIODIC_TASKS)
