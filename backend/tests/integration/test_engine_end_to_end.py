"""The whole loop against a real Postgres: message → card → correction.

One test walks every step the product exists for, with no API key and no money
spent — the model layer is real, the provider reads scripted answers, and the
embeddings are the deterministic fake ones.

    two messages, two days apart
      → signals, each with a quote that is really in the message
      → an interpretation with its evidence
      → conf-v1 and thr-v1, with the decision written to the ledger
      → a card with at least two provenance rows, placed in the conversation
      → the user corrects it
      → an assertion, an amended claim carrying the correction as dated support,
        and a "what changed" panel that is ready

What the test refuses to accept is as important as what it asserts: the card body
must not repeat a quote, and the amended claim must not be the old one edited.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knori.db.models import Conversation, ConversationEvent, Message, User, UserSettings
from ros.engine.pipeline import (
    PipelineDeps,
    apply_feedback,
    run_composition,
    run_extraction,
    run_interpretation,
)
from ros.llm.providers.fake import FakeProvider
from ros.llm.router import build_router
from ros.persistence.models import (
    CorrectionEffect,
    Evidence,
    Interpretation,
    MemoryItem,
    Recognition,
    RecognitionFeedback,
    RecognitionProvenance,
    Signal,
    ThresholdEvaluation,
    UserAssertion,
)
from ros.persistence.pg_memory import PgMemoryStore, PgRetriever

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
DAY_ONE = datetime(2026, 9, 18, 9, 5, tzinfo=UTC)
DAY_TWO = datetime(2026, 9, 19, 21, 40, tzinfo=UTC)

TEXT_ONE = "i keep putting off the invoices, third week now tbh"
TEXT_TWO = "still have not sent the invoices, spent the day on other things"
QUOTE_ONE = "i keep putting off the invoices"
QUOTE_TWO = "still have not sent the invoices"

CORRECTION = "That is only when a project is still running. I invoice fine once it ships."


# ------------------------------------------------------------------ the answers


def _signal(ref: str, quote: str) -> dict[str, Any]:
    return {
        "message_ref": ref,
        "kind": "behavior",
        "subject": "self",
        "topic": "work.workload",
        "content": f"The user mentions {quote}.",
        "quote_text": quote,
        "polarity": -1,
        "strength": 1.0,
        "sensitive_category": None,
        "context_tags": ["work"],
    }


REPLIES: dict[str, Any] = {
    "extract.signals": {
        "signals": [_signal("M1", QUOTE_ONE), _signal("M2", QUOTE_TWO)],
        "memory_candidates": [
            {
                "message_ref": "M1",
                "kind": "fact",
                "key": "fact.billing",
                "statement": "The user bills clients by invoice.",
                "quote_text": "the invoices",
                "sensitive_category": None,
            }
        ],
        "skipped_reason": None,
    },
    "interpret.recognize": {
        "proposals": [
            {
                "action": "create",
                "ref": None,
                "kind": "pattern",
                "topic": "work.workload",
                "statement": "The user postpones invoicing for weeks at a time.",
                "rationale": "Raised on two separate days, both times unfinished.",
                "evidence": [
                    {
                        "signal_ref": ref,
                        "role": "supports",
                        "weight": 1.0,
                        "note": "Their own words about the same unfinished task.",
                    }
                    for ref in ("S1", "S2")
                ],
                "model_confidence": 0.82,
                "sensitive_category": None,
            }
        ],
        "declined": [
            {
                "about": "a second reading about being disorganised in general",
                "reason": "ambiguous",
                "signal_refs": ["S1"],
            }
        ],
    },
    "recognize.compose": {
        "title": "Billing slips down the list",
        "body": (
            "It looks like sending money requests is the thing that waits when the week "
            "fills up. You have come back to it on different days without finishing it."
        ),
        "explanation": (
            "Two separate days, the same unfinished task, both in your own words. "
            "That is a tentative read — correct it if it is wrong."
        ),
        "cited_signal_refs": ["S1", "S2"],
    },
    "correction.parse": {
        "kind": "amend",
        "assertion_statement": "The user delays invoicing only while a project is still running.",
        "replacement_claim": "The user delays invoicing while a project is still running.",
        "contradicted_signal_refs": [],
        "topic": "work.workload",
    },
    "profile.compile": {
        "profile_text": "## About\n\n- Bills clients by invoice.",
        "sections": [{"heading": "About", "lines": ["Bills clients by invoice."]}],
    },
}


def router_with(tmp_path: Path, replies: dict[str, Any]) -> Any:
    for task, parsed in replies.items():
        (tmp_path / f"{task}.json").write_text(json.dumps({"parsed": parsed}), encoding="utf-8")
    router = build_router()
    provider = FakeProvider(fixtures_dir=tmp_path)
    router.providers = dict.fromkeys(router.providers, provider)
    return router


# --------------------------------------------------------------------- the data


@dataclass(slots=True)
class World:
    user: User
    conversation: Conversation
    messages: list[Message]
    deps: PipelineDeps
    queued: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    published: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


@pytest.fixture
async def world(db_session: AsyncSession, tmp_path: Path) -> AsyncIterator[World]:
    user = User(
        id=uuid.uuid4(),
        email=f"engine-{uuid.uuid4().hex}@knori.test",
        password_hash="argon2-not-a-real-hash",
        display_name="Sam",
        timezone="UTC",
        email_verified_at=DAY_ONE,
    )
    db_session.add(user)
    # These models carry no ORM relationships, so one flush does not order the inserts
    # for us: the user has to exist before anything points at it.
    await db_session.flush()
    db_session.add(UserSettings(user_id=user.id))
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user.id, kind="chat", title="Invoices", last_seq=2
    )
    db_session.add(conversation)
    await db_session.flush()

    messages = [
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=user.id,
            seq=seq,
            role="user",
            content=content,
            created_at=sent_at,
        )
        for seq, content, sent_at in (
            (1, TEXT_ONE, DAY_ONE),
            (2, TEXT_TWO, DAY_TWO),
        )
    ]
    db_session.add_all(messages)
    await db_session.flush()

    queued: list[tuple[str, dict[str, Any]]] = []
    published: list[tuple[str, dict[str, Any]]] = []

    async def _enqueue(kind: str, payload: dict[str, Any], **kwargs: Any) -> None:
        queued.append((kind, payload))

    async def _publish(user_id: Any, event: str, data: dict[str, Any]) -> None:
        published.append((event, data))

    deps = PipelineDeps(
        session=db_session,
        router=router_with(tmp_path, REPLIES),
        clock=lambda: NOW,
        retriever=PgRetriever(db_session),
        memory=PgMemoryStore(db_session, clock=lambda: NOW),
        enqueue=_enqueue,
        publish=_publish,
    )
    yield World(
        user=user,
        conversation=conversation,
        messages=messages,
        deps=deps,
        queued=queued,
        published=published,
    )


async def _all(session: AsyncSession, model: Any, user_id: uuid.UUID) -> list[Any]:
    rows = await session.scalars(select(model).where(model.user_id == user_id))
    return list(rows.all())


# --------------------------------------------------------------------- the walk


async def test_two_messages_become_a_card_the_user_can_correct(
    world: World, db_session: AsyncSession
) -> None:
    user_id = world.user.id

    # 1. extraction — quotes are located in the message or the signal is dropped.
    extraction = await run_extraction(world.deps, user_id, [m.id for m in world.messages])
    assert (extraction.signals, extraction.dropped_quotes) == (2, 0)

    signals = sorted(await _all(db_session, Signal, user_id), key=lambda s: s.observed_at)
    by_message = {str(m.id): m for m in world.messages}
    for row in signals:
        source = by_message[str(row.message_id)]
        assert source.content[row.quote_start : row.quote_end] == row.quote_text
        assert row.observed_at == source.created_at
        assert row.embedding is not None
    # mark_extracted is a SQL UPDATE, so expire the loaded rows before reading them back.
    for message in world.messages:
        await db_session.refresh(message)
    assert [m.extracted_at is not None for m in world.messages] == [True, True]
    assert len(await _all(db_session, MemoryItem, user_id)) == 1

    # 2. interpretation — the claim, its evidence, and the ledger of what was not said.
    interpretation = await run_interpretation(world.deps, user_id)
    assert (interpretation.proposals, interpretation.declined) == (1, 1)

    claims = await _all(db_session, Interpretation, user_id)
    assert len(claims) == 1
    claim = claims[0]
    evidence = list(
        (
            await db_session.scalars(select(Evidence).where(Evidence.interpretation_id == claim.id))
        ).all()
    )
    assert len(evidence) == 2
    assert all(e.role == "supports" for e in evidence)

    ledger = await _all(db_session, ThresholdEvaluation, user_id)
    assert any(row.outcome == "decline" and row.candidate_text for row in ledger)
    assert any(row.outcome == "recognize" for row in ledger)
    # Numeric columns come back as Decimal; compare as floats.
    assert float(claim.confidence) == pytest.approx(0.73, abs=0.02)
    assert ("compose_recognition", {"interpretation_id": str(claim.id), "version": 1}) in [
        (kind, payload) for kind, payload in world.queued
    ]

    # 3. composition — a card with its receipt, placed in the conversation.
    composed = await run_composition(world.deps, user_id, claim.id)
    assert composed.recognition_id is not None

    card = (await _all(db_session, Recognition, user_id))[0]
    assert card.state == "pending"
    assert card.confidence_label == "likely"
    assert QUOTE_ONE not in card.body and QUOTE_TWO not in card.body
    assert QUOTE_ONE not in card.explanation and QUOTE_TWO not in card.explanation

    provenance = list(
        (
            await db_session.scalars(
                select(RecognitionProvenance).where(RecognitionProvenance.recognition_id == card.id)
            )
        ).all()
    )
    assert len(provenance) >= 2
    assert all(row.message_id is not None for row in provenance)
    assert {row.quote_text for row in provenance} == {QUOTE_ONE, QUOTE_TWO}

    placement = (
        await db_session.scalars(
            select(ConversationEvent).where(ConversationEvent.recognition_id == card.id)
        )
    ).first()
    assert placement is not None
    assert placement.conversation_id == world.conversation.id
    assert any(event == "recognition.created" for event, _ in world.published)

    # 4. the user corrects it, the way the API records the answer.
    feedback = RecognitionFeedback(
        id=uuid.uuid4(),
        user_id=user_id,
        recognition_id=card.id,
        action="correct",
        correction_text=CORRECTION,
        created_at=NOW,
    )
    card.state = "corrected"
    card.resolved_at = NOW
    db_session.add(feedback)
    # The effect row points at the feedback row, and one flush will not order them.
    await db_session.flush()
    db_session.add(
        CorrectionEffect(
            user_id=user_id,
            feedback_id=feedback.id,
            status="pending",
            summary="KnoRI is working out what your correction changes.",
            profile_before_text="## About\n\n- Bills clients by invoice.",
        )
    )
    await db_session.flush()

    applied = await apply_feedback(world.deps, user_id, feedback.id)
    assert applied.action == "correct"
    assert applied.amended_interpretation_id is not None

    assertions = await _all(db_session, UserAssertion, user_id)
    assert [a.kind for a in assertions] == ["amend"]
    assert "not true" not in assertions[0].statement.lower()

    await db_session.refresh(claim)
    amended = (
        await db_session.scalars(
            select(Interpretation).where(
                Interpretation.id == uuid.UUID(applied.amended_interpretation_id)
            )
        )
    ).one()
    assert claim.lifecycle_status == "superseded"
    assert amended.source == "user_correction"
    assert amended.supersedes_id == claim.id
    assert float(amended.model_confidence) == 1.0
    assert amended.statement != claim.statement
    assert assertions[0].applies_to_interpretation_id == amended.id

    effect = (
        await db_session.scalars(
            select(CorrectionEffect).where(CorrectionEffect.feedback_id == feedback.id)
        )
    ).one()
    assert effect.status == "ready"
    assert effect.ready_at is not None
    assert effect.profile_before_text == "## About\n\n- Bills clients by invoice."
    assert effect.assertions_created == [str(assertions[0].id)]

    await db_session.refresh(feedback)
    assert feedback.processed_at is not None
    assert any(event == "correction.effect.ready" for event, _ in world.published)
    assert any(kind == "compile_profile" for kind, _ in world.queued)


async def test_the_amended_claim_still_has_two_dated_supports(
    world: World, db_session: AsyncSession
) -> None:
    """R3 survives a correction: the assertion itself counts as a support (plan §4.6)."""
    user_id = world.user.id
    await run_extraction(world.deps, user_id, [m.id for m in world.messages])
    await run_interpretation(world.deps, user_id)
    claim = (await _all(db_session, Interpretation, user_id))[0]
    await run_composition(world.deps, user_id, claim.id)
    card = (await _all(db_session, Recognition, user_id))[0]

    feedback = RecognitionFeedback(
        id=uuid.uuid4(),
        user_id=user_id,
        recognition_id=card.id,
        action="correct",
        correction_text=CORRECTION,
        created_at=NOW,
    )
    card.state = "corrected"
    db_session.add(feedback)
    await db_session.flush()

    applied = await apply_feedback(world.deps, user_id, feedback.id)
    amended_id = uuid.UUID(str(applied.amended_interpretation_id))

    carried = list(
        (
            await db_session.scalars(
                select(Evidence).where(
                    Evidence.interpretation_id == amended_id, Evidence.removed_at.is_(None)
                )
            )
        ).all()
    )
    assert len(carried) == 2
    amended = (
        await db_session.scalars(select(Interpretation).where(Interpretation.id == amended_id))
    ).one()
    # A claim the user wrote is never scored below the floor in conf-v1.
    assert float(amended.confidence) >= 0.73
    assert amended.gate_outcome in ("recognize", "hold")
