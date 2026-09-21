"""Liveness, readiness and version — the three URLs ops and CI actually call.

``/healthz`` answers from the process alone: if it replies, the container is alive.
``/readyz`` answers "should traffic go here?" and checks the things that make a
request fail — the database, migrations being at head, and a worker that has beaten
in the last two minutes. The deploy script polls it and the uptime pinger watches it
(plan.md §9), so it returns 503 rather than raising when something is wrong.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.core.config import BACKEND_ROOT, settings
from knori.core.logging import get_logger
from knori.db.session import SessionLocal, ping

log = get_logger("knori.health")

router = APIRouter(tags=["ops"])

WORKER_STALE_SECONDS = 120.0
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
MIGRATIONS_DIR = BACKEND_ROOT / "knori" / "db" / "migrations"

_dev_invite_checked = False


@lru_cache(maxsize=1)
def app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("knori")
    except PackageNotFoundError:
        return "0.0.0"


@lru_cache(maxsize=1)
def migration_head() -> str | None:
    """The newest revision on disk. None when Alembic cannot be read at all."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(ALEMBIC_INI))
        # alembic.ini spells the location relative to backend/; the API's working
        # directory is not guaranteed to be there, so make it absolute.
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception as exc:  # a broken alembic setup must not crash the probe
        log.warning("migration_head_unreadable", error=str(exc))
        return None
    return heads[0] if len(heads) == 1 else ",".join(sorted(heads))


@router.get("/healthz", summary="Is the process alive?")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "version": app_version(), "at": now().isoformat()}


@router.get("/version", summary="What is deployed here?")
async def version() -> dict[str, Any]:
    return {
        "version": app_version(),
        "commit": os.getenv("GIT_SHA", ""),
        "env": settings.env,
        "llm_mode": settings.llm_mode,
        "signup_mode": settings.signup_mode,
        "migration_head": migration_head(),
    }


@router.get("/readyz", summary="Should traffic come here?", response_model=None)
async def readyz() -> JSONResponse:
    checks: dict[str, Any] = {
        "database": False,
        "migrations": False,
        "worker": False,
    }
    details: dict[str, Any] = {}

    if not await ping():
        return _not_ready(checks, details, "database is unreachable")
    checks["database"] = True

    head = migration_head()
    try:
        async with SessionLocal() as session:
            current = await session.scalar(text("SELECT version_num FROM alembic_version"))
            worker_age = await session.scalar(
                text(
                    "SELECT EXTRACT(EPOCH FROM (CAST(:now AS timestamptz) - max(last_beat_at)))"
                    " FROM worker_heartbeats"
                ),
                {"now": now()},
            )
            await _ensure_dev_invite(session)
    except Exception as exc:
        log.warning("readyz_query_failed", error=str(exc))
        return _not_ready(checks, details, "database query failed")

    details["migration_head"] = head
    details["migration_current"] = current
    checks["migrations"] = bool(head) and current == head

    age = float(worker_age) if worker_age is not None else None
    details["worker_heartbeat_age_seconds"] = age
    checks["worker"] = age is not None and age < WORKER_STALE_SECONDS

    if not all(checks.values()):
        failing = [name for name, ok in checks.items() if not ok]
        return _not_ready(checks, details, f"not ready: {', '.join(failing)}")

    return JSONResponse(
        {"status": "ready", "checks": checks, "details": details, "version": app_version()}
    )


async def _ensure_dev_invite(session: AsyncSession) -> None:
    """First-run convenience in dev: one invite code so signup is possible.

    Runs at most once per process and never outside development (plan.md §2.4).
    """
    global _dev_invite_checked
    if _dev_invite_checked or not settings.is_dev:
        return
    _dev_invite_checked = True
    from knori.services.invites import ensure_dev_invite

    try:
        created = await ensure_dev_invite(session)
        if created:
            await session.commit()
    except Exception as exc:  # never let a convenience break the probe
        log.warning("dev_invite_failed", error=str(exc))
        await session.rollback()


def _not_ready(checks: dict[str, Any], details: dict[str, Any], reason: str) -> JSONResponse:
    return JSONResponse(
        {"status": "not_ready", "reason": reason, "checks": checks, "details": details},
        status_code=503,
    )


__all__ = ["WORKER_STALE_SECONDS", "app_version", "migration_head", "router"]
