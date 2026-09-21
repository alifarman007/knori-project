"""The fake provider: every model call, with no network and no API key.

``LLM_MODE=fake`` is the default. It is what the test suite runs against, what CI
uses, and what makes a demo possible before a single dollar of credit is bought.

Two sources of answers, in order:

1. a scripted fixture at ``backend/tests/fixtures/llm/<task>.json`` — use this when a
   test or a demo needs one exact reply (see that directory's README for the format);
2. otherwise ``synthetic.build``, which reads the request and writes a plausible,
   schema-valid answer whose quotes are verbatim spans of the input.

Everything is deterministic: the same request gives the same answer, in this process
and the next, because the only randomness is seeded from the request itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any

import structlog
from pydantic import BaseModel

from ros.llm import spec
from ros.llm.base import (
    Capabilities,
    CompletionRequest,
    CompletionResult,
    ProviderError,
    RefusalError,
    StreamEvent,
    TruncatedError,
    Usage,
)
from ros.llm.providers import synthetic

log = structlog.get_logger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "llm"

# Roughly the ratio Claude 4.7+ models produce; only used so a fake `llm_calls` row
# and the cost charts in a demo are not obviously wrong.
_CHARS_PER_TOKEN = 3.6
_CHUNK_WORDS = 6


@dataclass(frozen=True, slots=True)
class ScriptedReply:
    """One entry from a fixture file."""

    text: str = ""
    parsed: Any = None
    match: str | None = None
    stop_reason: str | None = "end_turn"
    status: str = "ok"

    def matches(self, request_text: str) -> bool:
        return self.match is None or self.match.lower() in request_text.lower()


class FakeProvider:
    """Deterministic stand-in for any provider. Never opens a socket."""

    name = "fake"
    capabilities = Capabilities(
        streaming=True,
        structured_outputs=True,
        prompt_cache_control=True,
        thinking=True,
        effort_levels=("low", "medium", "high", "xhigh", "max"),
        max_context=1_000_000,
        min_cache_prefix_tokens=0,
    )

    def __init__(
        self,
        *,
        delay: float = 0.0,
        fixtures_dir: Path | str | None = None,
        provider_name: str = "fake",
        chunk_words: int = _CHUNK_WORDS,
    ) -> None:
        # `delay` is the per-chunk pause when streaming: 0 in tests, ~0.02 for a demo
        # where a wall of instant text would look broken.
        self.delay = delay
        self.chunk_words = max(1, chunk_words)
        self.provider_name = provider_name
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir is not None else FIXTURES_DIR
        self._fixtures: dict[str, list[ScriptedReply]] = {}

    # ------------------------------------------------------------------- requests

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        reply = self._reply_for(request)
        text = (
            reply.text
            if reply and reply.text
            else synthetic.chat_reply(spec.last_user_text(request), self._rng(request))
        )
        self._raise_if_scripted_failure(reply)
        return self._result(request, text, stop_reason=_stop_reason(reply))

    async def complete_structured(
        self, request: CompletionRequest, schema: type[Any]
    ) -> CompletionResult:
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise TypeError("structured output needs a Pydantic model")

        reply = self._reply_for(request)
        self._raise_if_scripted_failure(reply)
        if reply is not None and reply.parsed is not None:
            parsed: BaseModel = schema.model_validate(reply.parsed)
        else:
            parsed = synthetic.build(schema, spec.readable_text(request), self._rng(request))

        result = self._result(
            request, parsed.model_dump_json(indent=2), stop_reason=_stop_reason(reply)
        )
        result.parsed = parsed
        return result

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        reply = self._reply_for(request)
        self._raise_if_scripted_failure(reply)
        text = (
            reply.text
            if reply and reply.text
            else synthetic.chat_reply(spec.last_user_text(request), self._rng(request))
        )

        if request.thinking and spec.thinking_display_of(request) == "summarized":
            yield StreamEvent(kind="thinking", text="Looking back over what you have said…")
            await self._pause()

        for chunk in _chunks(text, self.chunk_words):
            yield StreamEvent(kind="text", text=chunk)
            await self._pause()

        result = self._result(request, text, stop_reason=_stop_reason(reply))
        yield StreamEvent(kind="usage", result=result)
        yield StreamEvent(kind="done", result=result)

    async def count_tokens(self, request: CompletionRequest) -> int | None:
        return _tokens(spec.readable_text(request))

    # -------------------------------------------------------------------- innards

    def _rng(self, request: CompletionRequest) -> Random:
        seed = hashlib.sha256(f"{request.task}\x00{spec.readable_text(request)}".encode()).digest()
        return Random(int.from_bytes(seed[:8], "big"))

    def _result(
        self, request: CompletionRequest, text: str, *, stop_reason: str | None
    ) -> CompletionResult:
        prompt_tokens = _tokens(spec.readable_text(request))
        cached = sum(_tokens(block.text) for block in request.system_blocks if block.cache) + sum(
            _tokens(message.content) for message in request.messages if message.cache
        )
        return CompletionResult(
            text=text,
            usage=Usage(
                input_tokens=max(prompt_tokens - cached, 0),
                output_tokens=_tokens(text),
                cache_read_tokens=cached,
                cache_write_tokens=0,
            ),
            model=spec.model_of(request),
            provider=self.provider_name,
            stop_reason=stop_reason,
            latency_ms=int(self.delay * 1000),
            request_id=f"fake_{hashlib.sha1(text.encode()).hexdigest()[:16]}",
        )

    async def _pause(self) -> None:
        if self.delay > 0:
            await asyncio.sleep(self.delay)

    def _raise_if_scripted_failure(self, reply: ScriptedReply | None) -> None:
        """A fixture can script the failures the engine has to survive."""
        if reply is None or reply.status == "ok":
            return
        if reply.status == "refused":
            raise RefusalError("scripted refusal", category="scripted")
        if reply.status == "truncated":
            raise TruncatedError("scripted max_tokens")
        raise ProviderError(f"scripted {reply.status}", retryable=reply.status == "error")

    # ------------------------------------------------------------------- fixtures

    def _reply_for(self, request: CompletionRequest) -> ScriptedReply | None:
        replies = self._load(request.task)
        if not replies:
            return None
        request_text = spec.readable_text(request)
        for reply in replies:
            if reply.matches(request_text):
                return reply
        return None

    def _load(self, task: str) -> list[ScriptedReply]:
        cached = self._fixtures.get(task)
        if cached is not None:
            return cached

        path = self.fixtures_dir / f"{task}.json"
        replies: list[ScriptedReply] = []
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ProviderError(f"{path} is not valid JSON: {exc}", retryable=False) from exc
            entries = raw if isinstance(raw, list) else raw.get("replies") or [raw]
            replies = [_scripted(entry) for entry in entries if isinstance(entry, dict)]
            log.debug("fake.fixture_loaded", task=task, replies=len(replies))

        self._fixtures[task] = replies
        return replies

    def reload_fixtures(self) -> None:
        self._fixtures.clear()


# ------------------------------------------------------------------------ helpers


def _scripted(entry: dict[str, Any]) -> ScriptedReply:
    return ScriptedReply(
        text=str(entry.get("text") or ""),
        parsed=entry.get("parsed"),
        match=str(entry["match"]) if entry.get("match") else None,
        stop_reason=entry.get("stop_reason", "end_turn"),
        status=str(entry.get("status") or "ok"),
    )


def _stop_reason(reply: ScriptedReply | None) -> str | None:
    return reply.stop_reason if reply is not None else "end_turn"


def _chunks(text: str, words_per_chunk: int) -> list[str]:
    """Split on whitespace but keep it, so the joined chunks equal the original."""
    pieces = text.split(" ")
    return [
        " ".join(pieces[index : index + words_per_chunk])
        + (" " if index + words_per_chunk < len(pieces) else "")
        for index in range(0, len(pieces), words_per_chunk)
    ]


def _tokens(text: str) -> int:
    return max(1, round(len(text) / _CHARS_PER_TOKEN)) if text else 0
