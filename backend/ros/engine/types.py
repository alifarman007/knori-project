"""The plain values the Recognition rules work on, and the constants they use.

Everything here is a frozen dataclass. The engine takes data in and returns data
out, so ``conf-v1`` and ``thr-v1`` can be table-tested without a database, a
network or a model — CLAUDE.md engine rule 3.

Ids are ``str``, not ``uuid.UUID``: the rules never parse them. "Now" arrives on
:class:`EngineContext` rather than being read here, because ``ros`` must not
import ``knori.core.clock`` — the caller reads the clock once, so one pipeline
run sees one consistent time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

GateOutcome = Literal["recognize", "hold", "suppress", "decline", "merge"]
EvidenceRole = Literal["supports", "contradicts", "context"]
# "hidden" never reaches the database: a card below the label cutoff is not
# created at all, so `recognitions.confidence_label` only ever sees the other two.
ConfidenceLabel = Literal["hidden", "likely", "strong"]
ClaimBand = Literal["same", "different", "needs_judge"]

#: What a rule recorded. Kept JSON-shaped: it lands in `threshold_evaluations.rules`.
RuleValue = float | int | str | bool | None | Mapping[str, float | int | str | bool | None]

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "thresholds.yaml"


# --- rows the rules read -------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignalIn:
    """One observation taken from one user message (the `signals` row)."""

    id: str
    subject: str = "self"
    topic: str = ""
    strength: float = 0.6
    polarity: int = 0
    sensitive_category: str | None = None
    observed_at: datetime | None = None
    message_id: str | None = None
    quote_text: str = ""
    quote_start: int = 0
    quote_end: int = 0

    @property
    def eligible_support(self) -> bool:
        """Whether this signal may ever back a Recognition (CLAUDE.md rule 8)."""
        return self.subject == "self" and not self.sensitive_category


@dataclass(frozen=True, slots=True)
class EvidenceIn:
    """A signal attached to an interpretation (the `evidence` row).

    ``removed_at`` means a correction withdrew the link: kept for history, never
    counted.
    """

    signal: SignalIn
    role: EvidenceRole = "supports"
    weight: float = 1.0
    id: str | None = None
    note: str | None = None
    removed_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.removed_at is None

    @property
    def w(self) -> float:
        """``signal.strength x evidence.weight`` — the w(e) of plan §4.4."""
        return float(self.signal.strength) * float(self.weight)


@dataclass(frozen=True, slots=True)
class InterpretationIn:
    """A candidate claim about the user (the `interpretations` row)."""

    id: str
    kind: str = "pattern"
    topic: str = ""
    statement: str = ""
    source: str = "model"
    model_confidence: float = 0.0
    version: int = 1
    lifecycle_status: str = "candidate"
    cooldown_until: datetime | None = None
    dismiss_count: int = 0
    sensitive_category: str | None = None
    evidence: tuple[EvidenceIn, ...] = ()
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, tuple):
            object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def open(self) -> bool:
        return self.lifecycle_status in ("candidate", "recognized")

    def active_evidence(self, role: EvidenceRole | None = None) -> tuple[EvidenceIn, ...]:
        return tuple(e for e in self.evidence if e.active and (role is None or e.role == role))

    def support_signal_ids(self) -> frozenset[str]:
        return frozenset(e.signal.id for e in self.active_evidence("supports"))


@dataclass(frozen=True, slots=True)
class AssertionIn:
    """A correction the user made, kept as a claim (the `user_assertions` row)."""

    id: str
    kind: str = "deny"  # affirm | deny | amend | scope
    statement: str = ""
    topic: str | None = None
    applies_to_interpretation_id: str | None = None
    weight: float = 1.0
    status: str = "active"
    created_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True, slots=True)
class ClaimMatchIn:
    """An already-decided "is this the same claim?" (the `claim_matches` row).

    The threshold reads ``same`` as a boolean and never calls a model.
    """

    interpretation_id: str
    target_kind: str  # assertion | memory_item | interpretation
    target_id: str
    same: bool = False
    cosine: float = 0.0
    decided_by: str = "cosine"  # cosine | judge


@dataclass(frozen=True, slots=True)
class UserPolicy:
    """The settings a user controls that the engine must obey."""

    recognition_enabled: bool = True
    max_recognitions_per_day: int = 2
    timezone: str = "UTC"


@dataclass(frozen=True, slots=True)
class EngineContext:
    """Everything outside the interpretation that a decision depends on."""

    now: datetime
    policy: UserPolicy = UserPolicy()
    open_card_count: int = 0
    cards_created_today: int = 0
    #: (interpretation_id, version) pairs that already have a non-withdrawn card.
    has_card_for_version: frozenset[tuple[str, int]] = frozenset()
    claim_matches: tuple[ClaimMatchIn, ...] = ()
    assertions: tuple[AssertionIn, ...] = ()
    #: Memory items still active. A match against a retracted item must not block.
    active_memory_ids: frozenset[str] = frozenset()

    def has_card(self, interpretation_id: str, version: int) -> bool:
        return (interpretation_id, version) in self.has_card_for_version

    def matches_for(self, interp_id: str, kind: str | None = None) -> tuple[ClaimMatchIn, ...]:
        return tuple(
            m
            for m in self.claim_matches
            if m.interpretation_id == interp_id and kind in (None, m.target_kind)
        )

    def active_assertions(self, kind: str | None = None) -> tuple[AssertionIn, ...]:
        return tuple(a for a in self.assertions if a.active and (kind is None or a.kind == kind))


# --- what the rules return -----------------------------------------------


@dataclass(frozen=True, slots=True)
class SupportTimeline:
    """When the supporting evidence happened — the raw material for R3."""

    count: int = 0
    signal_ids: tuple[str, ...] = ()
    message_ids: tuple[str, ...] = ()
    days: tuple[str, ...] = ()
    earliest: datetime | None = None
    latest: datetime | None = None
    weight_sum: float = 0.0

    @property
    def distinct_days(self) -> int:
        return len(self.days)

    @property
    def distinct_messages(self) -> int:
        return len(self.message_ids)

    @property
    def span_hours(self) -> float:
        if self.earliest is None or self.latest is None:
            return 0.0
        return (self.latest - self.earliest).total_seconds() / 3600.0


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    """What ``conf-v1`` decided, plus the arithmetic that got there."""

    value: float
    label: ConfidenceLabel
    breakdown: dict[str, Any] = field(default_factory=dict)
    version: str = "conf-v1"

    @property
    def consistency(self) -> float:
        return float(self.breakdown.get("consistency", 1.0))

    @property
    def shown(self) -> bool:
        return self.label != "hidden"


@dataclass(frozen=True, slots=True)
class RuleCheck:
    """One rule, evaluated. Serialised into `threshold_evaluations.rules`."""

    rule: str
    passed: bool
    value: RuleValue = None
    limit: RuleValue = None
    #: What happens if this rule is the first to fail.
    outcome: GateOutcome = "hold"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "value": dict(self.value) if isinstance(self.value, Mapping) else self.value,
            "limit": dict(self.limit) if isinstance(self.limit, Mapping) else self.limit,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ThresholdResult:
    """What ``thr-v1`` decided about one interpretation."""

    outcome: GateOutcome
    reason: str | None
    rules: tuple[RuleCheck, ...]
    confidence: float
    interpretation_id: str = ""
    policy_version: str = "thr-v1"
    timezone_used: str = "UTC"

    @property
    def recognized(self) -> bool:
        return self.outcome == "recognize"

    @property
    def failing_rules(self) -> tuple[str, ...]:
        return tuple(r.rule for r in self.rules if not r.passed)

    def rules_json(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.rules]

    def ledger_key(self) -> tuple[str, tuple[str, ...]]:
        """Outcome + failing rules.

        A new `threshold_evaluations` row is written only when this changes;
        otherwise just `last_evaluated_at` moves (CLAUDE.md engine rule 4).
        """
        return (self.outcome, self.failing_rules)


# --- config/thresholds.yaml ----------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfidenceConstants:
    version: str
    evidence_tau: float
    spread: Mapping[int, float]
    affirm_adjustment: float
    scope_adjustment: float
    user_correction_floor: float
    hidden_below: float
    strong_at: float

    def spread_for(self, distinct_days: int) -> float:
        if distinct_days <= 0:
            return 0.0
        top = max(self.spread)
        return self.spread[min(distinct_days, top)]


@dataclass(frozen=True, slots=True)
class ThresholdConstants:
    version: str
    min_supports: int
    min_distinct_days: int
    min_span_hours: float
    min_model_confidence: float
    min_consistency: float
    kind_thresholds: Mapping[str, float]
    max_open_recognitions: int
    default_max_per_day: int
    cooldown_days_first: int
    cooldown_days_repeat: int

    def threshold_for(self, kind: str) -> float:
        """Unknown kinds get the strictest cutoff rather than a free pass."""
        return self.kind_thresholds.get(kind, max(self.kind_thresholds.values()))


@dataclass(frozen=True, slots=True)
class SensitiveConstants:
    categories: tuple[str, ...]
    deny_patterns: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ValidationConstants:
    actions: tuple[str, ...]
    kinds: tuple[str, ...]
    roles: tuple[str, ...]
    support_subjects: tuple[str, ...]
    min_statement_chars: int
    max_statement_chars: int
    first_second_person: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProvenanceConstants:
    min_supporting_rows: int
    verbatim_min_chars: int


@dataclass(frozen=True, slots=True)
class SimilarityCutoffs:
    dedup: float
    deny_same: float
    deny_different: float
    memory: float
    retrieval: float
    cascade: float


@dataclass(frozen=True, slots=True)
class Thresholds:
    version: str
    confidence: ConfidenceConstants
    threshold: ThresholdConstants
    sensitive: SensitiveConstants
    validation: ValidationConstants
    provenance: ProvenanceConstants
    similarity: Mapping[str, SimilarityCutoffs]
    default_embedding_model: str

    def cutoffs(self, embedding_model: str | None = None) -> SimilarityCutoffs:
        name = embedding_model or self.default_embedding_model
        try:
            return self.similarity[name]
        except KeyError as exc:  # a model with no calibrated cutoffs must not guess
            raise KeyError(
                f"no similarity cutoffs for embedding model {name!r}; "
                "add a block to config/thresholds.yaml and re-run the calibration pairs"
            ) from exc


def _floats(raw: Mapping[str, Any]) -> dict[str, float]:
    return {str(k): float(v) for k, v in raw.items()}


def _strs(raw: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in raw or ())


def _confidence(raw: Mapping[str, Any]) -> ConfidenceConstants:
    return ConfidenceConstants(
        version=str(raw["version"]),
        evidence_tau=float(raw["evidence_tau"]),
        spread={int(k): float(v) for k, v in raw["spread"].items()},
        affirm_adjustment=float(raw["assertion_adjustment"]["affirm"]),
        scope_adjustment=float(raw["assertion_adjustment"]["scope"]),
        user_correction_floor=float(raw["user_correction_floor"]),
        hidden_below=float(raw["labels"]["hidden_below"]),
        strong_at=float(raw["labels"]["strong_at"]),
    )


def _threshold(raw: Mapping[str, Any]) -> ThresholdConstants:
    return ThresholdConstants(
        version=str(raw["version"]),
        min_supports=int(raw["min_supports"]),
        min_distinct_days=int(raw["min_distinct_days"]),
        min_span_hours=float(raw["min_span_hours"]),
        min_model_confidence=float(raw["min_model_confidence"]),
        min_consistency=float(raw["min_consistency"]),
        kind_thresholds=_floats(raw["kind_thresholds"]),
        max_open_recognitions=int(raw["max_open_recognitions"]),
        default_max_per_day=int(raw["default_max_per_day"]),
        cooldown_days_first=int(raw["cooldown_days"]["first_dismiss"]),
        cooldown_days_repeat=int(raw["cooldown_days"]["repeat_dismiss"]),
    )


def _validation(raw: Mapping[str, Any]) -> ValidationConstants:
    lists = {k: _strs(raw[k]) for k in ("actions", "kinds", "roles", "support_subjects")}
    return ValidationConstants(
        min_statement_chars=int(raw["min_statement_chars"]),
        max_statement_chars=int(raw["max_statement_chars"]),
        first_second_person=_strs(raw["first_second_person"]),
        **lists,
    )


@lru_cache(maxsize=4)
def load_thresholds(path: str | None = None) -> Thresholds:
    """Read `config/thresholds.yaml`. Cached: the file does not change at runtime."""
    raw = yaml.safe_load((Path(path) if path else CONFIG_PATH).read_text(encoding="utf-8"))
    sensitive = raw["sensitive"]
    return Thresholds(
        version=str(raw["version"]),
        confidence=_confidence(raw["confidence"]),
        threshold=_threshold(raw["threshold"]),
        sensitive=SensitiveConstants(
            categories=_strs(sensitive["categories"]),
            deny_patterns={str(k): _strs(v) for k, v in sensitive["deny_patterns"].items()},
        ),
        validation=_validation(raw["validation"]),
        provenance=ProvenanceConstants(**{k: int(v) for k, v in raw["provenance"].items()}),
        similarity={
            str(model): SimilarityCutoffs(**_floats(cuts))
            for model, cuts in raw["similarity"].items()
        },
        default_embedding_model=str(raw["default_embedding_model"]),
    )
