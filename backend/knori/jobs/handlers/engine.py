"""Background work for the Recognition engine: thin wrappers around the pipeline.

Every handler here does the same three things — open a session, build
:class:`~ros.engine.pipeline.PipelineDeps`, call one pipeline function — because
the order of the loop belongs to ``ros.engine.pipeline`` and nothing else
(CLAUDE.md → repo layout). If you find yourself writing a rule in this file, it
belongs in the engine.

The triggers of plan.md §4.2 live here rather than in the engine, because they
are about *when* the product spends money, not about what is true:

* **T1** four or more uninterpreted ``subject=self`` signals;
* **T2** a conversation that has gone quiet with something new in it;
* **T3** the user pressing "What have you noticed?" (owned by the API slice).

T1 and T2 run at most once an hour per user. T3 is exempt — a person asking is
always worth an answer.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.core.config import settings
from knori.core.events import publish
from knori.core.logging import get_logger
from knori.db.models import UserSettings
from knori.jobs import queue
from knori.jobs.registry import JobContext, JobSpec, get_spec, job, register
from knori.services.feedback import FEEDBACK_JOB, INTERPRET_JOB, reasoning_lock_key
from ros.engine import pipeline
from ros.engine.pipeline import PipelineDeps
from ros.llm.cost import get_limits, spent_today
from ros.llm.router import Router, build_router
from ros.persistence.engine_repo import EngineRepo
from ros.persistence.pg_memory import PgMemoryStore, PgRetriever

log = get_logger("knori.jobs.engine")

#: T1 — plan §4.2. Fewer than this and there is nothing worth an Opus run.
T1_MIN_SIGNALS = 4
#: T1/T2 together, per user. The button (T3) ignores this.
TRIGGER_COOLDOWN = timedelta(hours=1)
#: `extract_sweep` picks up anything the per-message job missed.
SWEEP_AFTER = timedelta(minutes=2)
SWEEP_LIMIT = 50
HELD_USERS_LIMIT = 200

_router: Router | None = None


def get_router() -> Router:
    """One router per worker process, built from the product's settings.

    Built here rather than taken from ``ros.llm.router.get_router`` so the ``.env``
    file is honoured: the module-level fallback reads the real environment only.
    """
    global _router
    if _router is None:
        _router = build_router(settings, clock=now)
    return _router


def build_deps(ctx: JobContext | None, session: AsyncSession) -> PipelineDeps:
    """The engine's view of the product: a queue, a bus, a clock and two protocols."""

    async def _enqueue(kind: str, payload: dict[str, Any], **kwargs: Any) -> None:
        spec = get_spec(kind)
        if spec is None:
            log.warning("engine.enqueue_unregistered", kind=kind)
            return
        await queue.enqueue(
            session,
            kind,
            payload,
            lane=kwargs.pop("lane", spec.lane),
            user_id=kwargs.pop("user_id", None),
            max_attempts=spec.max_attempts,
            **kwargs,
        )

    async def _publish(user_id: uuid.UUID | str, event: str, data: dict[str, Any]) -> None:
        await publish(session, user_id, event, data)

    return PipelineDeps(
        session=session,
        router=get_router(),
        clock=now,
        retriever=PgRetriever(session),
        memory=PgMemoryStore(session, clock=now),
        enqueue=_enqueue,
        publish=_publish,
        job_id=ctx.job_id if ctx is not None else None,
    )


# ------------------------------------------------------------------- extraction


@job("extract_signals", lane="fast", timeout_seconds=300.0, priority=4)
async def extract_signals(ctx: JobContext) -> dict[str, Any]:
    """One conversation's unextracted messages become signals (plan §4.2).

    The handler loops once more after writing: a message that arrived while the
    model was thinking would otherwise wait for the sweep.
    """
    conversation_id = ctx.require_uuid("conversation_id")
    user_id = ctx.require_user_id()
    totals = {"messages": 0, "signals": 0, "dropped_quotes": 0, "memories": 0}
    skipped: str | None = None

    async with ctx.session_factory() as session:
        deps = build_deps(ctx, session)
        repo = EngineRepo(session, user_id)
        for _ in range(2):
            pending = await repo.unextracted_messages(conversation_id, limit=20)
            if not pending:
                break
            result = await pipeline.run_extraction(deps, user_id, [m.id for m in pending])
            totals["messages"] += result.messages
            totals["signals"] += result.signals
            totals["dropped_quotes"] += result.dropped_quotes
            totals["memories"] += result.memories
            if result.messages == 0:
                skipped = result.skipped
                break
        if totals["signals"]:
            await maybe_enqueue_interpret(session, user_id, trigger="signals")
        await session.commit()
    return {**totals, "skipped": skipped}


@job("extract_sweep", lane="fast", priority=8)
async def extract_sweep(ctx: JobContext) -> dict[str, Any]:
    """Every 2 minutes: any conversation whose messages were never extracted."""
    async with ctx.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT m.conversation_id, m.user_id
                      FROM messages m
                      JOIN conversations c ON c.id = m.conversation_id
                      LEFT JOIN user_settings s ON s.user_id = m.user_id
                     WHERE m.role = 'user'
                       AND m.extracted_at IS NULL
                       AND m.status IN ('complete','partial')
                       AND m.created_at < :cutoff
                       AND c.is_incognito = FALSE
                       AND COALESCE(s.memory_enabled, TRUE)
                     LIMIT :limit
                    """
                ),
                {"cutoff": now() - SWEEP_AFTER, "limit": SWEEP_LIMIT},
            )
        ).all()
        queued = 0
        for row in rows:
            created = await queue.enqueue(
                session,
                "extract_signals",
                {"conversation_id": str(row.conversation_id)},
                lane="fast",
                user_id=row.user_id,
                dedupe_key=queue.dedupe_key_for("extract_signals", row.conversation_id),
            )
            queued += 1 if created is not None else 0
        await session.commit()
    return {"conversations": len(rows), "queued": queued}


# --------------------------------------------------------------- interpretation


@job(INTERPRET_JOB, lane="slow", timeout_seconds=900.0, priority=4)
async def interpret(ctx: JobContext) -> dict[str, Any]:
    """The Opus run: what the new signals might mean, then the gates (plan §4.3)."""
    user_id = ctx.require_user_id()
    async with ctx.session_factory() as session:
        moment = now()
        spent = await spent_today(session, user_id, occurred_at=moment)
        cap = get_limits().user_cap()
        if cap > 0 and spent >= cap:
            # plan §6.6: at the cap, interpretation waits for tomorrow rather than
            # failing. Chat is what the user is waiting for; this is not.
            await queue.enqueue(
                session,
                INTERPRET_JOB,
                {"trigger": "deferred"},
                lane="slow",
                user_id=user_id,
                run_at=_tomorrow(moment),
                dedupe_key=queue.dedupe_key_for(INTERPRET_JOB, user_id),
                lock_key=reasoning_lock_key(user_id),
                priority=6,
            )
            await session.commit()
            log.warning("interpret_deferred_daily_cap", spent_usd=spent, cap_usd=cap)
            return {"skipped": "daily_cost_cap", "spent_usd": spent}

        deps = build_deps(ctx, session)
        result = await pipeline.run_interpretation(deps, user_id)
        if result.remaining >= pipeline.MAX_NEW_SIGNALS:
            # More than one batch is waiting: come straight back for the rest.
            await queue.enqueue(
                session,
                INTERPRET_JOB,
                {"trigger": "continuation"},
                lane="slow",
                user_id=user_id,
                dedupe_key=queue.dedupe_key_for(INTERPRET_JOB, user_id),
                lock_key=reasoning_lock_key(user_id),
                priority=5,
            )
        await session.commit()
    return {
        "new_signals": result.new_signals,
        "proposals": result.proposals,
        "rejected": result.rejected,
        "declined": result.declined,
        "recognized": sum(1 for d in result.decisions if d.outcome == "recognize"),
        "remaining": result.remaining,
        "skipped": result.skipped,
    }


async def maybe_enqueue_interpret(
    session: AsyncSession, user_id: uuid.UUID, *, trigger: str
) -> bool:
    """T1 and T2 of plan §4.2. Returns True when a run was actually queued.

    Called by the extraction handler (T1) and by the idle-conversation check (T2).
    The hourly cap is read from ``jobs`` rather than kept in memory, because it is
    a spending limit and has to survive a restart.
    """
    if trigger not in ("signals", "idle"):
        raise ValueError(f"unknown interpret trigger {trigger!r}")
    row = await session.get(UserSettings, user_id)
    if row is not None and not row.recognition_enabled:
        return False
    waiting = await EngineRepo(session, user_id).count_uninterpreted()
    if waiting < (T1_MIN_SIGNALS if trigger == "signals" else 1):
        return False
    recent = await session.scalar(
        text(
            "SELECT 1 FROM jobs WHERE user_id = :user_id AND kind = :kind "
            "AND created_at > :cutoff AND COALESCE(payload ->> 'trigger', '') <> 'button' "
            "LIMIT 1"
        ),
        {"user_id": user_id, "kind": INTERPRET_JOB, "cutoff": now() - TRIGGER_COOLDOWN},
    )
    if recent:
        return False
    created = await queue.enqueue(
        session,
        INTERPRET_JOB,
        {"trigger": trigger},
        lane="slow",
        user_id=user_id,
        dedupe_key=queue.dedupe_key_for(INTERPRET_JOB, user_id),
        lock_key=reasoning_lock_key(user_id),
        priority=4,
    )
    return created is not None


# ----------------------------------------------------------------- composition


@job("compose_recognition", lane="fast", timeout_seconds=300.0, priority=3)
async def compose_recognition(ctx: JobContext) -> dict[str, Any]:
    """Write the card. Idempotent per ``(interpretation, version)`` — R1."""
    interpretation_id = ctx.require_uuid("interpretation_id")
    user_id = ctx.require_user_id()
    async with ctx.session_factory() as session:
        deps = build_deps(ctx, session)
        result = await pipeline.run_composition(deps, user_id, interpretation_id)
        await session.commit()
    return {
        "recognition_id": result.recognition_id,
        "skipped": result.skipped,
        "violations": list(result.violations),
    }


# -------------------------------------------------------------------- feedback


async def apply_feedback(ctx: JobContext) -> dict[str, Any]:
    """Turn one answer into assertions, rescoring and a "what changed" panel."""
    feedback_id = ctx.require_uuid("feedback_id")
    user_id = ctx.require_user_id()
    async with ctx.session_factory() as session:
        deps = build_deps(ctx, session)
        result = await pipeline.apply_feedback(deps, user_id, feedback_id)
        await session.commit()
    return {
        "action": result.action,
        "assertions": list(result.assertions),
        "withdrawn": list(result.withdrawn),
        "amended": result.amended_interpretation_id,
        "rescored": result.rescored,
        "skipped": result.skipped,
    }


# The API slice enqueues `apply_feedback`; whichever module is imported first
# registers the handler, and neither has to know about the other.
if get_spec(FEEDBACK_JOB) is None:
    register(
        JobSpec(
            kind=FEEDBACK_JOB,
            handler=apply_feedback,
            lane="slow",
            timeout_seconds=600.0,
            priority=2,
            description="Apply one piece of Recognition feedback.",
        )
    )


# -------------------------------------------------------------------- rescoring


@job("rescore_user", lane="slow", timeout_seconds=600.0, priority=6)
async def rescore_user(ctx: JobContext) -> dict[str, Any]:
    """Settings or timezone changed: re-run the gates over everything open.

    R3 counts calendar days in the user's zone, so moving zones really can change
    what passes.
    """
    user_id = ctx.require_user_id()
    async with ctx.session_factory() as session:
        deps = build_deps(ctx, session)
        decisions = await pipeline.decide(deps, user_id)
        await session.commit()
    return _decision_counts(decisions, reason=str(ctx.payload.get("reason") or ""))


@job("release_held", lane="slow", timeout_seconds=900.0, priority=8)
async def release_held(ctx: JobContext) -> dict[str, Any]:
    """Every 6 hours: look again at the claims that were held, in gate order."""
    released = 0
    users = 0
    async with ctx.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT user_id FROM interpretations "
                    "WHERE lifecycle_status = 'candidate' AND gate_outcome = 'hold' "
                    "LIMIT :limit"
                ),
                {"limit": HELD_USERS_LIMIT},
            )
        ).all()
        for row in rows:
            users += 1
            decisions = await pipeline.decide(build_deps(ctx, session), row.user_id)
            released += sum(1 for d in decisions if d.outcome == "recognize")
        await session.commit()
    return {"users": users, "released": released}


def _tomorrow(moment: datetime) -> datetime:
    """Just after midnight UTC, when the daily spend counter rolls over."""
    return datetime.combine((moment + timedelta(days=1)).date(), time(0, 5), tzinfo=UTC)


def _decision_counts(decisions: list[pipeline.Decision], *, reason: str = "") -> dict[str, Any]:
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.outcome] = counts.get(decision.outcome, 0) + 1
    return {"evaluated": len(decisions), "outcomes": counts, "reason": reason}


SessionJob = Callable[[JobContext], Awaitable[dict[str, Any]]]

__all__ = [
    "SWEEP_AFTER",
    "T1_MIN_SIGNALS",
    "TRIGGER_COOLDOWN",
    "apply_feedback",
    "build_deps",
    "compose_recognition",
    "extract_signals",
    "extract_sweep",
    "get_router",
    "interpret",
    "maybe_enqueue_interpret",
    "release_held",
    "rescore_user",
]
