"""OpenAI adapter. The other place in the repo allowed to import `openai`.

Phase 5 of the proposal asks that ROS stay reasonably model-agnostic, so every
engine task must be able to run on GPT by changing one line of
``config/model_routing.yaml``. This adapter is what makes that true.

Verified against the installed SDK (`openai` 3.16.2) on 2026-09-21: Responses API,
``store=False``, system blocks become ``instructions``, effort becomes
``reasoning={"effort": ...}``, structured output through ``responses.parse(
text_format=Model)`` → ``.output_parsed``, streaming through ``responses.stream()``
→ ``get_final_response()``. Prompt-cache flags are ignored: OpenAI caches prefixes
by itself.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import openai
import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

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

log = structlog.get_logger(__name__)

# What the gpt-5.6 family accepts. A model without a level gets the next one down.
GPT56_EFFORT_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
_LADDER = ("max", "xhigh", "high", "medium", "low", "minimal", "none")

DEFAULT_TIMEOUT = 600.0


class OpenAIProvider:
    """GPT, through the Responses API."""

    name = "openai"
    capabilities = Capabilities(
        streaming=True,
        structured_outputs=True,
        prompt_cache_control=False,  # automatic, not steerable
        thinking=True,
        effort_levels=("low", "medium", "high", "xhigh", "max"),
        max_context=400_000,
        min_cache_prefix_tokens=1024,
    )

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        max_retries: int = 2,
        timeout: float = DEFAULT_TIMEOUT,
        effort_levels: tuple[str, ...] = GPT56_EFFORT_LEVELS,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._effort_levels = effort_levels
        self._client = client or AsyncOpenAI(
            api_key=api_key or None,
            base_url=base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

    # ------------------------------------------------------------------- requests

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        try:
            response = await self._client.responses.create(**self._params(request))
        except (openai.APIStatusError, openai.APIConnectionError, openai.APIError) as exc:
            raise self._error(request, exc) from exc
        return self._result(request, response, started)

    async def complete_structured(
        self, request: CompletionRequest, schema: type[Any]
    ) -> CompletionResult:
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise TypeError("structured output needs a Pydantic model")

        started = time.perf_counter()
        try:
            response = await self._client.responses.parse(
                **self._params(request), text_format=schema
            )
        except (openai.APIStatusError, openai.APIConnectionError, openai.APIError) as exc:
            raise self._error(request, exc) from exc

        result = self._result(request, response, started)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            try:
                parsed = schema.model_validate_json(result.text)
            except ValidationError as exc:
                raise ProviderError(
                    f"{request.task}: {schema.__name__} did not validate: {exc}", retryable=False
                ) from exc
        result.parsed = parsed
        return result

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        try:
            async with self._client.responses.stream(**self._params(request)) as stream:
                async for event in stream:
                    # The Responses stream carries sixty-odd event types; only the two
                    # delta events below have text for a reader.
                    kind = getattr(event, "type", "")
                    if kind == "response.output_text.delta":
                        yield StreamEvent(kind="text", text=str(getattr(event, "delta", "")))
                    elif kind == "response.reasoning_summary_text.delta":
                        yield StreamEvent(kind="thinking", text=str(getattr(event, "delta", "")))
                response = await stream.get_final_response()
        except (openai.APIStatusError, openai.APIConnectionError, openai.APIError) as exc:
            raise self._error(request, exc) from exc

        result = self._result(request, response, started)
        yield StreamEvent(kind="usage", result=result)
        yield StreamEvent(kind="done", result=result)

    async def count_tokens(self, request: CompletionRequest) -> int | None:
        return None  # no equivalent of the Anthropic token-counting endpoint

    # -------------------------------------------------------------------- mapping

    def _params(self, request: CompletionRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": spec.model_of(request),
            "input": [
                {"role": message.role, "content": message.content} for message in request.messages
            ],
            "max_output_tokens": spec.max_tokens_of(request),
            "store": False,  # never leave conversation content on OpenAI's servers
        }
        instructions = "\n\n".join(block.text for block in request.system_blocks if block.text)
        if instructions:
            params["instructions"] = instructions
        params["reasoning"] = {"effort": self._effort(request)}

        user_id = spec.user_id_of(request)
        if user_id:
            params["safety_identifier"] = user_id
        return params

    def _effort(self, request: CompletionRequest) -> str:
        wanted = "none" if not request.thinking else (request.effort or "medium")
        if wanted in self._effort_levels:
            return wanted
        # Map down the ladder to the nearest level this model does have.
        start = _LADDER.index(wanted) if wanted in _LADDER else _LADDER.index("medium")
        for level in _LADDER[start:]:
            if level in self._effort_levels:
                log.info("openai.effort_mapped", task=request.task, wanted=wanted, used=level)
                return level
        return self._effort_levels[-1]

    def _result(
        self, request: CompletionRequest, response: Any, started: float
    ) -> CompletionResult:
        request_id = getattr(response, "_request_id", None) or getattr(response, "id", None)

        refusal = _refusal_of(response)
        if refusal is not None:
            log.warning("openai.refused", task=request.task, request_id=request_id)
            raise RefusalError(f"model refused: {refusal}", request_id=request_id)

        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None)
        if reason == "max_output_tokens":
            raise TruncatedError(
                f"hit max_output_tokens ({spec.max_tokens_of(request)}); retry at lower effort",
                request_id=request_id,
            )
        error = getattr(response, "error", None)
        if error is not None:
            raise ProviderError(
                f"openai returned an error: {getattr(error, 'message', error)}",
                retryable=False,
                request_id=request_id,
            )

        return CompletionResult(
            text=getattr(response, "output_text", "") or "",
            usage=_usage(getattr(response, "usage", None)),
            model=str(getattr(response, "model", "") or spec.model_of(request)),
            provider=self.name,
            stop_reason=reason or getattr(response, "status", None),
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_id=request_id,
        )

    def _error(self, request: CompletionRequest, exc: Exception) -> ProviderError:
        request_id = getattr(exc, "request_id", None)
        status = getattr(exc, "status_code", None)
        log.warning(
            "openai.call_failed",
            task=request.task,
            status=status,
            request_id=request_id,
            error=type(exc).__name__,
        )
        if isinstance(exc, openai.RateLimitError):
            return ProviderError(f"rate limited: {exc}", retryable=True, request_id=request_id)
        if isinstance(exc, openai.APIStatusError):
            return ProviderError(
                f"openai {status}: {exc}",
                retryable=bool(status and status >= 500),
                request_id=request_id,
            )
        if isinstance(exc, openai.APIConnectionError):
            return ProviderError(f"cannot reach openai: {exc}", retryable=True)
        return ProviderError(str(exc), retryable=False, request_id=request_id)


# ------------------------------------------------------------------------ helpers


def _refusal_of(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            if getattr(block, "type", "") == "refusal":
                return str(getattr(block, "refusal", "")) or "refused"
    return None


def _usage(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    details = getattr(usage, "input_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0)
    total_input = int(getattr(usage, "input_tokens", 0) or 0)
    return Usage(
        # OpenAI counts cached tokens inside input_tokens; we bill them separately.
        input_tokens=max(total_input - cached, 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_tokens=cached,
        cache_write_tokens=int(getattr(details, "cache_write_tokens", 0) or 0),
    )
