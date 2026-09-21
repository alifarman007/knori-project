"""Which memories go into this turn's prompt, and in what order.

A pure module: candidates in, a ranked and budgeted selection out. No database,
no model, no clock of its own — ``now`` is passed in, so the same inputs always
give the same prompt and a selection can be table-tested (plan §5.4).

The score is deliberately boring and inspectable::

    0.60 x cosine
  + 0.25 x recency      (exponential, 30-day half-life)
  + 0.15 x confirmations (how often they have said it again, capped)

Cosine alone would keep handing back the one thing they said in March; recency
alone would forget what matters. Confirmations are the user's own repetition,
which is the strongest signal there is that something is still true.

Two things then protect the prompt from the score: near-duplicates are dropped
at 0.95 cosine (the same fact in two wordings is one line, not two), and each
section has its own token budget so a wall of old messages can never crowd out
what they told KnoRI directly.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from ros.engine.claims import cosine
from ros.memory.protocols import Hit

#: Weights of the three score parts. They sum to 1.0 so a score reads as 0..1.
COSINE_WEIGHT = 0.60
RECENCY_WEIGHT = 0.25
CONFIRMATION_WEIGHT = 0.15

RECENCY_HALF_LIFE_DAYS = 30.0
#: Saying something five times is as confirmed as this scorer needs it to be.
CONFIRMATION_CAP = 5
#: Two candidates this close are the same thing said twice.
DUPLICATE_COSINE = 0.95


@dataclass(frozen=True, slots=True)
class Candidate:
    """One thing that could go into the prompt."""

    id: uuid.UUID
    kind: str
    text: str
    cosine: float = 0.0
    created_at: datetime | None = None
    confirmations: int = 0
    pinned: bool = False
    item_kind: str | None = None
    embedding: tuple[float, ...] | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_hit(cls, hit: Hit) -> Candidate:
        return cls(
            id=hit.id,
            kind=hit.kind,
            text=hit.text,
            cosine=hit.score,
            created_at=hit.created_at,
            confirmations=hit.confirmations,
            pinned=hit.pinned,
            item_kind=hit.item_kind,
            embedding=hit.embedding,
            meta=dict(hit.meta) | ({"seq": hit.seq} if hit.seq is not None else {}),
        )


@dataclass(frozen=True, slots=True)
class Scored:
    """A candidate with its score and the arithmetic behind it."""

    candidate: Candidate
    score: float
    parts: Mapping[str, float] = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        return self.candidate.id

    @property
    def text(self) -> str:
        return self.candidate.text

    @property
    def pinned(self) -> bool:
        return self.candidate.pinned


@dataclass(frozen=True, slots=True)
class SectionBudget:
    """How much of the prompt one section of retrieved context may take."""

    name: str
    max_tokens: int
    max_items: int = 50
    #: Pinned items go in whatever the score says — the user asked for them.
    always_include_pinned: bool = False


@dataclass(frozen=True, slots=True)
class Selection:
    """What was chosen, and what was left out and why."""

    kept: tuple[Scored, ...] = ()
    dropped_duplicate: tuple[Scored, ...] = ()
    dropped_budget: tuple[Scored, ...] = ()
    tokens: int = 0

    @property
    def ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(item.id for item in self.kept)

    def texts(self) -> tuple[str, ...]:
        return tuple(item.text for item in self.kept)


TokenEstimator = Callable[[str], int]


def _default_tokens(text: str) -> int:
    """Only a fallback: the context builder passes the calibrated estimator in."""
    return max(1, round(len(text) / 3.6)) if text else 0


# ----------------------------------------------------------------------- scoring


def recency(created_at: datetime | None, now: datetime, *, half_life_days: float = 30.0) -> float:
    """1.0 for something said now, 0.5 after one half-life, never below 0.

    A missing timestamp scores 0 rather than 1: an unknown date is not a fresh one.
    """
    if created_at is None or half_life_days <= 0:
        return 0.0
    age_days = (now - created_at).total_seconds() / 86_400.0
    if age_days <= 0:
        return 1.0
    return float(0.5 ** (age_days / half_life_days))


def confirmation_score(confirmations: int, *, cap: int = CONFIRMATION_CAP) -> float:
    """How often they said it again, as 0..1. One mention is not a confirmation."""
    if confirmations <= 1 or cap <= 1:
        return 0.0
    return min(confirmations - 1, cap - 1) / float(cap - 1)


def score_candidate(
    candidate: Candidate,
    now: datetime,
    *,
    half_life_days: float = RECENCY_HALF_LIFE_DAYS,
    confirmation_cap: int = CONFIRMATION_CAP,
) -> Scored:
    """plan §5.4: ``0.6 x cosine + 0.25 x recency + 0.15 x confirmations``."""
    cos = max(0.0, min(1.0, float(candidate.cosine)))
    rec = recency(candidate.created_at, now, half_life_days=half_life_days)
    conf = confirmation_score(candidate.confirmations, cap=confirmation_cap)
    total = COSINE_WEIGHT * cos + RECENCY_WEIGHT * rec + CONFIRMATION_WEIGHT * conf
    return Scored(
        candidate=candidate,
        score=round(total, 6),
        parts={"cosine": round(cos, 6), "recency": round(rec, 6), "confirmations": round(conf, 6)},
    )


def rank(
    candidates: Iterable[Candidate],
    now: datetime,
    *,
    half_life_days: float = RECENCY_HALF_LIFE_DAYS,
    confirmation_cap: int = CONFIRMATION_CAP,
) -> list[Scored]:
    """Highest score first. Ties break on id, so the order never wobbles."""
    scored = [
        score_candidate(
            candidate, now, half_life_days=half_life_days, confirmation_cap=confirmation_cap
        )
        for candidate in candidates
    ]
    scored.sort(key=lambda item: (-item.score, str(item.id)))
    return scored


# ------------------------------------------------------------------ near-duplicates


def _normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def similarity(a: Candidate, b: Candidate) -> float:
    """Cosine when both carry a vector, otherwise exact text equality.

    Falling back to equality rather than to a fuzzy string ratio keeps this
    honest: without vectors we only claim two items are the same when they
    literally are.
    """
    if a.embedding is not None and b.embedding is not None and len(a.embedding) == len(b.embedding):
        return cosine(a.embedding, b.embedding)
    return 1.0 if _normalise(a.text) == _normalise(b.text) else 0.0


def dedup(
    scored: Sequence[Scored],
    *,
    threshold: float = DUPLICATE_COSINE,
) -> tuple[list[Scored], list[Scored]]:
    """Keep the best of each cluster. Returns ``(kept, dropped)``.

    Input order decides which of two duplicates survives, so pass a ranked list.
    """
    kept: list[Scored] = []
    dropped: list[Scored] = []
    for item in scored:
        if any(similarity(item.candidate, other.candidate) >= threshold for other in kept):
            dropped.append(item)
            continue
        kept.append(item)
    return kept, dropped


# ----------------------------------------------------------------------- budgeting


def fit_budget(
    scored: Sequence[Scored],
    budget: SectionBudget,
    *,
    tokens: TokenEstimator = _default_tokens,
) -> Selection:
    """Take from the top until the section is full. Pinned items can jump the queue.

    Nothing is truncated mid-sentence: an item either fits whole or waits for the
    next prompt. A budgeted-out item is returned, not forgotten, so the manifest
    can say what was left out.
    """
    ordered = list(scored)
    if budget.always_include_pinned:
        ordered.sort(key=lambda item: (not item.pinned,))  # stable: keeps score order

    kept: list[Scored] = []
    dropped: list[Scored] = []
    used = 0
    for item in ordered:
        cost = tokens(item.text)
        if len(kept) >= budget.max_items or used + cost > budget.max_tokens:
            dropped.append(item)
            continue
        kept.append(item)
        used += cost
    return Selection(kept=tuple(kept), dropped_budget=tuple(dropped), tokens=used)


def select(
    candidates: Iterable[Candidate],
    *,
    now: datetime,
    budget: SectionBudget,
    tokens: TokenEstimator = _default_tokens,
    duplicate_threshold: float = DUPLICATE_COSINE,
    min_score: float = 0.0,
    half_life_days: float = RECENCY_HALF_LIFE_DAYS,
) -> Selection:
    """Rank, drop near-duplicates, then fill the section budget. One call per section."""
    scored = [
        item
        for item in rank(candidates, now, half_life_days=half_life_days)
        if item.score >= min_score or item.pinned
    ]
    kept, duplicates = dedup(scored, threshold=duplicate_threshold)
    fitted = fit_budget(kept, budget, tokens=tokens)
    return replace(fitted, dropped_duplicate=tuple(duplicates))


def trim_lowest(selection: Selection, *, to_tokens: int, tokens: TokenEstimator) -> Selection:
    """Give tokens back by dropping the worst-scoring items first.

    Used when the whole prompt is over its cap: the cheapest thing to lose is the
    least relevant retrieved line, never a message the person actually sent.
    """
    kept = list(selection.kept)
    dropped = list(selection.dropped_budget)
    used = sum(tokens(item.text) for item in kept)
    while kept and used > to_tokens:
        worst = min(range(len(kept)), key=lambda index: (kept[index].score, str(kept[index].id)))
        removed = kept.pop(worst)
        dropped.append(removed)
        used -= tokens(removed.text)
    return replace(selection, kept=tuple(kept), dropped_budget=tuple(dropped), tokens=used)


__all__ = [
    "CONFIRMATION_CAP",
    "CONFIRMATION_WEIGHT",
    "COSINE_WEIGHT",
    "DUPLICATE_COSINE",
    "RECENCY_HALF_LIFE_DAYS",
    "RECENCY_WEIGHT",
    "Candidate",
    "Scored",
    "SectionBudget",
    "Selection",
    "TokenEstimator",
    "confirmation_score",
    "dedup",
    "fit_budget",
    "rank",
    "recency",
    "score_candidate",
    "select",
    "similarity",
    "trim_lowest",
]
