"""The one thing product code calls to reach a model.

``await router.run("interpret.recognize", prompt="interpret/recognize", vars={...},
schema=InterpretationBatch, user_id=..., job_id=..., session=...)``

The router resolves the task through ``config/model_routing.yaml``, renders the
versioned prompt, hands a provider-neutral ``CompletionRequest`` to whichever provider
the route names, prices the answer by the model that actually replied, and writes an
``llm_calls`` row for **every** attempt — ok, error, refused or truncated. Nothing
above this layer ever names a model or an SDK.

With ``LLM_MODE=fake`` every task resolves to the fake provider, so the whole app
runs, streams and demos with no API keys at all.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ros.llm import calls, spec
from ros.llm.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    Effort,
    EmbeddingProvider,
    LLMProvider,
    ProviderError,
    StreamEvent,
    SystemBlock,
    Usage,
)
from ros.llm.calls import Clock
from ros.llm.cost import Limits, PricingTable, get_limits, get_pricing, record_call
from ros.llm.errors import LLMConfigError
from ros.llm.registry import PromptRegistry, get_registry
from ros.llm.routing import EFFORT_LEVELS, LLMSettings, Route, RoutingTable, load_routes

log = structlog.get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Router:
    """Task → provider, with the ledger written on the way out."""

    def __init__(
        self,
        *,
        routes: RoutingTable,
        providers: Mapping[str, LLMProvider],
        embedder: EmbeddingProvider,
        registry: PromptRegistry | None = None,
        pricing: PricingTable | None = None,
        limits: Limits | None = None,
        mode: str = "fake",
        clock: Clock = _utc_now,
    ) -> None:
        self.routes = routes
        self.providers = dict(providers)
        self.embedder = embedder
        self.registry = registry or get_registry()
        self.pricing = pricing or get_pricing()
        self.limits = limits or get_limits()
        self.mode = mode
        # `ros` cannot import `knori.core.clock`, so the product passes `now` in.
        self.clock = clock

    # ------------------------------------------------------------------ resolution

    def route(self, task: str) -> Route:
        return self.routes.resolve(task)

    def provider_for(self, route: Route) -> LLMProvider:
        try:
            return self.providers[route.provider]
        except KeyError:
            raise LLMConfigError(
                f"task {route.task!r} wants provider {route.provider!r}, which is not configured"
            ) from None

    def validate(self) -> list[str]:
        """Every problem the routing file has, as plain sentences. Called at boot."""
        problems: list[str] = []
        for route in self.routes:
            if route.is_embedding:
                if route.dimensions and route.dimensions != self.embedder.dimensions:
                    problems.append(
                        f"{route.pattern}: routing says {route.dimensions} dimensions, "
                        f"{self.embedder.model_id} returns {self.embedder.dimensions}"
                    )
                continue

            provider = self.providers.get(route.provider)
            if provider is None:
                problems.append(f"{route.pattern}: unknown provider {route.provider!r}")
                continue
            capabilities = provider.capabilities
            if route.max_tokens < spec.MIN_MAX_TOKENS:
                problems.append(
                    f"{route.pattern}: max_tokens {route.max_tokens} is below "
                    f"{spec.MIN_MAX_TOKENS}; thinking tokens count against it"
                )
            if route.thinking and not capabilities.thinking:
                problems.append(f"{route.pattern}: {provider.name} cannot think")
            if route.effort and route.effort not in capabilities.effort_levels:
                problems.append(
                    f"{route.pattern}: {provider.name} has no effort level {route.effort!r}"
                )
            if route.stream and not capabilities.streaming:
                problems.append(f"{route.pattern}: {provider.name} cannot stream")
            if route.schema_name and not capabilities.structured_outputs:
                problems.append(f"{route.pattern}: {provider.name} has no structured output")
        return problems

    def validate_or_raise(self) -> None:
        problems = self.validate()
        if problems:
            raise LLMConfigError("model routing is not usable:\n  " + "\n  ".join(problems))

    # ------------------------------------------------------------------- one call

    async def run(
        self,
        task: str,
        *,
        prompt: str | None = None,
        vars: Mapping[str, Any] | None = None,
        schema: type[BaseModel] | None = None,
        system: str | Sequence[SystemBlock] | None = None,
        messages: str | Sequence[ChatMessage] | None = None,
        user_id: uuid.UUID | str | None = None,
        job_id: uuid.UUID | str | None = None,
        session: AsyncSession | None = None,
        effort: Effort | None = None,
        max_tokens: int | None = None,
        cache_system: bool = False,
        counts_as_chat_message: bool = False,
    ) -> CompletionResult:
        route = self._adjust(self.route(task), effort=effort, max_tokens=max_tokens)
        rendered = calls.render_prompt(self.registry, route, prompt, vars)
        request = calls.build_request(
            route,
            rendered,
            system=system,
            messages=messages,
            user_id=user_id,
            job_id=job_id,
            cache_system=cache_system,
        )
        provider = self.provider_for(route)

        started = time.perf_counter()
        try:
            result = (
                await provider.complete_structured(request, schema)
                if schema is not None
                else await provider.complete(request)
            )
        except ProviderError as exc:
            await calls.record_failure(
                session,
                route,
                rendered,
                exc,
                request,
                started=started,
                clock=self.clock,
                pricing=self.pricing,
                counts_as_chat_message=counts_as_chat_message,
            )
            raise

        await self._finish(session, route, rendered, result, request, counts_as_chat_message)
        return result

    async def stream(
        self,
        task: str,
        *,
        prompt: str | None = None,
        vars: Mapping[str, Any] | None = None,
        system: str | Sequence[SystemBlock] | None = None,
        messages: str | Sequence[ChatMessage] | None = None,
        user_id: uuid.UUID | str | None = None,
        job_id: uuid.UUID | str | None = None,
        session: AsyncSession | None = None,
        effort: Effort | None = None,
        max_tokens: int | None = None,
        cache_system: bool = False,
        counts_as_chat_message: bool = True,
    ) -> AsyncIterator[StreamEvent]:
        """Text and thinking deltas, then one ``done`` event carrying the result."""
        route = replace(
            self._adjust(self.route(task), effort=effort, max_tokens=max_tokens), stream=True
        )
        rendered = calls.render_prompt(self.registry, route, prompt, vars)
        request = calls.build_request(
            route,
            rendered,
            system=system,
            messages=messages,
            user_id=user_id,
            job_id=job_id,
            cache_system=cache_system,
        )
        provider = self.provider_for(route)

        started = time.perf_counter()
        try:
            async for event in provider.stream(request):
                if event.kind == "done" and event.result is not None:
                    await self._finish(
                        session, route, rendered, event.result, request, counts_as_chat_message
                    )
                yield event
        except ProviderError as exc:
            await calls.record_failure(
                session,
                route,
                rendered,
                exc,
                request,
                started=started,
                clock=self.clock,
                pricing=self.pricing,
                counts_as_chat_message=counts_as_chat_message,
            )
            yield StreamEvent(kind="error", error=str(exc))
            raise

    async def embed(
        self,
        texts: Sequence[str],
        *,
        task: str = "embed.text",
        user_id: uuid.UUID | str | None = None,
        job_id: uuid.UUID | str | None = None,
        session: AsyncSession | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        route = self.route(task)
        started = time.perf_counter()
        with_usage = getattr(self.embedder, "embed_with_usage", None)
        if callable(with_usage):
            vectors, usage = await with_usage(list(texts))
        else:
            vectors = await self.embedder.embed(list(texts))
            usage = Usage(input_tokens=sum(len(text) for text in texts) // 4)

        if session is not None:
            await record_call(
                session,
                task=task,
                provider=route.provider,
                model=self.embedder.model_id,
                status="ok",
                usage=usage,
                latency_ms=int((time.perf_counter() - started) * 1000),
                user_id=calls.as_uuid(user_id),
                job_id=calls.as_uuid(job_id),
                result={"texts": len(texts), "dimensions": self.embedder.dimensions},
                occurred_at=self.clock(),
                pricing=self.pricing,
            )
        return vectors

    async def count_tokens(self, task: str, request: CompletionRequest) -> int | None:
        return await self.provider_for(self.route(task)).count_tokens(request)

    # ------------------------------------------------------------------- internals

    def _adjust(self, route: Route, *, effort: Effort | None, max_tokens: int | None) -> Route:
        if effort is not None:
            if effort not in EFFORT_LEVELS:
                raise LLMConfigError(f"unknown effort {effort!r}")
            route = replace(route, effort=effort)
        if max_tokens is not None:
            route = replace(route, max_tokens=max(max_tokens, spec.MIN_MAX_TOKENS))
        return route

    async def _finish(
        self,
        session: AsyncSession | None,
        route: Route,
        rendered: Any,
        result: CompletionResult,
        request: CompletionRequest,
        counts_as_chat_message: bool,
    ) -> None:
        # Priced by the model that answered, which a refusal fallback can change.
        result.cost_usd = self.pricing.price(result.model, result.usage, cache_ttl=route.cache_ttl)
        await calls.record_result(
            session,
            route,
            rendered,
            result,
            request,
            status="ok",
            clock=self.clock,
            pricing=self.pricing,
            counts_as_chat_message=counts_as_chat_message,
        )


# -------------------------------------------------------------------- construction


def build_router(
    settings: LLMSettings | Any | None = None,
    *,
    registry: PromptRegistry | None = None,
    clock: Clock = _utc_now,
    fake_delay: float = 0.0,
) -> Router:
    """Build a router from ``config/``.

    ``settings`` may be an ``LLMSettings`` or anything with the same attribute names —
    ``knori.core.config.Settings`` is what the product passes, and passing it is what
    makes the ``.env`` file take effect. In fake mode no API key is read and no
    provider SDK is imported.
    """
    from ros.llm.cost import load_limits, load_pricing
    from ros.llm.embeddings.fake import FakeEmbeddingProvider
    from ros.llm.providers.fake import FakeProvider

    resolved = (
        settings
        if isinstance(settings, LLMSettings)
        else LLMSettings.from_object(settings)
        if settings is not None
        else LLMSettings.from_env()
    )
    config_dir = resolved.config_dir
    routes = load_routes(config_dir / "model_routing.yaml", settings=resolved)
    pricing = load_pricing(config_dir / "pricing.yaml")
    limits = load_limits(config_dir / "limits.yaml")
    needed = {route.provider for route in routes.values() if not route.is_embedding}

    providers: dict[str, LLMProvider]
    embedder: EmbeddingProvider
    if resolved.is_fake:
        fake = FakeProvider(delay=fake_delay)
        providers = dict.fromkeys(needed | {"anthropic", "openai"}, fake)
        embedder = FakeEmbeddingProvider()
    else:
        providers = _live_providers(needed, resolved)
        embedder = _live_embedder(routes, resolved)

    return Router(
        routes=RoutingTable(routes),
        providers=providers,
        embedder=embedder,
        registry=registry,
        pricing=pricing,
        limits=limits,
        mode="fake" if resolved.is_fake else "live",
        clock=clock,
    )


def _live_providers(needed: set[str], settings: LLMSettings) -> dict[str, LLMProvider]:
    from ros.llm.providers.anthropic_provider import AnthropicProvider
    from ros.llm.providers.openai_provider import OpenAIProvider

    providers: dict[str, LLMProvider] = {}
    for name in needed:
        key = settings.api_key_for(name)
        if not key:
            raise LLMConfigError(f"LLM_MODE=live but no API key for provider {name!r}")
        providers[name] = (
            AnthropicProvider(api_key=key)
            if name.startswith("anthropic")
            else OpenAIProvider(api_key=key)
        )
    return providers


def _live_embedder(routes: Mapping[str, Route], settings: LLMSettings) -> EmbeddingProvider:
    from ros.llm.embeddings.openai_embeddings import OpenAIEmbeddings

    if not settings.openai_api_key:
        raise LLMConfigError("LLM_MODE=live needs OPENAI_API_KEY for embeddings")
    route = next((entry for entry in routes.values() if entry.is_embedding), None)
    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=route.model if route else "text-embedding-3-small",
        dimensions=(route.dimensions if route else None) or 1536,
        batch_size=route.batch_size if route else 64,
    )


_router: Router | None = None


def get_router() -> Router:
    """The process-wide router.

    Falls back to ``LLMSettings.from_env()``, which reads the real environment but
    **not** the ``.env`` file — so the product calls ``set_router(build_router(
    settings))`` at start-up rather than relying on this.
    """
    global _router
    if _router is None:
        _router = build_router()
    return _router


def set_router(router: Router | None) -> None:
    """Install the router the product built at start-up (or reset it in tests)."""
    global _router
    _router = router
