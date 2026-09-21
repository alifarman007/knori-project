"""The shape of the chat stream, without a database.

Two things are pinned here.

**The wire format**, because the frontend parses it by hand: every frame is
``event: <name>\\ndata: <json>\\n\\n`` and the names are a closed set. A renamed
event is a silently blank chat window.

**The detached generation**, because it is the one failure a chat product cannot
have: when the browser goes away mid-answer, the model call and the save must
carry on. The test closes the stream after the first frame and then waits for the
generation to finish on its own.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest

from knori.api.schemas.chat import SSE_EVENTS, AssistantMessageEvent, SendMessageIn
from knori.services import chat as chat_service
from knori.services.chat import ServerEvent


class FakeMessage:
    """Just the three fields ``start_turn`` reads off the user's row."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.seq = 7
        self.content = "busy week again"
        self.client_message_id = "c-1"


class FakeUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


def parse(frame: str) -> tuple[str, dict[str, Any]]:
    name, payload = frame.rstrip("\n").split("\n", 1)
    assert name.startswith("event: ")
    assert payload.startswith("data: ")
    return name[len("event: ") :], json.loads(payload[len("data: ") :])


# ------------------------------------------------------------------ the format


def test_a_frame_is_name_json_blank_line() -> None:
    frame = ServerEvent("delta", {"text": "hello"}).encode()
    assert frame == 'event: delta\ndata: {"text": "hello"}\n\n'


def test_uuids_and_times_survive_encoding() -> None:
    identifier = uuid.uuid4()
    name, data = parse(ServerEvent("message.assistant", {"id": identifier}).encode())
    assert name == "message.assistant"
    assert data["id"] == str(identifier)


def test_every_frame_ends_with_a_blank_line() -> None:
    for name in SSE_EVENTS:
        assert ServerEvent(name, {}).encode().endswith("\n\n")


def test_the_event_names_are_the_ones_the_frontend_listens_for() -> None:
    assert SSE_EVENTS == ("message.user", "delta", "thinking", "message.assistant", "error")


def test_the_assistant_event_carries_a_final_status() -> None:
    event = AssistantMessageEvent(id=uuid.uuid4(), seq=8, status="partial", content="half")
    assert event.status == "partial"


def test_a_blank_message_is_rejected_before_it_costs_anything() -> None:
    with pytest.raises(ValueError):
        SendMessageIn(content="   ")


def test_a_message_over_the_cap_is_rejected() -> None:
    with pytest.raises(ValueError):
        SendMessageIn(content="x" * 8_001)


# -------------------------------------------------------------- the stream

# `start_turn` starts the generation and then only relays events, so replacing
# the generation is exactly the seam these tests need: no database, no model.


async def test_the_user_message_is_the_first_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate(**kwargs: Any) -> None:
        await kwargs["events"].put(ServerEvent("delta", {"text": "hi"}))

    monkeypatch.setattr(chat_service, "_generate_in_session", fake_generate)

    message = FakeMessage()
    frames = [frame async for frame in _turn(uuid.uuid4(), message)]
    names = [parse(frame)[0] for frame in frames]
    assert names[0] == "message.user"
    assert parse(frames[0])[1] == {
        "id": str(message.id),
        "seq": 7,
        "client_message_id": "c-1",
    }
    assert "delta" in names


async def test_the_stream_ends_when_the_generation_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate(**kwargs: Any) -> None:
        return None

    monkeypatch.setattr(chat_service, "_generate_in_session", fake_generate)

    conversation_id = uuid.uuid4()
    frames = [frame async for frame in _turn(conversation_id)]
    assert [parse(frame)[0] for frame in frames] == ["message.user"]
    # The 409 guard must not be left armed once the turn is over.
    assert conversation_id not in chat_service._STREAMING


async def test_a_broken_generation_becomes_an_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(**kwargs: Any) -> None:
        raise RuntimeError("the database fell over")

    monkeypatch.setattr(chat_service, "_generate_in_session", explode)

    frames = [frame async for frame in _turn(uuid.uuid4())]
    names = [parse(frame)[0] for frame in frames]
    assert names[-1] == "error"
    assert parse(frames[-1])[1]["code"] == "generation_failed"


async def test_the_reply_is_still_written_when_the_client_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the whole design: closing the stream must not cancel the turn."""
    finished = asyncio.Event()

    async def slow_generate(**kwargs: Any) -> None:
        await asyncio.sleep(0.05)
        await kwargs["events"].put(ServerEvent("delta", {"text": "still going"}))
        finished.set()

    monkeypatch.setattr(chat_service, "_generate_in_session", slow_generate)

    conversation_id = uuid.uuid4()
    stream = _turn(conversation_id)
    first = await stream.__anext__()
    assert parse(first)[0] == "message.user"
    await stream.aclose()  # the browser went away

    await asyncio.wait_for(finished.wait(), timeout=2.0)
    for _ in range(50):
        if conversation_id not in chat_service._STREAMING:
            break
        await asyncio.sleep(0.01)
    assert conversation_id not in chat_service._STREAMING


class _StubSession:
    """The generation is replaced in these tests, so the session does nothing."""

    async def __aenter__(self) -> _StubSession:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False


def _turn(conversation_id: uuid.UUID, message: Any = None) -> Any:
    """``start_turn`` with the database and the model layer stubbed out."""
    return chat_service.start_turn(
        FakeUser(),
        conversation_id,
        message or FakeMessage(),
        session_factory=_StubSession,
        router=object(),
    )
