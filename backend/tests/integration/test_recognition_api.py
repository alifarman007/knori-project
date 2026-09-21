"""The Recognition endpoints against a real database.

The app is assembled here from the Recognition router alone rather than from
``knori.main``: this slice must be testable while the other routers are still
being written, and a narrower app makes a failure here unambiguous.

The test that matters most is the last kind: one user must never be able to read
another's card, and the answer must be **404** — a 403 would confirm that the
card exists.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api import deps
from knori.api.routers import recognitions as recognitions_router
from knori.core.errors import PROBLEM_CONTENT_TYPE, AppError
from knori.core.rate_limit import get_rate_limiter
from knori.db.models import Conversation, Job, Message, User, UserSettings
from knori.services.feedback import reasoning_lock_key
from ros.persistence.models import (
    CorrectionEffect,
    Interpretation,
    Recognition,
    RecognitionEvent,
    RecognitionFeedback,
    RecognitionProvenance,
)

pytestmark = pytest.mark.integration

API = "/api/v1"
DAY_ONE = datetime(2026, 3, 3, 8, 30, tzinfo=UTC)
DAY_TWO = datetime(2026, 3, 5, 21, 15, tzinfo=UTC)
QUOTE_ONE = "I went for a run before work again"
QUOTE_TWO = "ended up walking the long way home to clear my head"


# ------------------------------------------------------------------ the app


async def _problem(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        exc.to_problem(instance=request.url.path),
        status_code=exc.status,
        media_type=PROBLEM_CONTENT_TYPE,
    )


def build_app(session: AsyncSession, user: User) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, _problem)
    app.include_router(recognitions_router.router, prefix=API)

    async def _session() -> AsyncSession:
        return session

    async def _current_user(request: Request) -> User:
        # The real dependency does this too; the per-user rate limit reads it.
        request.state.user_id = user.id
        return user

    app.dependency_overrides[deps.db_session] = _session
    app.dependency_overrides[deps.current_user] = _current_user
    return app


async def client_for(session: AsyncSession, user: User) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=build_app(session, user)), base_url="http://test"
    )


# ----------------------------------------------------------------- the data


@dataclass(slots=True)
class World:
    owner: User
    stranger: User
    conversation: Conversation
    card: Recognition
    interpretation: Interpretation


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash="argon2-not-a-real-hash",
        display_name=email.split("@")[0],
        timezone="UTC",
        email_verified_at=DAY_ONE,
    )


@pytest.fixture
async def world(db_session: AsyncSession) -> AsyncIterator[World]:
    get_rate_limiter().reset()
    owner, stranger = (
        _user(f"owner-{uuid.uuid4().hex}@knori.test"),
        _user(f"other-{uuid.uuid4().hex}@knori.test"),
    )
    db_session.add_all([owner, stranger])
    db_session.add_all([UserSettings(user_id=owner.id), UserSettings(user_id=stranger.id)])
    await db_session.flush()

    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, kind="chat", title="Monday morning", last_seq=4
    )
    db_session.add(conversation)
    messages = [
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=owner.id,
            seq=seq,
            role="user",
            content=content,
            created_at=created_at,
        )
        for seq, content, created_at in (
            (1, QUOTE_ONE, DAY_ONE),
            (3, QUOTE_TWO, DAY_TWO),
        )
    ]
    db_session.add_all(messages)

    interpretation = Interpretation(
        id=uuid.uuid4(),
        user_id=owner.id,
        kind="pattern",
        topic="movement",
        statement="They move on their own before and after work.",
        rationale="Two separate days, both unprompted.",
        lifecycle_status="recognized",
        gate_outcome="recognize",
        version=1,
        confidence=0.73,
        confidence_breakdown={"supports": 2, "contradicts": 0, "distinct_days": 2},
        model_confidence=0.8,
    )
    db_session.add(interpretation)
    await db_session.flush()

    card = Recognition(
        id=uuid.uuid4(),
        user_id=owner.id,
        interpretation_id=interpretation.id,
        interpretation_version=1,
        kind="pattern",
        title="Moving to think",
        body="It looks like walking and running are how you clear your head, not just exercise.",
        explanation="You mentioned this twice, two days apart, both times unprompted.",
        confidence=0.73,
        confidence_label="likely",
        state="pending",
        created_at=DAY_TWO,
    )
    db_session.add(card)
    await db_session.flush()

    for order, (message, quote, at) in enumerate(
        [(messages[0], QUOTE_ONE, DAY_ONE), (messages[1], QUOTE_TWO, DAY_TWO)]
    ):
        db_session.add(
            RecognitionProvenance(
                id=uuid.uuid4(),
                recognition_id=card.id,
                kind="signal",
                message_id=message.id,
                conversation_id=conversation.id,
                conversation_title=conversation.title,
                seq=message.seq,
                quote_text=quote,
                quote_start=0,
                quote_end=len(quote),
                message_created_at=at,
                role="supports",
                weight=1.0,
                display_order=order,
            )
        )
    db_session.add(
        RecognitionEvent(
            id=uuid.uuid4(),
            user_id=owner.id,
            interpretation_id=interpretation.id,
            recognition_id=card.id,
            event="created",
            actor="system",
            payload={"confidence": 0.73},
        )
    )
    await db_session.flush()

    yield World(
        owner=owner,
        stranger=stranger,
        conversation=conversation,
        card=card,
        interpretation=interpretation,
    )


# ------------------------------------------------------------------- reads


async def test_the_new_tab_lists_the_card_with_its_plain_sentence(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        response = await client.get(f"{API}/recognitions", params={"state": "new"})

    assert response.status_code == 200
    page = response.json()
    assert [item["id"] for item in page["items"]] == [str(world.card.id)]
    confidence = page["items"][0]["confidence"]
    assert confidence["plain"] == (
        "Based on 2 things you said across 2 days; nothing you said pointed the other way."
    )
    assert confidence["label"] == "likely"
    assert page["next_cursor"] is None


async def test_the_detail_carries_the_quotes_and_the_deep_links(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        response = await client.get(f"{API}/recognitions/{world.card.id}")

    assert response.status_code == 200
    card = response.json()
    supports = card["evidence"]["supports"]
    assert [row["quote"] for row in supports] == [QUOTE_ONE, QUOTE_TWO]
    assert card["evidence"]["contradicts"] == []
    assert supports[0]["deep_link"] == (
        f"/app/chat/{world.conversation.id}?m=1&hl=0-{len(QUOTE_ONE)}"
    )
    assert supports[0]["conversation_title"] == "Monday morning"
    assert card["interpretation"]["lifecycle_status"] == "recognized"
    assert card["feedback"] is None and card["correction_effect"] is None


async def test_the_summary_counts_what_the_badge_shows(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        response = await client.get(f"{API}/recognitions/summary")

    assert response.status_code == 200
    assert response.json()["new"] == 1
    assert response.json()["unseen"] == 1
    assert response.json()["accepted"] == 0


async def test_the_history_reads_as_a_timeline(db_session: AsyncSession, world: World) -> None:
    async with await client_for(db_session, world.owner) as client:
        response = await client.get(f"{API}/recognitions/{world.card.id}/history")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["event"] for entry in entries] == ["created"]
    assert entries[0]["label"] == "KnoRI wrote this card."


async def test_an_unknown_tab_is_rejected(db_session: AsyncSession, world: World) -> None:
    async with await client_for(db_session, world.owner) as client:
        response = await client.get(f"{API}/recognitions", params={"state": "everything"})
    assert response.status_code == 400
    assert response.json()["code"] == "bad_state"


# ------------------------------------------------------------------ writes


async def test_seen_moves_pending_to_presented_once(db_session: AsyncSession, world: World) -> None:
    async with await client_for(db_session, world.owner) as client:
        first = await client.post(f"{API}/recognitions/{world.card.id}/seen")
        second = await client.post(f"{API}/recognitions/{world.card.id}/seen")

    assert first.status_code == 200
    assert first.json()["state"] == "presented"
    assert second.json()["presented_at"] == first.json()["presented_at"]

    events = list(
        await db_session.scalars(
            select(RecognitionEvent).where(
                RecognitionEvent.recognition_id == world.card.id,
                RecognitionEvent.event == "presented",
            )
        )
    )
    assert len(events) == 1


async def test_accepting_leaves_everything_the_ui_needs_before_the_202(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        await client.post(f"{API}/recognitions/{world.card.id}/seen")
        response = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback", json={"action": "accept"}
        )

    assert response.status_code == 202
    body = response.json()
    feedback_id = uuid.UUID(body["feedback_id"])
    assert body["state"] == "accepted"
    assert body["effect_status"] == "pending"
    assert response.headers["Location"] == body["effect_url"]

    await db_session.refresh(world.card)
    assert world.card.state == "accepted"
    assert world.card.resolved_at is not None

    feedback = await db_session.get(RecognitionFeedback, feedback_id)
    assert feedback is not None and feedback.action == "accept"

    effect = await db_session.scalar(
        select(CorrectionEffect).where(CorrectionEffect.feedback_id == feedback_id)
    )
    assert effect is not None and effect.status == "pending"

    job = await db_session.scalar(select(Job).where(Job.id == uuid.UUID(body["job_id"])))
    assert job is not None
    assert job.kind == "apply_feedback"
    assert job.payload == {"feedback_id": str(feedback_id)}
    assert job.lock_key == reasoning_lock_key(world.owner.id)
    assert job.lane == "fast"

    event = await db_session.scalar(
        select(RecognitionEvent).where(
            RecognitionEvent.recognition_id == world.card.id,
            RecognitionEvent.event == "accepted",
        )
    )
    assert event is not None and event.actor == "user"


async def test_a_correction_needs_text_and_goes_to_the_slow_lane(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        empty = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback",
            json={"action": "correct", "correction_text": "   "},
        )
        assert empty.status_code == 422

        response = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback",
            json={
                "action": "correct",
                "correction_text": "It is about the noise, not the exercise.",
                "reason_code": "partly_true",
            },
        )
        assert response.status_code == 202
        effect = await client.get(f"{API}/corrections/{response.json()['feedback_id']}/effect")

    assert effect.status_code == 200
    assert effect.json()["status"] == "pending"
    assert effect.json()["plain"] == "KnoRI is working out what this changes."

    job = await db_session.scalar(select(Job).where(Job.id == uuid.UUID(response.json()["job_id"])))
    assert job is not None and job.lane == "slow"


async def test_you_cannot_answer_the_same_card_twice(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        first = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback", json={"action": "reject"}
        )
        second = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback", json={"action": "accept"}
        )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["code"] == "already_answered"


async def test_an_unknown_reason_code_is_refused(db_session: AsyncSession, world: World) -> None:
    async with await client_for(db_session, world.owner) as client:
        response = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback",
            json={"action": "dismiss", "reason_code": "because"},
        )
    # The literal is enforced by the schema before the service is reached.
    assert response.status_code == 422


# ------------------------------------------------------- the button and jobs


async def test_the_button_queues_one_interpret_run_per_ten_minutes(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        first = await client.post(f"{API}/recognitions/run")
        second = await client.post(f"{API}/recognitions/run")

    assert first.status_code == 202
    job_id = uuid.UUID(first.json()["job_id"])
    job = await db_session.get(Job, job_id)
    assert job is not None
    assert job.kind == "interpret"
    assert job.lane == "slow"
    assert job.payload == {"trigger": "button"}
    assert job.lock_key == reasoning_lock_key(world.owner.id)

    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"
    assert 0 < int(second.json()["retry_after"]) <= 600


async def test_the_button_is_refused_when_recognitions_are_switched_off(
    db_session: AsyncSession, world: World
) -> None:
    settings = await db_session.get(UserSettings, world.owner.id)
    assert settings is not None
    settings.recognition_enabled = False
    await db_session.flush()

    async with await client_for(db_session, world.owner) as client:
        response = await client.post(f"{API}/recognitions/run")

    assert response.status_code == 409
    assert response.json()["code"] == "recognition_disabled"


async def test_job_status_is_readable_by_its_owner(db_session: AsyncSession, world: World) -> None:
    job = Job(
        id=uuid.uuid4(),
        kind="interpret",
        lane="slow",
        user_id=world.owner.id,
        payload={"trigger": "button"},
        status="running",
        run_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    db_session.add(job)
    await db_session.flush()

    async with await client_for(db_session, world.owner) as client:
        response = await client.get(f"{API}/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["failed"] is False


# --------------------------------------------------- one user, one set of rows


async def test_another_users_card_is_not_found_never_forbidden(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.stranger) as client:
        detail = await client.get(f"{API}/recognitions/{world.card.id}")
        history = await client.get(f"{API}/recognitions/{world.card.id}/history")
        seen = await client.post(f"{API}/recognitions/{world.card.id}/seen")
        feedback = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback", json={"action": "accept"}
        )
        listed = await client.get(f"{API}/recognitions", params={"state": "new"})
        summary = await client.get(f"{API}/recognitions/summary")

    for response in (detail, history, seen, feedback):
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"
    assert listed.json()["items"] == []
    assert summary.json()["total"] == 0

    # Nothing the stranger did touched the owner's card.
    await db_session.refresh(world.card)
    assert world.card.state == "pending"


async def test_another_users_correction_effect_and_job_are_not_found(
    db_session: AsyncSession, world: World
) -> None:
    async with await client_for(db_session, world.owner) as client:
        accepted = await client.post(
            f"{API}/recognitions/{world.card.id}/feedback", json={"action": "dismiss"}
        )
    feedback_id = accepted.json()["feedback_id"]
    job_id = accepted.json()["job_id"]

    async with await client_for(db_session, world.stranger) as client:
        effect = await client.get(f"{API}/corrections/{feedback_id}/effect")
        job = await client.get(f"{API}/jobs/{job_id}")

    assert effect.status_code == 404
    assert job.status_code == 404
