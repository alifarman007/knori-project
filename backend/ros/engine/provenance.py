"""The receipt attached to a card: which words, from which message, when.

``recognition_provenance`` is a frozen copy of the evidence at the moment the
card was written. It is what the user opens when they ask "why does it think
that?", and what the deep link
``/app/chat/{conversation_id}?m={seq}&hl={start}-{end}`` highlights.

Two invariants are enforced here rather than trusted to the prompt:

* **at least two supporting rows.** A card with one quote behind it is not a
  Recognition, and R3 already refused to make one — this is the check that the
  refusal survived composition (plan §4.1);
* **the card text paraphrases.** Body and explanation must not repeat a quote
  word for word, or deleting the message would leave the user's sentence sitting
  in the card (CLAUDE.md engine rule 12).

Violations are returned, not raised. The caller decides whether to re-compose,
fall back, or fail the job — this module only reports what it found.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from ros.engine.quotes import normalize_for_match
from ros.engine.types import EvidenceIn, SignalIn, Thresholds, load_thresholds
from ros.schemas.llm_io import RecognitionDraft

PROVENANCE_RULES: dict[str, str] = {
    "P1": "insufficient_supports",
    "P2": "verbatim_quote",
    "P3": "unknown_message",
    "P4": "unknown_cited_ref",
    "P5": "missing_quote",
}


@dataclass(frozen=True, slots=True)
class MessageMeta:
    """Where a quote sits in the conversation, for the snapshot and the deep link."""

    message_id: str
    conversation_id: str | None = None
    conversation_title: str | None = None
    seq: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceRow:
    """One `recognition_provenance` row, ready to insert."""

    kind: str
    signal_id: str | None
    message_id: str | None
    conversation_id: str | None
    conversation_title: str | None
    seq: int | None
    quote_text: str
    quote_start: int | None
    quote_end: int | None
    message_created_at: datetime | None
    role: str
    weight: float
    display_order: int
    note: str | None = None
    feedback_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceViolation:
    rule: str
    reason: str
    detail: str = ""
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class ProvenanceResult:
    rows: tuple[ProvenanceRow, ...]
    violations: tuple[ProvenanceViolation, ...] = ()
    #: True when the model cited refs we could not use and all supports were kept instead.
    cited_fallback: bool = False

    @property
    def ok(self) -> bool:
        return not any(v.blocking for v in self.violations)

    @property
    def supports(self) -> tuple[ProvenanceRow, ...]:
        return tuple(r for r in self.rows if r.role == "supports")


def _violation(rule: str, detail: str = "", *, blocking: bool = True) -> ProvenanceViolation:
    return ProvenanceViolation(
        rule=rule, reason=PROVENANCE_RULES[rule], detail=detail, blocking=blocking
    )


def contains_quote_verbatim(text: str, quote: str, min_chars: int) -> bool:
    """Whether ``text`` repeats ``quote`` word for word.

    Compared in the same normalised form the quote locator uses, so swapping a
    curly apostrophe for a straight one is not a way around the rule. Very short
    quotes are skipped: a common phrase can recur honestly.
    """
    normalized_quote = normalize_for_match(quote)
    if len(normalized_quote) < min_chars:
        return False
    return normalized_quote.lower() in normalize_for_match(text).lower()


def _order_key(item: EvidenceIn) -> tuple[float, str, str]:
    observed = item.signal.observed_at
    return (-item.weight, observed.isoformat() if observed else "", item.signal.id)


def build_provenance(
    recognition_draft: RecognitionDraft,
    evidence: Sequence[EvidenceIn],
    signals: Mapping[str, SignalIn],
    messages_meta: Mapping[str, MessageMeta],
    *,
    thresholds: Thresholds | None = None,
) -> ProvenanceResult:
    """Turn the composed draft and its evidence into provenance rows.

    ``signals`` maps the short refs the model was given ("S7") to the real
    signals, which is how ``cited_signal_refs`` is resolved. A citation that is
    not a subset of the supporting evidence is discarded in favour of all the
    supports, ordered by weight — the model chooses the words, never the facts.
    """
    constants = (thresholds or load_thresholds()).provenance
    violations: list[ProvenanceViolation] = []

    supports = [
        e for e in evidence if e.active and e.role == "supports" and e.signal.eligible_support
    ]
    support_ids = {e.signal.id for e in supports}

    cited_ids: set[str] = set()
    for ref in recognition_draft.cited_signal_refs or ():
        signal = signals.get(ref)
        if signal is None:
            violations.append(_violation("P4", ref, blocking=False))
            continue
        cited_ids.add(signal.id)

    cited_fallback = not cited_ids or not cited_ids <= support_ids
    if cited_fallback and cited_ids:
        violations.append(
            _violation("P4", "cited refs are not supporting evidence", blocking=False)
        )
    chosen = supports if cited_fallback else [e for e in supports if e.signal.id in cited_ids]

    rows: list[ProvenanceRow] = []
    for item in sorted(chosen, key=_order_key):
        signal = item.signal
        if not signal.quote_text:
            violations.append(_violation("P5", signal.id, blocking=False))
            continue
        meta = messages_meta.get(signal.message_id or "")
        if meta is None:
            violations.append(_violation("P3", signal.message_id or signal.id, blocking=False))
        rows.append(
            ProvenanceRow(
                kind="signal",
                signal_id=signal.id,
                message_id=signal.message_id,
                conversation_id=meta.conversation_id if meta else None,
                conversation_title=meta.conversation_title if meta else None,
                seq=meta.seq if meta else None,
                quote_text=signal.quote_text,
                quote_start=signal.quote_start,
                quote_end=signal.quote_end,
                message_created_at=meta.created_at if meta else signal.observed_at,
                role="supports",
                weight=float(item.weight),
                display_order=len(rows),
                note=item.note,
            )
        )

    if len(rows) < constants.min_supporting_rows:
        violations.append(
            _violation("P1", f"{len(rows)} of {constants.min_supporting_rows} supporting rows")
        )

    for field_name, text in (
        ("title", recognition_draft.title),
        ("body", recognition_draft.body),
        ("explanation", recognition_draft.explanation),
    ):
        for row in rows:
            if contains_quote_verbatim(text or "", row.quote_text, constants.verbatim_min_chars):
                violations.append(_violation("P2", f"{field_name} repeats signal {row.signal_id}"))

    return ProvenanceResult(
        rows=tuple(rows), violations=tuple(violations), cited_fallback=cited_fallback
    )
