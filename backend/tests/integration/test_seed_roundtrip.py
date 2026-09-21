"""``./run seed`` and ``./run eval`` against a real Postgres.

Everything happens inside the rolled-back transaction the ``db_session`` fixture
opens, so these tests leave no demo accounts behind and can run against a database
that is in use. With no database reachable they skip rather than fail.

What is being checked is the claim the seed script makes about itself: that a
seeded account is not a fixture but the product's own output. A card exists only
because ``ros.engine.pipeline`` decided it should, and every quote behind it is
still an exact span of the message it came from.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from evals import corpus as corpus_module
from evals.judges import Judge, OfflineJudge
from evals.metrics import grounding, score_persona, trap_scores
from evals.runner import collect, judge_persona
from knori.db.models import Conversation, Message, User, UserSettings
from knori.scripts import seed
from ros.engine import pipeline
from ros.llm.router import build_router
from ros.llm.routing import LLMSettings
from ros.persistence.models import (
    Interpretation,
    MemoryItem,
    Recognition,
    RecognitionProvenance,
    Signal,
    ThresholdEvaluation,
    UserAssertion,
)

pytestmark = pytest.mark.integration


async def rows(session: AsyncSession, model: Any, user_id: uuid.UUID) -> list[Any]:
    result = await session.scalars(select(model).where(model.user_id == user_id))
    return list(result.all())


async def seed_persona(session: AsyncSession, name: str) -> tuple[seed.Persona, seed.SeedReport]:
    persona = seed.find_persona(name)
    seed.validate_or_raise(persona, topics=pipeline.taxonomy().topics)
    return persona, await seed.seed(session, persona)


# ------------------------------------------------------------------- the demo


async def test_seeding_alex_builds_an_account_with_cards_behind_real_quotes(
    db_session: AsyncSession,
) -> None:
    persona, report = await seed_persona(db_session, "alex")
    user_id = uuid.UUID(report.user_id)

    user = await db_session.get(User, user_id)
    assert user is not None
    assert user.email == persona.email
    assert user.email_verified_at is not None
    assert user.onboarding_completed_at is not None

    settings = await db_session.get(UserSettings, user_id)
    assert settings is not None
    assert settings.max_recognitions_per_day == persona.settings.max_recognitions_per_day

    # The conversations really are in the past, which is what R3 needs to be true.
    conversations = await rows(db_session, Conversation, user_id)
    assert len(conversations) == len(persona.conversations)
    messages = await rows(db_session, Message, user_id)
    assert len(messages) == report.messages
    assert all(message.created_at < persona.now for message in messages)
    assert len({m.created_at.date() for m in messages}) >= 3

    # Every signal's quote is an exact span of the message it came from.
    by_id = {str(message.id): message for message in messages}
    signals = await rows(db_session, Signal, user_id)
    assert signals and report.dropped_quotes == 0
    for signal in signals:
        source = by_id[str(signal.message_id)]
        assert source.content[signal.quote_start : signal.quote_end] == signal.quote_text
        assert signal.observed_at == source.created_at
        assert signal.embedding is not None

    assert await rows(db_session, MemoryItem, user_id)

    cards = await rows(db_session, Recognition, user_id)
    assert len(cards) >= 2, "alex is the happy path; it has to produce cards"
    for card in cards:
        provenance = list(
            (
                await db_session.scalars(
                    select(RecognitionProvenance).where(
                        RecognitionProvenance.recognition_id == card.id
                    )
                )
            ).all()
        )
        supports = [row for row in provenance if row.role == "supports"]
        assert len(supports) >= 2
        for row in supports:
            message = by_id[str(row.message_id)]
            assert message.content[row.quote_start : row.quote_end] == row.quote_text
            assert row.quote_text.lower() not in card.body.lower()


async def test_seeding_twice_rebuilds_the_account_instead_of_duplicating_it(
    db_session: AsyncSession,
) -> None:
    persona, first = await seed_persona(db_session, "alex")
    _, second = await seed_persona(db_session, "alex")

    assert second.replaced is True
    assert second.user_id != first.user_id
    assert (second.messages, second.signals, second.recognitions) == (
        first.messages,
        first.signals,
        first.recognitions,
    )

    same_email = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == persona.email)
    )
    assert same_email == 1
    # The first account's rows went with it.
    assert await rows(db_session, Signal, uuid.UUID(first.user_id)) == []


async def test_seeding_mina_shows_the_refusals_and_no_cards(db_session: AsyncSession) -> None:
    _, report = await seed_persona(db_session, "mina")
    user_id = uuid.UUID(report.user_id)

    assert report.recognitions == 0
    assert report.declined > 0
    ledger = await rows(db_session, ThresholdEvaluation, user_id)
    assert ledger, "a decision not to recognise is still written down"
    reasons = {row.reason for row in ledger}
    assert "insufficient_evidence" in reasons
    assert "below_threshold" in reasons
    # A sensitive signal is stored because the user said it, and never interpreted.
    sensitive = [row for row in await rows(db_session, Signal, user_id) if row.sensitive_category]
    assert sensitive
    assert all(row.interpreted_at is None for row in sensitive)


async def test_seeding_sam_leaves_a_finished_correction_loop(db_session: AsyncSession) -> None:
    persona, report = await seed_persona(db_session, "sam")
    user_id = uuid.UUID(report.user_id)

    assertions = await rows(db_session, UserAssertion, user_id)
    kinds = sorted(row.kind for row in assertions)
    assert kinds == ["amend", "deny"], f"expected one correction and one rejection, got {kinds}"
    assert all("not true" not in row.statement.lower() for row in assertions)

    states = {row.state for row in await rows(db_session, Recognition, user_id)}
    assert {"corrected", "rejected"} <= states

    amended = [
        row
        for row in await rows(db_session, Interpretation, user_id)
        if row.source == "user_correction"
    ]
    assert len(amended) == 1
    correction = next(f for f in persona.feedback if f.action == "correct")
    assert correction.parse is not None
    assert amended[0].statement == correction.parse.replacement
    assert float(amended[0].confidence) >= 0.85


# ------------------------------------------------------------------- the eval


async def test_an_eval_persona_replays_and_scores(db_session: AsyncSession) -> None:
    """One persona end to end through the runner's own collect-and-score path."""
    item = corpus_module.load_corpus(names=["p01_ravi"])[0]
    corpus_module.validate_or_raise(item, topics=pipeline.taxonomy().topics)

    report = await seed.seed(db_session, item.persona)
    user_id = uuid.UUID(report.user_id)
    outcome = await collect(db_session, item, user_id, report)

    assert outcome.cards, "p01 is the baseline persona; it has to produce cards"
    assert grounding(outcome).rate == 1.0

    router = build_router(LLMSettings(llm_mode="fake"))
    router.providers = dict.fromkeys(router.providers, OfflineJudge())
    judge = Judge(router, session=db_session, user_id=user_id)
    matches = await judge_persona(judge, item, outcome)

    scored = score_persona(
        outcome, item.gold, item.traps, matches, sensitive_refs=item.sensitive_refs()
    )
    failing = [score for score in scored.scores if not score.ok]
    assert not failing, "\n".join(
        f"{score.name}: {[str(f) for f in score.failures]}" for score in failing
    )

    false_recognition, abstention = trap_scores(item.traps, outcome)
    assert false_recognition.rate == 0.0
    assert abstention.rate == 1.0
