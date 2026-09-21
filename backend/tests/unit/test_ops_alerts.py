"""The alerting rules, without a database.

``knori/jobs/handlers/ops.py`` keeps the deciding in pure functions on purpose, so
these tests cover the part that actually decides whether somebody's phone buzzes at
three in the morning: which conditions fire, and how often each one may be emailed.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import pytest

from knori.jobs import registry
from knori.jobs.handlers import ops
from knori.services import email as email_service

AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def snapshot(**overrides: object) -> ops.OpsSnapshot:
    """A healthy install. Each test breaks exactly one thing."""
    defaults: dict[str, object] = {
        "at": AT,
        "dead_jobs": 0,
        "queue_age_seconds": {"fast": 2.0, "slow": 30.0},
        "llm_calls_15m": 100,
        "llm_errors_15m": 1,
        "disk_used_fraction": 0.40,
        "backup_age_seconds": 3600.0,
        "backup_ok": True,
        "global_cost_today_usd": 2.0,
        "global_cap_usd": 15.0,
        "users_at_cap": 0,
    }
    defaults.update(overrides)
    return ops.OpsSnapshot(**defaults)  # type: ignore[arg-type]


def conditions(alerts: list[ops.Alert]) -> set[str]:
    return {alert.condition for alert in alerts}


# ----------------------------------------------------------------------- evaluate


def test_a_healthy_install_raises_nothing() -> None:
    assert ops.evaluate(snapshot()) == []


def test_one_dead_job_is_enough() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    assert conditions(alerts) == {"dead_jobs"}
    assert "1 dead job" in alerts[0].subject


def test_a_lane_queued_for_more_than_ten_minutes() -> None:
    alerts = ops.evaluate(snapshot(queue_age_seconds={"fast": 5.0, "slow": 11 * 60.0}))
    assert conditions(alerts) == {"queue_age:slow"}
    # The lane is in the key, so a slow lane alert does not silence a fast lane one.
    both = ops.evaluate(snapshot(queue_age_seconds={"fast": 20 * 60.0, "slow": 11 * 60.0}))
    assert conditions(both) == {"queue_age:fast", "queue_age:slow"}


def test_exactly_ten_minutes_is_not_yet_late() -> None:
    assert ops.evaluate(snapshot(queue_age_seconds={"fast": 600.0})) == []


def test_llm_error_rate_over_twenty_percent() -> None:
    alerts = ops.evaluate(snapshot(llm_calls_15m=10, llm_errors_15m=3))
    assert conditions(alerts) == {"llm_error_rate"}


def test_two_failures_out_of_three_calls_is_not_a_rate() -> None:
    """One bad minute on a quiet install must not wake anybody."""
    assert ops.evaluate(snapshot(llm_calls_15m=3, llm_errors_15m=2)) == []


def test_disk_over_eighty_five_percent() -> None:
    assert conditions(ops.evaluate(snapshot(disk_used_fraction=0.86))) == {"disk"}
    assert ops.evaluate(snapshot(disk_used_fraction=0.85)) == []


def test_unreadable_disk_is_not_an_alert() -> None:
    assert ops.evaluate(snapshot(disk_used_fraction=None)) == []


def test_backup_older_than_eight_hours() -> None:
    alerts = ops.evaluate(snapshot(backup_age_seconds=9 * 3600.0))
    assert conditions(alerts) == {"backup_stale"}
    assert "9 h old" in alerts[0].subject


def test_a_recent_backup_whose_last_run_failed_still_alerts() -> None:
    """The dump is two hours old but the run after it failed: say so now, not in six
    hours when the age finally crosses the line."""
    alerts = ops.evaluate(snapshot(backup_age_seconds=2 * 3600.0, backup_ok=False))
    assert conditions(alerts) == {"backup_stale"}


def test_never_having_had_a_backup_alerts_in_production() -> None:
    assert conditions(ops.evaluate(snapshot(backup_age_seconds=None))) == {"backup_stale"}


def test_a_laptop_is_not_told_off_for_having_no_backups() -> None:
    rules = ops.AlertRules(expect_backups=False)
    assert ops.evaluate(snapshot(backup_age_seconds=None), rules) == []
    assert ops.evaluate(snapshot(backup_age_seconds=99 * 3600.0), rules) == []


def test_the_daily_cost_cap() -> None:
    assert conditions(ops.evaluate(snapshot(global_cost_today_usd=15.0))) == {"cost_cap"}
    assert ops.evaluate(snapshot(global_cost_today_usd=14.99)) == []


def test_no_cap_configured_means_no_cost_alert() -> None:
    assert ops.evaluate(snapshot(global_cost_today_usd=999.0, global_cap_usd=0.0)) == []


def test_users_at_their_own_cap() -> None:
    assert conditions(ops.evaluate(snapshot(users_at_cap=2))) == {"user_cost_cap"}


def test_several_conditions_at_once_are_all_reported() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=3, disk_used_fraction=0.99, backup_age_seconds=None))
    assert conditions(alerts) == {"dead_jobs", "disk", "backup_stale"}


def test_a_condition_key_never_contains_the_changing_number() -> None:
    """Otherwise every tick would look like a new problem and email again."""
    first = ops.evaluate(snapshot(dead_jobs=1))[0]
    later = ops.evaluate(snapshot(dead_jobs=7))[0]
    assert first.condition == later.condition
    assert first.subject != later.subject


# ---------------------------------------------------------------------- due_alerts


def test_an_unseen_condition_is_sent_straight_away() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    assert ops.due_alerts(alerts, {}, AT) == alerts


def test_the_same_condition_is_not_sent_twice_within_an_hour() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    last_sent = {"dead_jobs": AT - timedelta(minutes=59)}
    assert ops.due_alerts(alerts, last_sent, AT) == []


def test_it_is_sent_again_after_an_hour() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    last_sent = {"dead_jobs": AT - timedelta(minutes=60)}
    assert ops.due_alerts(alerts, last_sent, AT) == alerts


def test_a_quiet_condition_does_not_hold_back_a_new_one() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1, disk_used_fraction=0.99))
    due = ops.due_alerts(alerts, {"dead_jobs": AT - timedelta(minutes=1)}, AT)
    assert conditions(due) == {"disk"}


# ---------------------------------------------------------------------- build_state


def test_state_of_a_healthy_install() -> None:
    state = ops.build_state({}, [], [], AT)
    assert state["healthy"] is True
    assert state["active"] == []
    assert state["last_sent"] == {}
    assert state["checked_at"] == AT.isoformat()


def test_state_records_when_each_alert_was_emailed() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    state = ops.build_state({}, alerts, ["dead_jobs"], AT)
    assert state["healthy"] is False
    assert state["last_sent"] == {"dead_jobs": AT.isoformat()}
    assert state["active"][0]["last_sent_at"] == AT.isoformat()


def test_since_is_carried_over_while_a_condition_keeps_firing() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    first = ops.build_state({}, alerts, ["dead_jobs"], AT)
    later = ops.build_state(first, alerts, [], AT + timedelta(minutes=5))
    assert later["active"][0]["since"] == AT.isoformat()
    assert later["active"][0]["last_sent_at"] == AT.isoformat()


def test_send_times_are_forgotten_once_a_condition_clears() -> None:
    """A problem that comes back tomorrow should email at once, not wait an hour."""
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    firing = ops.build_state({}, alerts, ["dead_jobs"], AT)
    cleared = ops.build_state(firing, [], [], AT + timedelta(minutes=5))
    assert cleared["last_sent"] == {}
    assert ops.due_alerts(alerts, ops.last_sent_from_state(cleared), AT + timedelta(minutes=10))


def test_last_sent_survives_a_round_trip_through_json_shaped_state() -> None:
    alerts = ops.evaluate(snapshot(dead_jobs=1))
    state = ops.build_state({}, alerts, ["dead_jobs"], AT)
    assert ops.last_sent_from_state(state) == {"dead_jobs": AT}


@pytest.mark.parametrize("state", [{}, {"last_sent": None}, {"last_sent": {"x": "nonsense"}}])
def test_unreadable_state_is_treated_as_never_sent(state: dict[str, object]) -> None:
    assert ops.last_sent_from_state(state) == {}


# --------------------------------------------------------------------------- email


def test_alerts_go_to_ops_email_when_it_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_EMAIL", "ops@knori.test")
    assert ops.ops_recipient() == "ops@knori.test"


def test_without_ops_email_it_falls_back_to_the_sender_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPS_EMAIL", raising=False)
    recipient = ops.ops_recipient()
    assert recipient is not None and "@" in recipient


def test_send_email_can_render_an_ops_alert() -> None:
    """The `alerts` job enqueues a send_email job with this kind, so the email module
    must know how to render it or every alert would die as a permanent failure."""
    message = email_service.render_email(
        ops.OPS_EMAIL_KIND,
        "ops@knori.test",
        {"subject": "disk is 91% full", "detail": "Clean up old dumps.", "env": "prod"},
    )
    assert message.to == "ops@knori.test"
    assert message.subject == "[KnoRI prod] disk is 91% full"
    assert "Clean up old dumps." in message.text
    assert "/admin/ops" in message.text


def test_the_alert_email_escapes_what_it_is_given() -> None:
    message = ops.render_ops_alert("ops@knori.test", {"detail": "<script>x</script>"})
    assert "<script>" not in message.html


# ------------------------------------------------------------------------ plumbing


def test_the_disk_check_answers_none_for_a_path_that_does_not_exist() -> None:
    assert ops.disk_used_fraction("/definitely/not/a/real/path") is None


def test_the_disk_check_reads_a_real_path(tmp_path: object) -> None:
    fraction = ops.disk_used_fraction(str(tmp_path))
    assert fraction is not None and 0.0 <= fraction <= 1.0


def test_the_three_jobs_register_themselves_on_import() -> None:
    # Another test module empties the shared registry, so reload this one into a clean
    # registry rather than depending on the order tests happen to run in.
    registry.clear_registry()
    try:
        importlib.reload(ops)
        for kind in ("alerts", "backup_verify", "usage_rollup"):
            spec = registry.get_spec(kind)
            assert spec is not None, f"{kind} did not register"
            assert spec.lane == "fast"
    finally:
        registry.clear_registry()
