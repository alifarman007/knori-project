"""The Recognition surface, without a database.

Three things are worth testing on their own here, because getting them wrong is
invisible until a user is looking at the screen:

* the sentence under a card (:func:`plain_confidence`) — the number is useless
  to a person, the sentence is the whole product promise;
* the transition table (:func:`plan_feedback`) — every legal move and, more
  importantly, every illegal one;
* the deep link back to the exact words, which is how a user checks KnoRI.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from knori.api.routers.events import FORWARDED, event_frames, frame, stream_events
from knori.core.errors import BadRequest, Conflict
from knori.core.events import EVENT_TYPES, Event, EventBus
from knori.services.feedback import (
    ACTION_STATES,
    ANSWERABLE_STATES,
    RESOLVED_STATES,
    check_reason_code,
    clean_correction,
    plan_feedback,
)
from knori.services.recognitions import (
    TAB_STATES,
    ConfidenceBreakdown,
    breakdown_from_json,
    breakdown_from_provenance,
    decode_cursor,
    deep_link_for,
    encode_cursor,
    group_evidence,
    plain_confidence,
    states_for_tab,
)
from ros.persistence.models import RECOGNITION_STATES, RecognitionProvenance


def _tzdata_present() -> bool:
    """Windows ships no tz database; without ``tzdata`` every zone falls back to UTC."""
    try:
        ZoneInfo("Pacific/Honolulu")
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


_HAS_TZDATA = _tzdata_present()


def _prov(
    *,
    role: str = "supports",
    kind: str = "signal",
    day: int = 1,
    hour: int = 9,
    order: int = 0,
    seq: int | None = 4,
    conversation_id: uuid.UUID | None = None,
    scrubbed: bool = False,
    quote: str = "I went for a run before work again",
) -> RecognitionProvenance:
    """A provenance row as it exists in memory, before anything is flushed."""
    return RecognitionProvenance(
        id=uuid.uuid4(),
        recognition_id=uuid.uuid4(),
        kind=kind,
        role=role,
        weight=1.0,
        quote_text="[deleted by you]" if scrubbed else quote,
        quote_start=None if scrubbed else 0,
        quote_end=None if scrubbed else len(quote),
        message_id=None if scrubbed else uuid.uuid4(),
        conversation_id=conversation_id or uuid.uuid4(),
        conversation_title="Monday morning",
        seq=seq,
        message_created_at=datetime(2026, 3, day, hour, tzinfo=UTC),
        display_order=order,
        scrubbed_at=datetime(2026, 3, 9, tzinfo=UTC) if scrubbed else None,
        note=None,
    )


# ----------------------------------------------------------- the sentence


def test_the_example_from_the_plan() -> None:
    sentence = plain_confidence(ConfidenceBreakdown(supports=3, distinct_days=2))
    assert sentence == (
        "Based on 3 things you said across 2 days; nothing you said pointed the other way."
    )


@pytest.mark.parametrize(
    ("breakdown", "expected"),
    [
        (
            ConfidenceBreakdown(supports=2, distinct_days=2, contradicts=1),
            "Based on 2 things you said across 2 days; 1 thing you said pointed the other way.",
        ),
        (
            ConfidenceBreakdown(supports=4, distinct_days=3, contradicts=2),
            "Based on 4 things you said across 3 days; 2 things you said pointed the other way.",
        ),
        (
            ConfidenceBreakdown(supports=1, distinct_days=1),
            "Based on 1 thing you said on one day; nothing you said pointed the other way.",
        ),
        (
            ConfidenceBreakdown(supports=3, distinct_days=0),
            "Based on 3 things you said; nothing you said pointed the other way.",
        ),
        (
            ConfidenceBreakdown(supports=2, distinct_days=2, deleted_sources=1),
            "Based on 2 things you said across 2 days, one of which you have since deleted; "
            "nothing you said pointed the other way.",
        ),
        (
            ConfidenceBreakdown(supports=3, distinct_days=2, deleted_sources=2),
            "Based on 3 things you said across 2 days, 2 of which you have since deleted; "
            "nothing you said pointed the other way.",
        ),
        (
            ConfidenceBreakdown(supports=2, distinct_days=2, user_authored=True),
            "Based on your own correction and 2 things you said across 2 days; "
            "nothing you said pointed the other way.",
        ),
    ],
)
def test_wording_for_each_shape(breakdown: ConfidenceBreakdown, expected: str) -> None:
    assert plain_confidence(breakdown) == expected


def test_nothing_left_to_show_when_every_source_is_gone() -> None:
    gone = plain_confidence(ConfidenceBreakdown(supports=0))
    assert gone == "The messages behind this are gone, so there is nothing left to show."


def test_a_user_authored_card_says_so() -> None:
    authored = plain_confidence(ConfidenceBreakdown(supports=0, user_authored=True))
    assert authored.startswith("Based on a correction you made")


@pytest.mark.parametrize(
    "breakdown",
    [
        ConfidenceBreakdown(supports=3, distinct_days=2, value=0.734, label="likely"),
        ConfidenceBreakdown(supports=2, distinct_days=2, contradicts=1, value=0.92),
        ConfidenceBreakdown(supports=0),
    ],
)
def test_the_sentence_is_one_sentence_and_hides_the_arithmetic(
    breakdown: ConfidenceBreakdown,
) -> None:
    sentence = plain_confidence(breakdown)
    assert sentence.count(".") == 1, sentence
    assert sentence.endswith(".")
    # A person cannot check "0.73"; they can check "3 things you said".
    assert "0." not in sentence
    assert "confidence" not in sentence.lower()


def _midnight_rows() -> list[RecognitionProvenance]:
    """23:00 and 00:00 UTC: two days in UTC, one evening in Honolulu."""
    return [_prov(day=3, hour=23, order=0), _prov(day=4, hour=0, order=1)]


def test_breakdown_counts_calendar_days_not_elapsed_time() -> None:
    assert breakdown_from_provenance(_midnight_rows(), timezone="UTC").distinct_days == 2


@pytest.mark.skipif(not _HAS_TZDATA, reason="no tz database on this machine (tzdata not installed)")
def test_breakdown_counts_days_in_the_users_timezone() -> None:
    breakdown = breakdown_from_provenance(_midnight_rows(), timezone="Pacific/Honolulu")
    assert breakdown.distinct_days == 1


def test_breakdown_separates_contradicting_rows_and_counts_deletions() -> None:
    rows = [
        _prov(day=1, order=0),
        _prov(day=3, order=1, scrubbed=True),
        _prov(day=3, order=2, role="contradicts"),
        _prov(day=3, order=3, role="context"),
    ]
    breakdown = breakdown_from_provenance(rows, timezone="UTC", value=0.7, label="likely")
    assert (breakdown.supports, breakdown.contradicts, breakdown.deleted_sources) == (2, 1, 1)
    assert breakdown.span_hours == pytest.approx(48.0)
    assert breakdown.label == "likely"


def test_breakdown_from_the_stored_conf_v1_json() -> None:
    stored = {
        "supports": 3,
        "contradicts": 1,
        "distinct_days": 2,
        "span_hours": 26.5,
        "user_correction_floor_applied": False,
    }
    breakdown = breakdown_from_json(stored, value=0.69, label="likely")
    assert (breakdown.supports, breakdown.contradicts, breakdown.distinct_days) == (3, 1, 2)
    assert plain_confidence(breakdown).endswith("1 thing you said pointed the other way.")


# --------------------------------------------------------------- evidence


def test_deep_link_points_at_the_exact_span() -> None:
    conversation = uuid.UUID("11111111-2222-3333-4444-555555555555")
    assert deep_link_for(conversation, 12, 40, 61) == f"/app/chat/{conversation}?m=12&hl=40-61"


def test_deep_link_without_offsets_still_opens_the_message() -> None:
    conversation = uuid.uuid4()
    assert deep_link_for(conversation, 12, None, None) == f"/app/chat/{conversation}?m=12"


@pytest.mark.parametrize(
    ("conversation_id", "seq"),
    [(None, 4), (uuid.uuid4(), None), (None, None)],
)
def test_no_deep_link_once_the_message_is_gone(
    conversation_id: uuid.UUID | None, seq: int | None
) -> None:
    assert deep_link_for(conversation_id, seq, 0, 3) is None


def test_contradicting_evidence_keeps_its_own_group() -> None:
    groups = group_evidence(
        [
            _prov(order=1, role="supports"),
            _prov(order=0, role="contradicts"),
            _prov(order=2, role="context"),
            _prov(order=3, role="supports"),
        ]
    )
    assert len(groups.supports) == 2
    assert len(groups.contradicts) == 1
    assert len(groups.context) == 1
    assert [item.role for item in groups.supports] == ["supports", "supports"]


def test_a_scrubbed_quote_carries_no_link_and_is_marked() -> None:
    (item,) = group_evidence([_prov(scrubbed=True)]).supports
    assert item.scrubbed is True
    assert item.deep_link is None
    assert item.quote == "[deleted by you]"


def test_evidence_keeps_the_fields_the_ui_deep_links_with() -> None:
    conversation = uuid.uuid4()
    (item,) = group_evidence([_prov(conversation_id=conversation, seq=7)]).supports
    assert item.conversation_id == conversation
    assert item.seq == 7
    assert item.message_id is not None
    assert item.conversation_title == "Monday morning"
    assert item.deep_link == f"/app/chat/{conversation}?m=7&hl=0-34"


# ----------------------------------------------------- tabs and cursors


def test_every_card_state_is_reachable_from_some_tab() -> None:
    covered = {state for states in TAB_STATES.values() for state in states}
    assert covered == set(RECOGNITION_STATES)


def test_the_new_tab_is_everything_not_yet_answered() -> None:
    assert states_for_tab("new") == ("pending", "presented")


def test_an_unknown_tab_is_a_bad_request_not_an_empty_page() -> None:
    with pytest.raises(BadRequest):
        states_for_tab("everything")


def test_cursor_round_trip() -> None:
    moment = datetime(2026, 3, 4, 9, 30, tzinfo=UTC)
    row_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(moment, row_id)) == (moment, row_id)


@pytest.mark.parametrize("cursor", ["not-base64!!", "", "Zm9v", "!!!!"])
def test_a_broken_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(BadRequest):
        decode_cursor(cursor)


# ------------------------------------------------- the transition table


LEGAL = [(state, action) for state in sorted(ANSWERABLE_STATES) for action in ACTION_STATES]
ILLEGAL = [
    (state, action) for state in sorted(RESOLVED_STATES | {"withdrawn"}) for action in ACTION_STATES
]


@pytest.mark.parametrize(("state", "action"), LEGAL)
def test_every_legal_move(state: str, action: str) -> None:
    plan = plan_feedback(state, action)
    assert plan.to_state == ACTION_STATES[action]
    assert plan.from_state == state
    assert plan.event == plan.to_state
    # A card answered straight from the chat was never marked seen first.
    assert plan.mark_presented is (state == "pending")


@pytest.mark.parametrize(("state", "action"), ILLEGAL)
def test_every_illegal_move(state: str, action: str) -> None:
    with pytest.raises(Conflict) as raised:
        plan_feedback(state, action)
    assert raised.value.status == 409


def test_the_table_covers_every_state_the_database_allows() -> None:
    tested = {state for state, _ in LEGAL} | {state for state, _ in ILLEGAL}
    assert tested == set(RECOGNITION_STATES)


def test_accepting_a_rejected_card_says_what_happened() -> None:
    with pytest.raises(Conflict) as raised:
        plan_feedback("rejected", "accept")
    assert raised.value.code == "already_answered"
    assert "not true" in raised.value.detail


def test_a_withdrawn_card_has_nothing_to_answer() -> None:
    with pytest.raises(Conflict) as raised:
        plan_feedback("withdrawn", "accept")
    assert raised.value.code == "card_withdrawn"


def test_an_unknown_action_is_rejected() -> None:
    with pytest.raises(BadRequest):
        plan_feedback("presented", "snooze")


def test_correction_goes_to_the_slow_lane_and_the_rest_do_not() -> None:
    assert plan_feedback("presented", "correct").lane == "slow"
    assert plan_feedback("presented", "correct").needs_model is True
    for action in ("accept", "reject", "dismiss"):
        plan = plan_feedback("presented", action)
        assert plan.lane == "fast"
        assert plan.needs_model is False


# ----------------------------------------------------- what the user typed


def test_a_correction_must_say_something() -> None:
    with pytest.raises(Exception) as raised:
        clean_correction("correct", "   ")
    assert getattr(raised.value, "status", None) == 422


def test_a_correction_is_trimmed_and_capped() -> None:
    assert clean_correction("correct", "  not quite  ") == "not quite"
    assert len(clean_correction("correct", "x" * 5000) or "") == 2000


def test_the_other_actions_may_carry_no_text() -> None:
    assert clean_correction("accept", None) is None
    assert clean_correction("dismiss", "  ") is None


def test_only_the_five_reason_codes_are_accepted() -> None:
    assert check_reason_code("not_useful") == "not_useful"
    assert check_reason_code(None) is None
    with pytest.raises(BadRequest):
        check_reason_code("because")


# ------------------------------------------------------------ the live stream


async def _wait_for(predicate: Callable[[], bool], *, timeout: float = 2.0) -> bool:
    """Poll instead of sleeping a fixed time, so the test is not a race."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


def test_a_frame_is_named_so_addeventlistener_can_match_it() -> None:
    event = Event(
        type="recognition.created", data={"recognition_id": "r1"}, at="2026-03-05T21:15:00"
    )
    text = frame(event)
    assert text.startswith("event: recognition.created\ndata: {")
    assert text.endswith("\n\n")
    assert "r1" in text


def test_the_stream_forwards_exactly_the_events_the_app_acts_on() -> None:
    assert "recognition.created" in FORWARDED
    assert "correction.effect.ready" in FORWARDED
    assert "profile.updated" in FORWARDED
    assert "heartbeat" in FORWARDED
    # Everything the bus can carry is either forwarded or deliberately dropped.
    assert set(EVENT_TYPES) >= FORWARDED


async def test_the_stream_drops_unknown_events_beats_and_cleans_up() -> None:
    bus = EventBus(heartbeat_seconds=0.05)
    user_id = uuid.uuid4()
    frames = event_frames(bus, user_id)
    collected: list[str] = []

    async def pump() -> None:
        async for chunk in frames:
            collected.append(chunk)

    task = asyncio.create_task(pump())
    try:
        assert await _wait_for(lambda: bus.subscriber_count == 1)
        bus.dispatch(Event(type="memory.changed", user_id=str(user_id)))
        bus.dispatch(
            Event(type="recognition.created", data={"recognition_id": "r1"}, user_id=str(user_id))
        )
        assert await _wait_for(lambda: any("recognition.created" in c for c in collected))
        assert await _wait_for(lambda: any("event: heartbeat" in c for c in collected))
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await frames.aclose()

    assert collected[0] == "retry: 3000\n\n"
    assert collected[1] == ": connected\n\n"
    assert not any("memory.changed" in chunk for chunk in collected)
    # The client going away must not leave a queue behind on the bus.
    assert bus.subscriber_count == 0


async def test_one_users_events_never_reach_another_stream() -> None:
    bus = EventBus(heartbeat_seconds=5.0)
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    frames = event_frames(bus, mine)
    collected: list[str] = []

    async def pump() -> None:
        async for chunk in frames:
            collected.append(chunk)

    task = asyncio.create_task(pump())
    try:
        assert await _wait_for(lambda: bus.subscriber_count == 1)
        bus.dispatch(Event(type="recognition.created", data={"id": "x"}, user_id=str(theirs)))
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await frames.aclose()

    assert not any("recognition.created" in chunk for chunk in collected)


async def test_the_events_endpoint_promises_an_event_stream() -> None:
    # httpx's ASGI transport buffers a whole response, so an endless stream
    # cannot be driven through a test client; the handler is checked directly
    # and the frames it produces are covered above.
    response = await stream_events(user=SimpleNamespace(id=uuid.uuid4()))  # type: ignore[arg-type]
    try:
        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
    finally:
        await response.body_iterator.aclose()  # type: ignore[attr-defined]
