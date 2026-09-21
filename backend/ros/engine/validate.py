"""Code validation of what the interpreter returned (plan §4.3, Call 2).

The model proposes claims; this module decides which of them are even allowed to
exist. Two habits matter here:

* **one item at a time.** A bad proposal is rejected on its own. A batch is never
  thrown away, because one hallucinated signal ref should not cost the user the
  four good claims that came with it;
* **every rejection has a rule id.** They are written to the ledger and shown in
  ``/admin/decisions``, so "the model said something odd" is never the
  explanation for a missing card.

The most important rule is V1: only a ``subject='self'`` signal with no sensitive
category may be ``supports`` evidence. The prompt asks for that too, but asking
is not enforcing (CLAUDE.md engine rule 8).

``signals_by_ref`` and ``interpretations_by_ref`` are built by the caller from
*what it sent in this request*, for *this user*. That is what makes "the ref
exists, belongs to the user and was in the input" a single lookup here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from ros.engine.types import (
    EvidenceRole,
    InterpretationIn,
    SignalIn,
    Thresholds,
    UserPolicy,
    ValidationConstants,
    load_thresholds,
)
from ros.schemas.llm_io import InterpretationBatch, Proposal

#: rule id -> reason code. Stable: these ids appear in the decisions ledger.
VALIDATION_RULES: dict[str, str] = {
    "V0": "unknown_action",
    "V1": "supports_not_eligible",
    "V2": "unknown_signal_ref",
    "V3": "duplicate_evidence",
    "V4": "unknown_role",
    "V5": "no_supporting_evidence",
    "V6": "no_evidence",
    "V7": "missing_target_ref",
    "V8": "unknown_interpretation_ref",
    "V9": "target_denied",
    "V10": "target_accepted",
    "V11": "not_third_person",
    "V12": "invalid_statement",
    "V13": "unknown_kind",
    "V14": "unknown_topic",
    "V15": "unknown_sensitive_category",
}

DECLINE_REASONS: frozenset[str] = frozenset(
    {
        "single_occurrence",
        "ambiguous",
        "contradicted",
        "user_denied",
        "sensitive",
        "trivial",
        "already_known",
        "not_self",
    }
)

_WORD = re.compile(r"[a-z']+")


@dataclass(frozen=True, slots=True)
class Rejection:
    """Why one proposal, or one piece of its evidence, was not accepted."""

    rule: str
    reason: str
    index: int
    ref: str | None = None
    detail: str = ""
    scope: str = "proposal"  # proposal | evidence


@dataclass(frozen=True, slots=True)
class AcceptedEvidence:
    signal_ref: str
    signal_id: str
    role: EvidenceRole
    weight: float
    note: str = ""


@dataclass(frozen=True, slots=True)
class AcceptedProposal:
    """A proposal that survived validation, with its refs resolved to real ids."""

    index: int
    action: str
    ref: str | None
    target_id: str | None
    kind: str
    topic: str
    statement: str
    rationale: str
    evidence: tuple[AcceptedEvidence, ...]
    model_confidence: float
    sensitive_category: str | None = None
    #: Evidence items dropped from an otherwise good proposal, with their rule.
    dropped: tuple[Rejection, ...] = ()

    @property
    def supports(self) -> tuple[AcceptedEvidence, ...]:
        return tuple(e for e in self.evidence if e.role == "supports")


@dataclass(frozen=True, slots=True)
class DeclinedItem:
    """Something the model chose not to claim. Also a decision, also recorded."""

    about: str
    reason: str
    signal_refs: tuple[str, ...] = ()
    rule: str = "M0_model_declined"


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    """The user state that decides what a proposal is allowed to touch."""

    denied_interpretation_ids: frozenset[str] = frozenset()
    accepted_interpretation_ids: frozenset[str] = frozenset()
    #: Empty means "any topic"; otherwise the taxonomy the prompt supplied.
    allowed_topics: frozenset[str] = frozenset()
    user: UserPolicy = field(default_factory=UserPolicy)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _reject(
    rule: str, index: int, ref: str | None = None, detail: str = "", scope: str = "proposal"
) -> Rejection:
    return Rejection(
        rule=rule, reason=VALIDATION_RULES[rule], index=index, ref=ref, detail=detail, scope=scope
    )


def _drop(rule: str, index: int, ref: str | None = None, detail: str = "") -> Rejection:
    """A rejection that costs one piece of evidence, not the whole proposal."""
    return _reject(rule, index, ref, detail, scope="evidence")


def topic_required(proposal: Proposal) -> bool:
    """A topic is only meaningful on rows that create or rewrite a claim."""
    return proposal.action in ("create", "revise")


def is_third_person(statement: str, constants: ValidationConstants) -> bool:
    """An interpretation is a claim about the user, not a sentence spoken to them."""
    words = set(_WORD.findall(statement.lower()))
    return not words & set(constants.first_second_person)


def _validate_evidence(
    proposal: Proposal,
    index: int,
    signals_by_ref: Mapping[str, SignalIn],
    constants: ValidationConstants,
) -> tuple[list[AcceptedEvidence], list[Rejection]]:
    kept: list[AcceptedEvidence] = []
    dropped: list[Rejection] = []
    seen: set[str] = set()
    for item in proposal.evidence:
        ref = item.signal_ref
        signal = signals_by_ref.get(ref)
        if signal is None:
            dropped.append(_drop("V2", index, ref, "not in the input for this user"))
            continue
        if ref in seen:
            dropped.append(_drop("V3", index, ref))
            continue
        if item.role not in constants.roles:
            dropped.append(_drop("V4", index, ref, f"role={item.role!r}"))
            continue
        if item.role == "supports" and not signal.eligible_support:
            why = "sensitive" if signal.sensitive_category else f"subject={signal.subject}"
            dropped.append(_drop("V1", index, ref, why))
            continue
        seen.add(ref)
        kept.append(
            AcceptedEvidence(
                signal_ref=ref,
                signal_id=signal.id,
                role=item.role,  # type: ignore[arg-type]
                weight=_clamp(item.weight),
                note=(item.note or "").strip(),
            )
        )
    return kept, dropped


def _check_target(
    proposal: Proposal,
    index: int,
    interpretations_by_ref: Mapping[str, InterpretationIn],
    policy: ValidationPolicy,
) -> tuple[InterpretationIn | None, Rejection | None]:
    if proposal.action == "create":
        return None, None
    ref = proposal.ref
    if not ref:
        return None, _reject("V7", index, None, f"action={proposal.action}")
    target = interpretations_by_ref.get(ref)
    if target is None:
        return None, _reject("V8", index, ref)
    if proposal.action in ("attach", "revise") and target.id in policy.denied_interpretation_ids:
        return None, _reject("V9", index, ref)
    if proposal.action in ("revise", "retire") and target.id in policy.accepted_interpretation_ids:
        return None, _reject("V10", index, ref, "the user accepted this claim")
    return target, None


def _check_statement(
    proposal: Proposal, index: int, constants: ValidationConstants
) -> Rejection | None:
    if proposal.action not in ("create", "revise"):
        return None
    statement = (proposal.statement or "").strip()
    if not (constants.min_statement_chars <= len(statement) <= constants.max_statement_chars):
        return _reject("V12", index, proposal.ref, f"{len(statement)} chars")
    if not is_third_person(statement, constants):
        return _reject("V11", index, proposal.ref, statement[:80])
    return None


def validate_proposals(
    batch: InterpretationBatch,
    signals_by_ref: Mapping[str, SignalIn],
    interpretations_by_ref: Mapping[str, InterpretationIn],
    policy: ValidationPolicy,
    *,
    thresholds: Thresholds | None = None,
) -> tuple[list[AcceptedProposal], list[Rejection]]:
    """Split a model batch into what may be written and what may not."""
    config = thresholds or load_thresholds()
    constants = config.validation
    categories = set(config.sensitive.categories)
    accepted: list[AcceptedProposal] = []
    rejections: list[Rejection] = []

    for index, proposal in enumerate(batch.proposals):
        if proposal.action not in constants.actions:
            rejections.append(_reject("V0", index, proposal.ref, f"action={proposal.action!r}"))
            continue
        if proposal.kind not in constants.kinds:
            rejections.append(_reject("V13", index, proposal.ref, f"kind={proposal.kind!r}"))
            continue

        statement_problem = _check_statement(proposal, index, constants)
        if statement_problem is not None:
            rejections.append(statement_problem)
            continue

        topic = (proposal.topic or "").strip()
        if (
            topic_required(proposal)
            and policy.allowed_topics
            and topic not in policy.allowed_topics
        ):
            rejections.append(_reject("V14", index, proposal.ref, f"topic={topic!r}"))
            continue

        sensitive = proposal.sensitive_category
        if sensitive is not None and sensitive not in categories:
            rejections.append(_reject("V15", index, proposal.ref, f"category={sensitive!r}"))
            continue

        target, target_problem = _check_target(proposal, index, interpretations_by_ref, policy)
        if target_problem is not None:
            rejections.append(target_problem)
            continue

        evidence, dropped = _validate_evidence(proposal, index, signals_by_ref, constants)
        supports = [e for e in evidence if e.role == "supports"]
        if proposal.action == "create" and not supports:
            rejections.append(_reject("V5", index, proposal.ref))
            rejections.extend(dropped)
            continue
        if proposal.action == "attach" and not evidence:
            rejections.append(_reject("V6", index, proposal.ref))
            rejections.extend(dropped)
            continue

        accepted.append(
            AcceptedProposal(
                index=index,
                action=proposal.action,
                ref=proposal.ref,
                target_id=target.id if target else None,
                kind=proposal.kind,
                topic=topic,
                statement=(proposal.statement or "").strip(),
                rationale=(proposal.rationale or "").strip(),
                evidence=tuple(evidence),
                model_confidence=_clamp(proposal.model_confidence),
                sensitive_category=sensitive,
                dropped=tuple(dropped),
            )
        )
        rejections.extend(dropped)

    return accepted, rejections


def validate_declined(batch: InterpretationBatch) -> list[DeclinedItem]:
    """Normalise the model's own refusals so each one can be written to the ledger.

    An unrecognised reason becomes ``ambiguous`` rather than being dropped: the
    decision not to say something is still a decision worth recording.
    """
    return [
        DeclinedItem(
            about=(item.about or "").strip(),
            reason=item.reason if item.reason in DECLINE_REASONS else "ambiguous",
            signal_refs=tuple(item.signal_refs or ()),
        )
        for item in batch.declined
    ]
