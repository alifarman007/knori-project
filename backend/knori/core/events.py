"""Server-sent events, carried between processes by Postgres LISTEN/NOTIFY.

The worker finishes a Recognition and the browser must see the card without
reloading. Postgres is already the only stateful service (plan.md §1), so the
notification rides on it instead of a second broker.

Two halves:

* :func:`publish` runs ``pg_notify`` **inside the caller's transaction**, so a
  rolled-back write can never announce itself.
* :class:`EventBus` holds one dedicated LISTEN connection per API process and
  fans messages out to the open SSE streams of that user. If the connection
  drops, subscribers keep getting heartbeats while it reconnects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.core.config import settings
from knori.core.logging import get_logger

log = get_logger("knori.events")

CHANNEL = "user_events"
# Postgres refuses a NOTIFY payload over 8000 bytes; stay well clear of it.
MAX_PAYLOAD_BYTES = 7000
HEARTBEAT_SECONDS = 25.0
QUEUE_SIZE = 100

# Event names the frontend knows (plan.md §7 → Events).
EVENT_TYPES = (
    "recognition.created",
    "recognition.withdrawn",
    "recognition.updated",
    "correction.effect.ready",
    "correction.effect.updated",
    "profile.updated",
    "job.finished",
    "heartbeat",
)


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    at: str = ""

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "data": self.data, "at": self.at})


def _encode(user_id: uuid.UUID | str, event_type: str, data: dict[str, Any]) -> str:
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "type": event_type,
        "data": data,
        "at": now().isoformat(),
    }
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) <= MAX_PAYLOAD_BYTES:
        return encoded
    # Too big to carry: send the shape and let the client re-fetch the resource.
    payload["data"] = {k: v for k, v in data.items() if k.endswith("_id")}
    payload["truncated"] = True
    return json.dumps(payload, separators=(",", ":"), default=str)


async def publish(
    session: AsyncSession,
    user_id: uuid.UUID | str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Announce an event to that user's open streams, on commit of this transaction."""
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": _encode(user_id, event_type, data or {})},
    )


def _listen_dsn() -> str:
    """asyncpg wants a plain libpq URL, not SQLAlchemy's ``+asyncpg`` form."""
    return settings.sync_database_url()


class EventBus:
    """One LISTEN connection, many SSE subscribers."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        channel: str = CHANNEL,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        queue_size: int = QUEUE_SIZE,
    ) -> None:
        self._dsn = dsn
        self._channel = channel
        self._heartbeat = heartbeat_seconds
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._connected = False
        self._dropped = 0

    # -- lifecycle --------------------------------------------------------------

    async def start(self) -> None:
        """Start listening. Never raises if the database is unreachable."""
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._listen_forever(), name="event-bus")

    async def stop(self) -> None:
        self._stopping.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def subscriber_count(self) -> int:
        return sum(len(queues) for queues in self._subscribers.values())

    # -- fan-out ----------------------------------------------------------------

    def dispatch(self, event: Event) -> None:
        """Hand an event to every stream of that user. Slow readers lose the oldest."""
        if event.user_id is None:
            return
        for queue in tuple(self._subscribers.get(event.user_id, ())):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                self._dropped += 1
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    async def subscribe(self, user_id: uuid.UUID | str) -> AsyncIterator[Event]:
        """Yield that user's events, with a heartbeat so proxies keep the stream open."""
        key = str(user_id)
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(key, set()).add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self._heartbeat)
                except TimeoutError:
                    yield Event(type="heartbeat", user_id=key, at=now().isoformat())
                    continue
                yield event
        finally:
            queues = self._subscribers.get(key)
            if queues is not None:
                queues.discard(queue)
                if not queues:
                    self._subscribers.pop(key, None)

    # -- listener ---------------------------------------------------------------

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("event_payload_unreadable", bytes=len(payload))
            return
        if not isinstance(parsed, dict):
            return
        self.dispatch(
            Event(
                type=str(parsed.get("type", "")),
                data=parsed.get("data") or {},
                user_id=str(parsed["user_id"]) if parsed.get("user_id") else None,
                at=str(parsed.get("at", "")),
            )
        )

    async def _listen_forever(self) -> None:
        import asyncpg  # imported here so importing this module never needs a driver

        backoff = 1.0
        while not self._stopping.is_set():
            conn: Any = None
            try:
                conn = await asyncpg.connect(self._dsn or _listen_dsn())
                await conn.add_listener(self._channel, self._on_notify)
                self._connected = True
                backoff = 1.0
                log.info("event_bus_listening", channel=self._channel)
                while not self._stopping.is_set():
                    await asyncio.sleep(10)
                    await conn.execute("SELECT 1")  # detects a dead connection
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # any driver or network error: reconnect
                self._connected = False
                log.warning("event_bus_disconnected", error=str(exc), retry_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                self._connected = False
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.close()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


__all__ = [
    "CHANNEL",
    "EVENT_TYPES",
    "Event",
    "EventBus",
    "get_event_bus",
    "publish",
]
