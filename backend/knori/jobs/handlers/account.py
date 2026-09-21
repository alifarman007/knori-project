"""Background work for accounts: send the mail, sweep the tokens, finish a deletion.

``purge_deleted_users`` is the one that matters. A person who asked to leave has a
24-hour grace period; after it, this job deletes every row that belongs to them and
sets ``user_id`` to NULL on the two tables that are kept (plan.md §4.7). It runs
daily from the scheduler, and it is written so that one failing account cannot stop
the others: each purge gets its own transaction.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select, text

from knori.core.clock import now
from knori.core.logging import get_logger
from knori.db.models import User
from knori.jobs.queue import purge_finished
from knori.jobs.registry import JobContext, JobFailure, job
from knori.services.accounts import record_audit
from knori.services.email import EmailRenderError, deliver, render_email
from knori.services.export_delete import purge_user

log = get_logger("knori.jobs.account")

# A revoked or expired session row is worth keeping for a while: it is what tells an
# admin that a token was used after it was revoked.
SESSION_KEEP = timedelta(days=7)
EMAIL_TOKEN_KEEP = timedelta(days=7)
FINISHED_JOB_KEEP = timedelta(days=7)
PURGE_BATCH = 50


def _rowcount(result: Any) -> int:
    """``execute`` is typed as Result; a DELETE always gives a CursorResult."""
    return int(getattr(result, "rowcount", 0) or 0)


@job("send_email", lane="fast", max_attempts=3, timeout_seconds=60.0)
async def send_email(ctx: JobContext) -> dict[str, Any]:
    """Deliver one queued message. A bad template is permanent; SMTP trouble is not."""
    to = str(ctx.require("to"))
    kind = str(ctx.require("kind"))
    context = ctx.payload.get("context") or {}
    try:
        message = render_email(kind, to, dict(context))
    except EmailRenderError as exc:
        raise JobFailure(str(exc), retryable=False) from exc

    try:
        sent = await deliver(message)
    except Exception as exc:  # any SMTP or network failure: worth another attempt
        raise JobFailure(f"smtp: {type(exc).__name__}: {exc}", retryable=True) from exc
    return {"sent": sent, "kind": kind}


@job("expire_sessions", lane="fast")
async def expire_sessions(ctx: JobContext) -> dict[str, Any]:
    """Clear out sessions and email links that can no longer be used."""
    moment = now()
    async with ctx.session_factory() as session:
        sessions = await session.execute(
            text(
                """
                DELETE FROM auth_sessions
                 WHERE expires_at < :session_cutoff
                    OR (revoked_at IS NOT NULL AND revoked_at < :session_cutoff)
                """
            ),
            {"session_cutoff": moment - SESSION_KEEP},
        )
        tokens = await session.execute(
            text(
                """
                DELETE FROM email_tokens
                 WHERE expires_at < :token_cutoff
                    OR (used_at IS NOT NULL AND used_at < :token_cutoff)
                """
            ),
            {"token_cutoff": moment - EMAIL_TOKEN_KEEP},
        )
        await session.commit()
    removed = {
        "sessions": _rowcount(sessions),
        "email_tokens": _rowcount(tokens),
    }
    if any(removed.values()):
        log.info("sessions_expired", **removed)
    return removed


@job("job_gc", lane="fast")
async def job_gc(ctx: JobContext) -> dict[str, Any]:
    """Drop finished job rows. Dead ones stay: the admin page is the point of them."""
    async with ctx.session_factory() as session:
        removed = await purge_finished(session, older_than=FINISHED_JOB_KEEP)
        await session.commit()
    return {"jobs_deleted": removed}


@job("purge_deleted_users", lane="fast", timeout_seconds=900.0)
async def purge_deleted_users(ctx: JobContext) -> dict[str, Any]:
    """Finish every deletion whose grace period has run out."""
    async with ctx.session_factory() as session:
        due = list(
            await session.scalars(
                select(User.id)
                .where(
                    User.status == "deleting",
                    User.purge_after.is_not(None),
                    User.purge_after <= now(),
                )
                .limit(PURGE_BATCH)
            )
        )

    purged: list[str] = []
    failed: list[str] = []
    for user_id in due:
        try:
            async with ctx.session_factory() as session:
                report = await purge_user(session, user_id)
                # The user row is gone, so the trail records the id in ``meta``.
                await record_audit(
                    session,
                    action="account.purged",
                    user_id=None,
                    actor="system",
                    target_type="user",
                    target_id=user_id,
                    meta={
                        "purged_user_id": str(user_id),
                        "rows_deleted": report.rows_deleted,
                        "rows_anonymised": sum(report.anonymised.values()),
                    },
                )
                await session.commit()
            purged.append(str(user_id))
        except Exception as exc:
            # One bad account must not stop the rest; the next run tries again.
            log.error("purge_failed", purge_user_id=str(user_id), error=str(exc))
            failed.append(str(user_id))

    if purged:
        log.info("users_purged", count=len(purged))
    if failed:
        raise JobFailure(f"{len(failed)} account(s) could not be purged", retryable=True)
    return {"purged": len(purged), "checked": len(due)}


__all__ = [
    "EMAIL_TOKEN_KEEP",
    "FINISHED_JOB_KEEP",
    "PURGE_BATCH",
    "SESSION_KEEP",
    "expire_sessions",
    "job_gc",
    "purge_deleted_users",
    "send_email",
]
