"""'Is this the same claim?' — decided once per pair, before the threshold runs.

Three bands, because cosine is good at the ends and vague in the middle:

* at or above ``deny_same`` (0.90) the two texts are the same claim;
* below ``deny_different`` (0.70) they are different claims;
* in between, and only in between, one ``claims.same_claim`` judge call decides.

The band lives here rather than in ``thr-v1`` for a reason: the threshold must
stay a pure function that never calls a model (CLAUDE.md engine rule 3). This
module tells the caller which pairs need the judge; the caller makes the call and
writes the answers to ``claim_matches``, and the threshold only ever reads the
boolean that comes out.

Cutoffs are a property of the embedding model, so they are looked up by model
name. A new model means new calibration, never these numbers reused.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ros.engine.types import ClaimBand, ClaimMatchIn, SimilarityCutoffs, Thresholds, load_thresholds


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, clamped to [-1, 1]. A zero vector matches nothing."""
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / math.sqrt(norm_a * norm_b)))


def band(value: float, cutoffs: SimilarityCutoffs) -> ClaimBand:
    if value >= cutoffs.deny_same:
        return "same"
    if value < cutoffs.deny_different:
        return "different"
    return "needs_judge"


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    """One interpretation compared with one thing the user already said."""

    interpretation_id: str
    target_kind: str  # assertion | memory_item | interpretation
    target_id: str
    cosine: float
    band: ClaimBand

    @property
    def needs_judge(self) -> bool:
        return self.band == "needs_judge"

    def to_match(self) -> ClaimMatchIn:
        """The row to store when cosine alone was enough."""
        if self.needs_judge:
            raise ValueError(
                f"{self.interpretation_id}->{self.target_id} is in the judge band; "
                "call the judge and use resolved()"
            )
        return ClaimMatchIn(
            interpretation_id=self.interpretation_id,
            target_kind=self.target_kind,
            target_id=self.target_id,
            same=self.band == "same",
            cosine=round(self.cosine, 3),
            decided_by="cosine",
        )

    def resolved(self, same: bool) -> ClaimMatchIn:
        """The row to store once the judge has answered."""
        return ClaimMatchIn(
            interpretation_id=self.interpretation_id,
            target_kind=self.target_kind,
            target_id=self.target_id,
            same=same,
            cosine=round(self.cosine, 3),
            decided_by="judge",
        )


def compare(
    interpretation_id: str,
    vector: Sequence[float],
    targets: Sequence[tuple[str, str, Sequence[float]]],
    *,
    embedding_model: str | None = None,
    thresholds: Thresholds | None = None,
) -> list[ClaimCandidate]:
    """Score one interpretation against ``(target_kind, target_id, vector)`` rows."""
    cutoffs = (thresholds or load_thresholds()).cutoffs(embedding_model)
    out: list[ClaimCandidate] = []
    for target_kind, target_id, target_vector in targets:
        value = cosine(vector, target_vector)
        out.append(
            ClaimCandidate(
                interpretation_id=interpretation_id,
                target_kind=target_kind,
                target_id=target_id,
                cosine=value,
                band=band(value, cutoffs),
            )
        )
    return out


def split_by_band(
    candidates: Sequence[ClaimCandidate],
) -> tuple[list[ClaimMatchIn], list[ClaimCandidate]]:
    """Split into rows ready to store and pairs that still need one judge call."""
    settled = [c.to_match() for c in candidates if not c.needs_judge]
    to_judge = [c for c in candidates if c.needs_judge]
    return settled, to_judge


def merge_candidates(
    candidates: Sequence[ClaimCandidate],
    *,
    embedding_model: str | None = None,
    thresholds: Thresholds | None = None,
) -> list[ClaimCandidate]:
    """Interpretation pairs close enough to be worth the dedup check (plan §4.5)."""
    cutoffs = (thresholds or load_thresholds()).cutoffs(embedding_model)
    return [
        c for c in candidates if c.target_kind == "interpretation" and c.cosine >= cutoffs.dedup
    ]
