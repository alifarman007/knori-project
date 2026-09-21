"""``thr-v1`` — the decision to show a Recognition, or not (plan §4.5).

Ordered, pure, and loud about refusing. Every rule R0-R10 is evaluated on every
run, even the ones after the first failure, and all eleven results are written to
``threshold_evaluations.rules``. The *first* failing rule decides the outcome, so
"why didn't KnoRI say anything?" always has one answer with a rule id behind it.

This function never calls a model. "Is this the same claim as something the user
already told us, or already denied?" was decided earlier, in
``ros.engine.claims``, and arrives here as a boolean on a ``ClaimMatchIn``.

R3 is the one that matters most: two supporting signals, on two different
calendar days, at least twelve hours apart. One message, one sitting, or one day
can never become a Recognition — not even a very confident one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from ros.engine.confidence import support_timeline
from ros.engine.types import (
    ConfidenceResult,
    EngineContext,
    GateOutcome,
    InterpretationIn,
    RuleCheck,
    RuleValue,
    SensitiveConstants,
    ThresholdConstants,
    ThresholdResult,
    Thresholds,
    load_thresholds,
)

#: rule -> (outcome if it fails, reason code written to the ledger)
RULE_OUTCOMES: dict[str, tuple[GateOutcome, str]] = {
    "R0": ("hold", "user_disabled"),
    "R1": ("hold", "already_presented"),
    "R2": ("decline", "already_known"),
    "R3": ("hold", "insufficient_evidence"),
    "R4": ("hold", "low_model_confidence"),
    "R5": ("hold", "contradicted"),
    "R6": ("suppress", "sensitive"),
    "R7": ("suppress", "user_denied"),
    "R8": ("hold", "below_threshold"),
    "R9": ("hold", "cooldown"),
    "R10": ("hold", "rate_limited"),
}

RULE_ORDER: tuple[str, ...] = tuple(RULE_OUTCOMES)


def _rule(rule: str, passed: bool, value: RuleValue = None, limit: RuleValue = None) -> RuleCheck:
    outcome, reason = RULE_OUTCOMES[rule]
    return RuleCheck(
        rule=rule, passed=passed, value=value, limit=limit, outcome=outcome, reason=reason
    )


@lru_cache(maxsize=8)
def _compiled(patterns: tuple[tuple[str, str], ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((category, re.compile(pattern, re.IGNORECASE)) for category, pattern in patterns)


def sensitive_hit(statement: str, constants: SensitiveConstants) -> str | None:
    """The sensitive category a statement reads as, or None.

    A second net under the extracted ``sensitive_category``. Categories are never
    *inferred* into a Recognition by this — the only thing a hit can do is
    suppress one.
    """
    flat = tuple(
        (category, pattern)
        for category, patterns in constants.deny_patterns.items()
        for pattern in patterns
    )
    for category, compiled in _compiled(flat):
        if compiled.search(statement or ""):
            return category
    return None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def cooldown_until(now: datetime, dismiss_count: int, constants: ThresholdConstants) -> datetime:
    """How long a dismissed claim stays quiet. A second dismissal means longer."""
    days = constants.cooldown_days_first if dismiss_count < 1 else constants.cooldown_days_repeat
    return _aware(now) + timedelta(days=days)


def evaluate(
    interpretation: InterpretationIn,
    confidence: ConfidenceResult,
    ctx: EngineContext,
    *,
    thresholds: Thresholds | None = None,
) -> ThresholdResult:
    """Run every rule, then let the first failure decide."""
    config = thresholds or load_thresholds()
    limits = config.threshold
    timezone = ctx.policy.timezone
    checks: list[RuleCheck] = []

    # R0 — the user's own switch comes before everything else.
    enabled = bool(ctx.policy.recognition_enabled)
    checks.append(_rule("R0", enabled, value=enabled, limit=True))

    # R1 — one card per (interpretation, version), ever. Only a revise bumps it.
    has_card = ctx.has_card(interpretation.id, interpretation.version)
    checks.append(_rule("R1", not has_card, value=has_card, limit=False))

    # R2 — an explicit fact the user already told us is not a Recognition.
    # With no active-memory set supplied, a match is honoured rather than ignored.
    memory_hit = next(
        (
            m.target_id
            for m in ctx.matches_for(interpretation.id, "memory_item")
            if m.same and (not ctx.active_memory_ids or m.target_id in ctx.active_memory_ids)
        ),
        None,
    )
    checks.append(_rule("R2", memory_hit is None, value=memory_hit))

    # R3 — the hard minimum.
    timeline = support_timeline(interpretation.evidence, timezone)
    span_hours = timeline.span_hours
    r3_passed = (
        timeline.count >= limits.min_supports
        and timeline.distinct_days >= limits.min_distinct_days
        and span_hours >= limits.min_span_hours
    )
    checks.append(
        _rule(
            "R3",
            r3_passed,
            value={
                "supports": timeline.count,
                "distinct_days": timeline.distinct_days,
                "distinct_messages": timeline.distinct_messages,
                "span_hours": round(span_hours, 2),
            },
            limit={
                "supports": limits.min_supports,
                "distinct_days": limits.min_distinct_days,
                "span_hours": limits.min_span_hours,
            },
        )
    )

    # R4 — the model's own confidence is a gate, not a term in the score.
    # A row the user wrote is authored, not guessed, so it enters as 1.0 (§4.6).
    model_confidence = (
        1.0
        if interpretation.source == "user_correction"
        else float(interpretation.model_confidence)
    )
    checks.append(
        _rule(
            "R4",
            model_confidence >= limits.min_model_confidence,
            value=round(model_confidence, 3),
            limit=limits.min_model_confidence,
        )
    )

    # R5 — too much evidence pointing the other way.
    consistency = confidence.consistency
    checks.append(
        _rule(
            "R5",
            consistency >= limits.min_consistency,
            value=round(consistency, 3),
            limit=limits.min_consistency,
        )
    )

    # R6 — categories KnoRI does not draw conclusions about.
    statement_hit = sensitive_hit(interpretation.statement, config.sensitive)
    sensitive_reason = interpretation.sensitive_category or (
        f"deny_list:{statement_hit}" if statement_hit else None
    )
    checks.append(_rule("R6", sensitive_reason is None, value=sensitive_reason))

    # R7 — the user said no. That answer outlives the card.
    deny_ids = {a.id for a in ctx.active_assertions("deny")}
    denied_by = next(
        (
            a.id
            for a in ctx.active_assertions("deny")
            if a.applies_to_interpretation_id == interpretation.id
        ),
        None,
    ) or next(
        (
            m.target_id
            for m in ctx.matches_for(interpretation.id, "assertion")
            if m.same and m.target_id in deny_ids
        ),
        None,
    )
    checks.append(_rule("R7", denied_by is None, value=denied_by))

    # R8 — sure enough, for this kind of claim.
    kind_threshold = limits.threshold_for(interpretation.kind)
    checks.append(
        _rule(
            "R8",
            confidence.value >= kind_threshold,
            value=confidence.value,
            limit=kind_threshold,
        )
    )

    # R9 — dismissed means "not now", and now has a length.
    cooldown = interpretation.cooldown_until
    cooldown_passed = cooldown is None or _aware(cooldown) <= _aware(ctx.now)
    checks.append(
        _rule(
            "R9",
            cooldown_passed,
            value=_aware(cooldown).isoformat() if cooldown else None,
            limit=_aware(ctx.now).isoformat(),
        )
    )

    # R10 — the daily budget, and never more than a few cards waiting at once.
    budget_left = max(0, ctx.policy.max_recognitions_per_day - ctx.cards_created_today)
    room_left = ctx.open_card_count < limits.max_open_recognitions
    checks.append(
        _rule(
            "R10",
            budget_left > 0 and room_left,
            value={"budget_left": budget_left, "open": ctx.open_card_count},
            limit={
                "per_day": ctx.policy.max_recognitions_per_day,
                "max_open": limits.max_open_recognitions,
            },
        )
    )

    first_failure = next((c for c in checks if not c.passed), None)
    return ThresholdResult(
        outcome=first_failure.outcome if first_failure else "recognize",
        reason=first_failure.reason if first_failure else None,
        rules=tuple(checks),
        confidence=confidence.value,
        interpretation_id=interpretation.id,
        policy_version=limits.version,
        timezone_used=timezone,
    )


def _created_key(interpretation: InterpretationIn) -> tuple[datetime, str]:
    created = interpretation.created_at
    return (
        _aware(created) if created else datetime.max.replace(tzinfo=UTC),
        interpretation.id,
    )


def candidate_order(
    items: Sequence[tuple[InterpretationIn, ConfidenceResult]],
) -> list[tuple[InterpretationIn, ConfidenceResult]]:
    """Who gets the day's budget first: most confident, least dismissed, oldest."""
    return sorted(
        items,
        key=lambda pair: (-pair[1].value, pair[0].dismiss_count, _created_key(pair[0])),
    )


def evaluate_batch(
    items: Sequence[tuple[InterpretationIn, ConfidenceResult]],
    ctx: EngineContext,
    *,
    thresholds: Thresholds | None = None,
) -> list[ThresholdResult]:
    """Evaluate a whole run, spending the daily budget as it goes.

    Returned in evaluation order, not input order, because that order is itself
    the decision when the budget runs out.
    """
    config = thresholds or load_thresholds()
    created_today = ctx.cards_created_today
    open_count = ctx.open_card_count
    results: list[ThresholdResult] = []
    for interpretation, confidence in candidate_order(items):
        run_ctx = replace(ctx, cards_created_today=created_today, open_card_count=open_count)
        result = evaluate(interpretation, confidence, run_ctx, thresholds=config)
        if result.recognized:
            created_today += 1
            open_count += 1
        results.append(result)
    return results
