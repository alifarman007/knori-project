"""Conversations against a real database (plan §5.1, §4.7).

Everything here needs Postgres, so it is all ``@pytest.mark.integration`` and is
skipped — never failed — when there is none.

What is worth a database to check:

* ``seq`` is handed out under a row lock and never repeats;
* the user's message and its ``extract_signals`` job land in **one** transaction;
* a second reply is refused, and an abandoned one is recovered rather than
  blocking the thread for ever;
* one user can never read or delete another's rows;
* deleting a message really removes the words — including from the provenance of
  a Recognition that quoted them.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.core.errors import Conflict, NotFound
from knori.db.models import Conversation, User, UserSettings
from knori.services import chat as chat_service
from ros.memory.protocols import MemoryItemIn, MemorySourceIn
from ros.persistence import repositories
from ros.persistence.models import (
    EMBEDDING_DIM,
    Interpretation,
    Recognition,
    RecognitionProvenance,
    Signal,
)
from ros.persistence.pg_memory import PgMemoryStore, PgRetriever

pytestmark = pytest.mark.integration


# ----------------------------------------------------------------- fixtures


async def make_user(session: AsyncSession, name: str = "alif") -> User:
    user = User(
        email=f"{name}-{uuid.uuid4().hex[:8]}@example.test",
        password_hash="x",
        display_name=name,
        timezone="UTC",
    )
    session.add(user)
    await session.flush()
    session.add(UserSettings(user_id=user.id))
    await session.flush()
    return user


async def make_conversation(
    session: AsyncSession, user: User, *, incognito: bool = False
) -> Conversation:
    conversation = Conversation(user_id=user.id, kind="chat", is_incognito=incognito)
    session.add(conversation)
    await session.flush()
    return conversation


def vector(first: float = 1.0) -> list[float]:
    body = [0.0] * EMBEDDING_DIM
    body[0] = first
    body[1] = 1.0 - first
    return body


# --------------------------------------------------------------- the turn


async def test_seq_is_handed_out_in_order(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user)

    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    first = await chat_service.record_user_message(
        db_session, locked, content="hello", client_message_id="a"
    )
    reply = await chat_service.append_message(
        db_session, locked, role="assistant", content="hi there"
    )
    second = await chat_service.record_user_message(
        db_session, locked, content="again", client_message_id="b"
    )

    assert [first.seq, reply.seq, second.seq] == [1, 2, 3]
    assert locked.message_count == 3
    assert locked.last_seq == 3


async def test_the_message_and_its_job_are_one_transaction(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    await chat_service.record_user_message(
        db_session, locked, content="I skipped lunch again", client_message_id=None
    )

    queued = (
        await db_session.execute(
            text(
                "SELECT kind, run_at, dedupe_key FROM jobs "
                "WHERE user_id = :user_id AND kind = 'extract_signals'"
            ),
            {"user_id": user.id},
        )
    ).all()
    assert len(queued) == 1
    # plan §4.2: extraction waits 30 s so one job covers a burst of typing.
    assert queued[0].run_at > now()
    assert str(conversation.id) in queued[0].dedupe_key


async def test_an_incognito_conversation_is_never_extracted_from(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user, incognito=True)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    await chat_service.record_user_message(
        db_session, locked, content="off the record", client_message_id=None
    )
    count = await db_session.scalar(
        text("SELECT count(*) FROM jobs WHERE user_id = :user_id"), {"user_id": user.id}
    )
    assert count == 0


async def test_memory_off_means_nothing_is_learned(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    settings = await db_session.get(UserSettings, user.id)
    assert settings is not None
    settings.memory_enabled = False
    conversation = await make_conversation(db_session, user)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    await chat_service.record_user_message(
        db_session, locked, content="something", client_message_id=None, settings=settings
    )
    count = await db_session.scalar(
        text("SELECT count(*) FROM jobs WHERE user_id = :user_id"), {"user_id": user.id}
    )
    assert count == 0


# ------------------------------------------------------- one reply at a time


async def test_a_second_reply_is_refused(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    await chat_service.append_message(
        db_session, locked, role="assistant", content="", status="streaming"
    )
    with pytest.raises(Conflict):
        await chat_service.guard_not_streaming(db_session, user.id, conversation.id)


async def test_an_abandoned_reply_is_recovered_and_stops_blocking(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    stale = await chat_service.append_message(
        db_session,
        locked,
        role="assistant",
        content="half an ans",
        status="streaming",
        at=now() - timedelta(minutes=10),
    )
    empty = await chat_service.append_message(
        db_session,
        locked,
        role="assistant",
        content="",
        status="streaming",
        at=now() - timedelta(minutes=10),
    )

    assert await chat_service.recover_orphans(db_session) >= 2
    await db_session.refresh(stale)
    await db_session.refresh(empty)
    # Text that arrived is kept as `partial`; nothing at all is a `failed` turn.
    assert stale.status == "partial"
    assert empty.status == "failed"
    await chat_service.guard_not_streaming(db_session, user.id, conversation.id)


# ------------------------------------------------------------------ reading


async def test_pages_and_windows_of_a_thread(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    for index in range(20):
        await chat_service.append_message(
            db_session,
            locked,
            role="user" if index % 2 == 0 else "assistant",
            content=f"message {index}",
        )

    latest = await repositories.list_messages(db_session, user.id, conversation.id, limit=5)
    assert [row.seq for row in latest] == [16, 17, 18, 19, 20]

    older = await repositories.list_messages(
        db_session, user.id, conversation.id, before_seq=16, limit=5
    )
    assert [row.seq for row in older] == [11, 12, 13, 14, 15]

    # A deep link from a Recognition opens the thread around one message.
    window = await repositories.list_messages(
        db_session, user.id, conversation.id, around_seq=10, limit=6
    )
    assert window[0].seq <= 10 <= window[-1].seq


async def test_another_users_conversation_does_not_exist(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, "owner")
    stranger = await make_user(db_session, "stranger")
    conversation = await make_conversation(db_session, owner)

    assert await repositories.get_conversation(db_session, stranger.id, conversation.id) is None
    assert await repositories.list_messages(db_session, stranger.id, conversation.id) == []
    with pytest.raises(NotFound):
        await chat_service.lock_conversation(db_session, stranger.id, conversation.id)


# ---------------------------------------------------------------- retrieval


async def test_retrieval_only_ever_returns_your_own_rows(db_session: AsyncSession) -> None:
    mine = await make_user(db_session, "mine")
    theirs = await make_user(db_session, "theirs")
    store = PgMemoryStore(db_session, clock=now)
    await store.upsert_item(
        mine.id,
        MemoryItemIn(
            kind="preference",
            statement="They are vegetarian.",
            embedding=vector(1.0),
            embedding_model="text-embedding-3-small",
        ),
    )
    await store.upsert_item(
        theirs.id,
        MemoryItemIn(
            kind="preference",
            statement="They are vegetarian.",
            embedding=vector(1.0),
            embedding_model="text-embedding-3-small",
        ),
    )

    hits = await PgRetriever(db_session).search(
        mine.id, query_embedding=vector(1.0), kinds=("memory_item",), k=10
    )
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)


async def test_a_user_edited_memory_is_never_overwritten(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    store = PgMemoryStore(db_session, clock=now)
    first = await store.upsert_item(
        user.id,
        MemoryItemIn(kind="fact", statement="They live in Dhaka.", key="fact.city"),
    )
    await db_session.execute(
        text("UPDATE memory_items SET source = 'user_edited' WHERE id = :id"),
        {"id": first.item_id},
    )

    again = await store.upsert_item(
        user.id,
        MemoryItemIn(kind="fact", statement="They live in Chittagong.", key="fact.city"),
    )
    assert again.item_id == first.item_id
    assert again.confirmed is True
    assert again.skipped_reason == "protected_by_user"

    row = await repositories.get_memory_item(db_session, user.id, first.item_id)
    assert row is not None
    assert row.statement == "They live in Dhaka."


async def test_the_same_key_supersedes_an_extracted_memory(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    store = PgMemoryStore(db_session, clock=now)
    first = await store.upsert_item(
        user.id, MemoryItemIn(kind="fact", statement="They live in Dhaka.", key="fact.city")
    )
    second = await store.upsert_item(
        user.id, MemoryItemIn(kind="fact", statement="They live in Chittagong.", key="fact.city")
    )
    assert second.superseded_id == first.item_id
    old = await repositories.get_memory_item(db_session, user.id, first.item_id)
    assert old is not None
    assert old.status == "superseded"


async def test_a_source_quote_that_is_not_in_the_message_is_dropped(
    db_session: AsyncSession,
) -> None:
    """Same rule as a signal's quote: a source that highlights nothing is not stored."""
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    message = await chat_service.append_message(
        db_session, locked, role="user", content="I stopped eating meat last year"
    )

    store = PgMemoryStore(db_session, clock=now)
    good = await store.upsert_item(
        user.id,
        MemoryItemIn(kind="preference", statement="They do not eat meat."),
        sources=[MemorySourceIn(message_id=message.id, quote_text="stopped eating meat")],
    )
    added = await store.add_source(
        user.id,
        good.item_id,
        MemorySourceIn(message_id=message.id, quote_text="words they never typed"),
    )
    assert added is False
    sources = await repositories.list_memory_sources(db_session, user.id, good.item_id)
    assert [source.quote_text for source in sources] == ["stopped eating meat"]
    assert sources[0].quote_start == len("I ")


# -------------------------------------------------------------- plan §4.7


async def test_deleting_a_message_scrubs_the_quote_it_left_behind(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    conversation = await make_conversation(db_session, user)
    locked = await chat_service.lock_conversation(db_session, user.id, conversation.id)
    message = await chat_service.append_message(
        db_session, locked, role="user", content="I cancelled my own plans again"
    )

    signal = Signal(
        user_id=user.id,
        message_id=message.id,
        conversation_id=conversation.id,
        kind="behavior",
        subject="self",
        topic="work.boundaries",
        content="They cancelled their own plans.",
        quote_text="cancelled my own plans",
        quote_start=2,
        quote_end=24,
        observed_at=now(),
    )
    interpretation = Interpretation(
        user_id=user.id,
        kind="pattern",
        topic="work.boundaries",
        statement="They drop their own plans when work gets heavy.",
        model_confidence=0.8,
    )
    db_session.add_all([signal, interpretation])
    await db_session.flush()
    card = Recognition(
        user_id=user.id,
        interpretation_id=interpretation.id,
        kind="pattern",
        title="Your plans go first",
        body="It looks like your own plans are the first thing to go.",
        explanation="Twice this month.",
        confidence=0.73,
    )
    db_session.add(card)
    await db_session.flush()
    provenance = RecognitionProvenance(
        recognition_id=card.id,
        kind="signal",
        signal_id=signal.id,
        message_id=message.id,
        conversation_id=conversation.id,
        quote_text="cancelled my own plans",
        quote_start=2,
        quote_end=24,
    )
    db_session.add(provenance)
    await db_session.flush()

    from knori.api.routers.conversations import _after_deletion, _scrub_provenance

    await _scrub_provenance(db_session, user.id, [message.id])
    await db_session.execute(text("DELETE FROM messages WHERE id = :id"), {"id": message.id})
    await _after_deletion(db_session, user.id, [], deleted=1)
    await db_session.flush()

    await db_session.refresh(provenance)
    # The row stays — the card still had two pieces of evidence — but the words go.
    assert provenance.quote_text == "[deleted by you]"
    assert provenance.quote_start is None
    assert provenance.scrubbed_at is not None
    # The signal went with the message, so nothing can quote it again. The delete ran
    # as SQL, so drop the identity map first or we would read our own stale copy.
    db_session.expunge_all()
    assert await db_session.get(Signal, signal.id) is None

    queued = await db_session.scalar(
        text("SELECT count(*) FROM jobs WHERE user_id = :user_id AND kind = 'rescore_user'"),
        {"user_id": user.id},
    )
    assert queued == 1
