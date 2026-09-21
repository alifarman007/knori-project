"""The first five minutes: a name, consent, and three questions.

Steps 1 and 2 write to ``users`` and ``legal_acceptances`` directly. Step 3 is
different on purpose: the answers are written as **real messages** in a conversation
of kind ``onboarding``, so they go through extraction like anything else the person
types and end up in memory with verifiable quotes (plan.md §8). Nothing about
onboarding is special-cased downstream.

Progress is derived, never stored: a preferred name means step 1 is done, a legal
acceptance means step 2 is done, and the number of user messages in the onboarding
conversation says how far step 3 got. There is no counter that can disagree with the
data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.deps import CurrentUser, DbSession, client_ip
from knori.api.schemas.account import (
    OnboardingAnswerIn,
    OnboardingCompleteOut,
    OnboardingStateOut,
)
from knori.core.clock import now
from knori.core.errors import Conflict, ValidationFailed
from knori.core.logging import get_logger
from knori.db.models import Conversation, Message, User
from knori.jobs.queue import dedupe_key_for, enqueue
from knori.services import accounts
from knori.services.accounts import ONBOARDING_QUESTIONS

log = get_logger("knori.onboarding")

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

PARSE_JOB = "onboarding_parse"
PROFILE_JOB = "compile_profile"

# Roughly four characters per token; good enough for a budget, never for billing.
CHARS_PER_TOKEN = 4


# ---------------------------------------------------------------- derived progress


@dataclass(frozen=True, slots=True)
class OnboardingFacts:
    """Derived state — there is no progress column that could drift from reality."""

    step_1_done: bool
    step_2_done: bool
    answers_given: int
    conversation_id: uuid.UUID | None
    completed: bool

    @property
    def step_3_done(self) -> bool:
        return self.answers_given >= len(ONBOARDING_QUESTIONS)

    @property
    def current_step(self) -> int:
        if not self.step_1_done:
            return 1
        if not self.step_2_done:
            return 2
        return 3

    @property
    def next_question(self) -> str | None:
        if self.step_3_done:
            return None
        return ONBOARDING_QUESTIONS[self.answers_given]


async def onboarding_conversation(session: AsyncSession, user_id: uuid.UUID) -> Conversation | None:
    return await session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.kind == "onboarding")
        .order_by(Conversation.created_at.asc())
        .limit(1)
    )


async def onboarding_facts(session: AsyncSession, user: User) -> OnboardingFacts:
    """Read the four facts that say how far this person got."""
    conversation = await onboarding_conversation(session, user.id)
    answers = 0
    if conversation is not None:
        answers = int(
            await session.scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.user_id == user.id,
                    Message.role == "user",
                )
            )
            or 0
        )
    legal = await accounts.latest_legal(session, user.id)
    return OnboardingFacts(
        step_1_done=bool(user.preferred_name),
        step_2_done=legal is not None,
        answers_given=answers,
        conversation_id=conversation.id if conversation is not None else None,
        completed=user.onboarding_completed_at is not None,
    )


def build_onboarding_state(facts: OnboardingFacts) -> OnboardingStateOut:
    return OnboardingStateOut(
        completed=facts.completed,
        current_step=facts.current_step,
        steps_total=3,
        step_1_done=facts.step_1_done,
        step_2_done=facts.step_2_done,
        step_3_done=facts.step_3_done,
        questions=list(ONBOARDING_QUESTIONS),
        answers_given=facts.answers_given,
        next_question=facts.next_question,
        conversation_id=str(facts.conversation_id) if facts.conversation_id else None,
    )


@router.get("", summary="How far through onboarding am I?")
async def read_state(user: CurrentUser, session: DbSession) -> OnboardingStateOut:
    return build_onboarding_state(await onboarding_facts(session, user))


@router.post("/answer", summary="Answer one onboarding step")
async def answer(
    body: OnboardingAnswerIn, request: Request, user: CurrentUser, session: DbSession
) -> OnboardingStateOut:
    ip = client_ip(request)
    if body.step == 1:
        await _step_one(session, user, body)
    elif body.step == 2:
        await _step_two(session, user, body, ip=ip)
    else:
        await _step_three(session, user, body)

    await accounts.record_audit(
        session,
        action="onboarding.answer",
        user_id=user.id,
        meta={"step": body.step},
        ip=ip,
    )
    await session.commit()
    return build_onboarding_state(await onboarding_facts(session, user))


@router.post("/complete", status_code=status.HTTP_202_ACCEPTED, summary="Finish onboarding")
async def complete(
    request: Request, user: CurrentUser, session: DbSession
) -> OnboardingCompleteOut:
    """Mark onboarding done and ask for the two background passes over the answers.

    Both handlers belong to other slices; this only enqueues them, in the same
    transaction as the change, so neither can run for an onboarding that rolled back.
    """
    facts = await onboarding_facts(session, user)
    if not facts.step_2_done:
        raise Conflict("Accept the terms before finishing onboarding.", code="consent_missing")

    if user.onboarding_completed_at is None:
        user.onboarding_completed_at = now()

    enqueued: list[str] = []
    payload: dict[str, Any] = {
        "conversation_id": str(facts.conversation_id) if facts.conversation_id else None,
        "reason": "onboarding_complete",
    }
    if facts.conversation_id is not None:
        created = await enqueue(
            session,
            PARSE_JOB,
            payload,
            user_id=user.id,
            dedupe_key=dedupe_key_for(PARSE_JOB, user.id),
        )
        if created is not None:
            enqueued.append(PARSE_JOB)
    # Lower priority so the parse is claimed first and the profile sees its output.
    created_profile = await enqueue(
        session,
        PROFILE_JOB,
        {"reason": "onboarding_complete"},
        user_id=user.id,
        priority=7,
        dedupe_key=dedupe_key_for(PROFILE_JOB, user.id),
    )
    if created_profile is not None:
        enqueued.append(PROFILE_JOB)

    await accounts.record_audit(
        session,
        action="onboarding.complete",
        user_id=user.id,
        meta={"jobs": enqueued},
        ip=client_ip(request),
    )
    await session.commit()
    return OnboardingCompleteOut(
        onboarding=build_onboarding_state(await onboarding_facts(session, user)),
        jobs_enqueued=enqueued,
    )


# ----------------------------------------------------------------------------- steps


async def _step_one(session: AsyncSession, user: User, body: OnboardingAnswerIn) -> None:
    name = (body.preferred_name or body.text or "").strip()
    if not name:
        raise ValidationFailed(
            "Tell KnoRI what to call you.",
            errors=[{"field": "preferred_name", "code": "required"}],
        )
    user.preferred_name = name[:80]
    if body.timezone:
        user.timezone = body.timezone
    await session.flush()


async def _step_two(
    session: AsyncSession, user: User, body: OnboardingAnswerIn, *, ip: str
) -> None:
    await accounts.accept_legal(
        session,
        user,
        tos_version=body.tos_version or accounts.CURRENT_TOS_VERSION,
        privacy_version=body.privacy_version or accounts.CURRENT_PRIVACY_VERSION,
        ip=ip,
    )


async def _step_three(session: AsyncSession, user: User, body: OnboardingAnswerIn) -> None:
    answer_text = body.text.strip()
    if not answer_text:
        raise ValidationFailed(
            "Write a sentence or two.", errors=[{"field": "text", "code": "required"}]
        )

    conversation = await onboarding_conversation(session, user.id)
    if conversation is None:
        conversation = Conversation(
            user_id=user.id,
            kind="onboarding",
            title=accounts.ONBOARDING_CONVERSATION_TITLE,
        )
        session.add(conversation)
        await session.flush()

    facts = await onboarding_facts(session, user)
    if facts.step_3_done:
        raise Conflict("All the onboarding questions are answered.", code="onboarding_done")

    question = ONBOARDING_QUESTIONS[facts.answers_given]
    first_seq = await _reserve_seq(session, conversation.id, user.id, count=2)
    moment = now()
    session.add(
        Message(
            conversation_id=conversation.id,
            user_id=user.id,
            seq=first_seq,
            role="assistant",
            content=question,
            token_estimate=len(question) // CHARS_PER_TOKEN,
            status="complete",
            created_at=moment,
        )
    )
    session.add(
        Message(
            conversation_id=conversation.id,
            user_id=user.id,
            seq=first_seq + 1,
            role="user",
            content=answer_text,
            token_estimate=len(answer_text) // CHARS_PER_TOKEN,
            status="complete",
            created_at=moment,
        )
    )
    await session.flush()


async def _reserve_seq(
    session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, *, count: int
) -> int:
    """Take ``count`` sequence numbers in one statement, and return the first.

    Doing the increment inside the UPDATE is what makes it safe: two requests can
    never be handed the same seq, and ``user_id`` in the WHERE means a conversation
    that is not yours cannot be advanced at all.
    """
    row = (
        await session.execute(
            text(
                """
                UPDATE conversations
                   SET last_seq = last_seq + :count,
                       message_count = message_count + :count,
                       last_message_at = :now
                 WHERE id = :id AND user_id = :user_id
                RETURNING last_seq
                """
            ),
            {"count": count, "id": conversation_id, "user_id": user_id, "now": now()},
        )
    ).first()
    if row is None:
        raise Conflict("That conversation is gone.", code="conversation_missing")
    return int(row.last_seq) - count + 1


__all__ = [
    "PARSE_JOB",
    "PROFILE_JOB",
    "OnboardingFacts",
    "build_onboarding_state",
    "onboarding_conversation",
    "onboarding_facts",
    "router",
]
