"""``GET /events`` — the live stream the app keeps open (plan.md §7 → Events).

A Recognition is written by the worker, minutes after the message that caused
it. Without this stream the card would only appear on the next page load, which
would make KnoRI feel like it had forgotten. The browser opens one
``EventSource`` here and keeps it for the session.

The stream carries only the event *names and ids* the UI needs; it re-fetches
the resource over the normal API, so nothing sensitive is duplicated into a
long-lived connection. Events are fanned out per user by
:class:`knori.core.events.EventBus`, which is fed by Postgres ``LISTEN``.

Cleanup matters more than it looks: every open stream holds a queue on the bus,
so the subscription is closed in a ``finally`` — the client going away is the
normal case, not an error.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from knori.api.deps import CurrentUser
from knori.core.events import Event, EventBus, get_event_bus
from knori.core.logging import get_logger

log = get_logger("knori.api.events")

router = APIRouter(tags=["events"])

#: Exactly the events the app knows how to act on. Anything else is dropped
#: here rather than sent to a browser that would ignore it.
FORWARDED: frozenset[str] = frozenset(
    {
        "recognition.created",
        "recognition.withdrawn",
        "correction.effect.ready",
        "correction.effect.updated",
        "profile.updated",
        "heartbeat",
    }
)

#: How long the browser waits before reconnecting after a dropped stream.
RETRY_MS = 3000

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Caddy gets `flush_interval -1` (plan.md §9); this covers an nginx in front.
    "X-Accel-Buffering": "no",
}


def frame(event: Event) -> str:
    """One SSE frame. ``event:`` is what ``addEventListener`` matches on."""
    return f"event: {event.type}\ndata: {event.to_json()}\n\n"


async def event_frames(bus: EventBus, user_id: uuid.UUID) -> AsyncIterator[str]:
    """This user's events as SSE frames, until the client goes away.

    The bus yields a ``heartbeat`` on its own after 25 s of silence, which keeps
    proxies from closing an idle stream.
    """
    # `subscribe` is an async generator; its declared return type hides
    # `aclose`, and closing it explicitly is what frees its queue on the bus.
    stream = cast(AsyncGenerator[Event, None], bus.subscribe(user_id))
    try:
        yield f"retry: {RETRY_MS}\n\n"
        yield ": connected\n\n"
        async for event in stream:
            if event.type in FORWARDED:
                yield frame(event)
    finally:
        # The client disconnecting cancels this generator; closing the
        # subscription is what releases its queue on the bus.
        with contextlib.suppress(Exception):
            await stream.aclose()


@router.get("/events", summary="Live updates for the signed-in user")
async def stream_events(user: CurrentUser) -> StreamingResponse:
    bus = get_event_bus()
    if not bus.connected:
        # Heartbeats still flow while the bus reconnects, so the stream is
        # useful; say so once instead of failing the request.
        log.info("sse.bus_reconnecting")
    return StreamingResponse(
        event_frames(bus, user.id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


__all__ = ["FORWARDED", "RETRY_MS", "event_frames", "frame", "router"]
