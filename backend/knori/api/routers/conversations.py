"""Conversations and chat (plan.md §7 → Convers., §8 → /app/chat).

No route takes a user id: the session decides whose rows these are, and another
user's conversation is **404, not 403**, so the API never confirms that it exists.

Two routes are unusual and both are deliberate:

* ``POST /{id}/messages`` answers with ``text/event-stream`` rather than JSON,
  because a reply arrives a word at a time. The generation itself is detached
  (``knori.services.chat``) and finishes even if the browser goes away.
* ``DELETE`` on a message or a conversation does more than delete: it scrubs the
  quotes those messages left inside Recognition provenance, in the same
  transaction, and then asks the engine to re-score. plan §4.7 — deleting a
  message has to really remove the words, not just hide the row.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.deps import DbSession, UserSettingsDep, VerifiedUser, rate_limit
from knori.api.schemas.chat import (
    ConversationEventOut,
    ConversationListOut,
    ConversationOut,
    CreateConversationIn,
    MessageOut,
    MessagesPageOut,
    NewConversationOut,
    SendMessageIn,
    UpdateConversationIn,
    WelcomeBackOut,
)
from knori.core.clock import now
from knori.core.errors import Conflict, NotFound
from knori.core.logging import get_logger
from knori.db.models import Conversation
from knori.jobs import queue
from knori.jobs.handlers.chat import write_opener
from knori.services import chat as chat_service
from knori.services import summaries
from knori.services.feedback import reasoning_lock_key
from ros.persistence import repositories

log = get_logger("knori.api.conversations")

router = APIRouter(prefix="/conversations", tags=["conversations"])

#: Caddy gets `flush_interval -1` (plan §9); these cover anything else in front.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
#: How long ``POST /conversations`` will wait for an opener before giving up on it.
OPENER_TIMEOUT_SECONDS = 8.0
DEFAULT_MESSAGE_PAGE = 50


def _view(row: Any) -> ConversationOut:
    return ConversationOut(
        id=row.id,
        kind=row.kind,
        title=row.title,
        is_incognito=row.is_incognito,
        message_count=row.message_count,
        last_seq=row.last_seq,
        last_message_at=row.last_message_at,
        archived_at=row.archived_at,
        created_at=row.created_at,
        has_summary=bool(row.summary),
    )


# --------------------------------------------------------------- the thread list


@router.get("", response_model=ConversationListOut, summary="Your conversations")
async def list_conversations(
    user: VerifiedUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    include_archived: Annotated[bool, Query()] = False,
) -> ConversationListOut:
    rows = await repositories.list_conversations(
        session, user.id, limit=limit, include_archived=include_archived
    )
    last = rows[-1] if len(rows) == limit else None
    return ConversationListOut(
        conversations=[_view(row) for row in rows],
        next_before=(last.last_message_at or last.created_at) if last else None,
    )


@router.post(
    "",
    response_model=NewConversationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
)
async def create_conversation(
    user: VerifiedUser,
    session: DbSession,
    payload: CreateConversationIn,
) -> NewConversationOut:
    """Create the thread, and — for someone coming back — its opening line."""
    welcome = await summaries.welcome_back(session, user.id, since=None)
    conversation = Conversation(
        user_id=user.id,
        kind="chat",
        title=payload.title,
        is_incognito=payload.is_incognito,
    )
    session.add(conversation)
    await session.flush()

    opener = await _opener(session, user, conversation)
    await session.commit()
    await session.refresh(conversation)
    return NewConversationOut(
        conversation=_view(conversation),
        opener=opener,
        welcome_back=WelcomeBackOut(
            days_since_last_visit=welcome.days_since_last_visit,
            last_conversation_id=welcome.last_conversation_id,
            memories_added=welcome.memories_added,
            new_recognitions=welcome.new_recognitions,
            show=welcome.show,
        ),
    )


async def _opener(session: AsyncSession, user: Any, conversation: Conversation) -> str | None:
    """Best effort. A slow or failing model leaves a blank thread, never an error."""
    if conversation.is_incognito:
        return None
    try:
        async with asyncio.timeout(OPENER_TIMEOUT_SECONDS):
            return await write_opener(
                session, user, conversation.id, router=chat_service.get_chat_router()
            )
    except Exception as exc:  # a missing opener is a blank thread, not a failed request
        log.warning("chat.opener_failed", error=str(exc))
        return None


@router.get("/{conversation_id}", response_model=ConversationOut, summary="One conversation")
async def get_conversation(
    user: VerifiedUser, session: DbSession, conversation_id: uuid.UUID
) -> ConversationOut:
    row = await repositories.get_conversation(session, user.id, conversation_id)
    if row is None:
        raise NotFound("That conversation does not exist.")
    return _view(row)


@router.patch("/{conversation_id}", response_model=ConversationOut, summary="Rename or archive")
async def update_conversation(
    user: VerifiedUser,
    session: DbSession,
    conversation_id: uuid.UUID,
    payload: UpdateConversationIn,
) -> ConversationOut:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise NotFound("That conversation does not exist.")
    if payload.title is not None:
        conversation.title = payload.title
    if payload.archived is not None:
        conversation.archived_at = now() if payload.archived else None
    await session.commit()
    return _view(conversation)


@router.delete(
    "/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a conversation"
)
async def delete_conversation(
    user: VerifiedUser, session: DbSession, conversation_id: uuid.UUID
) -> Response:
    conversation = await repositories.get_conversation(session, user.id, conversation_id)
    if conversation is None:
        raise NotFound("That conversation does not exist.")
    ids = await _message_ids(session, user.id, conversation_id)
    touched = await _memory_items_for(session, user.id, ids)
    await _scrub_provenance(session, user.id, ids)
    await session.execute(
        text("DELETE FROM conversations WHERE id = :id AND user_id = :user_id"),
        {"id": conversation_id, "user_id": user.id},
    )
    await _after_deletion(session, user.id, touched, deleted=len(ids))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------------- messages


@router.get(
    "/{conversation_id}/messages", response_model=MessagesPageOut, summary="A page of a thread"
)
async def list_messages(
    user: VerifiedUser,
    session: DbSession,
    conversation_id: uuid.UUID,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
    around_seq: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_MESSAGE_PAGE,
) -> MessagesPageOut:
    """Messages plus the card placements that belong between them."""
    if await repositories.get_conversation(session, user.id, conversation_id) is None:
        raise NotFound("That conversation does not exist.")
    rows = await repositories.list_messages(
        session,
        user.id,
        conversation_id,
        before_seq=before_seq,
        around_seq=around_seq,
        limit=limit,
    )
    events = await repositories.list_conversation_events(
        session,
        user.id,
        conversation_id,
        after_seq=rows[0].seq if rows else None,
        before_seq=rows[-1].seq if rows else None,
    )
    has_more = bool(rows) and rows[0].seq > 1
    return MessagesPageOut(
        messages=[MessageOut.model_validate(row) for row in rows],
        events=[ConversationEventOut.model_validate(event) for event in events],
        has_more=has_more,
        next_before_seq=rows[0].seq if has_more else None,
    )


@router.post(
    "/{conversation_id}/messages",
    summary="Send a message and stream the reply",
    response_class=StreamingResponse,
)
async def send_message(
    user: VerifiedUser,
    session: DbSession,
    settings: UserSettingsDep,
    conversation_id: uuid.UUID,
    payload: SendMessageIn,
    # Declared after `user` on purpose: the per-user bucket needs the session
    # resolved first, and FastAPI solves dependencies in parameter order.
    _limited: Annotated[None, Depends(rate_limit("messages", per_user=True))],
) -> StreamingResponse:
    conversation = await chat_service.lock_conversation(session, user.id, conversation_id)
    await chat_service.guard_not_streaming(session, user.id, conversation_id)

    message = await _existing_turn(session, user.id, conversation_id, payload.client_message_id)
    if message is None:
        message = await chat_service.record_user_message(
            session,
            conversation,
            content=payload.content,
            client_message_id=payload.client_message_id,
            settings=settings,
        )
    await session.commit()

    return StreamingResponse(
        chat_service.start_turn(user, conversation_id, message),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _existing_turn(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_message_id: str | None,
) -> Any:
    """A retry of the same turn reuses the row instead of saying it twice.

    The browser keeps ``client_message_id`` across a dropped stream, so this is
    how "retry" stops being "send again".
    """
    if not client_message_id:
        return None
    row = (
        await session.execute(
            text(
                "SELECT id, seq, client_message_id FROM messages "
                "WHERE user_id = :user_id AND conversation_id = :conversation_id "
                "AND client_message_id = :client_id AND role = 'user'"
            ),
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "client_id": client_message_id,
            },
        )
    ).first()
    if row is None:
        return None
    answered = await session.scalar(
        text(
            "SELECT 1 FROM messages WHERE conversation_id = :conversation_id "
            "AND role = 'assistant' AND seq > :seq AND status = 'complete' LIMIT 1"
        ),
        {"conversation_id": conversation_id, "seq": row.seq},
    )
    if answered:
        raise Conflict("KnoRI already answered that message.", code="already_answered")
    return row


@router.delete(
    "/{conversation_id}/messages/{seq}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one message",
)
async def delete_message(
    user: VerifiedUser, session: DbSession, conversation_id: uuid.UUID, seq: int
) -> Response:
    message = await repositories.get_message_by_seq(session, user.id, conversation_id, seq)
    if message is None:
        raise NotFound("That message does not exist.")
    touched = await _memory_items_for(session, user.id, [message.id])
    await _scrub_provenance(session, user.id, [message.id])
    await session.execute(
        text("DELETE FROM messages WHERE id = :id AND user_id = :user_id"),
        {"id": message.id, "user_id": user.id},
    )
    await _after_deletion(session, user.id, touched, deleted=1)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- plan §4.7


async def _message_ids(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[uuid.UUID]:
    rows = (
        await session.execute(
            text(
                "SELECT id FROM messages "
                "WHERE conversation_id = :conversation_id AND user_id = :user_id"
            ),
            {"conversation_id": conversation_id, "user_id": user_id},
        )
    ).all()
    return [row.id for row in rows]


async def _scrub_provenance(
    session: AsyncSession, user_id: uuid.UUID, message_ids: list[uuid.UUID]
) -> None:
    """Remove the user's words from everything that quoted them, before the delete.

    The provenance *rows* stay — a card must still be able to say it had two
    pieces of evidence — but the quote becomes ``[deleted by you]`` and the
    offsets go, in the same transaction as the delete. ``ON DELETE SET NULL``
    would leave the text behind, which is exactly what the user asked to remove.
    """
    if not message_ids:
        return
    await session.execute(
        text(
            "UPDATE recognition_provenance SET quote_text = '[deleted by you]', "
            "quote_start = NULL, quote_end = NULL, scrubbed_at = :now "
            "WHERE message_id = ANY(:ids) AND recognition_id IN "
            "(SELECT id FROM recognitions WHERE user_id = :user_id)"
        ),
        {"ids": message_ids, "now": now(), "user_id": user_id},
    )
    await session.execute(
        text(
            "UPDATE threshold_evaluations SET candidate_text = NULL "
            "WHERE user_id = :user_id AND interpretation_id IN ("
            "  SELECT DISTINCT e.interpretation_id FROM evidence e "
            "  JOIN signals s ON s.id = e.signal_id WHERE s.message_id = ANY(:ids))"
        ),
        {"ids": message_ids, "user_id": user_id},
    )


async def _memory_items_for(
    session: AsyncSession, user_id: uuid.UUID, message_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Memories these messages are a source of — collected *before* the cascade."""
    if not message_ids:
        return []
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ms.memory_item_id AS id FROM memory_sources ms "
                "JOIN memory_items mi ON mi.id = ms.memory_item_id "
                "WHERE mi.user_id = :user_id AND ms.message_id = ANY(:ids)"
            ),
            {"user_id": user_id, "ids": message_ids},
        )
    ).all()
    return [row.id for row in rows]


async def _after_deletion(
    session: AsyncSession,
    user_id: uuid.UUID,
    memory_item_ids: list[uuid.UUID],
    *,
    deleted: int,
) -> None:
    """Retract memories that lost their last source, then ask for a re-score.

    Only rows the user did not write themselves: an edited or pinned memory is
    theirs and stays, even when the message it came from is gone.

    The engine owns what happens next — re-scoring, withdrawing cards that no
    longer have two supporting quotes, recompiling the profile. This only says
    that something changed.
    """
    if not deleted:
        return
    if memory_item_ids:
        await session.execute(
            text(
                "UPDATE memory_items SET status = 'retracted', "
                "retracted_reason = 'source_deleted', updated_at = :now "
                "WHERE user_id = :user_id AND id = ANY(:ids) AND status = 'active' "
                "AND source NOT IN ('user_added', 'user_edited') AND pinned = FALSE "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM memory_sources ms WHERE ms.memory_item_id = memory_items.id)"
            ),
            {"user_id": user_id, "ids": memory_item_ids, "now": now()},
        )
    await queue.enqueue(
        session,
        "rescore_user",
        {"reason": "source_deleted"},
        lane="slow",
        user_id=user_id,
        priority=6,
        dedupe_key=queue.dedupe_key_for("rescore_user", user_id, "source_deleted"),
        lock_key=reasoning_lock_key(user_id),
    )


__all__ = ["router"]
