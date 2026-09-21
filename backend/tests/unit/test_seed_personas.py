"""The demo personas, and the scripted provider that replays them.

No database. Three things are checked here, and all three are things that would
otherwise only fail during a demo:

1. **the files are usable** — every quote is really a span of its message, every
   topic is in the taxonomy, and no card repeats a quote it cites;
2. **the scripted provider still reads the prompts** — the answers are built by
   reading back the refs out of the *real* rendered templates, so a change to a
   prompt shows up as a failing test rather than as a seeded account with no
   evidence in it;
3. **the gates would do what the persona says** — ``conf-v1`` and ``thr-v1`` are
   run over each scripted claim, so "this persona should produce two cards and
   that one should produce none" is checked without Postgres.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from evals import corpus as corpus_module
from knori.scripts import seed
from knori.scripts.seed import (
    Persona,
    ScriptedClaim,
    ScriptedProvider,
    do_not_repropose,
    message_refs,
    quote_refs,
)
from ros.engine import pipeline
from ros.engine.confidence import score
from ros.engine.threshold import evaluate
from ros.engine.types import (
    EngineContext,
    EvidenceIn,
    InterpretationIn,
    SignalIn,
    UserPolicy,
)
from ros.llm.base import ChatMessage, CompletionRequest
from ros.llm.registry import render
from ros.schemas.llm_io import (
    CorrectionParse,
    InterpretationBatch,
    RecognitionDraft,
    SignalExtraction,
)

PERSONAS = [seed.load_persona(path) for path in seed.persona_paths()]
#: The eval corpus uses the same format and the same engine, so the checks that are
#: about the format rather than about the demo apply to it too.
ALL_PERSONAS = PERSONAS + [item.persona for item in corpus_module.load_corpus()]
TOPICS = pipeline.taxonomy().topics
IDS = [persona.name for persona in PERSONAS]
ALL_IDS = [persona.name for persona in ALL_PERSONAS]

#: R10 counts a claim already marked `recognize` but not yet composed as open, so
#: with `max_open_recognitions: 3` and a strict `<`, no more than two cards can be
#: waiting when a run starts composing. A persona that scripts three would silently
#: produce none of them.
MAX_OPEN_PER_PHASE = 2


def persona_by_name(name: str) -> Persona:
    return next(persona for persona in PERSONAS if persona.name == name)


def request_for(task: str, text: str) -> CompletionRequest:
    return CompletionRequest(
        task=task,
        messages=[ChatMessage(role="user", content=text)],
        metadata={"model": "claude-sonnet-5"},
    )


async def answer(persona: Persona, task: str, prompt: str, schema: type[Any]) -> Any:
    result = await ScriptedProvider(persona).complete_structured(request_for(task, prompt), schema)
    return result.parsed


# ------------------------------------------------------------------- the files


def test_there_are_demo_personas_to_seed() -> None:
    assert {persona.name for persona in PERSONAS} >= {"alex", "mina", "sam"}


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_every_persona_file_is_usable(persona: Persona) -> None:
    assert seed.validate(persona, topics=TOPICS) == []


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_every_quote_is_a_span_of_its_own_message(persona: Persona) -> None:
    """The check the engine does before it will store a signal, done up front."""
    for message, signal in persona.signals():
        start = message.text.index(signal.quote)
        assert message.text[start : start + len(signal.quote)] == signal.quote


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_no_card_repeats_a_quote_it_cites(persona: Persona) -> None:
    for claim in persona.claims:
        if claim.card is None:
            continue
        written = f"{claim.card.title} {claim.card.body} {claim.card.explanation}".lower()
        for message_id in claim.evidence:
            message = persona.message(message_id)
            for signal in message.signals if message else ():
                assert signal.quote.lower() not in written


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_every_persona_spans_at_least_three_days(persona: Persona) -> None:
    days = {conversation.started_at.date() for conversation in persona.conversations}
    assert len(days) >= 3, f"{persona.name} needs conversations on at least three days"


def test_a_broken_quote_is_reported_rather_than_silently_dropped() -> None:
    persona = persona_by_name("alex")
    message, signal = next(persona.signals())
    broken = seed.ScriptedSignal(
        quote="words that are not in the message at all",
        content=signal.content,
        topic=signal.topic,
    )
    damaged = _with_signal(persona, message.id, broken)
    problems = seed.validate(damaged, topics=TOPICS)
    assert any("is not in the message" in problem for problem in problems)


def _with_signal(persona: Persona, message_id: str, signal: seed.ScriptedSignal) -> Persona:
    """A copy of ``persona`` with one message's signals replaced."""
    conversations = tuple(
        seed.PersonaConversation(
            id=conversation.id,
            title=conversation.title,
            phase=conversation.phase,
            messages=tuple(
                seed.PersonaMessage(
                    id=message.id,
                    role=message.role,
                    text=message.text,
                    sent_at=message.sent_at,
                    signals=(signal,) if message.id == message_id else message.signals,
                    memories=message.memories,
                )
                for message in conversation.messages
            ),
        )
        for conversation in persona.conversations
    )
    return seed.Persona(
        name=persona.name,
        summary=persona.summary,
        display_name=persona.display_name,
        email=persona.email,
        password=persona.password,
        timezone=persona.timezone,
        now=persona.now,
        conversations=conversations,
        claims=persona.claims,
        declined=persona.declined,
        feedback=persona.feedback,
    )


# -------------------------------------------------- reading the real prompts


def extraction_prompt(persona: Persona, conversation_index: int = 0) -> str:
    """The extraction prompt as ``pipeline.run_extraction`` renders it."""
    taxonomy = pipeline.taxonomy()
    conversation = persona.conversations[conversation_index]
    user_messages = [m for m in conversation.messages if m.role == "user"]
    return render(
        "extract/signals",
        None,
        topics=list(taxonomy.topic_lines),
        sensitive_categories=list(taxonomy.sensitive),
        memory_context=[],
        recent_context=[],
        messages=[
            {
                "ref": f"M{index + 1}",
                "sent_at": message.sent_at.date().isoformat(),
                "text": message.text,
            }
            for index, message in enumerate(user_messages)
        ],
    ).text


def test_message_refs_are_read_back_out_of_the_extraction_prompt() -> None:
    persona = persona_by_name("alex")
    prompt = extraction_prompt(persona)
    user_messages = [m for m in persona.conversations[0].messages if m.role == "user"]
    found = message_refs(prompt)
    assert len(found) == len(user_messages)
    assert found[user_messages[0].text.strip()] == "M1"
    assert found[user_messages[-1].text.strip()] == f"M{len(user_messages)}"


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
async def test_extraction_answers_with_quotes_that_are_in_their_messages(
    persona: Persona,
) -> None:
    for index, conversation in enumerate(persona.conversations):
        prompt = extraction_prompt(persona, index)
        parsed = await answer(persona, "extract.signals", prompt, SignalExtraction)
        assert isinstance(parsed, SignalExtraction)

        refs = {ref: text for text, ref in message_refs(prompt).items()}
        expected = sum(len(m.signals) for m in conversation.messages)
        assert len(parsed.signals) == expected, f"{persona.name}/{conversation.id}"
        for signal in parsed.signals:
            assert signal.quote_text in refs[signal.message_ref]
            assert signal.topic in TOPICS
            assert signal.subject in seed.SIGNAL_SUBJECTS


def interpret_prompt(persona: Persona, *, denied: list[str] | None = None) -> str:
    """The interpret prompt as ``pipeline.run_interpretation`` renders it."""
    taxonomy = pipeline.taxonomy()
    signals = [
        {
            "ref": f"S{index + 1}",
            "when": message.sent_at.date().isoformat(),
            "topic": signal.topic,
            "kind": signal.kind,
            "strength": signal.strength,
            "content": signal.content,
            "quote": signal.quote,
        }
        for index, (message, signal) in enumerate(
            (m, s) for m, s in persona.signals() if s.subject == "self" and not s.sensitive
        )
    ]
    return render(
        "interpret/recognize",
        None,
        policy_text=pipeline.policy_text(),
        topics=list(taxonomy.topic_lines),
        today="2026-09-21",
        assertions=[],
        do_not_repropose=denied or [],
        open_interpretations=[],
        new_signals=signals,
        neighborhood_signals=[],
    ).text


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
async def test_interpretation_proposes_the_persona_claims_with_the_right_refs(
    persona: Persona,
) -> None:
    prompt = interpret_prompt(persona)
    parsed = await answer(persona, "interpret.recognize", prompt, InterpretationBatch)
    assert isinstance(parsed, InterpretationBatch)

    by_ref = {ref: quote for quote, ref in quote_refs(prompt).items()}
    proposed = {p.statement for p in parsed.proposals}
    for claim in persona.claims:
        if claim.propose:
            assert claim.statement in proposed, f"{persona.name}: {claim.id} was not proposed"
    for proposal in parsed.proposals:
        assert proposal.topic in TOPICS
        assert proposal.evidence, "a create proposal needs at least one support"
        for item in proposal.evidence:
            assert item.signal_ref in by_ref
            assert item.role == "supports"
    assert len(parsed.declined) >= len(persona.declined)


def test_a_denied_claim_is_declined_rather_than_proposed_again() -> None:
    """The do-not-repropose list is read out of the prompt, not remembered."""
    persona = persona_by_name("sam")
    claim = persona.claims[0]
    prompt = interpret_prompt(persona, denied=[claim.statement])
    assert claim.statement in do_not_repropose(prompt)

    provider = ScriptedProvider(persona)
    parsed = provider.interpretation(prompt)
    assert claim.statement not in {p["statement"] for p in parsed["proposals"]}
    refusal = next(d for d in parsed["declined"] if d["about"] == claim.statement)
    assert refusal["reason"] == "user_denied"


def compose_prompt(persona: Persona, claim: ScriptedClaim) -> str:
    """The compose prompt as ``pipeline.run_composition`` renders it."""
    evidence = []
    for index, message_id in enumerate(claim.evidence):
        message = persona.message(message_id)
        if message is None or not message.signals:
            continue
        evidence.append(
            {
                "ref": f"S{index + 1}",
                "quote": message.signals[0].quote,
                "when": message.sent_at.date().isoformat(),
            }
        )
    return render(
        "recognize/compose",
        None,
        user_name=persona.display_name,
        chat_style=persona.settings.chat_style,
        kind=claim.kind,
        statement=claim.statement,
        rationale=claim.rationale,
        confidence_label="likely",
        support_count=len(evidence),
        distinct_days=len(evidence),
        evidence=evidence,
        assertions=[],
    ).text


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
async def test_composition_answers_with_the_card_the_persona_wrote(persona: Persona) -> None:
    for claim in persona.claims:
        if claim.card is None:
            continue
        prompt = compose_prompt(persona, claim)
        parsed = await answer(persona, "recognize.compose", prompt, RecognitionDraft)
        assert isinstance(parsed, RecognitionDraft)
        assert parsed.title == claim.card.title
        assert parsed.cited_signal_refs
        assert set(parsed.cited_signal_refs) <= set(quote_refs(prompt).values())


async def test_a_correction_is_parsed_into_the_assertion_the_persona_scripted() -> None:
    persona = persona_by_name("sam")
    entry = next(f for f in persona.feedback if f.action == "correct")
    claim = persona.claim(entry.claim)
    assert claim is not None and claim.card is not None and entry.parse is not None

    prompt = render(
        "correction/parse",
        None,
        card_title=claim.card.title,
        card_body=claim.card.body,
        card_explanation=claim.card.explanation,
        statement=claim.statement,
        evidence=[{"ref": "S1", "quote": "a quote", "when": "2026-09-14"}],
        correction_text=entry.text,
        topics=list(pipeline.taxonomy().topic_lines),
    ).text
    parsed = await answer(persona, "correction.parse", prompt, CorrectionParse)
    assert isinstance(parsed, CorrectionParse)
    assert parsed.kind == entry.parse.kind
    assert parsed.assertion_statement == entry.parse.assertion
    assert parsed.replacement_claim == entry.parse.replacement


# ---------------------------------------------------------------- the gates


def view_of(persona: Persona, claim: ScriptedClaim) -> InterpretationIn:
    """One scripted claim as ``conf-v1`` and ``thr-v1`` will see it."""
    evidence: list[EvidenceIn] = []
    for message_id in claim.evidence:
        message = persona.message(message_id)
        if message is None or not message.signals:
            continue
        signal = message.signals[0]
        evidence.append(
            EvidenceIn(
                signal=SignalIn(
                    id=f"{message.id}-s",
                    subject=signal.subject,
                    topic=signal.topic,
                    strength=signal.strength,
                    observed_at=message.sent_at,
                    message_id=message.id,
                    quote_text=signal.quote,
                    sensitive_category=signal.sensitive,
                ),
                role="supports",
                weight=claim.weight,
            )
        )
    return InterpretationIn(
        id=claim.id,
        kind=claim.kind,
        topic=claim.topic,
        statement=claim.statement,
        model_confidence=claim.model_confidence,
        sensitive_category=claim.sensitive,
        evidence=tuple(evidence),
        created_at=persona.now,
    )


def gate(persona: Persona, claim: ScriptedClaim, *, now: datetime | None = None) -> Any:
    context = EngineContext(
        now=now or persona.now,
        policy=UserPolicy(
            max_recognitions_per_day=persona.settings.max_recognitions_per_day,
            timezone=persona.timezone,
        ),
    )
    view = view_of(persona, claim)
    return evaluate(view, score(view, context), context)


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_every_claim_with_a_card_would_pass_the_gates(persona: Persona) -> None:
    for claim in persona.claims:
        if claim.card is None or not claim.propose:
            continue
        result = gate(persona, claim)
        assert result.outcome == "recognize", (
            f"{persona.name}/{claim.id} is gated as {result.outcome} ({result.reason})"
        )


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_every_claim_without_a_card_is_stopped_by_a_named_rule(persona: Persona) -> None:
    for claim in persona.claims:
        if claim.card is not None:
            continue
        result = gate(persona, claim)
        assert result.outcome != "recognize", f"{persona.name}/{claim.id} would be shown"
        assert result.reason, "a refusal must name the rule that caused it"


def test_the_trap_persona_can_never_produce_a_card() -> None:
    """mina exists to show an empty Recognitions tab and a full ledger."""
    persona = persona_by_name("mina")
    assert persona.claims, "mina still has to propose something for the gates to refuse"
    outcomes = {claim.id: gate(persona, claim) for claim in persona.claims}
    assert all(result.outcome != "recognize" for result in outcomes.values())
    assert {r.reason for r in outcomes.values()} == {"insufficient_evidence", "below_threshold"}


def test_the_correction_persona_scripts_one_correction_and_one_rejection() -> None:
    persona = persona_by_name("sam")
    actions = sorted(entry.action for entry in persona.feedback)
    assert actions == ["correct", "reject"]
    correction = next(e for e in persona.feedback if e.action == "correct")
    assert correction.parse is not None
    assert correction.parse.kind == "amend"
    # The amended claim needs a card of its own, or the demo shows the correction
    # changing nothing.
    replacement = correction.parse.replacement
    assert any(c.statement == replacement and c.card for c in persona.claims)


def test_the_happy_path_persona_produces_more_than_one_card() -> None:
    persona = persona_by_name("alex")
    passing = [c for c in persona.claims if gate(persona, c).outcome == "recognize"]
    assert len(passing) >= 2
    assert persona.settings.max_recognitions_per_day >= len(passing)


def claim_phase(persona: Persona, claim: ScriptedClaim) -> int:
    """The phase a claim belongs to: the last phase any of its evidence is in."""
    phases = [
        conversation.phase
        for conversation in persona.conversations
        for message in conversation.messages
        if message.id in claim.evidence
    ]
    return max(phases, default=1)


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=ALL_IDS)
def test_no_phase_asks_for_more_cards_than_the_budget_allows(persona: Persona) -> None:
    """Three cards from one run is three cards nobody sees.

    ``card_budget`` counts an interpretation already gated `recognize` as open, so
    the third composition of a run is refused by R10 rather than queued. A persona
    that scripts three cards at once is a persona that produces none.
    """
    unanswered = 0
    for phase in sorted({conversation.phase for conversation in persona.conversations}):
        passing = [
            claim
            for claim in persona.claims
            if claim.propose
            and claim.card is not None
            and claim_phase(persona, claim) == phase
            and gate(persona, claim).outcome == "recognize"
        ]
        assert unanswered + len(passing) <= MAX_OPEN_PER_PHASE, (
            f"{persona.name} phase {phase}: {unanswered} card(s) still open plus "
            f"{len(passing)} new would exceed R10's open limit"
        )
        assert len(passing) <= persona.settings.max_recognitions_per_day, (
            f"{persona.name} phase {phase}: {len(passing)} cards but the daily budget "
            f"is {persona.settings.max_recognitions_per_day}"
        )
        answered = sum(
            1
            for entry in persona.feedback
            if entry.phase == phase
            for answered_claim in [persona.claim(entry.claim)]
            if answered_claim is not None and answered_claim.card is not None
        )
        unanswered += len(passing) - min(answered, len(passing))
