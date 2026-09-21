"""The Recognition engine: the code that decides, and nothing else.

Everything exported here is pure. No database, no network, no model call, no
import of ``knori``. Data goes in as frozen dataclasses and decisions come out
as frozen dataclasses, which is what lets every rule in plan.md §4 be a row in a
test table.

The order the pipeline uses them in:

    quotes      locate the user's exact words, or drop the signal
    validate    decide which model proposals are allowed to exist at all  (V*)
    claims      "same claim?" by cosine, or hand the pair to the judge
    dedup       collapse two readings of one thing into the older row
    confidence  conf-v1: how sure, and why                               (§4.4)
    threshold   thr-v1: recognize, hold, suppress or decline             (R0-R10)
    provenance  the receipt: which quotes, in which order, paraphrased

``ros.engine.pipeline`` owns the sequence; the job handlers only call it.
"""

from __future__ import annotations

from ros.engine.claims import ClaimCandidate, compare, cosine, split_by_band
from ros.engine.confidence import label_for, score, support_timeline
from ros.engine.dedup import MergePlan, plan_merges
from ros.engine.provenance import (
    MessageMeta,
    ProvenanceResult,
    ProvenanceRow,
    ProvenanceViolation,
    build_provenance,
)
from ros.engine.quotes import QuoteMatch, locate_quote, locate_quote_detail, verify_quote
from ros.engine.threshold import RULE_OUTCOMES, candidate_order, evaluate, evaluate_batch
from ros.engine.types import (
    AssertionIn,
    ClaimMatchIn,
    ConfidenceResult,
    EngineContext,
    EvidenceIn,
    InterpretationIn,
    RuleCheck,
    SignalIn,
    SupportTimeline,
    ThresholdResult,
    Thresholds,
    UserPolicy,
    load_thresholds,
)
from ros.engine.validate import (
    VALIDATION_RULES,
    AcceptedEvidence,
    AcceptedProposal,
    DeclinedItem,
    Rejection,
    ValidationPolicy,
    validate_declined,
    validate_proposals,
)

__all__ = [
    "RULE_OUTCOMES",
    "VALIDATION_RULES",
    "AcceptedEvidence",
    "AcceptedProposal",
    "AssertionIn",
    "ClaimCandidate",
    "ClaimMatchIn",
    "ConfidenceResult",
    "DeclinedItem",
    "EngineContext",
    "EvidenceIn",
    "InterpretationIn",
    "MergePlan",
    "MessageMeta",
    "ProvenanceResult",
    "ProvenanceRow",
    "ProvenanceViolation",
    "QuoteMatch",
    "Rejection",
    "RuleCheck",
    "SignalIn",
    "SupportTimeline",
    "ThresholdResult",
    "Thresholds",
    "UserPolicy",
    "ValidationPolicy",
    "build_provenance",
    "candidate_order",
    "compare",
    "cosine",
    "evaluate",
    "evaluate_batch",
    "label_for",
    "load_thresholds",
    "locate_quote",
    "locate_quote_detail",
    "plan_merges",
    "score",
    "split_by_band",
    "support_timeline",
    "validate_declined",
    "validate_proposals",
    "verify_quote",
]
