"""Wire shapes for the Recognition surface (plan.md §7 → Recogn., §8).

These are the only Recognition shapes the frontend ever sees. They are
deliberately flat and plain: the card, the words behind it, and who said what.

Two rules shaped this file:

* nothing here takes a user id — the session decides whose rows are read;
* the confidence number never travels alone. ``ConfidenceView`` always carries
  the sentence a person can read, because "0.73" on its own is not an
  explanation (plan.md §8, outcome 6).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FeedbackAction = Literal["accept", "correct", "reject", "dismiss"]
ReasonCode = Literal["not_true", "partly_true", "outdated", "too_personal", "not_useful"]
EvidenceRole = Literal["supports", "contradicts", "context"]

#: Tabs on /app/recognitions, plus the two the UI does not show as tabs.
CardTab = Literal["new", "accepted", "corrected", "rejected", "dismissed", "withdrawn", "all"]


class ConfidenceView(BaseModel):
    """How sure KnoRI is, and the same thing said in words."""

    value: float
    label: str
    plain: str
    supports: int = 0
    contradicts: int = 0
    distinct_days: int = 0
    span_hours: float = 0.0
    deleted_sources: int = 0


class EvidenceItem(BaseModel):
    """One provenance row: the user's own words, and how to get back to them."""

    id: uuid.UUID
    kind: str = "signal"
    role: EvidenceRole = "supports"
    weight: float = 1.0
    quote: str
    quote_start: int | None = None
    quote_end: int | None = None
    scrubbed: bool = False
    message_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    conversation_title: str | None = None
    seq: int | None = None
    said_at: datetime | None = None
    #: /app/chat/{conversation_id}?m={seq}&hl={start}-{end}, or null once deleted.
    deep_link: str | None = None
    note: str | None = None


class EvidenceGroups(BaseModel):
    """Contradicting evidence keeps its own group; it is never mixed in."""

    supports: list[EvidenceItem] = Field(default_factory=list)
    contradicts: list[EvidenceItem] = Field(default_factory=list)
    context: list[EvidenceItem] = Field(default_factory=list)


class InterpretationView(BaseModel):
    """The engine's current reading behind the card ("Technical details")."""

    # Field for field the same as the `interpretations` row, so it is read off
    # the row directly rather than copied by hand.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    topic: str
    statement: str
    lifecycle_status: str
    gate_outcome: str | None = None
    gate_reason: str | None = None
    version: int = 1
    confidence: float = 0.0
    confidence_version: str = "conf-v1"
    source: str = "model"
    last_evaluated_at: datetime | None = None


class FeedbackView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: FeedbackAction
    reason_code: ReasonCode | None = None
    correction_text: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class CorrectionEffectView(BaseModel):
    """What one piece of feedback changed — the "what changed" panel."""

    feedback_id: uuid.UUID
    status: Literal["pending", "ready"] = "pending"
    plain: str = ""
    summary: str = ""
    effects: list[dict[str, Any]] = Field(default_factory=list)
    recognitions_withdrawn: list[str] = Field(default_factory=list)
    recognitions_created: list[str] = Field(default_factory=list)
    assertions_created: list[str] = Field(default_factory=list)
    profile_before_text: str | None = None
    profile_after_text: str | None = None
    created_at: datetime | None = None
    ready_at: datetime | None = None


class RecognitionCard(BaseModel):
    """What a tab shows. Enough to render the card without a second request."""

    id: uuid.UUID
    interpretation_id: uuid.UUID
    interpretation_version: int = 1
    kind: str
    title: str
    body: str
    confidence: ConfidenceView
    state: str
    created_at: datetime
    presented_at: datetime | None = None
    resolved_at: datetime | None = None
    supersedes_id: uuid.UUID | None = None
    feedback_action: FeedbackAction | None = None
    correction_effect_status: Literal["pending", "ready"] | None = None


class RecognitionDetail(RecognitionCard):
    """The full card, with the words behind it."""

    explanation: str = ""
    evidence: EvidenceGroups = Field(default_factory=EvidenceGroups)
    interpretation: InterpretationView | None = None
    feedback: FeedbackView | None = None
    correction_effect: CorrectionEffectView | None = None
    withdrawn_reason: str | None = None


class CardPage(BaseModel):
    tab: str = "new"
    items: list[RecognitionCard] = Field(default_factory=list)
    next_cursor: str | None = None


class RecognitionSummary(BaseModel):
    """Counts for the nav badge and the tab headers."""

    new: int = 0
    accepted: int = 0
    corrected: int = 0
    rejected: int = 0
    dismissed: int = 0
    withdrawn: int = 0
    total: int = 0
    #: Cards written but never shown — what the badge counts.
    unseen: int = 0


class HistoryEntry(BaseModel):
    id: uuid.UUID
    event: str
    label: str
    at: datetime
    actor: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)


class HistoryView(BaseModel):
    recognition_id: uuid.UUID
    entries: list[HistoryEntry] = Field(default_factory=list)


class SeenResponse(BaseModel):
    id: uuid.UUID
    state: str
    presented_at: datetime | None = None


class FeedbackRequest(BaseModel):
    action: FeedbackAction
    correction_text: str | None = Field(default=None, max_length=2000)
    reason_code: ReasonCode | None = None


class FeedbackAccepted(BaseModel):
    """202: the card already moved; the durable effects are still being worked out."""

    feedback_id: uuid.UUID
    recognition_id: uuid.UUID
    state: str
    effect_status: Literal["pending", "ready"] = "pending"
    effect_url: str
    job_id: uuid.UUID | None = None


class RunResponse(BaseModel):
    job_id: uuid.UUID | None = None
    status: str = "queued"
    next_allowed_at: datetime | None = None


class JobView(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    attempts: int = 0
    max_attempts: int = 5
    created_at: datetime
    run_at: datetime | None = None
    finished_at: datetime | None = None
    #: True once the job will not be retried again. The error text stays in the logs.
    failed: bool = False


__all__ = [
    "CardPage",
    "CardTab",
    "ConfidenceView",
    "CorrectionEffectView",
    "EvidenceGroups",
    "EvidenceItem",
    "EvidenceRole",
    "FeedbackAccepted",
    "FeedbackAction",
    "FeedbackRequest",
    "FeedbackView",
    "HistoryEntry",
    "HistoryView",
    "InterpretationView",
    "JobView",
    "ReasonCode",
    "RecognitionCard",
    "RecognitionDetail",
    "RecognitionSummary",
    "RunResponse",
    "SeenResponse",
]
