"""Extraction: what the model says only becomes a signal if the user really said it.

These run with no database and no API key. The model layer is real — the fake
provider reads a scripted answer from a fixture file — so the prompt is rendered
for each test and a missing variable fails here rather than in production.

The rule under test is CLAUDE.md engine rule 2: a quote that cannot be located in
the message is dropped and counted, never stored.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ros.engine import pipeline
from ros.engine.pipeline import PipelineDeps, run_extraction
from ros.engine.types import UserPolicy
from ros.llm.providers.fake import FakeProvider
from ros.llm.router import build_router
from ros.memory.protocols import MemoryItemIn, MemorySourceIn, UpsertResult
from ros.persistence.engine_repo import ConversationRow, MessageRow, UserContext
from ros.persistence.models import Signal

MESSAGE_TEXT = "i keep putting off the invoices, third week now tbh"
SENT_AT = datetime(2026, 9, 19, 8, 30, tzinfo=UTC)
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)


def signal_payload(quote: str, **overrides: Any) -> dict[str, Any]:
    return {
        "message_ref": "M1",
        "kind": "behavior",
        "subject": "self",
        "topic": "work.workload",
        "content": "The user has been postponing their invoicing.",
        "quote_text": quote,
        "polarity": -1,
        "strength": 1.0,
        "sensitive_category": None,
        "context_tags": ["work"],
        **overrides,
    }


def memory_payload(quote: str) -> dict[str, Any]:
    return {
        "message_ref": "M1",
        "kind": "fact",
        "key": "fact.invoices",
        "statement": "The user bills clients by invoice.",
        "quote_text": quote,
        "sensitive_category": None,
    }


def extraction(signals: list[dict[str, Any]], memories: list[dict[str, Any]] | None = None) -> Any:
    return {
        "signals": signals,
        "memory_candidates": memories or [],
        "skipped_reason": None,
    }


def router_with(tmp_path: Path, replies: dict[str, Any]) -> Any:
    """A real router whose provider answers from scripted fixtures."""
    for task, parsed in replies.items():
        (tmp_path / f"{task}.json").write_text(json.dumps({"parsed": parsed}), encoding="utf-8")
    router = build_router()
    provider = FakeProvider(fixtures_dir=tmp_path)
    router.providers = dict.fromkeys(router.providers, provider)
    return router


class FakeRepo:
    """Just the reads and writes ``run_extraction`` makes, kept in memory."""

    def __init__(self, *, incognito: bool = False, memory_enabled: bool = True) -> None:
        self.user_id = uuid.uuid4()
        self.conversation_id = str(uuid.uuid4())
        self.message = MessageRow(
            id=str(uuid.uuid4()),
            conversation_id=self.conversation_id,
            seq=4,
            role="user",
            content=MESSAGE_TEXT,
            created_at=SENT_AT,
        )
        self.incognito = incognito
        self.memory_enabled = memory_enabled
        self.signals: list[Signal] = []
        self.extracted: list[str] = []

    async def user_context(self) -> UserContext:
        return UserContext(policy=UserPolicy(), memory_enabled=self.memory_enabled)

    async def messages_by_id(self, ids: Any) -> list[MessageRow]:
        wanted = {str(i) for i in ids}
        return [self.message] if self.message.id in wanted else []

    async def conversation(self, conversation_id: Any) -> ConversationRow:
        return ConversationRow(
            id=str(conversation_id),
            title="Invoices",
            is_incognito=self.incognito,
            archived_at=None,
            last_seq=4,
        )

    async def context_messages(self, *args: Any, **kwargs: Any) -> list[MessageRow]:
        return []

    async def active_memory(self, **kwargs: Any) -> list[Any]:
        return []

    async def add_signal(self, **values: Any) -> Signal:
        row = Signal(user_id=self.user_id, **values)
        self.signals.append(row)
        return row

    async def mark_extracted(self, ids: Any, at: datetime) -> int:
        self.extracted = [str(i) for i in ids]
        return len(self.extracted)


class FakeMemory:
    """The ``MemoryStore`` protocol, recorded rather than stored."""

    def __init__(self) -> None:
        self.items: list[tuple[MemoryItemIn, list[MemorySourceIn]]] = []

    async def upsert_item(
        self,
        user_id: uuid.UUID,
        item: MemoryItemIn,
        *,
        sources: Any = (),
        similarity_cutoff: float | None = None,
    ) -> UpsertResult:
        self.items.append((item, list(sources)))
        return UpsertResult(item_id=uuid.uuid4(), created=True)


def deps_for(
    repo: FakeRepo, router: Any, monkeypatch: pytest.MonkeyPatch, memory: Any = None
) -> PipelineDeps:
    monkeypatch.setattr(pipeline, "EngineRepo", lambda session, user_id: repo)
    return PipelineDeps(
        session=None,  # type: ignore[arg-type]
        router=router,
        clock=lambda: NOW,
        memory=memory,
    )


async def run(
    repo: FakeRepo, router: Any, monkeypatch: pytest.MonkeyPatch, memory: Any = None
) -> Any:
    deps = deps_for(repo, router, monkeypatch, memory)
    return await run_extraction(deps, repo.user_id, [repo.message.id])


async def test_a_paraphrased_quote_is_dropped_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {
            "extract.signals": extraction(
                [
                    signal_payload("i keep putting off the invoices"),
                    signal_payload("third week now"),
                    # Tidied up by the model, so it is not in the message any more.
                    signal_payload("I keep putting off the invoices for a third week"),
                ]
            )
        },
    )
    repo = FakeRepo()

    result = await run(repo, router, monkeypatch)

    assert result.signals == 2
    assert result.dropped_quotes == 1
    assert len(repo.signals) == 2
    assert all("for a third week" not in row.quote_text for row in repo.signals)


async def test_every_stored_quote_is_a_verbatim_slice_of_the_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {
            "extract.signals": extraction(
                [
                    signal_payload("i keep putting off the invoices"),
                    # Curly apostrophes and collapsed spacing still locate.
                    signal_payload("third  week   now"),
                ]
            )
        },
    )
    repo = FakeRepo()

    await run(repo, router, monkeypatch)

    assert len(repo.signals) == 2
    for row in repo.signals:
        assert MESSAGE_TEXT[row.quote_start : row.quote_end] == row.quote_text


async def test_observed_at_is_when_it_was_said_not_when_it_was_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {"extract.signals": extraction([signal_payload("third week now")])},
    )
    repo = FakeRepo()

    await run(repo, router, monkeypatch)

    assert repo.signals[0].observed_at == SENT_AT
    assert repo.extracted == [repo.message.id]


async def test_unknown_topic_and_category_are_clamped_not_stored_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {
            "extract.signals": extraction(
                [
                    signal_payload(
                        "third week now",
                        topic="invented.topic",
                        sensitive_category="astrology",
                        subject="nonsense",
                        strength=9.0,
                        polarity=-7,
                    )
                ]
            )
        },
    )
    repo = FakeRepo()

    await run(repo, router, monkeypatch)

    row = repo.signals[0]
    assert row.topic == "other.unclear"
    assert row.sensitive_category is None
    assert row.subject == "unclear"
    assert row.strength == 1.0
    assert row.polarity == -1


async def test_a_known_sensitive_category_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {
            "extract.signals": extraction(
                [signal_payload("third week now", sensitive_category="financial_distress")]
            )
        },
    )
    repo = FakeRepo()

    await run(repo, router, monkeypatch)

    assert repo.signals[0].sensitive_category == "financial_distress"


async def test_a_memory_candidate_with_an_invented_quote_never_reaches_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {
            "extract.signals": extraction(
                [],
                [memory_payload("I invoice monthly")],
            )
        },
    )
    repo, memory = FakeRepo(), FakeMemory()

    result = await run(repo, router, monkeypatch, memory)

    assert result.memories == 0
    assert result.dropped_quotes == 1
    assert memory.items == []


async def test_a_memory_candidate_is_stored_with_its_verified_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {"extract.signals": extraction([], [memory_payload("the invoices")])},
    )
    repo, memory = FakeRepo(), FakeMemory()

    result = await run(repo, router, monkeypatch, memory)

    assert result.memories == 1
    item, sources = memory.items[0]
    assert item.source == "extracted"
    assert item.key == "fact.invoices"
    span = sources[0]
    assert MESSAGE_TEXT[span.quote_start : span.quote_end] == span.quote_text == "the invoices"


async def test_an_incognito_conversation_is_never_extracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(
        tmp_path,
        {"extract.signals": extraction([signal_payload("third week now")])},
    )
    repo = FakeRepo(incognito=True)

    result = await run(repo, router, monkeypatch)

    assert result.skipped == "incognito"
    assert repo.signals == []
    assert repo.extracted == []


async def test_memory_switched_off_stops_extraction_before_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = router_with(tmp_path, {})
    repo = FakeRepo(memory_enabled=False)

    result = await run(repo, router, monkeypatch)

    assert result.skipped == "memory_disabled"
    assert repo.signals == []
