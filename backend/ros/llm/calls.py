"""The two edges of one model call: building the request, and writing the ledger row.

Kept out of ``router.py`` so that file stays what it says it is — task resolution and
orchestration — and so both edges can be tested without a router.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ros.llm import spec
from ros.llm.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    ProviderError,
    RefusalError,
    SystemBlock,
    TruncatedError,
    Usage,
)
from ros.llm.cost import PricingTable, record_call
from ros.llm.errors import LLMConfigError, PromptNotFoundError
from ros.llm.registry import PromptRegistry, RenderedPrompt
from ros.llm.routing import Route

log = structlog.get_logger(__name__)

Clock = Callable[[], datetime]


def render_prompt(
    registry: PromptRegistry,
    route: Route,
    prompt: str | None,
    variables: Mapping[str, Any] | None,
) -> RenderedPrompt | None:
    """The prompt this route pins, filled in. ``None`` when the task has no prompt file."""
    name = prompt or route.prompt
    if not name:
        return None
    try:
        return registry.render(name, route.prompt_version, **(variables or {}))
    except PromptNotFoundError:
        if prompt is not None:
            raise
        # A task can be routed before its prompt file is merged; the caller then
        # supplies the text through `system` / `messages` instead.
        log.warning("router.prompt_missing", task=route.task, prompt=name)
        return None


def build_request(
    route: Route,
    rendered: RenderedPrompt | None,
    *,
    system: str | Sequence[SystemBlock] | None = None,
    messages: str | Sequence[ChatMessage] | None = None,
    user_id: uuid.UUID | str | None = None,
    job_id: uuid.UUID | str | None = None,
    cache_system: bool = False,
) -> CompletionRequest:
    """Where the rendered prompt goes depends on whether there is a conversation.

    With no ``messages`` the task is single-shot (extract, interpret, compose): the
    template already holds every piece of data, so it becomes the user turn. With
    ``messages`` (chat) the template is the instruction, so it becomes the cacheable
    system prefix instead.
    """
    system_blocks = _as_system_blocks(system, route.cache_ttl)
    chat = _as_messages(messages)

    if rendered is not None:
        if chat:
            system_blocks.insert(
                0, SystemBlock(rendered.text, cache=cache_system, ttl=route.cache_ttl)
            )
        else:
            chat = [ChatMessage(role="user", content=rendered.text)]
    if not chat:
        raise LLMConfigError(f"task {route.task!r} has nothing to send")

    metadata: dict[str, Any] = {
        spec.MODEL: route.model,
        spec.CACHE_TTL: route.cache_ttl,
        spec.THINKING_DISPLAY: route.thinking_display,
        spec.REFUSAL_FALLBACK: route.refusal_fallback,
        spec.FALLBACK_MODEL: route.fallback_model,
    }
    if user_id is not None:
        metadata[spec.USER_ID] = str(user_id)
    if job_id is not None:
        metadata[spec.JOB_ID] = str(job_id)
    if rendered is not None:
        metadata[spec.PROMPT_NAME] = rendered.name
        metadata[spec.PROMPT_VERSION] = rendered.version_label
        metadata[spec.PROMPT_HASH] = rendered.sha

    return CompletionRequest(
        task=route.task,
        system_blocks=system_blocks,
        messages=chat,
        max_tokens=max(route.max_tokens, spec.MIN_MAX_TOKENS),
        thinking=route.thinking,
        effort=route.effort,
        stream=route.stream,
        metadata=metadata,
    )


def status_for(exc: ProviderError) -> str:
    if isinstance(exc, RefusalError):
        return "refused"
    if isinstance(exc, TruncatedError):
        return "truncated"
    return "error"


async def record_result(
    session: AsyncSession | None,
    route: Route,
    rendered: RenderedPrompt | None,
    result: CompletionResult,
    request: CompletionRequest,
    *,
    status: str,
    clock: Clock,
    pricing: PricingTable,
    counts_as_chat_message: bool,
    error: str | None = None,
) -> None:
    """One ``llm_calls`` row. Called for every attempt, successful or not."""
    if session is None:
        return
    await record_call(
        session,
        task=route.task,
        provider=result.provider or route.provider,
        model=result.model or route.model,
        status=status,
        usage=result.usage,
        cost_usd=result.cost_usd or None,
        cache_ttl=route.cache_ttl,
        prompt_name=rendered.name if rendered else None,
        prompt_version=rendered.version_label if rendered else None,
        prompt_hash=rendered.sha if rendered else None,
        effort=route.effort,
        latency_ms=result.latency_ms,
        stop_reason=result.stop_reason,
        error=error,
        request_id=result.request_id,
        user_id=request.user_id,
        job_id=spec.job_id_of(request),
        result={"chars": len(result.text)},
        occurred_at=clock(),
        counts_as_chat_message=counts_as_chat_message,
        pricing=pricing,
    )


async def record_failure(
    session: AsyncSession | None,
    route: Route,
    rendered: RenderedPrompt | None,
    exc: ProviderError,
    request: CompletionRequest,
    *,
    started: float,
    clock: Clock,
    pricing: PricingTable,
    counts_as_chat_message: bool,
) -> None:
    """A refusal, a truncation or an error still costs tokens and still gets a row."""
    status = status_for(exc)
    log.warning(
        "llm.call_failed",
        task=route.task,
        provider=route.provider,
        model=route.model,
        status=status,
        retryable=exc.retryable,
        request_id=exc.request_id,
    )
    await record_result(
        session,
        route,
        rendered,
        CompletionResult(
            text="",
            usage=Usage(),
            model=route.model,
            provider=route.provider,
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_id=exc.request_id,
        ),
        request,
        status=status,
        clock=clock,
        pricing=pricing,
        counts_as_chat_message=counts_as_chat_message,
        error=str(exc)[:1000],
    )


def as_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _as_system_blocks(system: str | Sequence[SystemBlock] | None, ttl: str) -> list[SystemBlock]:
    if system is None:
        return []
    if isinstance(system, str):
        return [SystemBlock(system, ttl=ttl)]
    return list(system)


def _as_messages(messages: str | Sequence[ChatMessage] | None) -> list[ChatMessage]:
    if messages is None:
        return []
    if isinstance(messages, str):
        return [ChatMessage(role="user", content=messages)]
    return list(messages)
