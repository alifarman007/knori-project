"""``conf-v1`` — how sure the engine is, and why (plan §4.4).

A pure function with a versioned name, because the number on a card has to be
explainable a year later. The breakdown it returns is stored verbatim in
``interpretations.confidence_breakdown`` and is what the UI turns into plain
words ("two things you said, on two different days, nothing against it").

The shape:

    w(e)           = signal.strength x evidence.weight
    S              = sum of w over active supports
    C              = sum of w over active contradicts
    evidence_score = 1 - exp(-S / tau)
    consistency    = S / (S + C)          (1.0 when there is no evidence at all)
    spread         = distinct calendar days, in the user's timezone
    base           = evidence_score x consistency x spread
    confidence     = clamp(base + assertion adjustments, 0, 1)

``model_confidence`` is deliberately absent: it is a gate (R4), not a term. One
mechanism per decision.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ros.engine.types import (
    ConfidenceConstants,
    ConfidenceLabel,
    ConfidenceResult,
    EngineContext,
    EvidenceIn,
    InterpretationIn,
    SupportTimeline,
    Thresholds,
    load_thresholds,
)


def _zone(tz_name: str) -> tzinfo:
    """The user's timezone, or UTC if it cannot be loaded.

    ``ZoneInfo`` needs a tz database, and Windows ships none of its own — so
    without the ``tzdata`` package even ``ZoneInfo("UTC")`` raises. Falling back
    to ``datetime.UTC`` keeps R3 counting days instead of failing the pipeline,
    but a real user timezone silently becoming UTC would shift day boundaries:
    ``tzdata`` belongs in the backend dependencies.
    """
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def local_day(moment: datetime, timezone: str) -> str:
    """The calendar date R3 counts, in the user's own timezone."""
    return _aware(moment).astimezone(_zone(timezone)).date().isoformat()


def eligible_supports(evidence: Iterable[EvidenceIn]) -> tuple[EvidenceIn, ...]:
    """Active supports that are allowed to back a Recognition.

    Validation already rejects the others (rule V1), but the score refuses them
    again: CLAUDE.md engine rule 8 says this is enforced in code, and "enforced
    once, upstream" is how that quietly stops being true.
    """
    return tuple(
        e for e in evidence if e.active and e.role == "supports" and e.signal.eligible_support
    )


def support_timeline(evidence: Iterable[EvidenceIn], timezone: str) -> SupportTimeline:
    """When the supporting evidence happened — shared by conf-v1 and R3."""
    supports = eligible_supports(evidence)
    moments = [e.signal.observed_at for e in supports if e.signal.observed_at is not None]
    days = sorted({local_day(m, timezone) for m in moments})
    messages = sorted({e.signal.message_id for e in supports if e.signal.message_id})
    return SupportTimeline(
        count=len(supports),
        signal_ids=tuple(sorted(e.signal.id for e in supports)),
        message_ids=tuple(messages),
        days=tuple(days),
        earliest=min(moments, default=None) if moments else None,
        latest=max(moments, default=None) if moments else None,
        weight_sum=sum(e.w for e in supports),
    )


def evidence_score(support_sum: float, tau: float) -> float:
    """Diminishing returns: S=1 -> 0.57, S=2 -> 0.81, S=3 -> 0.92."""
    return 1.0 - math.exp(-support_sum / tau)


def consistency_of(support_sum: float, contradict_sum: float) -> float:
    total = support_sum + contradict_sum
    return 1.0 if total <= 0 else support_sum / total


def label_for(value: float, constants: ConfidenceConstants) -> ConfidenceLabel:
    if value < constants.hidden_below:
        return "hidden"
    return "strong" if value >= constants.strong_at else "likely"


def _excluded(evidence: Sequence[EvidenceIn]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in evidence:
        if not e.active or e.role != "supports" or e.signal.eligible_support:
            continue
        reason = "sensitive" if e.signal.sensitive_category else "not_self"
        out.append({"signal_id": e.signal.id, "reason": reason})
    return out


def _adjustments(
    interpretation: InterpretationIn, ctx: EngineContext, constants: ConfidenceConstants
) -> list[dict[str, Any]]:
    """What the user's own corrections add to, or take off, this claim.

    An assertion counts once. It can reach a claim two ways — it was filed
    against this exact row, or the same-claim judge tied it to this row — and
    counting both would double a correction the user made once.
    """
    deltas = {"affirm": constants.affirm_adjustment, "scope": constants.scope_adjustment}
    similar = {m.target_id for m in ctx.matches_for(interpretation.id, "assertion") if m.same}
    out: list[dict[str, Any]] = []
    for assertion in sorted(ctx.active_assertions(), key=lambda a: a.id):
        delta = deltas.get(assertion.kind)
        if delta is None:
            continue  # deny is rule R7; amend supersedes the row outright
        direct = assertion.applies_to_interpretation_id == interpretation.id
        if not direct and assertion.id not in similar:
            continue
        out.append(
            {
                "assertion_id": assertion.id,
                "kind": assertion.kind,
                "weight": round(float(assertion.weight), 4),
                "delta": round(delta * float(assertion.weight), 6),
                "matched_by": "applies_to" if direct else "same_claim",
            }
        )
    return out


def score(
    interpretation: InterpretationIn,
    ctx: EngineContext,
    *,
    thresholds: Thresholds | None = None,
) -> ConfidenceResult:
    """Run ``conf-v1`` over one interpretation."""
    constants = (thresholds or load_thresholds()).confidence
    timezone = ctx.policy.timezone

    supports = eligible_supports(interpretation.evidence)
    contradicts = interpretation.active_evidence("contradicts")
    support_sum = sum(e.w for e in supports)
    contradict_sum = sum(e.w for e in contradicts)

    timeline = support_timeline(interpretation.evidence, timezone)
    ev_score = evidence_score(support_sum, constants.evidence_tau)
    consistency = consistency_of(support_sum, contradict_sum)
    spread = constants.spread_for(timeline.distinct_days)
    base = ev_score * consistency * spread

    adjustments = _adjustments(interpretation, ctx, constants)
    adjustment_total = sum(float(a["delta"]) for a in adjustments)
    value = min(1.0, max(0.0, base + adjustment_total))

    floor_applied = False
    if interpretation.source == "user_correction" and value < constants.user_correction_floor:
        value = constants.user_correction_floor
        floor_applied = True

    # 3 decimals: `interpretations.confidence` is numeric(4,3), so rounding here
    # means the stored number and the number the rules used are the same number.
    value = round(value, 3)
    breakdown: dict[str, Any] = {
        "version": constants.version,
        "timezone": timezone,
        "supports": len(supports),
        "contradicts": len(contradicts),
        "support_sum": round(support_sum, 6),
        "contradict_sum": round(contradict_sum, 6),
        "evidence_score": round(ev_score, 6),
        "consistency": round(consistency, 6),
        "spread": spread,
        "distinct_days": timeline.distinct_days,
        "support_days": list(timeline.days),
        "distinct_messages": timeline.distinct_messages,
        "span_hours": round(timeline.span_hours, 4),
        "base": round(base, 6),
        "adjustments": adjustments,
        "adjustment_total": round(adjustment_total, 6),
        "excluded_supports": _excluded(interpretation.evidence),
        "user_correction_floor_applied": floor_applied,
        "value": value,
    }
    return ConfidenceResult(
        value=value,
        label=label_for(value, constants),
        breakdown=breakdown,
        version=constants.version,
    )
