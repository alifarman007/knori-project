"""The dedup pre-step and the cosine bands behind it (plan §4.5).

Two runs, days apart, can reach the same claim in different words. Merging them
into the *older* row keeps the calendar spread R3 counts, and stops the user
seeing one thought twice. The band logic lives alongside it, because it is what
decides whether "the same claim" is a cheap cosine answer or a judge call.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ros.engine.claims import (
    ClaimCandidate,
    band,
    compare,
    cosine,
    merge_candidates,
    split_by_band,
)
from ros.engine.dedup import contradicts_link, plan_merges
from ros.engine.types import ClaimMatchIn, EvidenceIn, InterpretationIn, SignalIn, load_thresholds

DAY1 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
DAY2 = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
DAY3 = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
CUTOFFS = load_thresholds().cutoffs("text-embedding-3-small")


def sig(ref: str) -> SignalIn:
    return SignalIn(id=ref, topic="work.decisions", observed_at=DAY1, message_id=f"m-{ref}")


def ev(ref: str, role: str = "supports", weight: float = 1.0) -> EvidenceIn:
    return EvidenceIn(signal=sig(ref), role=role, weight=weight)  # type: ignore[arg-type]


def interp(ident: str, created_at: datetime, evidence, **kw) -> InterpretationIn:
    base: dict = {"kind": "pattern", "topic": "work.decisions", "lifecycle_status": "candidate"}
    base.update(kw)
    return InterpretationIn(id=ident, created_at=created_at, evidence=tuple(evidence), **base)


def same(a: str, b: str, value: float = 0.94) -> ClaimMatchIn:
    return ClaimMatchIn(
        interpretation_id=a, target_kind="interpretation", target_id=b, same=True, cosine=value
    )


# ------------------------------------------------------------------- merging


def test_evidence_moves_to_the_older_row() -> None:
    older = interp("I-old", DAY1, [ev("a"), ev("b")])
    newer = interp("I-new", DAY3, [ev("c")])
    plans = plan_merges([newer, older], [same("I-new", "I-old")])
    assert len(plans) == 1
    assert (plans[0].winner_id, plans[0].loser_id) == ("I-old", "I-new")
    assert [e.signal.id for e in plans[0].evidence_to_move] == ["c"]
    assert plans[0].cosine == 0.94
    assert plans[0].reason == "same_claim"


def test_evidence_the_winner_already_holds_is_not_moved_twice() -> None:
    older = interp("I-old", DAY1, [ev("a"), ev("b")])
    newer = interp("I-new", DAY3, [ev("b"), ev("c")])
    plans = plan_merges([older, newer], [same("I-old", "I-new")])
    assert [e.signal.id for e in plans[0].evidence_to_move] == ["c"]


def test_a_chain_collapses_into_one_winner() -> None:
    a = interp("I-a", DAY1, [ev("s1")])
    b = interp("I-b", DAY2, [ev("s2")])
    c = interp("I-c", DAY3, [ev("s3")])
    plans = plan_merges([c, b, a], [same("I-a", "I-b"), same("I-b", "I-c")])
    assert {p.winner_id for p in plans} == {"I-a"}
    assert sorted(p.loser_id for p in plans) == ["I-b", "I-c"]


def test_the_direction_of_the_claim_match_does_not_matter() -> None:
    older = interp("I-old", DAY1, [ev("a")])
    newer = interp("I-new", DAY3, [ev("b")])
    forward = plan_merges([older, newer], [same("I-old", "I-new")])
    backward = plan_merges([older, newer], [same("I-new", "I-old")])
    assert forward[0].winner_id == backward[0].winner_id == "I-old"


@pytest.mark.parametrize(
    ("field", "value"),
    [("kind", "preference"), ("topic", "life.routine"), ("lifecycle_status", "retired")],
)
def test_rows_that_are_not_comparable_are_left_alone(field: str, value: str) -> None:
    older = interp("I-old", DAY1, [ev("a")])
    newer = interp("I-new", DAY3, [ev("b")], **{field: value})
    assert plan_merges([older, newer], [same("I-old", "I-new")]) == []


def test_a_disagreement_between_two_rows_is_never_merged_away() -> None:
    """One row holds as counter-evidence a signal the other is built on."""
    older = interp("I-old", DAY1, [ev("a"), ev("b")])
    newer = interp("I-new", DAY3, [ev("c"), ev("a", role="contradicts")])
    assert contradicts_link(older, newer) is True
    assert plan_merges([older, newer], [same("I-old", "I-new")]) == []


def test_a_different_claim_is_not_merged() -> None:
    older = interp("I-old", DAY1, [ev("a")])
    newer = interp("I-new", DAY3, [ev("b")])
    not_same = ClaimMatchIn(
        interpretation_id="I-old", target_kind="interpretation", target_id="I-new", same=False
    )
    assert plan_merges([older, newer], [not_same]) == []


def test_a_match_against_something_that_is_not_an_interpretation_is_ignored() -> None:
    older = interp("I-old", DAY1, [ev("a")])
    newer = interp("I-new", DAY3, [ev("b")])
    memory_match = ClaimMatchIn(
        interpretation_id="I-old", target_kind="memory_item", target_id="I-new", same=True
    )
    assert plan_merges([older, newer], [memory_match]) == []


def test_rows_with_no_created_at_sort_last_but_still_merge() -> None:
    known = interp("I-known", DAY2, [ev("a")])
    unknown = InterpretationIn(
        id="I-unknown", kind="pattern", topic="work.decisions", evidence=(ev("b"),)
    )
    plans = plan_merges([unknown, known], [same("I-unknown", "I-known")])
    assert plans[0].winner_id == "I-known"


def test_removed_evidence_is_not_carried_over() -> None:
    older = interp("I-old", DAY1, [ev("a")])
    dropped = EvidenceIn(signal=sig("c"), removed_at=DAY2)
    newer = interp("I-new", DAY3, [ev("b"), dropped])
    plans = plan_merges([older, newer], [same("I-old", "I-new")])
    assert [e.signal.id for e in plans[0].evidence_to_move] == ["b"]


# --------------------------------------------------------------- the bands


def test_cosine_basics() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine([2.0, 0.0], [8.0, 0.0]) == pytest.approx(1.0)


def test_a_zero_vector_matches_nothing() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_mismatched_vectors_are_a_bug_not_a_score() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "same"),
        (0.90, "same"),
        (0.8999, "needs_judge"),
        (0.75, "needs_judge"),
        (0.70, "needs_judge"),
        (0.6999, "different"),
        (0.0, "different"),
    ],
)
def test_band_edges(value: float, expected: str) -> None:
    assert band(value, CUTOFFS) == expected


def test_compare_scores_every_target() -> None:
    candidates = compare(
        "I1",
        [1.0, 0.0],
        [("assertion", "A1", [1.0, 0.0]), ("memory_item", "M1", [0.0, 1.0])],
    )
    assert [(c.target_id, c.band) for c in candidates] == [("A1", "same"), ("M1", "different")]


def test_split_by_band_settles_what_it_can_and_hands_over_the_rest() -> None:
    candidates = [
        ClaimCandidate("I1", "assertion", "A1", 0.95, "same"),
        ClaimCandidate("I1", "assertion", "A2", 0.40, "different"),
        ClaimCandidate("I1", "assertion", "A3", 0.80, "needs_judge"),
    ]
    settled, to_judge = split_by_band(candidates)
    assert [(m.target_id, m.same, m.decided_by) for m in settled] == [
        ("A1", True, "cosine"),
        ("A2", False, "cosine"),
    ]
    assert [c.target_id for c in to_judge] == ["A3"]


def test_the_judge_band_must_not_be_settled_by_cosine() -> None:
    candidate = ClaimCandidate("I1", "assertion", "A3", 0.80, "needs_judge")
    with pytest.raises(ValueError, match="judge band"):
        candidate.to_match()
    resolved = candidate.resolved(same=True)
    assert (resolved.same, resolved.decided_by, resolved.cosine) == (True, "judge", 0.8)


def test_merge_candidates_uses_the_dedup_cutoff() -> None:
    candidates = [
        ClaimCandidate("I1", "interpretation", "I2", 0.93, "same"),
        ClaimCandidate("I1", "interpretation", "I3", 0.88, "needs_judge"),
        ClaimCandidate("I1", "assertion", "A1", 0.99, "same"),
    ]
    assert [c.target_id for c in merge_candidates(candidates)] == ["I2"]


def test_an_uncalibrated_embedding_model_refuses_to_guess() -> None:
    with pytest.raises(KeyError, match="calibration"):
        load_thresholds().cutoffs("some-new-model")
