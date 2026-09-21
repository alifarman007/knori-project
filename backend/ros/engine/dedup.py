"""Merging two readings of the same thing, before the threshold runs (plan §4.5).

Two interpret runs, days apart, can land on the same claim in slightly different
words. Left alone that becomes two cards saying one thing, which reads as KnoRI
not listening to itself. So the pre-step: open interpretations of the same kind
and topic, with no contradicting link between them, that the same-claim decision
says are the same, are merged — evidence moves to the *older* row, the newer one
becomes ``superseded (merged)``, and only the older row is re-scored.

The older row wins on purpose. It carries the earlier evidence, so merging into
it preserves the calendar spread that R3 counts, and it keeps the identity the
user may already have seen.

This module decides *what* to merge and returns instructions. It writes nothing:
``ros.engine.pipeline`` applies them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from ros.engine.types import ClaimMatchIn, EvidenceIn, InterpretationIn


@dataclass(frozen=True, slots=True)
class MergePlan:
    """Move this evidence from ``loser_id`` to ``winner_id``, then supersede the loser."""

    winner_id: str
    loser_id: str
    evidence_to_move: tuple[EvidenceIn, ...]
    cosine: float = 0.0
    reason: str = "same_claim"


def _sort_key(interpretation: InterpretationIn) -> tuple[datetime, str]:
    created = interpretation.created_at
    moment = (
        created
        if created and created.tzinfo
        else (created.replace(tzinfo=UTC) if created else datetime.max.replace(tzinfo=UTC))
    )
    return (moment, interpretation.id)


def contradicts_link(a: InterpretationIn, b: InterpretationIn) -> bool:
    """True when one row holds as counter-evidence a signal the other is built on.

    Rows like that disagree about the same evidence. Merging them would silently
    delete the disagreement, so they are left as two rows.
    """
    a_supports = a.support_signal_ids()
    b_supports = b.support_signal_ids()
    a_against = {e.signal.id for e in a.active_evidence("contradicts")}
    b_against = {e.signal.id for e in b.active_evidence("contradicts")}
    return bool(a_against & b_supports) or bool(b_against & a_supports)


def _mergeable(a: InterpretationIn, b: InterpretationIn) -> bool:
    return (
        a.id != b.id
        and a.open
        and b.open
        and a.kind == b.kind
        and a.topic == b.topic
        and not contradicts_link(a, b)
    )


def _group(pairs: Sequence[tuple[str, str]], ids: Sequence[str]) -> dict[str, list[str]]:
    """Union-find, so A~B and B~C put all three in one group."""
    parent = {i: i for i in ids}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for left, right in pairs:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    groups: dict[str, list[str]] = {}
    for node in ids:
        groups.setdefault(find(node), []).append(node)
    return groups


def plan_merges(
    interpretations: Sequence[InterpretationIn],
    claim_matches: Sequence[ClaimMatchIn],
) -> list[MergePlan]:
    """Work out which open interpretations collapse into which."""
    by_id = {i.id: i for i in interpretations if i.open}
    cosines: dict[tuple[str, str], float] = {}
    pairs: list[tuple[str, str]] = []

    for match in claim_matches:
        if match.target_kind != "interpretation" or not match.same:
            continue
        left = by_id.get(match.interpretation_id)
        right = by_id.get(match.target_id)
        if left is None or right is None or not _mergeable(left, right):
            continue
        first, second = sorted((left.id, right.id))
        pairs.append((first, second))
        cosines[first, second] = max(cosines.get((first, second), 0.0), float(match.cosine))

    plans: list[MergePlan] = []
    for members in _group(pairs, sorted(by_id)).values():
        if len(members) < 2:
            continue
        ordered = sorted((by_id[m] for m in members), key=_sort_key)
        winner, losers = ordered[0], ordered[1:]
        # Signals the winner will hold once earlier losers have been folded in,
        # so the same signal is never queued for the move twice.
        held = set(winner.support_signal_ids()) | {
            e.signal.id for e in winner.active_evidence() if e.role != "supports"
        }
        for loser in losers:
            moving = tuple(e for e in loser.active_evidence() if e.signal.id not in held)
            held.update(e.signal.id for e in moving)
            first, second = sorted((winner.id, loser.id))
            plans.append(
                MergePlan(
                    winner_id=winner.id,
                    loser_id=loser.id,
                    evidence_to_move=moving,
                    cosine=cosines.get((first, second), 0.0),
                )
            )
    return plans
