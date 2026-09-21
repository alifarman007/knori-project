"""The Recognition surface (plan.md §7 → Recogn., §8 → /app/recognitions).

Three groups of routes live here because they are one screen's worth of work:
the cards themselves, the effect of a correction, and the status of the job the
"What have you noticed?" button starts.

The reads are in this file with the routes they serve; the shaping is in
``knori.services.recognitions`` (pure) and the writes in
``knori.services.feedback``. No route takes a user id, every query filters by
the session's user, and a row belonging to somebody else is **404, not 403** —
a 403 would confirm that the card exists.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.deps import CurrentUser, DbSession, UserSettingsDep, VerifiedUser, rate_limit
from knori.api.schemas.recognitions import (
    CardPage,
    CorrectionEffectView,
    FeedbackAccepted,
    FeedbackRequest,
    HistoryView,
    JobView,
    RecognitionDetail,
    RecognitionSummary,
    RunResponse,
    SeenResponse,
)
from knori.core.errors import NotFound
from knori.db.models import Job, User
from knori.services import feedback as feedback_service
from knori.services import recognitions as view
from ros.persistence.models import (
    CorrectionEffect,
    Interpretation,
    Recognition,
    RecognitionEvent,
    RecognitionFeedback,
    RecognitionProvenance,
)

router = APIRouter()
cards = APIRouter(prefix="/recognitions", tags=["recognitions"])
corrections = APIRouter(prefix="/corrections", tags=["recognitions"])
jobs = APIRouter(prefix="/jobs", tags=["recognitions"])


# ------------------------------------------------------------------- loading
#
# `recognition_provenance` carries no user_id of its own. It is reached only
# through recognition ids that came out of a query already filtered by user,
# which is what keeps the isolation rule true for these tables too.


async def _provenance_for(
    session: AsyncSession, recognition_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[RecognitionProvenance]]:
    if not recognition_ids:
        return {}
    rows = await session.scalars(
        select(RecognitionProvenance)
        .where(RecognitionProvenance.recognition_id.in_(recognition_ids))
        .order_by(RecognitionProvenance.display_order, RecognitionProvenance.created_at)
    )
    grouped: dict[uuid.UUID, list[RecognitionProvenance]] = {rid: [] for rid in recognition_ids}
    for row in rows:
        grouped.setdefault(row.recognition_id, []).append(row)
    return grouped


async def _feedback_for(
    session: AsyncSession, user: User, recognition_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, RecognitionFeedback]:
    """The latest answer per card — a card is answered once, but be safe."""
    if not recognition_ids:
        return {}
    rows = await session.scalars(
        select(RecognitionFeedback)
        .where(
            RecognitionFeedback.user_id == user.id,
            RecognitionFeedback.recognition_id.in_(recognition_ids),
        )
        .order_by(RecognitionFeedback.created_at)
    )
    return {row.recognition_id: row for row in rows}


async def _effect_statuses(
    session: AsyncSession, user: User, feedback_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not feedback_ids:
        return {}
    rows = await session.execute(
        select(CorrectionEffect.feedback_id, CorrectionEffect.status).where(
            CorrectionEffect.user_id == user.id,
            CorrectionEffect.feedback_id.in_(feedback_ids),
        )
    )
    return {row.feedback_id: row.status for row in rows}


# ------------------------------------------------------------------ the tabs


@cards.get("", response_model=CardPage, summary="Cards for one tab")
async def list_recognitions(
    user: CurrentUser,
    session: DbSession,
    state: Annotated[
        str, Query(description="new, accepted, corrected, rejected, dismissed, withdrawn, all")
    ] = "new",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=view.MAX_PAGE_SIZE)] = view.DEFAULT_PAGE_SIZE,
) -> CardPage:
    states = view.states_for_tab(state)
    stmt = select(Recognition).where(Recognition.user_id == user.id, Recognition.state.in_(states))
    if cursor:
        created_at, row_id = view.decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Recognition.created_at < created_at,
                and_(Recognition.created_at == created_at, Recognition.id < row_id),
            )
        )
    rows = list(
        await session.scalars(
            stmt.order_by(Recognition.created_at.desc(), Recognition.id.desc()).limit(limit + 1)
        )
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = view.encode_cursor(rows[-1].created_at, rows[-1].id)

    ids = [row.id for row in rows]
    provenance = await _provenance_for(session, ids)
    answers = await _feedback_for(session, user, ids)
    statuses = await _effect_statuses(session, user, [a.id for a in answers.values()])
    return CardPage(
        tab=state,
        next_cursor=next_cursor,
        items=[
            view.card_row(
                row,
                provenance.get(row.id, []),
                timezone=user.timezone,
                feedback=answers.get(row.id),
                effect_status=(statuses.get(answers[row.id].id) if row.id in answers else None),
            )
            for row in rows
        ],
    )


@cards.get("/summary", response_model=RecognitionSummary, summary="Counts for the nav badge")
async def recognition_summary(user: CurrentUser, session: DbSession) -> RecognitionSummary:
    rows = await session.execute(
        select(Recognition.state, func.count())
        .where(Recognition.user_id == user.id)
        .group_by(Recognition.state)
    )
    counts = {state: int(total) for state, total in rows}
    return RecognitionSummary(
        new=counts.get("pending", 0) + counts.get("presented", 0),
        accepted=counts.get("accepted", 0),
        corrected=counts.get("corrected", 0),
        rejected=counts.get("rejected", 0),
        dismissed=counts.get("dismissed", 0),
        withdrawn=counts.get("withdrawn", 0),
        total=sum(counts.values()),
        unseen=counts.get("pending", 0),
    )


# --------------------------------------------------- the button, and its job


@cards.post(
    "/run",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="What have you noticed?",
)
async def run_recognition(
    user: VerifiedUser,
    session: DbSession,
    settings: UserSettingsDep,
    # Declared after `user` on purpose: the per-user bucket reads the user id
    # the session dependency binds, and FastAPI solves in parameter order.
    _limited: Annotated[None, Depends(rate_limit("recognitions_run", per_user=True))],
) -> RunResponse:
    return await feedback_service.request_run(session, user, settings)


@jobs.get("/{job_id}", response_model=JobView, summary="Status of your own job")
async def job_status(user: CurrentUser, session: DbSession, job_id: uuid.UUID) -> JobView:
    row = await session.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if row is None:
        raise NotFound("That job does not exist.")
    return view.job_view(row)


# ------------------------------------------------------------------ one card


@cards.get("/{recognition_id}", response_model=RecognitionDetail, summary="The full card")
async def get_recognition(
    user: CurrentUser, session: DbSession, recognition_id: uuid.UUID
) -> RecognitionDetail:
    card = await view.load_card(session, user, recognition_id)
    provenance = (await _provenance_for(session, [card.id])).get(card.id, [])
    interpretation = await session.scalar(
        select(Interpretation).where(
            Interpretation.id == card.interpretation_id,
            Interpretation.user_id == user.id,
        )
    )
    answer = (await _feedback_for(session, user, [card.id])).get(card.id)
    effect = None
    if answer is not None:
        effect = await session.scalar(
            select(CorrectionEffect).where(
                CorrectionEffect.user_id == user.id,
                CorrectionEffect.feedback_id == answer.id,
            )
        )
    return view.card_payload(
        card,
        provenance,
        timezone=user.timezone,
        interpretation=interpretation,
        feedback=answer,
        effect=effect,
    )


@cards.get("/{recognition_id}/history", response_model=HistoryView, summary="How it changed")
async def get_history(
    user: CurrentUser, session: DbSession, recognition_id: uuid.UUID
) -> HistoryView:
    card = await view.load_card(session, user, recognition_id)
    rows = await session.scalars(
        select(RecognitionEvent)
        .where(
            RecognitionEvent.user_id == user.id,
            or_(
                RecognitionEvent.recognition_id == card.id,
                # The reasoning that produced the card belongs in its story too.
                RecognitionEvent.interpretation_id == card.interpretation_id,
            ),
        )
        .order_by(RecognitionEvent.created_at, RecognitionEvent.id)
    )
    return HistoryView(recognition_id=card.id, entries=[view.history_entry(row) for row in rows])


@cards.post("/{recognition_id}/seen", response_model=SeenResponse, summary="Mark it as shown")
async def mark_seen(
    user: CurrentUser, session: DbSession, recognition_id: uuid.UUID
) -> SeenResponse:
    return await feedback_service.mark_seen(session, user, recognition_id)


@cards.post(
    "/{recognition_id}/feedback",
    response_model=FeedbackAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept, correct, reject or dismiss",
)
async def submit_feedback(
    user: VerifiedUser,
    session: DbSession,
    recognition_id: uuid.UUID,
    payload: FeedbackRequest,
    response: Response,
    _limited: Annotated[None, Depends(rate_limit("feedback", per_user=True))],
) -> FeedbackAccepted:
    accepted = await feedback_service.submit_feedback(session, user, recognition_id, payload)
    response.headers["Location"] = accepted.effect_url
    return accepted


# ----------------------------------------------------------- what it changed


@corrections.get(
    "/{feedback_id}/effect",
    response_model=CorrectionEffectView,
    summary="What your correction changed",
)
async def correction_effect(
    user: CurrentUser, session: DbSession, feedback_id: uuid.UUID
) -> CorrectionEffectView:
    row = await session.scalar(
        select(CorrectionEffect).where(
            CorrectionEffect.user_id == user.id,
            CorrectionEffect.feedback_id == feedback_id,
        )
    )
    if row is None:
        raise NotFound("There is nothing recorded for that correction.")
    return view.effect_view(row)


for _sub in (cards, corrections, jobs):
    router.include_router(_sub)

__all__ = ["router"]
