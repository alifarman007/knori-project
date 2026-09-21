"""The operator's page: is it healthy, what is it costing, and why did it stay quiet?

One screen answers all three (plan.md §8). The third question is the interesting one:
``/admin/decisions`` reads ``threshold_evaluations``, the ledger where every decision
*not* to recognise is written down with the rule that blocked it (CLAUDE.md → engine
rule 4). Without it, "KnoRI noticed nothing" is unexplainable.

Every read here is written to ``audit_log``. Looking at someone's data is an action,
not a free operation, and an admin should leave the same trail as anyone else.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Path, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.deps import AdminUser, DbSession, client_ip
from knori.api.schemas import Accepted
from knori.api.schemas.admin import (
    ConfigOut,
    CostGroupBy,
    CostRow,
    CostsOut,
    DecisionOut,
    DecisionsOut,
    ErrorRate,
    InviteCreateIn,
    InviteOut,
    JobOut,
    JobsOut,
    LaneHealth,
    OpsOut,
    PromptOut,
    RouteOut,
)
from knori.core.clock import now
from knori.core.config import settings
from knori.core.errors import NotFound
from knori.core.logging import get_logger
from knori.db.models import User
from knori.jobs import queue
from knori.services import accounts, invites

log = get_logger("knori.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

BACKUP_STATUS_KEY = "backup"
WORKER_STALE_SECONDS = 120.0
QUEUE_SLOW_SECONDS = 600.0
LLM_ERROR_RATE_ALERT = 0.20

# group_by is user input, so it can only ever choose from this table.
_COST_GROUPS: dict[str, str] = {
    "task": "task",
    "model": "model",
    "provider": "provider",
    "prompt_version": "COALESCE(prompt_name, '-') || ' v' || COALESCE(prompt_version, '?')",
    "day": "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')",
}


async def _audit_read(
    session: AsyncSession, admin: User, request: Request, action: str, meta: dict[str, Any]
) -> None:
    await accounts.record_audit(
        session,
        action=action,
        user_id=admin.id,
        actor="admin",
        meta=meta,
        ip=client_ip(request),
    )
    await session.commit()


# ------------------------------------------------------------------------------ ops


@router.get("/ops", summary="Queue, cost and worker health")
async def ops(request: Request, admin: AdminUser, session: DbSession) -> OpsOut:
    moment = now()
    lanes = await queue.lane_depths(session)
    dead = sum(lane.dead for lane in lanes)

    rates: list[ErrorRate] = []
    for label, window in (("15m", timedelta(minutes=15)), ("24h", timedelta(hours=24))):
        row = (
            await session.execute(
                text(
                    """
                    SELECT count(*) AS calls,
                           count(*) FILTER (WHERE status <> 'ok') AS errors
                      FROM llm_calls WHERE created_at >= :since
                    """
                ),
                {"since": moment - window},
            )
        ).first()
        calls = int(row.calls) if row else 0
        errors = int(row.errors) if row else 0
        rates.append(
            ErrorRate(
                window=label,
                calls=calls,
                errors=errors,
                rate=round(errors / calls, 4) if calls else 0.0,
            )
        )

    cost_today = float(
        await session.scalar(
            text(
                "SELECT COALESCE(sum(cost_usd), 0) FROM llm_calls"
                " WHERE created_at >= date_trunc('day', CAST(:now AS timestamptz) AT TIME ZONE"
                " 'UTC') AT TIME ZONE 'UTC'"
            ),
            {"now": moment},
        )
        or 0.0
    )

    worker = (
        await session.execute(
            text(
                "SELECT count(*) AS workers,"
                " EXTRACT(EPOCH FROM (CAST(:now AS timestamptz) - max(last_beat_at))) AS age"
                " FROM worker_heartbeats"
            ),
            {"now": moment},
        )
    ).first()
    worker_age = float(worker.age) if worker and worker.age is not None else None

    backup = (
        await session.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM (CAST(:now AS timestamptz) - updated_at)) AS age"
                " FROM system_status WHERE key = :key"
            ),
            {"now": moment, "key": BACKUP_STATUS_KEY},
        )
    ).first()
    backup_age = float(backup.age) if backup and backup.age is not None else None

    warnings: list[str] = []
    if dead:
        warnings.append(f"{dead} dead job(s) need a look")
    for lane in lanes:
        if lane.oldest_queued_seconds > QUEUE_SLOW_SECONDS:
            warnings.append(
                f"lane {lane.lane}: oldest queued job is "
                f"{int(lane.oldest_queued_seconds // 60)} min old"
            )
    if worker_age is None or worker_age > WORKER_STALE_SECONDS:
        warnings.append("no recent worker heartbeat")
    if rates and rates[0].rate > LLM_ERROR_RATE_ALERT:
        warnings.append(f"LLM error rate {rates[0].rate:.0%} in the last 15 minutes")

    await _audit_read(session, admin, request, "admin.ops", {"warnings": len(warnings)})
    return OpsOut(
        now=moment.isoformat(),
        env=settings.env,
        llm_mode=settings.llm_mode,
        lanes=[LaneHealth.from_depth(lane) for lane in lanes],
        dead_jobs=dead,
        llm_error_rates=rates,
        cost_today_usd=round(cost_today, 4),
        worker_heartbeat_age_seconds=round(worker_age, 1) if worker_age is not None else None,
        worker_count=int(worker.workers) if worker else 0,
        backup_age_seconds=round(backup_age, 1) if backup_age is not None else None,
        healthy=not warnings,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------- costs


@router.get("/costs", summary="What the models are costing")
async def costs(
    request: Request,
    admin: AdminUser,
    session: DbSession,
    group_by: CostGroupBy = "task",
    days: int = Query(default=7, ge=1, le=90),
) -> CostsOut:
    since = now() - timedelta(days=days)
    # Interpolated into SQL, so it must come from the table above and never from input.
    expression = _COST_GROUPS[group_by]
    rows = (
        await session.execute(
            text(
                f"""
                SELECT {expression} AS key,
                       count(*) AS calls,
                       COALESCE(sum(input_tokens), 0) AS input_tokens,
                       COALESCE(sum(output_tokens), 0) AS output_tokens,
                       COALESCE(sum(cache_read_tokens), 0) AS cache_read_tokens,
                       COALESCE(sum(cost_usd), 0) AS cost_usd
                  FROM llm_calls
                 WHERE created_at >= :since
                 GROUP BY 1
                 ORDER BY cost_usd DESC
                """
            ),
            {"since": since},
        )
    ).all()

    await _audit_read(session, admin, request, "admin.costs", {"group_by": group_by, "days": days})
    return CostsOut(
        group_by=group_by,
        since=since.isoformat(),
        total_usd=round(sum(float(row.cost_usd) for row in rows), 4),
        rows=[CostRow.from_row(row) for row in rows],
    )


# ------------------------------------------------------------------------ decisions


@router.get("/decisions", summary="Why a Recognition did or did not happen")
async def decisions(
    request: Request,
    admin: AdminUser,
    session: DbSession,
    user_id: uuid.UUID = Query(description="Whose decision ledger to read"),
    limit: int = Query(default=100, ge=1, le=500),
) -> DecisionsOut:
    rows = (
        await session.execute(
            text(
                """
                SELECT e.id, e.interpretation_id, e.candidate_text, e.outcome, e.reason,
                       e.rules, e.confidence_at_eval, e.policy_version, e.timezone_used,
                       e.created_at, i.statement
                  FROM threshold_evaluations e
                  LEFT JOIN interpretations i ON i.id = e.interpretation_id
                 WHERE e.user_id = :user_id
                 ORDER BY e.created_at DESC
                 LIMIT :limit
                """
            ),
            {"user_id": user_id, "limit": limit},
        )
    ).all()

    await _audit_read(
        session,
        admin,
        request,
        "admin.decisions",
        {"subject_user_id": str(user_id), "rows": len(rows)},
    )
    return DecisionsOut(
        user_id=str(user_id),
        rows=[DecisionOut.from_row(row) for row in rows],
    )


# ----------------------------------------------------------------------------- jobs


@router.get("/jobs", summary="The queue, newest first")
async def list_jobs(
    request: Request,
    admin: AdminUser,
    session: DbSession,
    status: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> JobsOut:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, kind, lane, status, priority, attempts, max_attempts, user_id,
                       run_at, last_error, created_at, finished_at
                  FROM jobs
                 WHERE (:status IS NULL OR status = :status)
                   AND (:lane IS NULL OR lane = :lane)
                 ORDER BY created_at DESC
                 LIMIT :limit
                """
            ),
            {"status": status, "lane": lane, "limit": limit},
        )
    ).all()

    await _audit_read(session, admin, request, "admin.jobs", {"status": status, "lane": lane})
    return JobsOut(rows=[JobOut.from_row(row) for row in rows])


@router.post("/jobs/{job_id}/retry", summary="Put a dead job back in the queue")
async def retry_job(
    request: Request,
    admin: AdminUser,
    session: DbSession,
    job_id: uuid.UUID = Path(description="The job to retry"),
) -> Accepted:
    if not await queue.retry_dead(session, job_id):
        raise NotFound("No dead job with that id.")
    await accounts.record_audit(
        session,
        action="admin.job_retry",
        user_id=admin.id,
        actor="admin",
        target_type="job",
        target_id=job_id,
        ip=client_ip(request),
    )
    await session.commit()
    return Accepted(detail="Queued again with a fresh attempt budget.")


# --------------------------------------------------------------------------- config


@router.get("/config", summary="Which model and prompt answer which task")
async def config(request: Request, admin: AdminUser, session: DbSession) -> ConfigOut:
    routes: list[RouteOut] = []
    prompts: list[PromptOut] = []
    problems: list[str] = []

    try:
        from ros.llm.registry import get_registry
        from ros.llm.router import build_router

        built = build_router(settings)
        problems = built.validate()
        routes = [RouteOut.from_route(route) for route in built.routes]
        registry = get_registry()
        for name in registry.list_prompts():
            versions = registry.versions(name)
            prompts.append(PromptOut(name=name, versions=versions, latest=versions[-1]))
    except Exception as exc:  # a broken config must be visible here, not a 500
        problems.append(f"{type(exc).__name__}: {exc}")

    await _audit_read(session, admin, request, "admin.config", {"problems": len(problems)})
    return ConfigOut(
        llm_mode=settings.llm_mode,
        env=settings.env,
        signup_mode=settings.signup_mode,
        routes=sorted(routes, key=lambda item: item.task),
        prompts=prompts,
        problems=problems,
    )


# -------------------------------------------------------------------------- invites


@router.post("/invites", summary="Create an invite code")
async def create_invite(
    body: InviteCreateIn, request: Request, admin: AdminUser, session: DbSession
) -> InviteOut:
    row = await invites.create_invite(
        session,
        created_by=admin.id,
        code=body.code,
        note=body.note,
        max_uses=body.max_uses,
        expires_in_days=body.expires_in_days,
    )
    await accounts.record_audit(
        session,
        action="admin.invite_created",
        user_id=admin.id,
        actor="admin",
        target_type="invite_code",
        target_id=row.id,
        meta={"max_uses": row.max_uses},
        ip=client_ip(request),
    )
    await session.commit()
    return InviteOut.from_row(row)


@router.get("/invites", summary="List invite codes")
async def list_invites(
    request: Request, admin: AdminUser, session: DbSession, limit: int = Query(100, ge=1, le=500)
) -> list[InviteOut]:
    rows = await invites.list_invites(session, limit=limit)
    await _audit_read(session, admin, request, "admin.invites", {"rows": len(rows)})
    return [InviteOut.from_row(row) for row in rows]


__all__ = ["BACKUP_STATUS_KEY", "router"]
