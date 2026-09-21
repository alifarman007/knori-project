"""Anthropic adapter. One of only two places in the repo allowed to import `anthropic`.

Verified against the installed SDK (`anthropic` 1.7.0) on 2026-09-21:

* ``messages.parse(..., output_format=Model)`` returns a ``ParsedMessage`` whose
  ``.parsed_output`` is the validated model;
* ``messages.stream(...)`` takes ``output_config={"format": {...}}`` — we send the
  schema that way and validate the final text ourselves, so one bad field costs one
  item rather than the whole batch;
* ``create``/``stream``/``parse`` accept no ``temperature``, ``top_p``, ``top_k`` or
  ``budget_tokens`` at all — depth is ``output_config={"effort": ...}``;
* the refusal fallback (``fallbacks``, ``betas``) lives on ``client.beta.messages``;
* ``usage.cache_creation`` splits cache writes into 5-minute and 1-hour buckets.

Never prefill an assistant turn: Opus 5 and Sonnet 5 return 400.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import anthropic
import structlog
from anthropic import AsyncAnthropic
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

# `fallbacks: "default"` lets the server pick by refusal category, so we never have
# to maintain a model list. The array form uses the older -06-01 beta instead.
FALLBACK_BETA_DEFAULT = "server-side-fallback-2026-07-01"
FALLBACK_BETA_EXPLICIT = "server-side-fallback-2026-06-01"

DEFAULT_TIMEOUT = 600.0


class AnthropicProvider:
    """Claude, through the official async SDK."""

    name = "anthropic"
    capabilities = Capabilities(
        streaming=True,
        structured_outputs=True,
        prompt_cache_control=True,
        thinking=True,
        effort_levels=("low", "medium", "high", "xhigh", "max"),
        max_context=1_000_000,
        # Model-dependent (512 to 4096); measured in the week-2 live test. A prefix
        # below the real minimum silently does not cache.
        min_cache_prefix_tokens=2048,
    )

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        max_retries: int = 2,
        timeout: float = DEFAULT_TIMEOUT,
        client: AsyncAnthropic | None = None,
    ) -> None:
        # The SDK's own retries are the only retry layer inside the adapter; job-level
        # retries are the second layer and skip typed failures (plan.md §3.4).
        self._client = client or AsyncAnthropic(
            api_key=api_key or None,
            base_url=base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

    # ------------------------------------------------------------------- requests

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        namespace, extra = self._namespace(request)
        started = time.perf_counter()
        try:
            message = await namespace.create(**self._params(request), **extra)
        except (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.APIError) as exc:
            raise self._error(request, exc) from exc
        return self._result(request, message, started)

    async def complete_structured(
        self, request: CompletionRequest, schema: type[Any]
    ) -> CompletionResult:
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise TypeError("structured output needs a Pydantic model")

        if request.stream:
            return await self._structured_stream(request, schema)

        namespace, extra = self._namespace(request)
        started = time.perf_counter()
        try:
            message = await namespace.parse(**self._params(request), output_format=schema, **extra)
        except (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.APIError) as exc:
            raise self._error(request, exc) from exc

        result = self._result(request, message, started)
        result.parsed = getattr(message, "parsed_output", None) or _validate(
            schema, result.text, request
        )
        return result

    async def _structured_stream(
        self, request: CompletionRequest, schema: type[BaseModel]
    ) -> CompletionResult:
        """The long calls (interpret, 16k tokens) stream so no HTTP timeout can bite."""
        params = self._params(request)
        params["output_config"] = {
            **params.get("output_config", {}),
            "format": {"type": "json_schema", "schema": spec.json_schema_for(schema)},
        }
        namespace, extra = self._namespace(request)
        started = time.perf_counter()
        try:
            async with namespace.stream(**params, **extra) as stream:
                message = await stream.get_final_message()
        except (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.APIError) as exc:
            raise self._error(request, exc) from exc

        result = self._result(request, message, started)
        result.parsed = _validate(schema, result.text, request)
        return result

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        namespace, extra = self._namespace(request)
        started = time.perf_counter()
        try:
            async with namespace.stream(**self._params(request), **extra) as stream:
                async for event in stream:
                    kind = getattr(event, "type", "")
                    if kind == "text":
                        yield StreamEvent(kind="text", text=event.text)
                    elif kind == "thinking":
                        yield StreamEvent(kind="thinking", text=event.thinking)
                message = await stream.get_final_message()
        except (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.APIError) as exc:
            raise self._error(request, exc) from exc

        result = self._result(request, message, started)
        yield StreamEvent(kind="usage", result=result)
        yield StreamEvent(kind="done", result=result)

    async def count_tokens(self, request: CompletionRequest) -> int | None:
        params = self._params(request)
        params.pop("max_tokens", None)
        params.pop("metadata", None)
        params.pop("output_config", None)
        try:
            counted = await self._client.messages.count_tokens(**params)
        except (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.APIError):
            return None
        return int(counted.input_tokens)

    # -------------------------------------------------------------------- mapping

    def _params(self, request: CompletionRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": spec.model_of(request),
            "max_tokens": spec.max_tokens_of(request),
            "messages": [
                _message(message, spec.cache_ttl_of(request)) for message in request.messages
            ],
            "thinking": (
                {"type": "adaptive", "display": spec.thinking_display_of(request)}
                if request.thinking
                else {"type": "disabled"}
            ),
        }
        system = [_text_block(block, spec.cache_ttl_of(request)) for block in request.system_blocks]
        if system:
            params["system"] = system

        effort = spec.effort_of(request)
        if effort is not None:
            params["output_config"] = {"effort": effort}

        user_id = spec.user_id_of(request)
        if user_id:
            params["metadata"] = {"user_id": user_id}
        return params

    def _namespace(self, request: CompletionRequest) -> tuple[Any, dict[str, Any]]:
        """The beta namespace plus its flags when this route wants a refusal fallback."""
        if not spec.refusal_fallback_of(request):
            return self._client.messages, {}
        explicit = spec.fallback_model_of(request)
        if explicit:
            return self._client.beta.messages, {
                "betas": [FALLBACK_BETA_EXPLICIT],
                "fallbacks": [{"model": explicit}],
            }
        return self._client.beta.messages, {
            "betas": [FALLBACK_BETA_DEFAULT],
            "fallbacks": "default",
        }

    def _result(self, request: CompletionRequest, message: Any, started: float) -> CompletionResult:
        request_id = getattr(message, "_request_id", None)
        stop_reason = getattr(message, "stop_reason", None)

        if stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            log.warning(
                "anthropic.refused",
                task=request.task,
                category=category,
                request_id=request_id,
            )
            raise RefusalError(
                f"model refused ({category or 'unknown'})",
                category=category,
                request_id=request_id,
            )
        if stop_reason == "max_tokens":
            raise TruncatedError(
                f"hit max_tokens ({spec.max_tokens_of(request)}); retry once at lower effort",
                request_id=request_id,
            )
        if stop_reason == "model_context_window_exceeded":
            raise ProviderError(
                "input is larger than the model's context window",
                retryable=False,
                request_id=request_id,
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        return CompletionResult(
            text=text,
            usage=_usage(getattr(message, "usage", None)),
            # The model that ANSWERED — a refusal fallback can change it, and
            # llm_calls is priced from this, not from what we asked for.
            model=str(getattr(message, "model", "") or spec.model_of(request)),
            provider=self.name,
            stop_reason=stop_reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_id=request_id,
        )

    def _error(self, request: CompletionRequest, exc: Exception) -> ProviderError:
        request_id = getattr(exc, "request_id", None)
        status = getattr(exc, "status_code", None)
        log.warning(
            "anthropic.call_failed",
            task=request.task,
            status=status,
            request_id=request_id,
            error=type(exc).__name__,
        )
        if isinstance(exc, anthropic.RateLimitError):
            return ProviderError(f"rate limited: {exc}", retryable=True, request_id=request_id)
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderError(
                f"anthropic {status}: {exc}",
                retryable=bool(status and status >= 500),
                request_id=request_id,
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderError(f"cannot reach anthropic: {exc}", retryable=True)
        return ProviderError(str(exc), retryable=False, request_id=request_id)


# ------------------------------------------------------------------------ helpers


def _cache_control(ttl: str | None, default_ttl: str) -> dict[str, str]:
    return {"type": "ephemeral", "ttl": ttl or default_ttl}


def _text_block(block: Any, default_ttl: str) -> dict[str, Any]:
    wire: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        wire["cache_control"] = _cache_control(block.ttl, default_ttl)
    return wire


def _message(message: Any, default_ttl: str) -> dict[str, Any]:
    if not message.cache:
        return {"role": message.role, "content": message.content}
    return {
        "role": message.role,
        "content": [
            {
                "type": "text",
                "text": message.content,
                "cache_control": _cache_control(None, default_ttl),
            }
        ],
    }


def _usage(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
    )


def _validate(schema: type[BaseModel], text: str, request: CompletionRequest) -> Any:
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        raise ProviderError(
            f"{request.task}: model returned a {schema.__name__} that does not validate: {exc}",
            retryable=False,
        ) from exc
