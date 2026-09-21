"""The eval scoring functions, and the offline judge, on fixture data.

No database and no model. Two halves:

* the pure metrics in ``evals.metrics``, each with one passing and one failing
  case, so a change to a gate is visible here before it is visible in a report;
* the offline judge in ``evals.judges``, exercised against the **real** rendered
  prompts from ``ros/prompts/eval/``. That is the part most likely to rot: the
  stand-in reads the prompt back, so a change to the template has to show up as a
  failing test rather than as an eval that quietly scores everything zero.

The last section checks the corpus itself — every persona loads, every label
points at a message that exists, and every expected observation is matched to its
own card and to nothing else.
"""

from __future__ import annotations

from typing import Any

import pytest

from evals import corpus as corpus_module
from evals.judges import (
    SAME_COVERAGE,
    GroundingVerdict,
    MatchVerdict,
    OfflineJudge,
    content_words,
    coverage,
    read_candidates,
    read_card,
    read_quotes,
)
from evals.metrics import (
    DIAGNOSTIC_WORDS,
    Failure,
    GoldExpectation,
    LedgerEntry,
    MatchResult,
    PersonaReport,
    ProducedCard,
    ProducedQuote,
    RunOutcome,
    Score,
    TrapExpectation,
    combine,
    correction_efficacy,
    diagnostic_words,
    evidence_recall,
    grounding,
    neutrality,
    paraphrase,
    precision_recall,
    score_persona,
    sensitive_leakage,
    trap_scores,
)
from ros.engine import pipeline
from ros.llm.base import ChatMessage, CompletionRequest
from ros.llm.registry import render

MESSAGE = "i keep putting off the invoices, third week now tbh"
QUOTE = "i keep putting off the invoices"


def quote(**kw: Any) -> ProducedQuote:
    base: dict[str, Any] = {
        "ref": "S1",
        "signal_id": "sig-1",
        "quote_text": QUOTE,
        "quote_start": MESSAGE.index(QUOTE),
        "quote_end": MESSAGE.index(QUOTE) + len(QUOTE),
        "message_id": "m-1",
        "message_text": MESSAGE,
        "observed_on": "2026-09-14",
        "source_ref": "m1",
    }
    base.update(kw)
    return ProducedQuote(**base)


def card(**kw: Any) -> ProducedCard:
    base: dict[str, Any] = {
        "id": "card-1",
        "interpretation_id": "int-1",
        "title": "Billing slips down the list",
        "body": "It looks like the money side waits until the week has emptied out.",
        "explanation": "Two things you said on two different days pointed the same way.",
        "confidence": 0.73,
        "state": "pending",
        "quotes": (quote(), quote(ref="S2", signal_id="sig-2", source_ref="m2")),
        "statement": "The user postpones invoicing.",
    }
    base.update(kw)
    return ProducedCard(**base)


def outcome(**kw: Any) -> RunOutcome:
    base: dict[str, Any] = {"persona": "fixture", "cards": (card(),)}
    base.update(kw)
    return RunOutcome(**base)


# ------------------------------------------------------------------------ Score


def test_a_score_with_nothing_to_measure_never_fails_either_way() -> None:
    assert Score("up", 0, 0, gate=1.0).ok
    assert Score("down", 0, 0, gate=0.0, higher_is_better=False).ok


def test_a_gate_is_a_floor_going_up_and_a_ceiling_going_down() -> None:
    assert Score("up", 8, 10, gate=0.80).ok
    assert not Score("up", 7, 10, gate=0.80).ok
    assert Score("down", 0, 10, gate=0.05, higher_is_better=False).ok
    assert not Score("down", 1, 10, gate=0.05, higher_is_better=False).ok


# -------------------------------------------------------------------- grounding


def test_grounding_passes_when_the_offsets_still_select_the_quote() -> None:
    result = grounding(outcome())
    assert (result.rate, result.ok, result.failures) == (1.0, True, ())


def test_grounding_fails_when_the_offsets_drift_by_one_character() -> None:
    drifted = card(quotes=(quote(quote_start=MESSAGE.index(QUOTE) + 1),))
    result = grounding(outcome(cards=(drifted,)))
    assert not result.ok
    assert "offsets select" in result.failures[0].detail


def test_grounding_fails_when_the_message_cannot_be_read_back() -> None:
    orphan = card(quotes=(quote(message_text=None),))
    result = grounding(outcome(cards=(orphan,)))
    assert not result.ok
    assert "could not be read back" in result.failures[0].detail


def test_grounding_fails_when_a_provenance_row_has_no_offsets() -> None:
    scrubbed = card(quotes=(quote(quote_start=None, quote_end=None),))
    assert not grounding(outcome(cards=(scrubbed,))).ok


# ------------------------------------------------------------------- paraphrase


def test_a_card_that_copies_its_own_quote_fails_paraphrase() -> None:
    copied = card(body=f"You said: {QUOTE}.")
    result = paraphrase(outcome(cards=(copied,)))
    assert not result.ok
    assert "verbatim" in result.failures[0].detail


def test_a_quote_too_short_to_be_distinctive_is_not_checked() -> None:
    short = card(body="You said yes.", quotes=(quote(quote_text="yes"),))
    assert paraphrase(outcome(cards=(short,))).total == 0


# ------------------------------------------------------------------------ traps


TRAP = TrapExpectation(
    id="t1",
    kind="single_mention",
    about="said once",
    expect_rule=("M0_model_declined", "R3"),
    messages=("m9",),
)


def test_a_trap_that_produced_a_card_is_a_false_recognition() -> None:
    fired = card(quotes=(quote(source_ref="m9"), quote(ref="S2", source_ref="m2")))
    false_recognition, abstention = trap_scores([TRAP], outcome(cards=(fired,)))
    assert not false_recognition.ok
    assert abstention.rate == 0.0


def test_a_trap_refused_for_the_expected_rule_passes_both_scores() -> None:
    ledger = (
        LedgerEntry(
            outcome="decline",
            reason="single_occurrence",
            failing_rules=("M0_model_declined",),
            candidate_text="a claim about cooking",
            source_refs=frozenset({"m9"}),
        ),
    )
    false_recognition, abstention = trap_scores([TRAP], outcome(cards=(), ledger=ledger))
    assert (false_recognition.rate, abstention.rate) == (0.0, 1.0)
    assert false_recognition.ok and abstention.ok


def test_a_trap_refused_for_no_recorded_reason_does_not_count_as_abstention() -> None:
    """Silence is not a decision. An eval that accepted it would measure luck."""
    false_recognition, abstention = trap_scores([TRAP], outcome(cards=()))
    assert false_recognition.ok
    assert not abstention.ok
    assert "nothing recorded" in abstention.failures[0].detail


def test_a_signal_filtered_before_the_interpreter_counts_as_its_own_reason() -> None:
    trap = TrapExpectation(
        id="t2",
        kind="quoting_others",
        about="somebody else's words",
        expect_rule=("F_subject",),
        messages=("m5",),
    )
    _, abstention = trap_scores([trap], outcome(cards=(), filtered={"m5": "F_subject"}))
    assert abstention.ok


# ----------------------------------------------------------- precision / recall


GOLD = GoldExpectation(id="g1", gist="The user postpones invoicing.", evidence=("m1", "m2"))


def test_a_matched_gold_gives_full_precision_and_recall() -> None:
    matches = [MatchResult(gold_id="g1", matched=True, card_id="card-1", verdict="same")]
    precision, recall = precision_recall([GOLD], outcome(), matches)
    assert (precision.rate, recall.rate) == (1.0, 1.0)


def test_a_card_nobody_asked_for_costs_precision() -> None:
    extra = card(id="card-2", title="Something else entirely")
    matches = [MatchResult(gold_id="g1", matched=True, card_id="card-1", verdict="same")]
    precision, recall = precision_recall([GOLD], outcome(cards=(card(), extra)), matches)
    assert precision.rate == 0.5
    assert recall.rate == 1.0


def test_a_related_verdict_is_a_miss_not_a_match() -> None:
    matches = [MatchResult(gold_id="g1", matched=False, card_id="card-1", verdict="related")]
    _, recall = precision_recall([GOLD], outcome(), matches)
    assert recall.rate == 0.0


def test_evidence_recall_counts_the_messages_the_label_demanded() -> None:
    matches = [MatchResult(gold_id="g1", matched=True, card_id="card-1", verdict="same")]
    assert evidence_recall([GOLD], outcome(), matches).rate == 1.0

    thin = card(quotes=(quote(),))
    result = evidence_recall([GOLD], outcome(cards=(thin,)), matches)
    assert result.rate == 0.5
    assert "m2 is not cited" in result.failures[0].detail


# ------------------------------------------------------------------ correction


def test_correction_efficacy_fails_when_a_rejected_claim_comes_back() -> None:
    rejected = ("The user avoids speaking in public.",)
    matches = [MatchResult(gold_id=rejected[0], matched=True, card_id="card-1", verdict="same")]
    result = correction_efficacy(outcome(rejected_statements=rejected), matches)
    assert not result.ok


def test_correction_efficacy_passes_when_nothing_makes_the_claim_again() -> None:
    rejected = ("The user avoids speaking in public.",)
    matches = [MatchResult(gold_id=rejected[0], matched=False, verdict="different")]
    assert correction_efficacy(outcome(rejected_statements=rejected), matches).ok


# ------------------------------------------------------- sensitive / neutrality


def test_a_card_resting_on_a_sensitive_signal_is_a_leak() -> None:
    leaked = card(quotes=(quote(sensitive_category="mental_health"), quote(ref="S2")))
    result = sensitive_leakage(outcome(cards=(leaked,)))
    assert not result.ok
    assert "rests on mental_health" in result.failures[0].detail


def test_a_card_citing_a_message_the_corpus_marked_sensitive_is_a_leak() -> None:
    result = sensitive_leakage(outcome(), sensitive_refs=["m2"])
    assert not result.ok


def test_a_clean_card_leaks_nothing() -> None:
    assert sensitive_leakage(outcome(), sensitive_refs=["m99"]).ok


@pytest.mark.parametrize("word", ["perfectionist", "anxiety", "self-sabotage", "Burnout"])
def test_the_deny_list_is_matched_on_whole_words(word: str) -> None:
    assert diagnostic_words(f"You seem to be {word} about it.")


def test_a_word_that_merely_contains_a_deny_listed_one_is_left_alone() -> None:
    assert diagnostic_words("You order things by ocdiality") == []
    assert "ocd" in DIAGNOSTIC_WORDS


def test_neutrality_fails_on_a_card_that_diagnoses() -> None:
    labelled = card(body="You seem to be a perfectionist about the intro.")
    assert not neutrality(outcome(cards=(labelled,))).ok
    assert neutrality(outcome()).ok


# --------------------------------------------------------------------- report


def test_a_persona_report_is_ok_only_when_every_score_is() -> None:
    matches = [MatchResult(gold_id="g1", matched=True, card_id="card-1", verdict="same")]
    report = score_persona(outcome(), [GOLD], [TRAP], matches)
    # The trap has no recorded reason in this fixture, so abstention must fail.
    assert not report.ok
    assert next(s.name for s in report.scores) == "grounding"


def test_combine_sums_the_counts_rather_than_averaging_the_rates() -> None:
    small = PersonaReport("a", (Score("recall", 1, 1, gate=0.6),), 1, 1, 0)
    large = PersonaReport("b", (Score("recall", 0, 9, gate=0.6),), 1, 1, 0)
    total = combine([small, large])[0]
    assert (total.passed, total.total) == (1, 10)
    assert not total.ok


# ------------------------------------------------------------- offline judge


def rendered(name: str, **variables: Any) -> str:
    """One of the real eval prompts, filled in exactly as the judge fills it in."""
    return render(name, None, **variables).text


def request_for(task: str, text: str) -> CompletionRequest:
    return CompletionRequest(
        task=task,
        messages=[ChatMessage(role="user", content=text)],
        metadata={"model": "claude-opus-5"},
    )


def test_content_words_ignore_tense_and_stopwords() -> None:
    assert content_words("The user arrives") & content_words("they arrived") == {"arriv"}
    assert coverage("", "anything") == 0.0


def test_the_stand_in_reads_candidates_out_of_the_real_match_prompt() -> None:
    prompt = rendered(
        "eval/judge_match",
        gold={"statement": "The user postpones invoicing.", "note": ""},
        candidates=[
            {"ref": "R1", "title": "Billing slips", "body": "You leave the money side late."},
            {"ref": "R2", "title": "Mornings", "body": "Your best hours are early."},
        ],
    )
    assert [c.ref for c in read_candidates(prompt)] == ["R1", "R2"]
    assert "money side late" in read_candidates(prompt)[0].text


async def test_the_stand_in_picks_the_card_that_carries_the_wording() -> None:
    prompt = rendered(
        "eval/judge_match",
        gold={"statement": "The user postpones sending invoices for weeks.", "note": ""},
        candidates=[
            {
                "ref": "R1",
                "title": "Early mornings",
                "body": "Your careful work happens before seven.",
            },
            {
                "ref": "R2",
                "title": "Invoices wait",
                "body": "You postpone sending invoices until weeks have passed.",
            },
        ],
    )
    answer = await OfflineJudge().complete_structured(
        request_for("eval.judge_match", prompt), MatchVerdict
    )
    verdict = answer.parsed
    assert isinstance(verdict, MatchVerdict)
    assert (verdict.candidate_ref, verdict.verdict, verdict.match) == ("R2", "same", True)


async def test_the_stand_in_says_different_when_nothing_was_produced() -> None:
    prompt = rendered(
        "eval/judge_match",
        gold={"statement": "The user postpones invoicing.", "note": ""},
        candidates=[],
    )
    answer = await OfflineJudge().complete_structured(
        request_for("eval.judge_match", prompt), MatchVerdict
    )
    verdict = answer.parsed
    assert isinstance(verdict, MatchVerdict)
    assert (verdict.match, verdict.candidate_ref) == (False, None)


def test_the_stand_in_reads_quotes_and_the_card_out_of_the_real_grounding_prompt() -> None:
    prompt = rendered(
        "eval/judge_grounding",
        card_title="Billing slips",
        card_body="You leave the money side late.",
        card_explanation="Two days, same unfinished job.",
        quotes=[
            {"ref": "S1", "when": "2026-09-14", "quote": QUOTE},
            {"ref": "S2", "when": "2026-09-16", "quote": "still have not sent them"},
        ],
    )
    assert [ref for ref, _, _ in read_quotes(prompt)] == ["S1", "S2"]
    assert read_card(prompt)["title"] == "Billing slips"


async def test_grounding_is_refused_when_every_quote_is_from_one_day() -> None:
    prompt = rendered(
        "eval/judge_grounding",
        card_title="Billing slips",
        card_body="You leave the money side late.",
        card_explanation="One evening.",
        quotes=[
            {"ref": "S1", "when": "2026-09-14", "quote": QUOTE},
            {"ref": "S2", "when": "2026-09-14", "quote": "still have not sent them"},
        ],
    )
    answer = await OfflineJudge().complete_structured(
        request_for("eval.judge_grounding", prompt), GroundingVerdict
    )
    verdict = answer.parsed
    assert isinstance(verdict, GroundingVerdict)
    assert verdict.grounded is False
    assert verdict.distinct_days == 1
    assert "one day" in verdict.reason


async def test_grounding_is_refused_when_the_card_copies_a_quote() -> None:
    prompt = rendered(
        "eval/judge_grounding",
        card_title="Billing slips",
        card_body=f"You said {QUOTE} and meant it.",
        card_explanation="Two days.",
        quotes=[
            {"ref": "S1", "when": "2026-09-14", "quote": QUOTE},
            {"ref": "S2", "when": "2026-09-16", "quote": "still have not sent them"},
        ],
    )
    answer = await OfflineJudge().complete_structured(
        request_for("eval.judge_grounding", prompt), GroundingVerdict
    )
    verdict = answer.parsed
    assert isinstance(verdict, GroundingVerdict)
    assert verdict.grounded is False
    assert "copies S1" in verdict.reason


# -------------------------------------------------------------------- corpus


CORPUS = corpus_module.load_corpus()


def test_the_corpus_is_not_empty() -> None:
    assert len(CORPUS) >= 6


@pytest.mark.parametrize("item", CORPUS, ids=lambda i: i.name)
def test_every_eval_persona_is_usable(item: Any) -> None:
    assert corpus_module.validate_corpus(item, topics=pipeline.taxonomy().topics) == []


def test_the_corpus_scripts_a_correction_and_a_rejection() -> None:
    """plan §10 asks for correction scripts, not only should-not-recognise cases."""
    actions = {entry.action for item in CORPUS for entry in item.persona.feedback}
    assert {"correct", "reject"} <= actions
    corrections = [
        entry for item in CORPUS for entry in item.persona.feedback if entry.action == "correct"
    ]
    assert all(entry.parse is not None and entry.text for entry in corrections)


def test_the_corpus_covers_every_trap_kind_the_plan_names() -> None:
    covered = {trap.kind for item in CORPUS for trap in item.traps}
    assert covered == set(corpus_module.TRAP_RULES)


@pytest.mark.parametrize("item", CORPUS, ids=lambda i: i.name)
def test_each_expected_observation_matches_its_own_card_and_no_other(item: Any) -> None:
    """The stand-in judge must be able to tell the corpus's cards apart.

    If two personas' cards are written so similarly that the wrong one scores as
    the same observation, the offline numbers stop meaning anything — so that is a
    failure here rather than a surprise in a report.
    """
    cards = [claim for claim in item.persona.claims if claim.card is not None]
    for gold in item.gold:
        scored = sorted(
            (
                (coverage(gold.gist, f"{claim.card.title}\n{claim.card.body}"), claim.id)
                for claim in cards
                if claim.card is not None
            ),
            reverse=True,
        )
        assert scored, f"{item.name}/{gold.id}: the persona scripts no card at all"
        best, runner_up = scored[0], (scored[1] if len(scored) > 1 else (0.0, "-"))
        assert best[0] >= SAME_COVERAGE, f"{item.name}/{gold.id}: best card scores {best[0]:.2f}"
        assert runner_up[0] < SAME_COVERAGE, (
            f"{item.name}/{gold.id}: {runner_up[1]} also scores as the same observation"
        )


def test_a_failure_reads_as_one_line() -> None:
    assert str(Failure("grounding", "card", "offsets drifted")) == (
        "grounding | card | offsets drifted"
    )
