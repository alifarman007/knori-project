"""``conf-v1`` as a table (plan §4.4).

The four worked examples in the plan are recomputed here, to two decimals. If a
constant in ``config/thresholds.yaml`` moves, these fail — which is the point: a
number on a card is a promise, and promises get a test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ros.engine.confidence import (
    consistency_of,
    evidence_score,
    label_for,
    score,
    support_timeline,
)
from ros.engine.types import (
    AssertionIn,
    ClaimMatchIn,
    EngineContext,
    EvidenceIn,
    InterpretationIn,
    UserPolicy,
    load_thresholds,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
DAY1 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
DAY2 = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
DAY3 = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


def sig(
    ref: str,
    when: datetime,
    *,
    strength: float = 1.0,
    subject: str = "self",
    sensitive: str | None = None,
):
    from ros.engine.types import SignalIn

    return SignalIn(
        id=ref,
        subject=subject,
        topic="work.decisions",
        strength=strength,
        observed_at=when,
        message_id=f"m-{ref}",
        quote_text=f"quote {ref}",
        sensitive_category=sensitive,
    )


def ev(signal, role: str = "supports", weight: float = 1.0) -> EvidenceIn:
    return EvidenceIn(signal=signal, role=role, weight=weight)  # type: ignore[arg-type]


def interp(evidence, **kw) -> InterpretationIn:
    base = {
        "id": "I1",
        "kind": "pattern",
        "topic": "work.decisions",
        "statement": "The user makes final calls alone after consulting others.",
        "model_confidence": 0.8,
    }
    base.update(kw)
    return InterpretationIn(evidence=tuple(evidence), **base)  # type: ignore[arg-type]


def ctx(**kw) -> EngineContext:
    return EngineContext(now=NOW, **kw)


# ------------------------------------------------- the plan's worked examples


def test_two_explicit_signals_on_two_days() -> None:
    """0.81 x 1.0 x 0.9 = 0.73 — recognize, 'likely'."""
    result = score(interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]), ctx())
    assert round(result.value, 2) == 0.73
    assert result.label == "likely"


def test_the_same_two_signals_on_one_day() -> None:
    """0.81 x 1.0 x 0.5 = 0.41 — and R3 would block it regardless."""
    same_day = DAY1 + timedelta(hours=8)
    result = score(interp([ev(sig("a", DAY1)), ev(sig("b", same_day))]), ctx())
    assert round(result.value, 2) == 0.41
    assert result.label == "hidden"


def test_three_signals_two_days_with_one_contradiction() -> None:
    """0.92 x 0.833 x 0.9 = 0.69 — recognize, 'likely'."""
    result = score(
        interp(
            [
                ev(sig("a", DAY1)),
                ev(sig("b", DAY2)),
                ev(sig("c", DAY2 + timedelta(hours=6))),
                ev(sig("d", DAY2, strength=0.6), role="contradicts"),
            ]
        ),
        ctx(),
    )
    assert round(result.value, 2) == 0.69
    assert round(result.breakdown["consistency"], 3) == 0.833
    assert result.label == "likely"


def test_three_signals_on_three_days() -> None:
    """0.92 x 1.0 x 1.0 = 0.92 — 'strong'."""
    result = score(interp([ev(sig("a", DAY1)), ev(sig("b", DAY2)), ev(sig("c", DAY3))]), ctx())
    assert round(result.value, 2) == 0.92
    assert result.label == "strong"


# --------------------------------------------------------------- the pieces


@pytest.mark.parametrize(
    ("support_sum", "expected"),
    [(0.0, 0.0), (1.0, 0.57), (2.0, 0.81), (3.0, 0.92)],
)
def test_evidence_score_curve(support_sum: float, expected: float) -> None:
    assert round(evidence_score(support_sum, 1.2), 2) == expected


def test_consistency_is_one_when_there_is_no_evidence_at_all() -> None:
    assert consistency_of(0.0, 0.0) == 1.0
    assert score(interp([]), ctx()).breakdown["consistency"] == 1.0
    assert score(interp([]), ctx()).value == 0.0


@pytest.mark.parametrize(("days", "spread"), [(1, 0.5), (2, 0.9), (3, 1.0), (4, 1.0), (9, 1.0)])
def test_spread_by_distinct_calendar_days(days: int, spread: float) -> None:
    evidence = [ev(sig(f"s{n}", DAY1 + timedelta(days=n))) for n in range(days)]
    result = score(interp(evidence), ctx())
    assert result.breakdown["spread"] == spread
    assert result.breakdown["distinct_days"] == days


def test_weight_is_strength_times_evidence_weight() -> None:
    result = score(interp([ev(sig("a", DAY1, strength=0.6), weight=0.5)]), ctx())
    assert result.breakdown["support_sum"] == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("value", "label"),
    [
        (0.0, "hidden"),
        (0.549, "hidden"),
        (0.55, "likely"),
        (0.74, "likely"),
        (0.75, "strong"),
        (1.0, "strong"),
    ],
)
def test_label_cutoffs(value: float, label: str) -> None:
    assert label_for(value, load_thresholds().confidence) == label


# ------------------------------------------------------ corrections and floors


def test_an_affirm_filed_against_this_row_adds_ten_points() -> None:
    base = score(interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]), ctx())
    affirmed = score(
        interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]),
        ctx(assertions=(AssertionIn(id="A1", kind="affirm", applies_to_interpretation_id="I1"),)),
    )
    assert round(affirmed.value - base.value, 3) == 0.1


def test_a_scope_assertion_takes_ten_points_off_and_respects_its_weight() -> None:
    result = score(
        interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]),
        ctx(
            assertions=(
                AssertionIn(id="A1", kind="scope", applies_to_interpretation_id="I1", weight=0.5),
            )
        ),
    )
    assert round(result.value, 3) == 0.68  # 0.730 - 0.05


def test_one_correction_counts_once_even_when_it_matches_two_ways() -> None:
    """Filed against this row *and* judged the same claim is still one correction."""
    assertion = AssertionIn(id="A1", kind="affirm", applies_to_interpretation_id="I1")
    both = score(
        interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]),
        ctx(
            assertions=(assertion,),
            claim_matches=(
                ClaimMatchIn(
                    interpretation_id="I1", target_kind="assertion", target_id="A1", same=True
                ),
            ),
        ),
    )
    assert round(both.value, 3) == 0.83
    assert len(both.breakdown["adjustments"]) == 1
    assert both.breakdown["adjustments"][0]["matched_by"] == "applies_to"


def test_a_similar_assertion_reaches_the_row_through_the_judge() -> None:
    result = score(
        interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]),
        ctx(
            assertions=(AssertionIn(id="A1", kind="affirm"),),
            claim_matches=(
                ClaimMatchIn(
                    interpretation_id="I1", target_kind="assertion", target_id="A1", same=True
                ),
            ),
        ),
    )
    assert result.breakdown["adjustments"][0]["matched_by"] == "same_claim"


def test_deny_and_amend_do_not_touch_the_score() -> None:
    """A denial is rule R7; an amend supersedes the row. One mechanism each."""
    plain = score(interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]), ctx())
    with_deny = score(
        interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]),
        ctx(
            assertions=(
                AssertionIn(id="A1", kind="deny", applies_to_interpretation_id="I1"),
                AssertionIn(id="A2", kind="amend", applies_to_interpretation_id="I1"),
            )
        ),
    )
    assert with_deny.value == plain.value
    assert with_deny.breakdown["adjustments"] == []


def test_a_retracted_assertion_is_ignored() -> None:
    plain = score(interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]), ctx())
    retracted = score(
        interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]),
        ctx(
            assertions=(
                AssertionIn(
                    id="A1",
                    kind="affirm",
                    applies_to_interpretation_id="I1",
                    status="retracted",
                ),
            )
        ),
    )
    assert retracted.value == plain.value


def test_a_claim_the_user_wrote_is_never_scored_below_the_floor() -> None:
    result = score(
        interp([ev(sig("a", DAY1))], source="user_correction", model_confidence=1.0), ctx()
    )
    assert result.value == 0.85
    assert result.breakdown["user_correction_floor_applied"] is True
    assert result.label == "strong"


def test_the_floor_never_lowers_a_higher_score() -> None:
    result = score(
        interp(
            [ev(sig("a", DAY1)), ev(sig("b", DAY2)), ev(sig("c", DAY3))],
            source="user_correction",
        ),
        ctx(),
    )
    assert round(result.value, 2) == 0.92
    assert result.breakdown["user_correction_floor_applied"] is False


def test_confidence_is_clamped_into_zero_to_one() -> None:
    result = score(
        interp([ev(sig("a", DAY1)), ev(sig("b", DAY2)), ev(sig("c", DAY3))]),
        ctx(
            assertions=tuple(
                AssertionIn(
                    id=f"A{n}", kind="affirm", applies_to_interpretation_id="I1", weight=1.0
                )
                for n in range(5)
            )
        ),
    )
    assert result.value == 1.0


# ---------------------------------------------- what may never count as support


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"subject": "other"}, "not_self"),
        ({"subject": "hypothetical"}, "not_self"),
        ({"sensitive": "mental_health"}, "sensitive"),
    ],
)
def test_ineligible_signals_are_refused_as_support(kwargs: dict, reason: str) -> None:
    """Enforced in code, not left to the prompt (CLAUDE.md engine rule 8)."""
    result = score(interp([ev(sig("a", DAY1)), ev(sig("b", DAY2, **kwargs))]), ctx())
    assert result.breakdown["supports"] == 1
    assert result.breakdown["excluded_supports"] == [{"signal_id": "b", "reason": reason}]
    assert result.breakdown["distinct_days"] == 1


def test_removed_evidence_is_not_counted() -> None:
    kept = EvidenceIn(signal=sig("a", DAY1))
    gone = EvidenceIn(signal=sig("b", DAY2), removed_at=NOW)
    result = score(interp([kept, gone]), ctx())
    assert result.breakdown["supports"] == 1
    assert result.breakdown["support_sum"] == 1.0


def test_support_timeline_records_days_messages_and_span() -> None:
    timeline = support_timeline(
        [ev(sig("a", DAY1)), ev(sig("b", DAY2)), ev(sig("c", DAY2 + timedelta(hours=2)))],
        "UTC",
    )
    assert timeline.count == 3
    assert timeline.days == ("2026-09-18", "2026-09-19")
    assert timeline.distinct_messages == 3
    assert round(timeline.span_hours, 1) == 26.0


def test_breakdown_is_json_shaped_for_the_jsonb_column() -> None:
    import json

    result = score(interp([ev(sig("a", DAY1)), ev(sig("b", DAY2))]), ctx())
    assert json.loads(json.dumps(result.breakdown))["value"] == result.value
    assert result.version == "conf-v1"


def test_timezone_travels_with_the_user_policy() -> None:
    result = score(interp([ev(sig("a", DAY1))]), ctx(policy=UserPolicy(timezone="Europe/Berlin")))
    assert result.breakdown["timezone"] == "Europe/Berlin"
