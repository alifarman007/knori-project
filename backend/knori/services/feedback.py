"""What the user does with a card: seen, accept, correct, reject, dismiss, run.

Feedback has to feel instant and be durable, and those pull in opposite
directions. The split here is the one plan.md §4.6 asks for:

* **Now, in one transaction** — the card moves state, the ``recognition_feedback``
  row exists, the history event is written, and an empty ``correction_effects``
  row is created with the profile text *as it was before*. When the 202 comes
  back, everything the UI needs to redraw is already in the database.
* **Later, in ``apply_feedback``** — assertions, rescoring, withdrawals, the new
  profile. That job is the engine's (CLAUDE.md engine rule 7); this module only
  enqueues it, in the same transaction as the write, so the two can never
  disagree.

The transition table is a pure function (:func:`plan_feedback`) so every legal
and illegal move can be tested without a database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.schemas.recognitions import (
    FeedbackAccepted,
    FeedbackRequest,
    RunResponse,
    SeenResponse,
)
from knori.core.clock import now
from knori.core.errors import BadRequest, Conflict, RateLimited, ValidationFailed
from knori.db.models import Job, User, UserSettings
from knori.jobs.queue import dedupe_key_for, enqueue, lock_key_for
from knori.services.recognitions import load_card
from ros.persistence.models import (
    CorrectionEffect,
    RecognitionEvent,
    RecognitionFeedback,
    UserProfile,
)

FEEDBACK_JOB = "apply_feedback"
INTERPRET_JOB = "interpret"

#: plan.md §4.2 T3 — the "What have you noticed?" button, at most once per 10 min.
RUN_COOLDOWN = timedelta(minutes=10)

#: action → the state the card ends in.
ACTION_STATES: dict[str, str] = {
    "accept": "accepted",
    "correct": "corrected",
    "reject": "rejected",
    "dismiss": "dismissed",
}
#: The only states a user may answer from (plan.md §4.6).
ANSWERABLE_STATES = frozenset({"pending", "presented"})
RESOLVED_STATES = frozenset(ACTION_STATES.values())
REASON_CODES = frozenset({"not_true", "partly_true", "outdated", "too_personal", "not_useful"})

MIN_CORRECTION_CHARS = 2
MAX_CORRECTION_CHARS = 2000

_ALREADY: dict[str, str] = {
    "accepted": "You already agreed with this one.",
    "corrected": "You already corrected this one.",
    "rejected": "You already said this one is not true.",
    "dismissed": "You already put this one aside.",
}

#: What the effect panel says while the job is still running.
PENDING_SUMMARY: dict[str, str] = {
    "accept": "KnoRI is noting that you agreed.",
    "correct": "KnoRI is working out what your correction changes.",
    "reject": "KnoRI is taking this claim out of its reasoning.",
    "dismiss": "KnoRI is putting this aside for now.",
}


def reasoning_lock_key(user_id: uuid.UUID | str) -> str:
    """One reasoning job per user at a time (CLAUDE.md → Data rules, jobs).

    ``interpret`` and ``apply_feedback`` share this key on purpose: two of them
    scoring the same evidence at once would race. Any slice that enqueues
    reasoning work must use this function, not its own string.
    """
    return lock_key_for("reasoning", user_id)


@dataclass(frozen=True, slots=True)
class FeedbackPlan:
    """The decided move, before anything is written."""

    action: str
    from_state: str
    to_state: str
    event: str
    #: A card answered without being marked seen is marked seen in the same step.
    mark_presented: bool
    #: `correct` calls Opus, so it goes to the slow lane; the rest must feel instant.
    lane: str
    needs_model: bool


def plan_feedback(current_state: str, action: str) -> FeedbackPlan:
    """The transition table of plan.md §4.6, as a function.

    Raises ``Conflict`` for a move the table does not allow — you cannot accept
    a card you already rejected, and a withdrawn card has nothing to answer.
    """
    if action not in ACTION_STATES:
        raise BadRequest(f"{action!r} is not something you can do to a card.", code="bad_action")
    if current_state == "withdrawn":
        raise Conflict(
            "KnoRI took this card back, so there is nothing to answer.",
            code="card_withdrawn",
        )
    if current_state in RESOLVED_STATES:
        raise Conflict(_ALREADY[current_state], code="already_answered")
    if current_state not in ANSWERABLE_STATES:
        raise Conflict(
            f"This card is {current_state}, so it cannot be answered.",
            code="invalid_transition",
        )
    to_state = ACTION_STATES[action]
    return FeedbackPlan(
        action=action,
        from_state=current_state,
        to_state=to_state,
        event=to_state,
        mark_presented=current_state == "pending",
        lane="slow" if action == "correct" else "fast",
        needs_model=action == "correct",
    )


def clean_correction(action: str, correction_text: str | None) -> str | None:
    """A correction must actually say something; the other actions must not."""
    cleaned = (correction_text or "").strip()
    if action != "correct":
        return cleaned or None
    if len(cleaned) < MIN_CORRECTION_CHARS:
        raise ValidationFailed(
            "Tell KnoRI what it got wrong, in your own words.",
            errors=[{"field": "correction_text", "message": "required"}],
            code="correction_text_required",
        )
    return cleaned[:MAX_CORRECTION_CHARS]


def check_reason_code(reason_code: str | None) -> str | None:
    if reason_code is None or reason_code in REASON_CODES:
        return reason_code
    raise BadRequest(f"{reason_code!r} is not a reason KnoRI knows.", code="bad_reason_code")


# --------------------------------------------------------------------- seen


async def mark_seen(session: AsyncSession, user: User, recognition_id: uuid.UUID) -> SeenResponse:
    """pending → presented. Safe to call twice; only the first one writes."""
    card = await load_card(session, user, recognition_id)
    if card.state == "pending":
        moment = now()
        card.state = "presented"
        card.presented_at = moment
        session.add(
            RecognitionEvent(
                user_id=user.id,
                interpretation_id=card.interpretation_id,
                recognition_id=card.id,
                event="presented",
                actor="user",
                payload={"before": {"state": "pending"}, "after": {"state": "presented"}},
            )
        )
        await session.commit()
    return SeenResponse(id=card.id, state=card.state, presented_at=card.presented_at)


# ----------------------------------------------------------------- feedback


async def _profile_text(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    """The current "How KnoRI sees you", snapshotted before the job changes it."""
    return await session.scalar(
        select(UserProfile.profile_text)
        .where(UserProfile.user_id == user_id)
        .order_by(UserProfile.version.desc())
        .limit(1)
    )


async def submit_feedback(
    session: AsyncSession,
    user: User,
    recognition_id: uuid.UUID,
    request: FeedbackRequest,
) -> FeedbackAccepted:
    """Record the answer, queue the durable work, and return 202 material."""
    card = await load_card(session, user, recognition_id)
    plan = plan_feedback(card.state, request.action)
    correction_text = clean_correction(plan.action, request.correction_text)
    reason_code = check_reason_code(request.reason_code)
    moment = now()

    feedback_id = uuid.uuid4()
    session.add(
        RecognitionFeedback(
            id=feedback_id,
            user_id=user.id,
            recognition_id=card.id,
            action=plan.action,
            correction_text=correction_text,
            reason_code=reason_code,
            created_at=moment,
        )
    )
    card.state = plan.to_state
    card.resolved_at = moment
    if plan.mark_presented:
        card.presented_at = moment
    session.add(
        RecognitionEvent(
            user_id=user.id,
            interpretation_id=card.interpretation_id,
            recognition_id=card.id,
            event=plan.event,
            actor="user",
            feedback_id=feedback_id,
            payload={
                "before": {"state": plan.from_state},
                "after": {"state": plan.to_state},
                "reason_code": reason_code,
                # The text itself lives in recognition_feedback, once.
                "has_text": correction_text is not None,
            },
            created_at=moment,
        )
    )
    await session.flush()

    session.add(
        CorrectionEffect(
            user_id=user.id,
            feedback_id=feedback_id,
            status="pending",
            summary=PENDING_SUMMARY[plan.action],
            profile_before_text=await _profile_text(session, user.id),
            created_at=moment,
        )
    )
    job = await enqueue(
        session,
        FEEDBACK_JOB,
        {"feedback_id": str(feedback_id)},
        lane=plan.lane,
        user_id=user.id,
        dedupe_key=dedupe_key_for(FEEDBACK_JOB, feedback_id),
        lock_key=reasoning_lock_key(user.id),
        priority=2 if plan.needs_model else 1,
    )
    await session.commit()

    return FeedbackAccepted(
        feedback_id=feedback_id,
        recognition_id=card.id,
        state=card.state,
        effect_status="pending",
        effect_url=f"/api/v1/corrections/{feedback_id}/effect",
        job_id=job.id if job is not None else None,
    )


# ---------------------------------------------------------------------- run


async def _last_button_run(session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    """When this user last pressed the button, if it was recently.

    Read from ``jobs`` rather than an in-process counter: the limit is part of
    how much the product is allowed to spend, so it has to survive a restart.
    """
    return await session.scalar(
        select(Job.created_at)
        .where(
            Job.user_id == user_id,
            Job.kind == INTERPRET_JOB,
            Job.created_at > now() - RUN_COOLDOWN,
            text("jobs.payload ->> 'trigger' = 'button'"),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )


async def request_run(session: AsyncSession, user: User, settings: UserSettings) -> RunResponse:
    """ "What have you noticed?" — trigger T3 of plan.md §4.2."""
    if not settings.recognition_enabled:
        raise Conflict(
            "Recognitions are switched off in your settings.",
            code="recognition_disabled",
        )

    last = await _last_button_run(session, user.id)
    if last is not None:
        next_allowed = last + RUN_COOLDOWN
        raise RateLimited(
            "KnoRI can take a fresh look once every 10 minutes. Try again shortly.",
            retry_after=max(1, int((next_allowed - now()).total_seconds()) + 1),
            bucket="recognitions_run",
        )

    dedupe_key = dedupe_key_for(INTERPRET_JOB, user.id)
    job = await enqueue(
        session,
        INTERPRET_JOB,
        {"trigger": "button"},
        lane="slow",
        user_id=user.id,
        dedupe_key=dedupe_key,
        lock_key=reasoning_lock_key(user.id),
        priority=3,
    )
    job_id = job.id if job is not None else await _queued_interpret(session, user.id, dedupe_key)
    await session.commit()
    return RunResponse(job_id=job_id, status="queued", next_allowed_at=now() + RUN_COOLDOWN)


async def _queued_interpret(
    session: AsyncSession, user_id: uuid.UUID, dedupe_key: str
) -> uuid.UUID | None:
    """A run was already waiting: point the caller at it instead of a new one."""
    return await session.scalar(
        select(Job.id).where(
            Job.user_id == user_id,
            Job.dedupe_key == dedupe_key,
            Job.status == "queued",
        )
    )


__all__ = [
    "ACTION_STATES",
    "ANSWERABLE_STATES",
    "FEEDBACK_JOB",
    "INTERPRET_JOB",
    "REASON_CODES",
    "RESOLVED_STATES",
    "RUN_COOLDOWN",
    "FeedbackPlan",
    "check_reason_code",
    "clean_correction",
    "mark_seen",
    "plan_feedback",
    "reasoning_lock_key",
    "request_run",
    "submit_feedback",
]
