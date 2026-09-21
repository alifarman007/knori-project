"""Conversation summaries, openers and the welcome-back strip.

A conversation "ends" after 30 minutes of silence; then it is summarised, so the
next one can pick up where it left off. A *running* conversation is only
summarised once its unsummarised tail passes 30 messages — rolling summaries are
expensive and, below that, the history still fits in the prompt (plan §5.1, §5.4).

Nothing here calls a model. It decides *whether* and prepares *what* to send; the
job handlers in ``knori.jobs.handlers.chat`` do the calling and the writing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.db.models import Conversation, Message
from ros.persistence.repositories import ConversationRow

#: A conversation with nothing new for this long is over.
IDLE_AFTER = timedelta(minutes=30)
#: Only roll a summary forward mid-conversation once the tail gets this long.
ROLLING_TAIL_MESSAGES = 30
#: Messages to send to the summariser in one go.
SUMMARY_WINDOW = 80
#: Below this, a conversation is not worth a summary — two lines and a goodbye.
MIN_MESSAGES_TO_SUMMARIZE = 4


@dataclass(frozen=True, slots=True)
class SummaryDecision:
    """Why a conversation is (or is not) being summarised. Logged, not guessed at."""

    should_run: bool
    reason: str
    unsummarised: int = 0

    def __bool__(self) -> bool:
        return self.should_run


def decide_summary(
    *,
    last_seq: int,
    summary_upto_seq: int,
    message_count: int,
    last_message_at: datetime | None,
    at: datetime,
    idle_after: timedelta = IDLE_AFTER,
    rolling_tail: int = ROLLING_TAIL_MESSAGES,
) -> SummaryDecision:
    """Pure. Idle conversations get summarised; busy ones only when the tail is long."""
    unsummarised = max(0, last_seq - summary_upto_seq)
    if unsummarised == 0:
        return SummaryDecision(False, "already_summarised")
    if message_count < MIN_MESSAGES_TO_SUMMARIZE:
        return SummaryDecision(False, "too_short", unsummarised)
    if unsummarised > rolling_tail:
        return SummaryDecision(True, "long_tail", unsummarised)
    if last_message_at is not None and at - last_message_at >= idle_after:
        return SummaryDecision(True, "idle", unsummarised)
    return SummaryDecision(False, "still_talking", unsummarised)


def decide_for(conversation: ConversationRow, *, at: datetime) -> SummaryDecision:
    return decide_summary(
        last_seq=conversation.last_seq,
        summary_upto_seq=conversation.summary_upto_seq,
        message_count=conversation.message_count,
        last_message_at=conversation.last_message_at,
        at=at,
    )


async def find_idle_conversations(
    session: AsyncSession,
    *,
    at: datetime | None = None,
    limit: int = 20,
) -> list[uuid.UUID]:
    """Conversations that have gone quiet and still have unsummarised messages.

    Incognito threads are skipped here as everywhere else: they leave no trace.
    """
    moment = at or now()
    rows = (
        await session.execute(
            text(
                "SELECT id FROM conversations "
                "WHERE is_incognito = FALSE AND archived_at IS NULL "
                "  AND last_message_at IS NOT NULL AND last_message_at < :cutoff "
                "  AND last_seq > summary_upto_seq "
                "  AND message_count >= :min_messages "
                "ORDER BY last_message_at ASC LIMIT :limit"
            ),
            {
                "cutoff": moment - IDLE_AFTER,
                "min_messages": MIN_MESSAGES_TO_SUMMARIZE,
                "limit": limit,
            },
        )
    ).all()
    return [row.id for row in rows]


async def messages_to_summarise(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    after_seq: int,
    limit: int = SUMMARY_WINDOW,
) -> list[dict[str, str]]:
    """The prompt's ``messages`` variable: role and text, oldest first."""
    stmt = (
        select(Message.role, Message.content)
        .where(
            Message.user_id == user_id,
            Message.conversation_id == conversation_id,
            Message.seq > after_seq,
            Message.status != "failed",
        )
        .order_by(Message.seq.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [{"role": row.role, "text": row.content} for row in rows]


async def apply_summary(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    summary: str,
    open_threads: list[str],
    upto_seq: int,
    at: datetime | None = None,
) -> bool:
    """Store the summary and move the boundary. Returns False for another user's row."""
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conversation is None:
        return False
    moment = at or now()
    conversation.summary = summary.strip()
    conversation.open_threads = [thread.strip() for thread in open_threads if thread.strip()][:5]
    conversation.summary_upto_seq = max(conversation.summary_upto_seq, upto_seq)
    conversation.summarised_at = moment
    conversation.ended_at = conversation.ended_at or conversation.last_message_at
    await session.flush()
    return True


# ------------------------------------------------------------------ welcome back


def days_between(earlier: datetime | None, later: datetime) -> int | None:
    """Whole days between two moments, floored at 0. None when there is no earlier."""
    if earlier is None:
        return None
    seconds = (later - earlier).total_seconds()
    return max(0, int(seconds // 86_400))


def days_away_phrase(days: int | None) -> str:
    """Plain words for the opener prompt — it must never invent a gap it was not told."""
    if days is None:
        return "for the first time"
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"about {max(2, days // 7)} weeks ago"
    return f"about {max(2, days // 30)} months ago"


@dataclass(frozen=True, slots=True)
class WelcomeBack:
    days_since_last_visit: int | None = None
    last_conversation_id: uuid.UUID | None = None
    memories_added: int = 0
    new_recognitions: int = 0

    @property
    def show(self) -> bool:
        """Only worth a strip after a real gap, or when something is waiting."""
        gap = self.days_since_last_visit or 0
        return gap >= 1 or self.new_recognitions > 0


async def welcome_back(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    since: datetime | None,
    at: datetime | None = None,
) -> WelcomeBack:
    """What changed while they were away. Counts only; the tabs hold the detail."""
    moment = at or now()
    last = await session.scalar(
        text(
            "SELECT max(last_message_at) FROM conversations "
            "WHERE user_id = :user_id AND is_incognito = FALSE"
        ),
        {"user_id": user_id},
    )
    previous = since or last
    days = days_between(previous, moment)
    if previous is None:
        return WelcomeBack()

    memories = await session.scalar(
        text(
            "SELECT count(*) FROM memory_items "
            "WHERE user_id = :user_id AND status = 'active' AND created_at >= :since"
        ),
        {"user_id": user_id, "since": previous},
    )
    recognitions = await session.scalar(
        text(
            "SELECT count(*) FROM recognitions "
            "WHERE user_id = :user_id AND state IN ('pending', 'presented') "
            "  AND created_at >= :since"
        ),
        {"user_id": user_id, "since": previous},
    )
    conversation_id = await session.scalar(
        text(
            "SELECT id FROM conversations "
            "WHERE user_id = :user_id AND is_incognito = FALSE AND archived_at IS NULL "
            "ORDER BY COALESCE(last_message_at, created_at) DESC LIMIT 1"
        ),
        {"user_id": user_id},
    )
    return WelcomeBack(
        days_since_last_visit=days,
        last_conversation_id=conversation_id,
        memories_added=int(memories or 0),
        new_recognitions=int(recognitions or 0),
    )


__all__ = [
    "IDLE_AFTER",
    "MIN_MESSAGES_TO_SUMMARIZE",
    "ROLLING_TAIL_MESSAGES",
    "SUMMARY_WINDOW",
    "SummaryDecision",
    "WelcomeBack",
    "apply_summary",
    "days_away_phrase",
    "days_between",
    "decide_for",
    "decide_summary",
    "find_idle_conversations",
    "messages_to_summarise",
    "welcome_back",
]
