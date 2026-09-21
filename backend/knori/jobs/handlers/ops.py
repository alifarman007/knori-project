"""Background work that watches the install itself: alerts, backups, usage totals.

Three jobs live here.

``alerts`` runs every five minutes. It reads six numbers, decides which of them are
bad, and emails ops about each bad one at most once an hour. It also writes what it
found into ``system_status`` under the key ``alerts``, which is what ``/admin/ops``
can render so the page and the email never disagree.

``backup_verify`` runs daily and looks at the row the backup container writes
(``deploy/backup/backup.sh``). It is the slower, louder second opinion: ``alerts``
notices a backup that is eight hours old, this notices one that has been broken all
day.

``usage_rollup`` runs hourly and rebuilds ``user_daily_usage`` from ``llm_calls``.
The counter is normally bumped inside the same transaction as the call it belongs to
(``ros.llm.cost.record_call``), so this changes nothing in a healthy install — it is
there for the day a crash between the two writes leaves a user able to spend past
their cap.

The deciding is kept in pure functions (:func:`evaluate`, :func:`due_alerts`,
:func:`build_state`) so the interesting part can be tested without a database, and
the handlers only gather numbers and write rows.
"""

from __future__ import annotations

import html
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.core.config import settings
from knori.core.logging import get_logger
from knori.db.models import SystemStatus
from knori.jobs import queue
from knori.jobs.registry import JobContext, job
from knori.services import email as email_service
from ros.llm.cost import Limits, get_limits

log = get_logger("knori.jobs.ops")

# ``system_status`` keys this module reads or writes.
BACKUP_KEY = "backup"
ALERTS_KEY = "alerts"
BACKUP_VERIFY_KEY = "backup_verify"
USAGE_ROLLUP_KEY = "usage_rollup"

#: The kind used on the ``send_email`` job for an ops alert.
OPS_EMAIL_KIND = "ops_alert"

#: How far back ``usage_rollup`` recomputes. Two days covers today and yesterday in
#: every timezone without rewriting months of history every hour.
ROLLUP_WINDOW = timedelta(days=2)
#: ``alerts`` enqueues the rollup when the last one is older than this (see the note
#: on scheduling at the bottom of this file).
ROLLUP_EVERY = timedelta(hours=1)

#: A backup older than this is worth an email; older than this is worth shouting.
BACKUP_STALE_AFTER = timedelta(hours=8)
BACKUP_BROKEN_AFTER = timedelta(hours=24)


# ---------------------------------------------------------------------------- rules


@dataclass(frozen=True, slots=True)
class AlertRules:
    """The numbers from plan.md §9. Kept here, not in a config file, because changing
    one is a decision about how loud the system is, and that belongs in a diff."""

    queue_age_seconds: float = 600.0  # oldest queued job, per lane
    llm_error_rate: float = 0.20  # share of failed calls in the last 15 minutes
    llm_min_calls: int = 5  # below this, one failure is not a rate
    disk_used_fraction: float = 0.85
    backup_age_seconds: float = BACKUP_STALE_AFTER.total_seconds()
    repeat_after: timedelta = timedelta(hours=1)
    #: False on a laptop, where there is no backup container and "no backup yet" is
    #: the normal state rather than an emergency.
    expect_backups: bool = True


DEFAULT_RULES = AlertRules()


@dataclass(frozen=True, slots=True)
class OpsSnapshot:
    """Everything :func:`evaluate` is allowed to look at."""

    at: datetime
    dead_jobs: int = 0
    #: lane name -> age in seconds of the oldest job still queued in it
    queue_age_seconds: Mapping[str, float] = field(default_factory=dict)
    llm_calls_15m: int = 0
    llm_errors_15m: int = 0
    #: None when the disk cannot be read (a sandbox, or a stripped container).
    disk_used_fraction: float | None = None
    #: Age of the newest *successful* backup. None when there has never been one.
    backup_age_seconds: float | None = None
    backup_ok: bool = True
    global_cost_today_usd: float = 0.0
    global_cap_usd: float = 0.0
    users_at_cap: int = 0


@dataclass(frozen=True, slots=True)
class Alert:
    """One thing that is wrong.

    ``condition`` is the stable key. It decides which alerts are "the same thing" for
    the once-an-hour rule, so it must not contain a changing number.
    """

    condition: str
    subject: str
    detail: str


def evaluate(snapshot: OpsSnapshot, rules: AlertRules = DEFAULT_RULES) -> list[Alert]:
    """Which of plan.md §9's six conditions are true right now. Pure."""
    alerts: list[Alert] = []

    if snapshot.dead_jobs > 0:
        alerts.append(
            Alert(
                condition="dead_jobs",
                subject=f"{snapshot.dead_jobs} dead job(s)",
                detail=(
                    f"{snapshot.dead_jobs} job(s) have used up every attempt and stopped. "
                    "Look at /admin/jobs, read last_error, and retry them once the cause "
                    "is fixed."
                ),
            )
        )

    for lane in sorted(snapshot.queue_age_seconds):
        age = snapshot.queue_age_seconds[lane]
        if age > rules.queue_age_seconds:
            alerts.append(
                Alert(
                    condition=f"queue_age:{lane}",
                    subject=f"lane {lane} is {int(age // 60)} min behind",
                    detail=(
                        f"The oldest job queued in the {lane} lane has been waiting "
                        f"{int(age // 60)} minutes. Either the worker is down or "
                        "something in that lane is taking far longer than it should."
                    ),
                )
            )

    if snapshot.llm_calls_15m >= rules.llm_min_calls:
        rate = snapshot.llm_errors_15m / snapshot.llm_calls_15m
        if rate > rules.llm_error_rate:
            alerts.append(
                Alert(
                    condition="llm_error_rate",
                    subject=f"{rate:.0%} of model calls are failing",
                    detail=(
                        f"{snapshot.llm_errors_15m} of {snapshot.llm_calls_15m} model calls "
                        "in the last 15 minutes failed. Check /admin/costs grouped by model, "
                        "and the provider's status page."
                    ),
                )
            )

    if snapshot.disk_used_fraction is not None and (
        snapshot.disk_used_fraction > rules.disk_used_fraction
    ):
        alerts.append(
            Alert(
                condition="disk",
                subject=f"disk is {snapshot.disk_used_fraction:.0%} full",
                detail=(
                    f"The disk is {snapshot.disk_used_fraction:.0%} full. Postgres stops "
                    "accepting writes when it runs out. Usual suspects: old dumps in the "
                    "backup volume, container logs, unused images (docker image prune)."
                ),
            )
        )

    if rules.expect_backups:
        if snapshot.backup_age_seconds is None:
            alerts.append(
                Alert(
                    condition="backup_stale",
                    subject="there has never been a backup",
                    detail=(
                        "No successful backup has ever been recorded. Check the backup "
                        "container: docker compose -f deploy/compose.prod.yml logs backup"
                    ),
                )
            )
        elif snapshot.backup_age_seconds > rules.backup_age_seconds or not snapshot.backup_ok:
            hours = snapshot.backup_age_seconds / 3600
            alerts.append(
                Alert(
                    condition="backup_stale",
                    subject=f"newest backup is {hours:.0f} h old",
                    detail=(
                        f"The newest good backup is {hours:.1f} hours old and backups run "
                        "every 6 hours, so at least one run failed. The plan allows losing "
                        "6 hours of data (RPO); this is already past that."
                    ),
                )
            )

    if snapshot.global_cap_usd > 0 and snapshot.global_cost_today_usd >= snapshot.global_cap_usd:
        alerts.append(
            Alert(
                condition="cost_cap",
                subject=f"daily cost cap reached (${snapshot.global_cost_today_usd:.2f})",
                detail=(
                    f"Model spend today is ${snapshot.global_cost_today_usd:.2f} against a cap "
                    f"of ${snapshot.global_cap_usd:.2f}. Model work is paused until midnight "
                    "UTC. Raise global_daily_usd in config/limits.yaml if this is normal now."
                ),
            )
        )

    if snapshot.users_at_cap > 0:
        alerts.append(
            Alert(
                condition="user_cost_cap",
                subject=f"{snapshot.users_at_cap} user(s) at their daily cap",
                detail=(
                    f"{snapshot.users_at_cap} user(s) have reached their own daily spend cap, "
                    "so their chat is limited until midnight UTC. One user is normal; several "
                    "on the same day usually means a loop."
                ),
            )
        )

    return alerts


def due_alerts(
    alerts: Sequence[Alert],
    last_sent: Mapping[str, datetime],
    at: datetime,
    repeat_after: timedelta = DEFAULT_RULES.repeat_after,
) -> list[Alert]:
    """Which alerts may be emailed now: one per condition per hour. Pure."""
    out: list[Alert] = []
    for alert in alerts:
        previous = last_sent.get(alert.condition)
        if previous is None or at - previous >= repeat_after:
            out.append(alert)
    return out


def last_sent_from_state(state: Mapping[str, Any]) -> dict[str, datetime]:
    """Read the send times back out of the stored state. Unreadable entries are
    dropped, which at worst sends one extra email."""
    raw = state.get("last_sent")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, datetime] = {}
    for condition, value in raw.items():
        moment = _parse_time(value)
        if moment is not None:
            out[str(condition)] = moment
    return out


def build_state(
    previous: Mapping[str, Any],
    alerts: Sequence[Alert],
    sent: Sequence[str],
    at: datetime,
) -> dict[str, Any]:
    """The next ``system_status['alerts']`` value. Pure.

    ``since`` is carried over from the previous state for a condition that was already
    firing, so the page can say "the queue has been behind for 40 minutes" rather than
    "for 5 minutes" over and over.
    """
    previous_active = {
        str(entry.get("condition")): entry
        for entry in previous.get("active", [])
        if isinstance(entry, dict)
    }
    last_sent = {
        condition: moment.isoformat()
        for condition, moment in last_sent_from_state(previous).items()
    }
    for condition in sent:
        last_sent[condition] = at.isoformat()

    active: list[dict[str, Any]] = []
    for alert in alerts:
        carried = previous_active.get(alert.condition, {})
        active.append(
            {
                "condition": alert.condition,
                "subject": alert.subject,
                "detail": alert.detail,
                "since": carried.get("since") or at.isoformat(),
                "last_sent_at": last_sent.get(alert.condition),
            }
        )

    # Keep send times only for conditions that are still firing, so the map cannot grow
    # forever and a condition that comes back after a quiet day alerts straight away.
    conditions = {alert.condition for alert in alerts}
    return {
        "checked_at": at.isoformat(),
        "healthy": not active,
        "active": active,
        "last_sent": {key: value for key, value in last_sent.items() if key in conditions},
    }


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------- email


def ops_recipient() -> str | None:
    """Where alerts go: ``OPS_EMAIL``, or the address KnoRI sends from.

    Read from the environment rather than from ``Settings`` because it belongs to the
    deployment, not to the app: a machine with no ops mailbox simply gets no alerts.
    """
    explicit = os.getenv("OPS_EMAIL", "").strip()
    if explicit and "@" in explicit:
        return explicit
    _, address = parseaddr(settings.smtp_from)
    return address if address and "@" in address else None


def render_ops_alert(to: str, context: dict[str, Any]) -> email_service.OutgoingEmail:
    """Plain, short, and it names the URL to open. Nobody reads a pretty alert."""
    subject = str(context.get("subject") or "alert")
    detail = str(context.get("detail") or "")
    env = str(context.get("env") or settings.env)
    console = f"{settings.app_url.rstrip('/')}/admin/ops"

    at = str(context.get("at", ""))

    body = f"{detail}\n\nOps page: {console}\nChecked at: {at}\n"
    html_body = (
        '<html><body style="font-family:system-ui,sans-serif;font-size:14px;">'
        f"<p><strong>{_escape(subject)}</strong></p>"
        f"<p>{_escape(detail)}</p>"
        f'<p><a href="{_escape(console)}">{_escape(console)}</a></p>'
        f'<p style="color:#6b7280;">KnoRI {_escape(env)} &middot; {_escape(at)}</p>'
        "</body></html>"
    )
    return email_service.OutgoingEmail(
        to=to, subject=f"[KnoRI {env}] {subject}", text=body, html=html_body
    )


def _escape(value: str) -> str:
    return html.escape(value)


# ``send_email`` renders by looking the kind up in the email module's template table.
# Ops mail is not a product email, so it is registered from here instead of being added
# to that module: the worker imports every handler in this package before it runs a
# job, so the kind is always known by the time one arrives.
email_service._TEMPLATES.setdefault(OPS_EMAIL_KIND, render_ops_alert)


# ------------------------------------------------------------------- reading the box


def disk_used_fraction(path: str | None = None) -> float | None:
    """How full the disk is, 0.0 to 1.0. None when it cannot be read."""
    target = path or os.getenv("KNORI_DISK_PATH") or "/"
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        log.debug("disk_usage_unavailable", path=target, error=str(exc))
        return None
    if usage.total <= 0:
        return None
    return (usage.total - usage.free) / usage.total


async def read_status(session: AsyncSession, key: str) -> tuple[dict[str, Any], datetime | None]:
    """One ``system_status`` row as (value, updated_at). Missing row is ({}, None)."""
    row = (
        await session.execute(
            text("SELECT value, updated_at FROM system_status WHERE key = :key"),
            {"key": key},
        )
    ).first()
    if row is None:
        return {}, None
    value = row.value if isinstance(row.value, dict) else {}
    return value, row.updated_at


async def write_status(session: AsyncSession, key: str, value: dict[str, Any]) -> None:
    """Replace one ``system_status`` row. The caller owns the transaction."""
    statement = pg_insert(SystemStatus).values(key=key, value=value, updated_at=now())
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[SystemStatus.key],
            set_={"value": statement.excluded.value, "updated_at": statement.excluded.updated_at},
        )
    )


async def collect(session: AsyncSession, *, at: datetime, limits: Limits) -> OpsSnapshot:
    """Read the six numbers plan.md §9 alerts on."""
    lanes = await queue.lane_depths(session)

    calls = (
        await session.execute(
            text(
                """
                SELECT count(*) AS calls,
                       count(*) FILTER (WHERE status <> 'ok') AS errors
                  FROM llm_calls
                 WHERE created_at >= :since
                """
            ),
            {"since": at - timedelta(minutes=15)},
        )
    ).first()

    day_start = at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    day = day_start.date().isoformat()
    # From llm_calls, not user_daily_usage: the global cap covers calls with no user
    # (evals, system work) as well, and /admin/costs adds up the same rows.
    global_cost = float(
        await session.scalar(
            text("SELECT COALESCE(sum(cost_usd), 0) FROM llm_calls WHERE created_at >= :since"),
            {"since": day_start},
        )
        or 0.0
    )
    users_at_cap = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM user_daily_usage WHERE day = :day AND cost_usd >= :cap",
            ),
            {"day": day, "cap": limits.user_cap()},
        )
        or 0
    )

    backup_value, backup_updated = await read_status(session, BACKUP_KEY)
    # `last_at` is the last *successful* run. A failed run updates the row but leaves
    # `last_at` alone (deploy/backup/backup.sh), so the age stays honest.
    last_backup = _parse_time(backup_value.get("last_at")) or (
        backup_updated if backup_value.get("ok") else None
    )
    backup_age = (at - last_backup).total_seconds() if last_backup is not None else None

    return OpsSnapshot(
        at=at,
        dead_jobs=sum(lane.dead for lane in lanes),
        queue_age_seconds={lane.lane: lane.oldest_queued_seconds for lane in lanes},
        llm_calls_15m=int(calls.calls) if calls else 0,
        llm_errors_15m=int(calls.errors) if calls else 0,
        disk_used_fraction=disk_used_fraction(),
        backup_age_seconds=backup_age,
        backup_ok=bool(backup_value.get("ok", True)),
        global_cost_today_usd=global_cost,
        global_cap_usd=limits.global_daily_usd,
        users_at_cap=users_at_cap,
    )


# ----------------------------------------------------------------------------- jobs


@job("alerts", lane="fast", max_attempts=2, timeout_seconds=120.0, priority=2)
async def alerts(ctx: JobContext) -> dict[str, Any]:
    """Every 5 minutes: check the six conditions and email ops about new ones."""
    moment = now()
    limits = get_limits()
    # Backups only exist on the VPS (plan.md §9), so a laptop is not told off for
    # having none.
    rules = AlertRules(expect_backups=settings.is_prod)

    async with ctx.session_factory() as session:
        snapshot = await collect(session, at=moment, limits=limits)
        previous, _ = await read_status(session, ALERTS_KEY)

        firing = evaluate(snapshot, rules)
        recipient = ops_recipient()
        to_send = (
            due_alerts(firing, last_sent_from_state(previous), moment, rules.repeat_after)
            if recipient
            else []
        )

        for alert in to_send:
            await queue.enqueue(
                session,
                email_service.SEND_EMAIL_JOB,
                {
                    "to": recipient,
                    "kind": OPS_EMAIL_KIND,
                    "context": {
                        "subject": alert.subject,
                        "detail": alert.detail,
                        "env": settings.env,
                        "at": moment.isoformat(),
                    },
                },
                lane="fast",
                priority=2,
                max_attempts=3,
                # One email per condition per hour, even if two workers tick together.
                dedupe_key=f"alert:{alert.condition}:{moment:%Y-%m-%dT%H}",
            )

        await write_status(
            session,
            ALERTS_KEY,
            build_state(previous, firing, [a.condition for a in to_send], moment),
        )
        await _enqueue_rollup_if_due(session, moment)
        await session.commit()

    if firing:
        log.warning("ops_alerts", conditions=[a.condition for a in firing], emailed=len(to_send))
    if firing and recipient is None:
        log.warning("ops_alerts_not_emailed", reason="no OPS_EMAIL and no usable SMTP_FROM")
    return {
        "conditions": [alert.condition for alert in firing],
        "emailed": [alert.condition for alert in to_send],
        "healthy": not firing,
    }


@job("backup_verify", lane="fast", max_attempts=2, timeout_seconds=120.0)
async def backup_verify(ctx: JobContext) -> dict[str, Any]:
    """Daily: is there a recent, successful backup? Says so loudly if not."""
    moment = now()
    async with ctx.session_factory() as session:
        value, updated_at = await read_status(session, BACKUP_KEY)
        last_at = _parse_time(value.get("last_at"))
        age_seconds = (moment - last_at).total_seconds() if last_at else None
        ok = bool(value.get("ok", False))

        if age_seconds is None:
            state = "never"
        elif age_seconds > BACKUP_BROKEN_AFTER.total_seconds():
            state = "broken"
        elif age_seconds > BACKUP_STALE_AFTER.total_seconds() or not ok:
            state = "stale"
        else:
            state = "ok"

        finding: dict[str, Any] = {
            "checked_at": moment.isoformat(),
            "state": state,
            "last_backup_at": last_at.isoformat() if last_at else None,
            "age_hours": round(age_seconds / 3600, 2) if age_seconds is not None else None,
            "size_bytes": value.get("size_bytes"),
            "last_run_ok": ok,
            "last_run_at": updated_at.isoformat() if updated_at else None,
            "failed_step": value.get("failed_step"),
        }
        await write_status(session, BACKUP_VERIFY_KEY, finding)
        await session.commit()

    if state == "ok":
        log.info("backup_verified", age_hours=finding["age_hours"])
    else:
        # `alerts` sends the email; this makes sure the reason is in the log either way.
        log.error("backup_not_verified", state=state, failed_step=value.get("failed_step"))
    return finding


# `chat_messages` is deliberately not touched: llm_calls cannot tell a chat turn from
# any other call, and the live counter in ros.llm.cost is the only thing that knows.
_REBUILD_USAGE = text(
    """
    INSERT INTO user_daily_usage
        (user_id, day, cost_usd, input_tokens, output_tokens, chat_messages)
    SELECT user_id,
           to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
           COALESCE(sum(cost_usd), 0),
           COALESCE(sum(input_tokens), 0),
           COALESCE(sum(output_tokens), 0),
           0
      FROM llm_calls
     WHERE user_id IS NOT NULL
       AND created_at >= :since
     GROUP BY 1, 2
    ON CONFLICT (user_id, day) DO UPDATE
       SET cost_usd      = EXCLUDED.cost_usd,
           input_tokens  = EXCLUDED.input_tokens,
           output_tokens = EXCLUDED.output_tokens
    """
)


@job("usage_rollup", lane="fast", max_attempts=2, timeout_seconds=300.0, priority=9)
async def usage_rollup(ctx: JobContext) -> dict[str, Any]:
    """Hourly: rebuild the last two days of ``user_daily_usage`` from ``llm_calls``."""
    moment = now()
    since = moment - ROLLUP_WINDOW
    async with ctx.session_factory() as session:
        result = await session.execute(_REBUILD_USAGE, {"since": since})
        rows = int(getattr(result, "rowcount", 0) or 0)
        await write_status(
            session,
            USAGE_ROLLUP_KEY,
            {"last_at": moment.isoformat(), "rows": rows, "since": since.isoformat()},
        )
        await session.commit()
    log.info("usage_rolled_up", rows=rows)
    return {"rows": rows, "since": since.isoformat()}


# The periodic table in knori/jobs/scheduler.py belongs to the jobs slice and lists
# `alerts` and `backup_verify` but not `usage_rollup`. Rather than reach into another
# slice's file, the five-minute job enqueues the hourly one when it is due. If
# `usage_rollup` is later added to PERIODIC_TASKS, delete this and nothing else
# changes: the dedupe key keeps the two from queueing twice.
async def _enqueue_rollup_if_due(session: AsyncSession, at: datetime) -> bool:
    value, _ = await read_status(session, USAGE_ROLLUP_KEY)
    last = _parse_time(value.get("last_at"))
    if last is not None and at - last < ROLLUP_EVERY:
        return False
    created = await queue.enqueue(
        session,
        "usage_rollup",
        {},
        lane="fast",
        priority=9,
        dedupe_key="sched:usage_rollup",
        run_at=at,
    )
    return created is not None


__all__ = [
    "ALERTS_KEY",
    "BACKUP_KEY",
    "BACKUP_VERIFY_KEY",
    "OPS_EMAIL_KIND",
    "ROLLUP_EVERY",
    "ROLLUP_WINDOW",
    "USAGE_ROLLUP_KEY",
    "Alert",
    "AlertRules",
    "OpsSnapshot",
    "alerts",
    "backup_verify",
    "build_state",
    "collect",
    "disk_used_fraction",
    "due_alerts",
    "evaluate",
    "last_sent_from_state",
    "ops_recipient",
    "read_status",
    "render_ops_alert",
    "usage_rollup",
    "write_status",
]
