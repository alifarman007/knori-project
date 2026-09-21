"""Provider-neutral types for talking to a language model.

Product code never imports `anthropic` or `openai`; it calls ``router.run(task, ...)``
and the router picks a provider from ``config/model_routing.yaml``. Swapping Claude
for GPT on any task is therefore a config change, which is what Phase 5 of the
proposal ("ROS should stay reasonably model-agnostic") needs us to prove now.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Role = Literal["user", "assistant"]


class ProviderError(RuntimeError):
    """Anything that went wrong while calling a model."""

    def __init__(self, message: str, *, retryable: bool = False, request_id: str | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.request_id = request_id


class RefusalError(ProviderError):
    """The model declined the request (``stop_reason='refusal'``). Never retried."""

    def __init__(self, message: str, *, category: str | None = None, request_id: str | None = None):
        super().__init__(message, retryable=False, request_id=request_id)
        self.category = category


class TruncatedError(ProviderError):
    """Output hit ``max_tokens``; thinking tokens count towards it. Retry once, lower effort."""


@dataclass(slots=True)
class SystemBlock:
    text: str
    cache: bool = False
    ttl: str | None = None  # "5m" (default) or "1h"; 1h writes cost 2x input


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str
    cache: bool = False


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(slots=True)
class CompletionRequest:
    task: str
    system_blocks: list[SystemBlock] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)
    max_tokens: int = 4000
    thinking: bool = True
    effort: Effort | None = "medium"
    stream: bool = False
    # Free-form context for logging: user_id, job_id, prompt name/version.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def user_id(self) -> uuid.UUID | None:
        value = self.metadata.get("user_id")
        return uuid.UUID(str(value)) if value else None


@dataclass(slots=True)
class CompletionResult:
    text: str
    usage: Usage
    model: str
    provider: str
    stop_reason: str | None = None
    latency_ms: int = 0
    request_id: str | None = None
    parsed: Any = None
    cost_usd: float = 0.0


@dataclass(slots=True)
class StreamEvent:
    kind: Literal["text", "thinking", "usage", "done", "error"]
    text: str = ""
    result: CompletionResult | None = None
    error: str | None = None


@dataclass(slots=True)
class Capabilities:
    streaming: bool = True
    structured_outputs: bool = True
    prompt_cache_control: bool = False
    thinking: bool = False
    effort_levels: tuple[str, ...] = ()
    max_context: int = 200_000
    # Prefixes shorter than this never cache; measured in the week-2 live test.
    min_cache_prefix_tokens: int = 1024


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    capabilities: Capabilities

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    async def complete_structured(
        self, request: CompletionRequest, schema: type[Any]
    ) -> CompletionResult: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]: ...

    async def count_tokens(self, request: CompletionRequest) -> int | None: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
