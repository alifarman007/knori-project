"""The fake provider and the fake embeddings.

These carry more weight than a normal test double: `LLM_MODE=fake` is the default,
so this is what every other test, all of CI, and a keyless demo actually run.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from ros.llm import spec
from ros.llm.base import ChatMessage, CompletionRequest, SystemBlock
from ros.llm.embeddings.fake import FakeEmbeddingProvider, cosine
from ros.llm.errors import RefusalError, TruncatedError
from ros.llm.providers import synthetic
from ros.llm.providers.fake import FakeProvider
from ros.schemas import llm_io

SCHEMAS = [
    value
    for _, value in inspect.getmembers(llm_io, inspect.isclass)
    if issubclass(value, BaseModel)
    and value.__module__ == llm_io.__name__
    and value is not llm_io.Strict
]

SAMPLE = (
    "I kept putting off the dentist again this week. "
    "It is the third time I have done that. "
    "I think I am just tired of appointments."
)


def request_for(task: str, text: str = SAMPLE, **metadata: object) -> CompletionRequest:
    return CompletionRequest(
        task=task,
        messages=[ChatMessage(role="user", content=text)],
        metadata={spec.MODEL: "claude-opus-5", **metadata},
    )


@pytest.fixture
def provider(tmp_path: Path) -> FakeProvider:
    return FakeProvider(delay=0.0, fixtures_dir=tmp_path)


# ------------------------------------------------------------------ every schema


def test_there_are_schemas_to_check() -> None:
    assert len(SCHEMAS) >= 10, "sanity: llm_io should expose the engine's schemas"


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda schema: schema.__name__)
async def test_every_schema_in_llm_io_gets_a_valid_instance(
    provider: FakeProvider, schema: type[BaseModel]
) -> None:
    result = await provider.complete_structured(request_for("some.task"), schema)

    assert isinstance(result.parsed, schema)
    schema.model_validate_json(result.text), "the text must be the object, serialised"


async def test_extracted_quotes_are_verbatim_spans_of_the_input(provider: FakeProvider) -> None:
    """ros.engine.signals drops any quote it cannot find in the message."""
    result = await provider.complete_structured(
        request_for("extract.signals"), llm_io.SignalExtraction
    )

    extraction = result.parsed
    assert isinstance(extraction, llm_io.SignalExtraction)
    assert extraction.signals
    for signal in extraction.signals:
        assert signal.quote_text in SAMPLE, signal.quote_text
        assert signal.subject == "self"


async def test_proposals_only_cite_refs_that_were_in_the_input(provider: FakeProvider) -> None:
    result = await provider.complete_structured(
        request_for("interpret.recognize", "S4 and S9 both describe the same evening habit."),
        llm_io.InterpretationBatch,
    )

    batch = result.parsed
    assert isinstance(batch, llm_io.InterpretationBatch)
    cited = {evidence.signal_ref for proposal in batch.proposals for evidence in proposal.evidence}
    assert cited <= {"S4", "S9"}


async def test_it_declines_rather_than_inventing_a_pattern(provider: FakeProvider) -> None:
    result = await provider.complete_structured(
        request_for("interpret.recognize", "S1 is the only thing here."), llm_io.InterpretationBatch
    )

    batch = result.parsed
    assert isinstance(batch, llm_io.InterpretationBatch)
    assert batch.proposals == []
    assert batch.declined[0].reason == "single_occurrence"


# ------------------------------------------------- reading a real rendered prompt


def test_quotes_come_from_the_data_block_not_the_instructions() -> None:
    """A rendered prompt is mostly instructions; only the data block is the person."""
    prompt = "\n".join(
        [
            "# Extraction rules",
            "You read what one person wrote and pull out the small, factual observations.",
            "You do not interpret, conclude or advise.",
            "",
            "<topics>- `health.exercise` - exercise</topics>",
            "",
            "<new_messages>",
            "Extract from these, and only these.[M1] (2026-09-19)",
            "I skipped the gym again tonight.[M2] (2026-09-20)",
            "Third week running now.</new_messages>",
        ]
    )

    said = synthetic.sentences(prompt)

    assert said == ["I skipped the gym again tonight.", "Third week running now."]


def test_plain_text_with_no_data_block_is_read_whole() -> None:
    assert synthetic.sentences("I have been sleeping badly.") == ["I have been sleeping badly."]


async def test_a_rendered_prompt_still_yields_verbatim_quotes(tmp_path: Path) -> None:
    """The check ros.engine.signals makes: the quote must be in the message."""
    message = "I skipped the gym again tonight and just watched telly instead."
    prompt = "\n".join(
        [
            "Rules go here, at length.",
            "<new_messages>[M1] (2026-09-19)",
            f"{message}</new_messages>",
        ]
    )
    provider = FakeProvider(delay=0.0, fixtures_dir=tmp_path)

    result = await provider.complete_structured(
        request_for("extract.signals", prompt), llm_io.SignalExtraction
    )

    extraction = result.parsed
    assert isinstance(extraction, llm_io.SignalExtraction)
    assert extraction.signals
    for signal in extraction.signals:
        assert signal.quote_text in message


# -------------------------------------------------------------------- chat text


async def test_a_chat_reply_mentions_something_from_the_input(provider: FakeProvider) -> None:
    result = await provider.complete(request_for("chat.reply"))

    assert "dentist" in result.text


async def test_the_same_request_always_gives_the_same_answer(provider: FakeProvider) -> None:
    first = await provider.complete(request_for("chat.reply"))
    second = await FakeProvider(delay=0.0).complete(request_for("chat.reply"))

    assert first.text == second.text


async def test_streaming_arrives_in_pieces_that_rejoin_exactly(provider: FakeProvider) -> None:
    chunks: list[str] = []
    result = None
    async for event in provider.stream(request_for("chat.reply")):
        if event.kind == "text":
            chunks.append(event.text)
        elif event.kind == "done":
            result = event.result

    assert len(chunks) > 1
    assert result is not None
    assert "".join(chunks) == result.text


async def test_summarized_thinking_produces_a_thinking_event(provider: FakeProvider) -> None:
    request = request_for("chat.reply", **{spec.THINKING_DISPLAY: "summarized"})
    kinds = [event.kind async for event in provider.stream(request)]

    assert "thinking" in kinds


async def test_cached_blocks_are_reported_as_cache_reads(provider: FakeProvider) -> None:
    request = CompletionRequest(
        task="chat.reply",
        system_blocks=[SystemBlock("A long, stable persona prompt.", cache=True)],
        messages=[ChatMessage(role="user", content=SAMPLE)],
        metadata={spec.MODEL: "claude-opus-5"},
    )

    result = await provider.complete(request)

    assert result.usage.cache_read_tokens > 0


# --------------------------------------------------------------------- fixtures


async def test_a_fixture_reply_wins_over_the_generated_one(tmp_path: Path) -> None:
    (tmp_path / "chat.reply.json").write_text(
        json.dumps(
            [
                {"match": "dentist", "text": "You have mentioned the dentist before."},
                {"text": "Tell me more."},
            ]
        ),
        encoding="utf-8",
    )
    provider = FakeProvider(delay=0.0, fixtures_dir=tmp_path)

    matched = await provider.complete(request_for("chat.reply"))
    fallthrough = await provider.complete(request_for("chat.reply", "Nothing relevant at all."))

    assert matched.text == "You have mentioned the dentist before."
    assert fallthrough.text == "Tell me more."


async def test_a_fixture_can_supply_a_structured_answer(tmp_path: Path) -> None:
    (tmp_path / "claims.same_claim.json").write_text(
        json.dumps({"parsed": {"same": True, "why": "Same behaviour, different words."}}),
        encoding="utf-8",
    )
    provider = FakeProvider(delay=0.0, fixtures_dir=tmp_path)

    result = await provider.complete_structured(request_for("claims.same_claim"), llm_io.SameClaim)

    assert result.parsed == llm_io.SameClaim(same=True, why="Same behaviour, different words.")


@pytest.mark.parametrize(
    ("status", "error"), [("refused", RefusalError), ("truncated", TruncatedError)]
)
async def test_a_fixture_can_script_a_failure(
    tmp_path: Path, status: str, error: type[Exception]
) -> None:
    (tmp_path / "chat.reply.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    provider = FakeProvider(delay=0.0, fixtures_dir=tmp_path)

    with pytest.raises(error):
        await provider.complete(request_for("chat.reply"))


# ------------------------------------------------------------------- embeddings


def test_fake_embeddings_are_unit_vectors_of_the_right_width() -> None:
    embedder = FakeEmbeddingProvider()

    vector = embedder.vector("a sentence about sleep")

    assert len(vector) == 1536
    assert cosine(vector, vector) == pytest.approx(1.0)


async def test_fake_embeddings_are_stable_across_instances() -> None:
    first = await FakeEmbeddingProvider().embed(["I have been sleeping badly."])
    second = await FakeEmbeddingProvider().embed(["I have been sleeping badly."])

    assert first == second


async def test_similar_text_scores_higher_than_unrelated_text() -> None:
    embedder = FakeEmbeddingProvider()

    base, near, far = await embedder.embed(
        [
            "I have been sleeping badly this week.",
            "I have been sleeping badly for the last few weeks.",
            "The tram to the coast leaves from platform nine.",
        ]
    )

    assert cosine(base, near) > cosine(base, far)
    assert cosine(base, near) > 0.5
    assert cosine(base, far) < 0.2


async def test_an_empty_string_is_still_a_unit_vector() -> None:
    (vector,) = await FakeEmbeddingProvider().embed([""])

    assert cosine(vector, vector) == pytest.approx(1.0)
