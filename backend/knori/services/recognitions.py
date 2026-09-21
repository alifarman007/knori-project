"""Turning Recognition rows into something a person can read.

Everything here is presentation, and almost all of it is pure — the only
database call is :func:`load_card`, the ownership check that both the read
routes and the feedback service start from. Two decisions run through the file:

* **The snapshot is the truth on screen.** A card shows the provenance rows
  frozen at composition time (plan.md §4.1), not a fresh walk of the evidence
  graph. If the user deleted a message the row stays, the quote reads
  ``[deleted by you]``, and the card must not quietly re-acquire the text.
* **The number never travels without the sentence.** :func:`plain_confidence`
  turns a breakdown into one honest line ("Based on 3 things you said across 2
  days; nothing you said pointed the other way."), and every payload carrying a
  confidence carries that line with it.

No LLM call happens here, and nothing here writes.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.schemas.recognitions import (
    ConfidenceView,
    CorrectionEffectView,
    EvidenceGroups,
    EvidenceItem,
    FeedbackView,
    HistoryEntry,
    InterpretationView,
    JobView,
    RecognitionCard,
    RecognitionDetail,
)
from knori.core.errors import BadRequest, NotFound
from knori.db.models import Job, User
from ros.engine.confidence import local_day
from ros.persistence.models import (
    CorrectionEffect,
    Interpretation,
    Recognition,
    RecognitionEvent,
    RecognitionFeedback,
    RecognitionProvenance,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

#: Tab name → the states behind it. "New" is everything not yet answered.
TAB_STATES: dict[str, tuple[str, ...]] = {
    "new": ("pending", "presented"),
    "accepted": ("accepted",),
    "corrected": ("corrected",),
    "rejected": ("rejected",),
    "dismissed": ("dismissed",),
    "withdrawn": ("withdrawn",),
    "all": ("pending", "presented", "accepted", "corrected", "rejected", "dismissed"),
}

#: recognition_events.event → what it means in plain words.
EVENT_LABELS: dict[str, str] = {
    "proposed": "KnoRI saw something that might be a pattern.",
    "evidence_added": "Something you said was added as evidence.",
    "rescored": "KnoRI worked out again how sure it is.",
    "gate": "KnoRI decided whether to show this.",
    "created": "KnoRI wrote this card.",
    "presented": "You were shown this card.",
    "accepted": "You said this is right.",
    "corrected": "You corrected this.",
    "rejected": "You said this is not true.",
    "dismissed": "You put this aside for now.",
    "withdrawn": "KnoRI took this card back.",
    "revised": "KnoRI revised its understanding.",
    "merged": "This was merged with another reading of the same evidence.",
}

EFFECT_PLAIN: dict[str, str] = {
    "pending": "KnoRI is working out what this changes.",
    "ready": "Here is what changed.",
}


# ----------------------------------------------------------------- plain words


@dataclass(frozen=True, slots=True)
class ConfidenceBreakdown:
    """The few numbers a person actually needs in order to judge a card.

    Built either from the frozen provenance rows (what the card can prove) or
    from ``interpretations.confidence_breakdown`` (what ``conf-v1`` computed).
    Both say the same thing until something is deleted.
    """

    supports: int = 0
    distinct_days: int = 0
    contradicts: int = 0
    span_hours: float = 0.0
    deleted_sources: int = 0
    user_authored: bool = False
    value: float = 0.0
    label: str = "likely"


def _things(count: int) -> str:
    return f"{count} thing you said" if count == 1 else f"{count} things you said"


def plain_confidence(breakdown: ConfidenceBreakdown) -> str:
    """One honest sentence about where a Recognition came from.

    Honest means it says what is missing too: evidence the user deleted, and
    anything that pointed the other way. It never says "high confidence" — a
    person cannot check that, but they can check "3 things you said".
    """
    if breakdown.supports <= 0:
        if breakdown.user_authored:
            return "Based on a correction you made, not on anything KnoRI worked out on its own."
        return "The messages behind this are gone, so there is nothing left to show."

    said = _things(breakdown.supports)
    if breakdown.user_authored:
        said = f"your own correction and {said}"

    if breakdown.distinct_days > 1:
        when = f" across {breakdown.distinct_days} days"
    elif breakdown.distinct_days == 1:
        when = " on one day"
    else:
        when = ""

    deleted = ""
    if breakdown.deleted_sources == 1:
        deleted = ", one of which you have since deleted"
    elif breakdown.deleted_sources > 1:
        deleted = f", {breakdown.deleted_sources} of which you have since deleted"

    against = (
        "nothing you said pointed the other way"
        if breakdown.contradicts <= 0
        else f"{_things(breakdown.contradicts)} pointed the other way"
    )
    return f"Based on {said}{when}{deleted}; {against}."


def breakdown_from_provenance(
    rows: Iterable[RecognitionProvenance],
    *,
    timezone: str,
    value: float = 0.0,
    label: str = "likely",
) -> ConfidenceBreakdown:
    """What the card itself can prove, counted from its frozen rows."""
    supports = [row for row in rows if row.role == "supports"]
    moments = [row.message_created_at for row in supports if row.message_created_at is not None]
    # The engine's own day function, so "across 2 days" on the card and R3's
    # day count can never disagree about where a day ends.
    days = {local_day(moment, timezone) for moment in moments}
    span = (max(moments) - min(moments)).total_seconds() / 3600.0 if len(moments) > 1 else 0.0
    return ConfidenceBreakdown(
        supports=len(supports),
        distinct_days=len(days),
        contradicts=sum(1 for row in rows if row.role == "contradicts"),
        span_hours=round(span, 2),
        deleted_sources=sum(1 for row in supports if row.scrubbed_at is not None),
        user_authored=any(row.kind == "assertion" for row in supports),
        value=float(value),
        label=label,
    )


def breakdown_from_json(
    breakdown: Mapping[str, Any], *, value: float = 0.0, label: str = "likely"
) -> ConfidenceBreakdown:
    """The same view over what ``conf-v1`` stored (plan.md §4.4)."""
    return ConfidenceBreakdown(
        supports=int(breakdown.get("supports", 0) or 0),
        distinct_days=int(breakdown.get("distinct_days", 0) or 0),
        contradicts=int(breakdown.get("contradicts", 0) or 0),
        span_hours=float(breakdown.get("span_hours", 0.0) or 0.0),
        user_authored=bool(breakdown.get("user_correction_floor_applied", False)),
        value=float(value),
        label=label,
    )


def confidence_view(breakdown: ConfidenceBreakdown) -> ConfidenceView:
    return ConfidenceView(
        value=breakdown.value,
        label=breakdown.label,
        plain=plain_confidence(breakdown),
        supports=breakdown.supports,
        contradicts=breakdown.contradicts,
        distinct_days=breakdown.distinct_days,
        span_hours=breakdown.span_hours,
        deleted_sources=breakdown.deleted_sources,
    )


# -------------------------------------------------------------------- evidence


def deep_link_for(
    conversation_id: uuid.UUID | None,
    seq: int | None,
    quote_start: int | None,
    quote_end: int | None,
) -> str | None:
    """Back to the exact words in the thread (plan.md §4.1).

    ``None`` once the message is gone: a link to a deleted message is a worse
    answer than no link.
    """
    if conversation_id is None or seq is None:
        return None
    link = f"/app/chat/{conversation_id}?m={seq}"
    if quote_start is not None and quote_end is not None:
        link = f"{link}&hl={quote_start}-{quote_end}"
    return link


def evidence_item(row: RecognitionProvenance) -> EvidenceItem:
    scrubbed = row.scrubbed_at is not None
    return EvidenceItem(
        id=row.id,
        kind=row.kind,
        role=row.role,
        weight=float(row.weight),
        quote=row.quote_text,
        quote_start=row.quote_start,
        quote_end=row.quote_end,
        scrubbed=scrubbed,
        message_id=row.message_id,
        conversation_id=row.conversation_id,
        conversation_title=row.conversation_title,
        seq=row.seq,
        said_at=row.message_created_at,
        deep_link=(
            None
            if scrubbed
            else deep_link_for(row.conversation_id, row.seq, row.quote_start, row.quote_end)
        ),
        note=row.note,
    )


def group_evidence(rows: Iterable[RecognitionProvenance]) -> EvidenceGroups:
    """Supports, contradicts and context, each in its own list and never mixed."""
    groups = EvidenceGroups()
    buckets = {
        "supports": groups.supports,
        "contradicts": groups.contradicts,
        "context": groups.context,
    }
    # display_order is assigned by the composer; the id only breaks a tie.
    for row in sorted(rows, key=lambda r: (r.display_order, str(r.id))):
        bucket = buckets.get(row.role)
        if bucket is not None:
            bucket.append(evidence_item(row))
    return groups


# ----------------------------------------------------------------- the payloads


def card_row(
    recognition: Recognition,
    provenance: Sequence[RecognitionProvenance],
    *,
    timezone: str,
    feedback: RecognitionFeedback | None = None,
    effect_status: str | None = None,
) -> RecognitionCard:
    """One card as a tab shows it."""
    breakdown = breakdown_from_provenance(
        provenance,
        timezone=timezone,
        value=float(recognition.confidence),
        label=recognition.confidence_label,
    )
    return RecognitionCard(
        id=recognition.id,
        interpretation_id=recognition.interpretation_id,
        interpretation_version=recognition.interpretation_version,
        kind=recognition.kind,
        title=recognition.title,
        body=recognition.body,
        confidence=confidence_view(breakdown),
        state=recognition.state,
        created_at=recognition.created_at,
        presented_at=recognition.presented_at,
        resolved_at=recognition.resolved_at,
        supersedes_id=recognition.supersedes_id,
        feedback_action=feedback.action if feedback else None,
        correction_effect_status=effect_status,
    )


def card_payload(
    recognition: Recognition,
    provenance: Sequence[RecognitionProvenance],
    *,
    timezone: str,
    interpretation: Interpretation | None = None,
    feedback: RecognitionFeedback | None = None,
    effect: CorrectionEffect | None = None,
) -> RecognitionDetail:
    """The full card: body, explanation, the words behind it, and what changed."""
    base = card_row(
        recognition,
        provenance,
        timezone=timezone,
        feedback=feedback,
        effect_status=effect.status if effect else None,
    )
    return RecognitionDetail(
        **base.model_dump(),
        explanation=recognition.explanation,
        evidence=group_evidence(provenance),
        interpretation=(
            InterpretationView.model_validate(interpretation) if interpretation else None
        ),
        feedback=FeedbackView.model_validate(feedback) if feedback else None,
        correction_effect=effect_view(effect) if effect else None,
        withdrawn_reason=recognition.withdrawn_reason,
    )


def effect_view(row: CorrectionEffect) -> CorrectionEffectView:
    return CorrectionEffectView(
        feedback_id=row.feedback_id,
        status=row.status,
        plain=EFFECT_PLAIN.get(row.status, ""),
        summary=row.summary,
        effects=list(row.effects or []),
        recognitions_withdrawn=[str(v) for v in row.recognitions_withdrawn or []],
        recognitions_created=[str(v) for v in row.recognitions_created or []],
        assertions_created=[str(v) for v in row.assertions_created or []],
        profile_before_text=row.profile_before_text,
        profile_after_text=row.profile_after_text,
        created_at=row.created_at,
        ready_at=row.ready_at,
    )


def history_entry(row: RecognitionEvent) -> HistoryEntry:
    return HistoryEntry(
        id=row.id,
        event=row.event,
        label=EVENT_LABELS.get(row.event, row.event.replace("_", " ")),
        at=row.created_at,
        actor=row.actor,
        payload=dict(row.payload or {}),
    )


def job_view(row: Job) -> JobView:
    """The job's progress. The error text stays in the logs, not in the API."""
    return JobView(
        id=row.id,
        kind=row.kind,
        status=row.status,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        created_at=row.created_at,
        run_at=row.run_at,
        finished_at=row.finished_at,
        failed=row.status == "dead",
    )


# --------------------------------------------------------------- tabs, cursors


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        stamp, _, row_id = raw.partition("|")
        return datetime.fromisoformat(stamp), uuid.UUID(row_id)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise BadRequest("That page cursor is not valid.", code="bad_cursor") from None


def states_for_tab(tab: str) -> tuple[str, ...]:
    try:
        return TAB_STATES[tab]
    except KeyError:
        raise BadRequest(
            f"Unknown tab {tab!r}. Try one of: {', '.join(TAB_STATES)}.", code="bad_state"
        ) from None


# ------------------------------------------------------------------ ownership


async def load_card(session: AsyncSession, user: User, recognition_id: uuid.UUID) -> Recognition:
    """The card, or 404.

    The single gate every card route and the feedback service go through:
    another user's card is *not found*, never forbidden, so the API cannot be
    used to confirm that a card exists.
    """
    row = await session.scalar(
        select(Recognition).where(Recognition.id == recognition_id, Recognition.user_id == user.id)
    )
    if row is None:
        raise NotFound("That Recognition does not exist.")
    return row
