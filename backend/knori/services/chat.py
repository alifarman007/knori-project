"""One chat turn, from the user's key press to a saved assistant message.

The shape of a turn (plan §3.2, §5.4):

1. allocate ``seq`` under a row lock on the conversation;
2. insert the user message **and** enqueue ``extract_signals`` in one transaction,
   so a message can never exist without the job that reads it;
3. build the context (system A + B, append-only history with one cache breakpoint,
   a volatile retrieved block) and stream Opus 5;
4. persist the assistant row as ``streaming``, flushing partial text every ~20
   deltas or 2 seconds, and finalise it in a ``finally`` block.

**The generation runs in its own task with its own session.** If the browser
closes the connection mid-answer the model call keeps going and the reply is
still saved — a half-written row and a lost paragraph is the one failure a chat
product cannot have. The stream the client reads is a queue that task writes to.

A second reply for the same conversation is refused with 409 rather than queued:
two streams writing to one thread would interleave seq numbers.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.api.schemas.chat import MAX_MESSAGE_CHARS
from knori.core.clock import now
from knori.core.config import settings
from knori.core.errors import Conflict, NotFound
from knori.core.logging import get_logger
from knori.db.models import Conversation, Message, User, UserSettings
from knori.db.session import SessionLocal
from knori.jobs import queue
from knori.services.chat_context import load_context_inputs, spend_decision
from ros.llm import calls, spec
from ros.llm.base import CompletionResult, ProviderError, RefusalError, TruncatedError, Usage
from ros.llm.cost import record_call
from ros.llm.router import Router, build_router
from ros.llm.routing import Route
from ros.memory.context_builder import (
    BuiltContext,
    ContextLimits,
    build_chat_context,
    make_estimator,
)

log = get_logger("knori.chat")

CHAT_TASK = "chat.reply"
#: A streaming row older than this was abandoned by a crash or a redeploy.
ORPHAN_AFTER = timedelta(minutes=2)
FLUSH_EVERY_DELTAS = 20
FLUSH_EVERY_SECONDS = 2.0

SessionFactory = Callable[[], AsyncSession]

#: Conversations with a generation in flight *in this process*. The database row
#: only appears once the task starts, so two fast clicks need this as well.
_STREAMING: set[uuid.UUID] = set()
#: Strong references, or the event loop may collect a detached generation.
_TASKS: set[asyncio.Task[None]] = set()

_router: Router | None = None


def get_chat_router() -> Router:
    """One router per API process, built from the product's settings.

    Built here rather than taken from ``ros.llm.router.get_router`` so the ``.env``
    file is honoured: that module-level fallback reads the real environment only.
    """
    global _router
    if _router is None:
        _router = build_router(settings, clock=now)
    return _router


@dataclass(frozen=True, slots=True)
class ServerEvent:
    """One server-sent event. The wire format is fixed: name, JSON, blank line."""

    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def encode(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.data, default=str)}\n\n"


# --------------------------------------------------------------- writing the turn


async def lock_conversation(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    """The conversation row, locked. Every ``seq`` in the thread is handed out here."""
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .with_for_update()
    )
    if conversation is None:
        raise NotFound("That conversation does not exist.")
    return conversation


async def append_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    role: str,
    content: str,
    status: str = "complete",
    client_message_id: str | None = None,
    at: datetime | None = None,
) -> Message:
    """Add a message to a locked conversation and move its counters."""
    moment = at or now()
    conversation.last_seq += 1
    conversation.message_count += 1
    conversation.last_message_at = moment
    message = Message(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        seq=conversation.last_seq,
        role=role,
        content=content,
        status=status,
        client_message_id=client_message_id,
        created_at=moment,
    )
    session.add(message)
    await session.flush()
    return message


async def guard_not_streaming(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """409 while a reply is in flight. Stale rows are recovered, not respected."""
    if conversation_id in _STREAMING:
        raise Conflict("KnoRI is still replying.", code="reply_in_progress")
    live = await session.scalar(
        text(
            "SELECT 1 FROM messages WHERE conversation_id = :conversation_id "
            "AND user_id = :user_id AND status = 'streaming' AND created_at > :cutoff LIMIT 1"
        ),
        {"conversation_id": conversation_id, "user_id": user_id, "cutoff": now() - ORPHAN_AFTER},
    )
    if live:
        raise Conflict("KnoRI is still replying.", code="reply_in_progress")
    # Nothing live, but this thread may still hold an abandoned row from a crash.
    # Closing it here means a conversation heals itself the next time it is used,
    # whatever else called `recover_orphans`.
    await recover_orphans(session, conversation_id=conversation_id)


async def record_user_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    content: str,
    client_message_id: str | None,
    settings: UserSettings | None = None,
) -> Message:
    """The user's turn plus its extraction job, in the caller's transaction.

    Incognito conversations and a user with memory switched off are never
    extracted from — the message is stored, nothing is learned from it.
    """
    body = content.strip()[:MAX_MESSAGE_CHARS]
    message = await append_message(
        session, conversation, role="user", content=body, client_message_id=client_message_id
    )
    extractable = not conversation.is_incognito and (settings is None or settings.memory_enabled)
    if extractable:
        await queue.enqueue(
            session,
            "extract_signals",
            {"conversation_id": str(conversation.id)},
            lane="fast",
            user_id=conversation.user_id,
            run_at=now() + timedelta(seconds=30),
            dedupe_key=queue.dedupe_key_for("extract_signals", conversation.id),
        )
    return message


async def recover_orphans(
    session: AsyncSession,
    *,
    older_than: timedelta = ORPHAN_AFTER,
    conversation_id: uuid.UUID | None = None,
) -> int:
    """Close out replies abandoned by a crash: text kept as ``partial``, else ``failed``.

    Meant for API start-up (whole table) and, with ``conversation_id``, for the
    one thread about to be used. A row left ``streaming`` shows the person a reply
    that never finishes arriving.
    """
    scope = "" if conversation_id is None else " AND conversation_id = :conversation_id"
    params: dict[str, Any] = {"cutoff": now() - older_than}
    if conversation_id is not None:
        params["conversation_id"] = conversation_id
    result = await session.execute(
        text(
            "UPDATE messages SET status = CASE WHEN length(content) > 0 "
            "THEN 'partial' ELSE 'failed' END "
            f"WHERE status = 'streaming' AND created_at < :cutoff{scope}"
        ),
        params,
    )
    count = int(getattr(result, "rowcount", 0) or 0)
    if count:
        log.info("chat.orphans_recovered", count=count)
    return count


# ---------------------------------------------------------------- the generation


async def start_turn(
    user: User,
    conversation_id: uuid.UUID,
    user_message: Message,
    *,
    session_factory: SessionFactory = SessionLocal,
    router: Router | None = None,
) -> AsyncIterator[str]:
    """Stream one reply. The generation outlives this iterator by design."""
    events: asyncio.Queue[ServerEvent | None] = asyncio.Queue()
    _STREAMING.add(conversation_id)
    task = asyncio.create_task(
        _generate(
            user_id=user.id,
            conversation_id=conversation_id,
            content=user_message.content,
            message_id=user_message.id,
            events=events,
            session_factory=session_factory,
            router=router or get_chat_router(),
        ),
        name=f"chat-{conversation_id}",
    )
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)

    yield ServerEvent(
        "message.user",
        {
            "id": str(user_message.id),
            "seq": user_message.seq,
            "client_message_id": user_message.client_message_id,
        },
    ).encode()
    while True:
        event = await events.get()
        if event is None:
            return
        yield event.encode()


async def _generate(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    message_id: uuid.UUID,
    events: asyncio.Queue[ServerEvent | None],
    session_factory: SessionFactory,
    router: Router,
) -> None:
    """Runs detached: the reply is saved whether or not anyone is still reading."""
    try:
        async with session_factory() as session:
            await _generate_in_session(
                session=session,
                user_id=user_id,
                conversation_id=conversation_id,
                content=content,
                message_id=message_id,
                events=events,
                router=router,
            )
    except Exception as exc:  # the client is gone; the log is the only place left
        log.exception("chat.generation_failed", error=str(exc))
        with contextlib.suppress(asyncio.QueueFull):
            events.put_nowait(
                ServerEvent("error", {"code": "generation_failed", "detail": "Something broke."})
            )
    finally:
        _STREAMING.discard(conversation_id)
        await events.put(None)


async def _generate_in_session(
    *,
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    message_id: uuid.UUID,
    events: asyncio.Queue[ServerEvent | None],
    router: Router,
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        return
    conversation = await lock_conversation(session, user_id, conversation_id)

    spend = await spend_decision(session, router, user_id)
    if spend.blocked:
        events.put_nowait(
            ServerEvent(
                "error",
                {
                    "code": "daily_limit",
                    "detail": "You have reached today's limit. It resets tomorrow.",
                },
            )
        )
        await session.rollback()
        return

    limits = ContextLimits()
    route = replace(router.route(CHAT_TASK), stream=True)
    if spend.effort is not None:
        route = replace(route, effort=spend.effort)
    inputs = await load_context_inputs(
        session,
        user,
        conversation,
        content=content,
        router=router,
        limits=limits,
        model=route.model,
        message_id=message_id,
    )
    built = build_chat_context(inputs, limits=limits, registry=router.registry)

    assistant = await append_message(
        session, conversation, role="assistant", content="", status="streaming"
    )
    assistant.context_manifest = built.manifest
    await session.commit()

    await _stream_into(
        session=session,
        router=router,
        route=route,
        built=built,
        assistant_id=assistant.id,
        user_id=user_id,
        conversation_id=conversation_id,
        events=events,
    )


async def _stream_into(
    *,
    session: AsyncSession,
    router: Router,
    route: Route,
    built: BuiltContext,
    assistant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    events: asyncio.Queue[ServerEvent | None],
) -> None:
    request = calls.build_request(
        route, None, system=built.system_blocks, messages=built.messages, user_id=user_id
    )
    prompt_meta = built.manifest.get("prompt") or {}
    request.metadata[spec.PROMPT_NAME] = prompt_meta.get("name")
    request.metadata[spec.PROMPT_VERSION] = prompt_meta.get("version")
    request.metadata[spec.PROMPT_HASH] = prompt_meta.get("hash")

    parts: list[str] = []
    result: CompletionResult | None = None
    failure: str | None = None
    started = time.perf_counter()
    since_flush = 0
    flushed_at = time.monotonic()

    try:
        async for event in router.provider_for(route).stream(request):
            if event.kind == "text" and event.text:
                parts.append(event.text)
                since_flush += 1
                events.put_nowait(ServerEvent("delta", {"text": event.text}))
                if since_flush >= FLUSH_EVERY_DELTAS or (
                    time.monotonic() - flushed_at >= FLUSH_EVERY_SECONDS
                ):
                    await _flush(session, assistant_id, "".join(parts))
                    since_flush, flushed_at = 0, time.monotonic()
            elif event.kind == "thinking":
                events.put_nowait(ServerEvent("thinking", {"text": event.text}))
            elif event.kind == "done" and event.result is not None:
                result = event.result
    except ProviderError as exc:
        failure = _failure_code(exc)
        log.warning("chat.provider_error", code=failure, request_id=exc.request_id)
        events.put_nowait(ServerEvent("error", {"code": failure, "detail": str(exc)}))
        await _record(session, router, route, prompt_meta, None, user_id, started, exc)
    finally:
        text_out = "".join(parts)
        status = (
            "complete" if result is not None and text_out else ("partial" if text_out else "failed")
        )
        call_id = (
            await _record(session, router, route, prompt_meta, result, user_id, started, None)
            if result is not None
            else None
        )
        await _finalise(session, assistant_id, conversation_id, text_out, status, call_id, router)
        events.put_nowait(
            ServerEvent(
                "message.assistant",
                {
                    "id": str(assistant_id),
                    "seq": await _seq_of(session, assistant_id),
                    "status": status,
                    "content": text_out,
                    "usage": _usage_json(result),
                },
            )
        )


def _failure_code(exc: ProviderError) -> str:
    """What the browser is told. ``refused`` and ``truncated`` are not retried."""
    if isinstance(exc, RefusalError):
        return "refused"
    if isinstance(exc, TruncatedError):
        return "truncated"
    return "provider_error"


def _call_status(exc: ProviderError | None) -> str:
    """The ``llm_calls.status`` value, which has its own small vocabulary."""
    if exc is None:
        return "ok"
    code = _failure_code(exc)
    return code if code in ("refused", "truncated") else "error"


async def _flush(session: AsyncSession, assistant_id: uuid.UUID, body: str) -> None:
    """Partial text is written as it arrives: a reload mid-answer shows the answer."""
    await session.execute(
        text("UPDATE messages SET content = :content WHERE id = :id"),
        {"content": body, "id": assistant_id},
    )
    await session.commit()


async def _finalise(
    session: AsyncSession,
    assistant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: str,
    status: str,
    call_id: uuid.UUID | None,
    router: Router,
) -> None:
    estimate = make_estimator()
    await session.execute(
        text(
            "UPDATE messages SET content = :content, status = :status, "
            "token_estimate = :tokens, llm_call_id = :call_id WHERE id = :id"
        ),
        {
            "content": body,
            "status": status,
            "tokens": estimate(body),
            "call_id": call_id,
            "id": assistant_id,
        },
    )
    await session.execute(
        text("UPDATE conversations SET last_message_at = :now WHERE id = :id"),
        {"now": now(), "id": conversation_id},
    )
    await _maybe_enqueue_title(session, conversation_id)
    await session.commit()


async def _maybe_enqueue_title(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    row = (
        await session.execute(
            text("SELECT user_id, title, message_count FROM conversations WHERE id = :id"),
            {"id": conversation_id},
        )
    ).first()
    if row is None or row.title or row.message_count < 2:
        return
    await queue.enqueue(
        session,
        "generate_title",
        {"conversation_id": str(conversation_id)},
        lane="fast",
        user_id=row.user_id,
        priority=7,
        dedupe_key=queue.dedupe_key_for("generate_title", conversation_id),
    )


async def _record(
    session: AsyncSession,
    router: Router,
    route: Route,
    prompt_meta: dict[str, Any],
    result: CompletionResult | None,
    user_id: uuid.UUID,
    started: float,
    error: ProviderError | None,
) -> uuid.UUID | None:
    """One ``llm_calls`` row per attempt, priced by the model that answered."""
    usage = result.usage if result is not None else Usage()
    model = result.model if result is not None else route.model
    cost = router.pricing.price(model, usage, cache_ttl=route.cache_ttl)
    row = await record_call(
        session,
        task=route.task,
        provider=result.provider if result is not None else route.provider,
        model=model,
        status=_call_status(error),
        usage=usage,
        cost_usd=cost,
        cache_ttl=route.cache_ttl,
        prompt_name=prompt_meta.get("name"),
        prompt_version=prompt_meta.get("version"),
        prompt_hash=prompt_meta.get("hash"),
        effort=route.effort,
        latency_ms=int((time.perf_counter() - started) * 1000),
        stop_reason=result.stop_reason if result is not None else None,
        error=str(error)[:1000] if error is not None else None,
        request_id=(result.request_id if result is not None else None)
        or (error.request_id if error is not None else None),
        user_id=user_id,
        result={"chars": len(result.text) if result is not None else 0},
        occurred_at=now(),
        counts_as_chat_message=True,
        pricing=router.pricing,
    )
    return row.id


async def _seq_of(session: AsyncSession, message_id: uuid.UUID) -> int:
    value = await session.scalar(
        text("SELECT seq FROM messages WHERE id = :id"), {"id": message_id}
    )
    return int(value or 0)


def _usage_json(result: CompletionResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "cache_read_tokens": result.usage.cache_read_tokens,
        "cache_write_tokens": result.usage.cache_write_tokens,
        "model": result.model,
    }


__all__ = [
    "CHAT_TASK",
    "FLUSH_EVERY_DELTAS",
    "FLUSH_EVERY_SECONDS",
    "ORPHAN_AFTER",
    "ServerEvent",
    "append_message",
    "get_chat_router",
    "guard_not_streaming",
    "load_context_inputs",
    "lock_conversation",
    "record_user_message",
    "recover_orphans",
    "start_turn",
]
