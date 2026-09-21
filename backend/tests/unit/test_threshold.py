"""``thr-v1``, one test per rule (plan §4.5).

Two properties matter as much as the rules themselves:

* **every rule is evaluated and recorded**, so the ledger can always answer "why
  didn't KnoRI say anything?";
* **the first failing rule decides**, so the answer is one rule, not a list.

R3 gets the most tests, because it is the rule that makes a Recognition mean
something: two signals, two calendar days, twelve hours apart. The 23:50 / 00:10
case is the one everyone gets wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ros.engine.confidence import score
from ros.engine.threshold import (
    RULE_ORDER,
    candidate_order,
    cooldown_until,
    evaluate,
    evaluate_batch,
    sensitive_hit,
)
from ros.engine.types import (
    AssertionIn,
    ClaimMatchIn,
    EngineContext,
    EvidenceIn,
    InterpretationIn,
    SignalIn,
    UserPolicy,
    load_thresholds,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
DAY1 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
DAY2 = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
DAY3 = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

STATEMENT = "The user makes the final call alone after asking other people first."


def sig(ref: str, when: datetime, *, strength: float = 1.0, **kw) -> SignalIn:
    return SignalIn(
        id=ref,
        topic="work.decisions",
        strength=strength,
        observed_at=when,
        message_id=kw.pop("message_id", f"m-{ref}"),
        quote_text=f"quote {ref}",
        **kw,
    )


def ev(signal: SignalIn, role: str = "supports", weight: float = 1.0) -> EvidenceIn:
    return EvidenceIn(signal=signal, role=role, weight=weight)  # type: ignore[arg-type]


def interp(evidence=None, **kw) -> InterpretationIn:
    base: dict = {
        "id": "I1",
        "kind": "pattern",
        "topic": "work.decisions",
        "statement": STATEMENT,
        "model_confidence": 0.8,
        "created_at": DAY1,
    }
    base.update(kw)
    if evidence is None:
        evidence = [ev(sig("a", DAY1)), ev(sig("b", DAY2))]
    return InterpretationIn(evidence=tuple(evidence), **base)


def ctx(**kw) -> EngineContext:
    kw.setdefault("now", NOW)
    return EngineContext(**kw)


def decide(interpretation: InterpretationIn, context: EngineContext):
    return evaluate(interpretation, score(interpretation, context), context)


def test_a_clean_candidate_is_recognized() -> None:
    result = decide(interp(), ctx())
    assert result.outcome == "recognize"
    assert result.reason is None
    assert result.failing_rules == ()
    assert result.interpretation_id == "I1"
    assert result.policy_version == "thr-v1"


def test_every_rule_is_evaluated_and_recorded_every_time() -> None:
    result = decide(interp(), ctx(policy=UserPolicy(recognition_enabled=False)))
    assert tuple(r.rule for r in result.rules) == RULE_ORDER
    assert len(result.rules) == 11
    # Even after the first failure, the rest still ran.
    assert all(r.rule in RULE_ORDER for r in result.rules)


# ------------------------------------------------------------- one per rule


def test_r0_the_user_turned_recognition_off() -> None:
    result = decide(interp(), ctx(policy=UserPolicy(recognition_enabled=False)))
    assert (result.outcome, result.reason) == ("hold", "user_disabled")
    assert result.failing_rules[0] == "R0"


def test_r1_one_card_per_interpretation_version() -> None:
    result = decide(interp(), ctx(has_card_for_version=frozenset({("I1", 1)})))
    assert (result.outcome, result.reason) == ("hold", "already_presented")


def test_r1_a_revise_bumps_the_version_and_clears_the_block() -> None:
    result = decide(interp(version=2), ctx(has_card_for_version=frozenset({("I1", 1)})))
    assert result.outcome == "recognize"


def test_r2_an_explicit_fact_is_not_a_recognition() -> None:
    result = decide(
        interp(),
        ctx(
            claim_matches=(
                ClaimMatchIn(
                    interpretation_id="I1",
                    target_kind="memory_item",
                    target_id="mem-1",
                    same=True,
                ),
            ),
            active_memory_ids=frozenset({"mem-1"}),
        ),
    )
    assert (result.outcome, result.reason) == ("decline", "already_known")


def test_r2_ignores_a_match_against_a_retracted_memory_item() -> None:
    result = decide(
        interp(),
        ctx(
            claim_matches=(
                ClaimMatchIn(
                    interpretation_id="I1",
                    target_kind="memory_item",
                    target_id="mem-1",
                    same=True,
                ),
            ),
            active_memory_ids=frozenset({"mem-2"}),
        ),
    )
    assert result.outcome == "recognize"


def test_r3_one_signal_is_never_enough() -> None:
    result = decide(interp([ev(sig("a", DAY1))]), ctx())
    assert (result.outcome, result.reason) == ("hold", "insufficient_evidence")
    assert result.failing_rules[0] == "R3"


def test_r3_one_message_can_never_become_a_recognition() -> None:
    """Two signals pulled from the same sentence are still one moment."""
    one_message = [
        ev(sig("a", DAY1, message_id="m-1")),
        ev(sig("b", DAY1, message_id="m-1")),
    ]
    result = decide(interp(one_message), ctx())
    assert (result.outcome, result.reason) == ("hold", "insufficient_evidence")
    r3 = next(r for r in result.rules if r.rule == "R3")
    assert r3.value == {
        "supports": 2,
        "distinct_days": 1,
        "distinct_messages": 1,
        "span_hours": 0.0,
    }


def test_r3_one_sitting_is_not_two_days() -> None:
    sitting = [ev(sig("a", DAY1)), ev(sig("b", DAY1 + timedelta(hours=2)))]
    assert decide(interp(sitting), ctx()).reason == "insufficient_evidence"


def test_r3_midnight_does_not_buy_a_second_day() -> None:
    """23:50 and 00:10 the next day are two dates and twenty minutes apart."""
    late = datetime(2026, 9, 18, 23, 50, tzinfo=UTC)
    early = datetime(2026, 9, 19, 0, 10, tzinfo=UTC)
    result = decide(interp([ev(sig("a", late)), ev(sig("b", early))]), ctx())
    assert (result.outcome, result.reason) == ("hold", "insufficient_evidence")
    r3 = next(r for r in result.rules if r.rule == "R3")
    assert r3.value["distinct_days"] == 2
    assert r3.value["span_hours"] == pytest.approx(0.33, abs=0.01)
    assert r3.limit == {"supports": 2, "distinct_days": 2, "span_hours": 12.0}


def _has_tzdata() -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo("America/New_York")
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


@pytest.mark.skipif(not _has_tzdata(), reason="no tz database installed (needs `tzdata`)")
def test_r3_counts_days_in_the_users_own_timezone() -> None:
    """The same two moments are two days in UTC and one long day in New York.

    New York is UTC-4 in September, so its 18 September runs from 04:00 UTC that day
    to 04:00 UTC the next. Both moments below fall inside it, 22 hours apart — enough
    for the 12-hour rule, but still one single day for the person living it.
    """
    early = datetime(2026, 9, 18, 5, 0, tzinfo=UTC)  # 01:00 in New York, 18 Sept
    late = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)  # 23:00 in New York, still 18 Sept
    evidence = [ev(sig("a", early)), ev(sig("b", late))]
    utc = decide(interp(evidence), ctx())
    local = decide(interp(evidence), ctx(policy=UserPolicy(timezone="America/New_York")))
    assert utc.outcome == "recognize"
    assert (local.outcome, local.reason) == ("hold", "insufficient_evidence")
    assert next(r for r in local.rules if r.rule == "R3").value["distinct_days"] == 1
    assert local.timezone_used == "America/New_York"


def test_r3_twelve_hours_is_the_line() -> None:
    late = datetime(2026, 9, 18, 23, 0, tzinfo=UTC)
    just_short = [ev(sig("a", late)), ev(sig("b", late + timedelta(hours=11, minutes=59)))]
    just_enough = [ev(sig("a", late)), ev(sig("b", late + timedelta(hours=12)))]
    assert decide(interp(just_short), ctx()).reason == "insufficient_evidence"
    assert decide(interp(just_enough), ctx()).outcome == "recognize"


def test_r4_the_model_was_not_sure_enough() -> None:
    result = decide(interp(model_confidence=0.4), ctx())
    assert (result.outcome, result.reason) == ("hold", "low_model_confidence")
    assert next(r for r in result.rules if r.rule == "R4").limit == 0.6


def test_r4_a_claim_the_user_wrote_enters_at_full_confidence() -> None:
    result = decide(interp(source="user_correction", model_confidence=0.0), ctx())
    assert next(r for r in result.rules if r.rule == "R4").passed is True


def test_r5_too_much_evidence_the_other_way() -> None:
    contradicted = [
        ev(sig("a", DAY1)),
        ev(sig("b", DAY2)),
        ev(sig("c", DAY2), role="contradicts"),
    ]
    result = decide(interp(contradicted), ctx())
    assert (result.outcome, result.reason) == ("hold", "contradicted")
    assert result.failing_rules[0] == "R5"


def test_r6_a_sensitive_category_is_suppressed() -> None:
    result = decide(interp(sensitive_category="health"), ctx())
    assert (result.outcome, result.reason) == ("suppress", "sensitive")
    assert next(r for r in result.rules if r.rule == "R6").value == "health"


def test_r6_the_deny_list_also_reads_the_statement() -> None:
    result = decide(interp(statement="The user leans on therapy when work gets heavy."), ctx())
    assert (result.outcome, result.reason) == ("suppress", "sensitive")
    assert next(r for r in result.rules if r.rule == "R6").value == "deny_list:mental_health"


@pytest.mark.parametrize(
    "statement",
    [
        STATEMENT,
        "The user plans their week on Sunday evenings.",
        "The user prefers written updates to meetings.",
        "The user takes a straight answer over a long explanation.",
    ],
)
def test_r6_leaves_ordinary_claims_alone(statement: str) -> None:
    assert sensitive_hit(statement, load_thresholds().sensitive) is None


def test_r7_the_user_said_no() -> None:
    result = decide(
        interp(),
        ctx(assertions=(AssertionIn(id="A1", kind="deny", applies_to_interpretation_id="I1"),)),
    )
    assert (result.outcome, result.reason) == ("suppress", "user_denied")
    assert next(r for r in result.rules if r.rule == "R7").value == "A1"


def test_r7_also_blocks_the_same_claim_in_different_words() -> None:
    result = decide(
        interp(),
        ctx(
            assertions=(AssertionIn(id="A1", kind="deny"),),
            claim_matches=(
                ClaimMatchIn(
                    interpretation_id="I1", target_kind="assertion", target_id="A1", same=True
                ),
            ),
        ),
    )
    assert (result.outcome, result.reason) == ("suppress", "user_denied")


def test_r7_lets_a_retracted_denial_go() -> None:
    result = decide(
        interp(),
        ctx(
            assertions=(
                AssertionIn(
                    id="A1",
                    kind="deny",
                    applies_to_interpretation_id="I1",
                    status="retracted",
                ),
            )
        ),
    )
    assert result.outcome == "recognize"


def test_r8_below_the_threshold_for_this_kind() -> None:
    weak = [ev(sig("a", DAY1, strength=0.3)), ev(sig("b", DAY2, strength=0.3))]
    result = decide(interp(weak), ctx())
    assert (result.outcome, result.reason) == ("hold", "below_threshold")
    assert result.failing_rules[0] == "R8"
    assert next(r for r in result.rules if r.rule == "R8").limit == 0.65


@pytest.mark.parametrize(
    ("kind", "limit"),
    [("pattern", 0.65), ("preference", 0.60), ("value", 0.65), ("tension", 0.70)],
)
def test_r8_threshold_per_kind(kind: str, limit: float) -> None:
    result = decide(interp(kind=kind), ctx())
    assert next(r for r in result.rules if r.rule == "R8").limit == limit


def test_r9_a_dismissed_claim_stays_quiet() -> None:
    result = decide(interp(cooldown_until=NOW + timedelta(days=5)), ctx())
    assert (result.outcome, result.reason) == ("hold", "cooldown")


def test_r9_a_passed_cooldown_no_longer_blocks() -> None:
    result = decide(interp(cooldown_until=NOW - timedelta(seconds=1)), ctx())
    assert result.outcome == "recognize"


def test_r10_the_daily_budget_is_spent() -> None:
    result = decide(interp(), ctx(cards_created_today=2))
    assert (result.outcome, result.reason) == ("hold", "rate_limited")
    assert next(r for r in result.rules if r.rule == "R10").value == {
        "budget_left": 0,
        "open": 0,
    }


def test_r10_too_many_cards_already_waiting() -> None:
    result = decide(interp(), ctx(open_card_count=3))
    assert (result.outcome, result.reason) == ("hold", "rate_limited")


# ------------------------------------------------------------------ ordering


def test_the_first_failing_rule_decides_even_when_later_ones_fail_too() -> None:
    """R0 fails and so do R3 and R8 — the user's own switch still answers."""
    result = decide(
        interp([ev(sig("a", DAY1))]),
        ctx(policy=UserPolicy(recognition_enabled=False)),
    )
    assert (result.outcome, result.reason) == ("hold", "user_disabled")
    assert result.failing_rules[0] == "R0"
    assert set(result.failing_rules) >= {"R0", "R3", "R8"}


def test_a_decline_outranks_a_later_hold() -> None:
    result = decide(
        interp([ev(sig("a", DAY1))]),
        ctx(
            claim_matches=(
                ClaimMatchIn(
                    interpretation_id="I1",
                    target_kind="memory_item",
                    target_id="mem-1",
                    same=True,
                ),
            ),
            active_memory_ids=frozenset({"mem-1"}),
        ),
    )
    assert result.outcome == "decline"
    assert result.failing_rules[:2] == ("R2", "R3")


def test_the_ledger_key_only_changes_with_the_decision() -> None:
    """A new `threshold_evaluations` row is written only when this moves."""
    first = decide(interp([ev(sig("a", DAY1))]), ctx())
    again = decide(interp([ev(sig("a", DAY1))]), ctx(now=NOW + timedelta(hours=3)))
    assert first.ledger_key() == again.ledger_key() == ("hold", ("R3", "R8"))
    assert decide(interp(), ctx()).ledger_key() == ("recognize", ())


def test_rules_serialise_for_the_jsonb_ledger() -> None:
    import json

    rows = decide(interp([ev(sig("a", DAY1))]), ctx()).rules_json()
    assert json.loads(json.dumps(rows))[3]["rule"] == "R3"
    assert set(rows[0]) == {"rule", "passed", "value", "limit", "reason"}


# --------------------------------------------------------------- the budget


def three_candidates() -> list[tuple[InterpretationIn, object]]:
    strong = interp([ev(sig("a", DAY1)), ev(sig("b", DAY2)), ev(sig("c", DAY3))], id="I-strong")
    middle = interp(id="I-middle")
    low = interp([ev(sig("e", DAY1, strength=0.9)), ev(sig("f", DAY2, strength=0.9))], id="I-low")
    context = ctx()
    return [(i, score(i, context)) for i in (middle, low, strong)]


def test_the_budget_is_decremented_inside_the_run() -> None:
    results = evaluate_batch(three_candidates(), ctx())
    assert [r.interpretation_id for r in results] == ["I-strong", "I-middle", "I-low"]
    assert [r.outcome for r in results] == ["recognize", "recognize", "hold"]
    assert results[2].reason == "rate_limited"


def test_a_bigger_budget_lets_all_three_through() -> None:
    results = evaluate_batch(three_candidates(), ctx(policy=UserPolicy(max_recognitions_per_day=3)))
    assert [r.outcome for r in results] == ["recognize"] * 3


def test_the_open_card_ceiling_still_applies_inside_a_run() -> None:
    results = evaluate_batch(
        three_candidates(),
        ctx(policy=UserPolicy(max_recognitions_per_day=5), open_card_count=2),
    )
    assert [r.outcome for r in results] == ["recognize", "hold", "hold"]


def test_candidate_order_is_confidence_then_dismissals_then_age() -> None:
    context = ctx()
    older = interp(id="I-older", created_at=DAY1)
    newer = interp(id="I-newer", created_at=DAY2)
    dismissed = interp(id="I-dismissed", created_at=DAY1, dismiss_count=1)
    stronger = interp(
        [ev(sig("a", DAY1)), ev(sig("b", DAY2)), ev(sig("c", DAY3))],
        id="I-stronger",
        created_at=DAY3,
    )
    items = [(i, score(i, context)) for i in (dismissed, newer, older, stronger)]
    assert [i.id for i, _ in candidate_order(items)] == [
        "I-stronger",
        "I-older",
        "I-newer",
        "I-dismissed",
    ]


@pytest.mark.parametrize(("dismissals", "days"), [(0, 30), (1, 90), (2, 90)])
def test_cooldown_lengthens_after_a_second_dismissal(dismissals: int, days: int) -> None:
    until = cooldown_until(NOW, dismissals, load_thresholds().threshold)
    assert until == NOW + timedelta(days=days)
