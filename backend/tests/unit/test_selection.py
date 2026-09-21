"""Which memories reach the prompt (plan §5.4).

The score is the whole product's taste in one line: 0.6 cosine, 0.25 recency,
0.15 confirmations. These tests pin the arithmetic, the near-duplicate cut at
0.95, and the two promises that matter more than the score — a pinned item is
always in, and nothing is ever truncated to fit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ros.memory.protocols import Hit
from ros.memory.selection import (
    CONFIRMATION_CAP,
    Candidate,
    SectionBudget,
    confirmation_score,
    dedup,
    fit_budget,
    rank,
    recency,
    score_candidate,
    select,
    similarity,
    trim_lowest,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def candidate(
    text: str = "They are vegetarian.",
    *,
    cosine: float = 0.0,
    days_old: float = 0.0,
    confirmations: int = 0,
    pinned: bool = False,
    embedding: tuple[float, ...] | None = None,
) -> Candidate:
    return Candidate(
        id=uuid.uuid5(uuid.NAMESPACE_OID, text + str(cosine) + str(days_old)),
        kind="memory_item",
        text=text,
        cosine=cosine,
        created_at=NOW - timedelta(days=days_old),
        confirmations=confirmations,
        pinned=pinned,
        embedding=embedding,
    )


def tokens(text: str) -> int:
    """A word is a token here, so budgets in the tests are easy to read."""
    return len(text.split())


# ------------------------------------------------------------------- the parts


def test_recency_halves_every_thirty_days() -> None:
    assert recency(NOW, NOW) == 1.0
    assert recency(NOW - timedelta(days=30), NOW) == pytest.approx(0.5)
    assert recency(NOW - timedelta(days=60), NOW) == pytest.approx(0.25)


def test_recency_of_an_unknown_date_is_zero_not_one() -> None:
    # An undated memory must not outrank one we know is fresh.
    assert recency(None, NOW) == 0.0


def test_a_single_mention_is_not_a_confirmation() -> None:
    assert confirmation_score(0) == 0.0
    assert confirmation_score(1) == 0.0
    assert confirmation_score(2) == pytest.approx(0.25)
    assert confirmation_score(CONFIRMATION_CAP) == 1.0
    assert confirmation_score(50) == 1.0


def test_score_is_the_weighted_sum() -> None:
    scored = score_candidate(candidate(cosine=1.0, days_old=0, confirmations=CONFIRMATION_CAP), NOW)
    assert scored.score == pytest.approx(1.0)
    assert scored.parts["cosine"] == 1.0

    half = score_candidate(candidate(cosine=0.8, days_old=30, confirmations=1), NOW)
    assert half.score == pytest.approx(0.6 * 0.8 + 0.25 * 0.5 + 0.0)


def test_negative_cosine_cannot_drag_a_score_below_zero() -> None:
    assert score_candidate(candidate(cosine=-0.9), NOW).score >= 0.0


def test_rank_is_stable_for_equal_scores() -> None:
    a = candidate("one", cosine=0.5)
    b = candidate("two", cosine=0.5)
    first = [item.id for item in rank([a, b], NOW)]
    second = [item.id for item in rank([b, a], NOW)]
    assert first == second


# -------------------------------------------------------------- near-duplicates


def test_duplicate_text_is_dropped_without_vectors() -> None:
    kept, dropped = dedup(rank([candidate("They  are VEGETARIAN."), candidate()], NOW))
    assert len(kept) == 1
    assert len(dropped) == 1


def test_near_duplicate_vectors_are_dropped_at_the_cutoff() -> None:
    close = candidate("a", cosine=0.9, embedding=(1.0, 0.0, 0.0))
    nearly = candidate("b", cosine=0.8, embedding=(0.999, 0.045, 0.0))
    far = candidate("c", cosine=0.7, embedding=(0.0, 1.0, 0.0))
    assert similarity(close, nearly) >= 0.95
    kept, dropped = dedup(rank([close, nearly, far], NOW))
    assert [item.text for item in kept] == ["a", "c"]
    assert [item.text for item in dropped] == ["b"]


def test_different_wordings_below_the_cutoff_both_survive() -> None:
    a = candidate("a", cosine=0.9, embedding=(1.0, 0.0))
    b = candidate("b", cosine=0.8, embedding=(0.8, 0.6))
    kept, _ = dedup(rank([a, b], NOW))
    assert len(kept) == 2


# -------------------------------------------------------------------- budgets


def test_budget_takes_from_the_top_and_never_truncates() -> None:
    items = rank(
        [
            candidate("one two three", cosine=0.9),
            candidate("four five six", cosine=0.5),
            candidate("seven eight nine", cosine=0.1),
        ],
        NOW,
    )
    fitted = fit_budget(items, SectionBudget("memory", max_tokens=6), tokens=tokens)
    assert [item.text for item in fitted.kept] == ["one two three", "four five six"]
    assert fitted.tokens == 6
    # The one that did not fit is reported, not silently swallowed.
    assert len(fitted.dropped_budget) == 1


def test_a_pinned_item_goes_in_even_with_no_similarity() -> None:
    chosen = select(
        [
            candidate("close but not pinned", cosine=0.95),
            candidate("pinned and old", cosine=0.0, days_old=400, pinned=True),
        ],
        now=NOW,
        budget=SectionBudget("memory", max_tokens=4, always_include_pinned=True),
        tokens=tokens,
    )
    assert "pinned and old" in [item.text for item in chosen.kept]


def test_min_score_never_excludes_a_pinned_item() -> None:
    chosen = select(
        [candidate("pinned", cosine=0.0, pinned=True), candidate("weak", cosine=0.01)],
        now=NOW,
        budget=SectionBudget("memory", max_tokens=100),
        tokens=tokens,
        min_score=0.5,
    )
    assert [item.text for item in chosen.kept] == ["pinned"]


def test_trim_lowest_gives_tokens_back_worst_first() -> None:
    chosen = select(
        [
            candidate("best one", cosine=0.9),
            candidate("middle one", cosine=0.5),
            candidate("worst one", cosine=0.1),
        ],
        now=NOW,
        budget=SectionBudget("memory", max_tokens=100),
        tokens=tokens,
    )
    trimmed = trim_lowest(chosen, to_tokens=4, tokens=tokens)
    assert [item.text for item in trimmed.kept] == ["best one", "middle one"]
    assert trimmed.tokens <= 4


def test_trim_to_nothing_empties_the_section() -> None:
    chosen = select(
        [candidate("anything", cosine=0.9)],
        now=NOW,
        budget=SectionBudget("memory", max_tokens=100),
        tokens=tokens,
    )
    assert trim_lowest(chosen, to_tokens=0, tokens=tokens).kept == ()


def test_candidate_from_hit_carries_the_score_through() -> None:
    hit = Hit(
        id=uuid.uuid4(),
        kind="message",
        text="I skipped lunch again",
        score=0.81,
        created_at=NOW,
        seq=12,
        confirmations=3,
    )
    made = Candidate.from_hit(hit)
    assert made.cosine == 0.81
    assert made.meta["seq"] == 12
    assert score_candidate(made, NOW).parts["confirmations"] > 0
