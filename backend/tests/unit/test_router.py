"""Task resolution, env overrides, boot validation and one end-to-end fake call.

No network and no database: every test here runs against the fake provider, which is
the same thing CI and a keyless demo run against.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import anthropic
import openai
import pydantic
import pytest
from anthropic.resources.messages import AsyncMessages
from openai.resources.responses import AsyncResponses

from ros.llm import spec
from ros.llm.base import ChatMessage, CompletionRequest, ProviderError, SystemBlock
from ros.llm.errors import LLMConfigError
from ros.llm.providers.anthropic_provider import AnthropicProvider
from ros.llm.providers.openai_provider import OpenAIProvider
from ros.llm.registry import PromptRegistry
from ros.llm.router import Router, build_router
from ros.llm.routing import CONFIG_DIR, LLMSettings, RoutingTable, load_routes
from ros.llm.spec import MIN_MAX_TOKENS
from ros.schemas import llm_io
from ros.schemas.llm_io import InterpretationBatch, SignalExtraction

ROUTING_FILE = CONFIG_DIR / "model_routing.yaml"


@pytest.fixture
def router(tmp_path: Path) -> Router:
    """A fake-mode router whose prompt directory is empty, so tasks send raw text."""
    return build_router(
        LLMSettings(llm_mode="fake", config_dir=CONFIG_DIR),
        registry=PromptRegistry(tmp_path),
    )


# ------------------------------------------------------------------- resolution


def test_every_task_in_the_plan_has_a_route() -> None:
    table = RoutingTable(load_routes(ROUTING_FILE, env={}))

    for task in (
        "chat.reply",
        "interpret.recognize",
        "recognize.compose",
        "correction.parse",
        "claims.same_claim",
        "extract.signals",
        "summarize.conversation",
        "profile.compile",
        "chat.opener",
        "onboarding.parse",
        "embed.text",
    ):
        assert table.resolve(task).model, task


def test_routes_match_the_table_in_plan_6_2() -> None:
    table = RoutingTable(load_routes(ROUTING_FILE, env={}))

    chat = table.resolve("chat.reply")
    assert (chat.model, chat.effort, chat.max_tokens) == ("claude-opus-5", "medium", 8000)
    assert chat.thinking and chat.stream and chat.thinking_display == "summarized"

    interpret = table.resolve("interpret.recognize")
    assert (interpret.model, interpret.effort, interpret.max_tokens) == (
        "claude-opus-5",
        "high",
        16000,
    )

    extract = table.resolve("extract.signals")
    assert (extract.model, extract.max_tokens) == ("claude-sonnet-5", 6000)
    assert not extract.thinking, "Sonnet 5 thinks by default, so utility tasks must opt out"
    assert extract.effort is None


def test_no_task_is_routed_below_the_minimum_max_tokens() -> None:
    for route in load_routes(ROUTING_FILE, env={}).values():
        if not route.is_embedding:
            assert route.max_tokens >= MIN_MAX_TOKENS, route.pattern


def test_eval_judges_resolve_through_the_wildcard() -> None:
    table = RoutingTable(load_routes(ROUTING_FILE, env={}))

    judge = table.resolve("eval.judge_grounding")

    assert judge.model == "claude-opus-5"
    assert judge.task == "eval.judge_grounding"


def test_unknown_task_is_a_config_error() -> None:
    table = RoutingTable(load_routes(ROUTING_FILE, env={}))

    with pytest.raises(LLMConfigError):
        table.resolve("does.not.exist")


# --------------------------------------------------------------- env overrides


def test_env_override_replaces_provider_model_and_effort() -> None:
    routes = load_routes(ROUTING_FILE, env={"KNORI_ROUTE__chat_reply": "openai:gpt-5.6-sol:low"})

    chat = routes["chat.reply"]
    assert (chat.provider, chat.model, chat.effort) == ("openai", "gpt-5.6-sol", "low")
    assert chat.max_tokens == 8000, "an override changes only what it names"


def test_env_override_accepts_the_dotted_task_name() -> None:
    routes = load_routes(ROUTING_FILE, env={"KNORI_ROUTE__chat.reply": "openai::"})

    assert routes["chat.reply"].provider == "openai"
    assert routes["chat.reply"].model == "claude-opus-5", "empty parts keep the file value"


def test_env_override_with_a_bad_effort_is_a_config_error() -> None:
    with pytest.raises(LLMConfigError):
        load_routes(ROUTING_FILE, env={"KNORI_ROUTE__chat_reply": "anthropic::turbo"})


def test_openai_model_placeholders_come_from_settings(tmp_path: Path) -> None:
    path = tmp_path / "routing.yaml"
    path.write_text(
        "defaults:\n  provider: openai\ntasks:\n"
        "  chat.reply:\n    model: ${OPENAI_REASONING_MODEL}\n    max_tokens: 4000\n",
        encoding="utf-8",
    )

    routes = load_routes(path, settings=LLMSettings(openai_reasoning_model="gpt-5.6-sol"), env={})

    assert routes["chat.reply"].model == "gpt-5.6-sol"


# ----------------------------------------------------------------- boot checks


def test_the_shipped_config_validates(router: Router) -> None:
    assert router.validate() == []


def test_validate_names_a_route_that_asks_for_too_few_tokens(
    router: Router, tmp_path: Path
) -> None:
    path = tmp_path / "routing.yaml"
    path.write_text(
        "tasks:\n  chat.reply:\n    model: claude-opus-5\n    max_tokens: 500\n", encoding="utf-8"
    )
    broken = Router(
        routes=RoutingTable(load_routes(path, env={})),
        providers=router.providers,
        embedder=router.embedder,
        registry=router.registry,
    )

    problems = broken.validate()

    assert len(problems) == 1
    assert "max_tokens" in problems[0]
    with pytest.raises(LLMConfigError):
        broken.validate_or_raise()


def test_a_task_routed_to_an_unconfigured_provider_is_caught(
    router: Router, tmp_path: Path
) -> None:
    path = tmp_path / "routing.yaml"
    path.write_text(
        "tasks:\n  chat.reply:\n    provider: mistral\n    model: m\n    max_tokens: 4000\n",
        encoding="utf-8",
    )
    broken = Router(
        routes=RoutingTable(load_routes(path, env={})),
        providers={},
        embedder=router.embedder,
        registry=router.registry,
    )

    assert "unknown provider" in broken.validate()[0]


def test_live_mode_without_a_key_refuses_to_build() -> None:
    with pytest.raises(LLMConfigError):
        build_router(LLMSettings(llm_mode="live", config_dir=CONFIG_DIR))


# -------------------------------------------------------------- calls, in fake


def test_fake_mode_needs_no_api_keys(router: Router) -> None:
    assert router.mode == "fake"
    assert all(provider.name == "fake" for provider in router.providers.values())


async def test_run_returns_text_usage_and_a_priced_result(router: Router) -> None:
    result = await router.run("chat.reply", messages="I put off the dentist again.")

    assert result.text
    assert result.model == "claude-opus-5"
    assert result.usage.output_tokens > 0
    assert result.cost_usd > 0, "a routed model must be priced from pricing.yaml"


async def test_run_with_a_schema_returns_a_validated_object(router: Router) -> None:
    result = await router.run(
        "extract.signals",
        messages="I kept putting off the dentist again this week.",
        schema=SignalExtraction,
    )

    assert isinstance(result.parsed, SignalExtraction)


async def test_the_structured_interpret_task_streams(router: Router) -> None:
    result = await router.run(
        "interpret.recognize", messages="S1 and S2 both mention sleep.", schema=InterpretationBatch
    )

    assert isinstance(result.parsed, InterpretationBatch)


async def test_stream_yields_text_then_one_done_event(router: Router) -> None:
    kinds: list[str] = []
    text = ""
    async for event in router.stream("chat.reply", messages="Tell me about mornings."):
        kinds.append(event.kind)
        if event.kind == "text":
            text += event.text

    assert text.strip()
    assert kinds.count("done") == 1
    assert kinds[-1] == "done"
    assert kinds.count("text") > 1, "a demo needs the answer to arrive in pieces"


async def test_per_call_effort_and_max_tokens_override_the_route(router: Router) -> None:
    result = await router.run("chat.reply", messages="hello there friend", effort="low")

    assert result.text
    with pytest.raises(LLMConfigError):
        await router.run("chat.reply", messages="hello", effort="turbo")  # type: ignore[arg-type]


async def test_a_call_with_nothing_to_send_is_refused(router: Router) -> None:
    with pytest.raises(LLMConfigError):
        await router.run("chat.reply")


async def test_system_blocks_and_history_reach_the_provider(router: Router) -> None:
    result = await router.run(
        "chat.reply",
        system=[SystemBlock("You are KnoRI.", cache=True)],
        messages=[
            ChatMessage(role="user", content="I have been sleeping badly."),
            ChatMessage(role="assistant", content="Since when?"),
            ChatMessage(role="user", content="About a fortnight now, I think."),
        ],
    )

    assert result.usage.cache_read_tokens > 0, "a cached block should be reported as cached"
    assert "fortnight" in result.text, "the reply should answer the last thing that was said"


async def test_embed_returns_vectors_of_the_routed_width(router: Router) -> None:
    vectors = await router.embed(["one", "two"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 1536


# ------------------------------------------ what the live adapters put on the wire
#
# No network: the SDK clients are constructed but never called. These tests pin the
# parameter names against the installed SDKs, which is the thing most likely to
# break silently on an upgrade.

BANNED = ("temperature", "top_p", "top_k", "budget_tokens")


def a_request(**metadata: object) -> CompletionRequest:
    return CompletionRequest(
        task="interpret.recognize",
        system_blocks=[SystemBlock("Policy text.", cache=True, ttl="1h")],
        messages=[ChatMessage(role="user", content="S1 and S2 both mention sleep.")],
        max_tokens=16000,
        thinking=True,
        effort="high",
        metadata={spec.MODEL: "claude-opus-5", **metadata},
    )


@pytest.fixture
def anthropic_provider() -> AnthropicProvider:
    return AnthropicProvider(client=anthropic.AsyncAnthropic(api_key="test-key-not-used"))


@pytest.fixture
def openai_provider() -> OpenAIProvider:
    return OpenAIProvider(client=openai.AsyncOpenAI(api_key="test-key-not-used"))


def test_anthropic_params_are_all_names_the_sdk_accepts(
    anthropic_provider: AnthropicProvider,
) -> None:
    params = anthropic_provider._params(a_request())

    accepted = set(inspect.signature(AsyncMessages.create).parameters)
    assert set(params) <= accepted, set(params) - accepted


def test_anthropic_sends_adaptive_thinking_and_effort_not_budget_tokens(
    anthropic_provider: AnthropicProvider,
) -> None:
    params = anthropic_provider._params(a_request(**{spec.THINKING_DISPLAY: "summarized"}))

    assert params["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert params["output_config"] == {"effort": "high"}
    for name in BANNED:
        assert name not in params, f"{name} returns 400 on Opus 5 and Sonnet 5"


def test_anthropic_disables_thinking_explicitly_for_utility_tasks(
    anthropic_provider: AnthropicProvider,
) -> None:
    """Sonnet 5 thinks when the field is omitted, so it has to be sent."""
    request = a_request()
    request.thinking = False
    request.effort = None

    params = anthropic_provider._params(request)

    assert params["thinking"] == {"type": "disabled"}
    assert "output_config" not in params


def test_thinking_off_never_asks_for_more_effort_than_opus_5_allows() -> None:
    request = a_request()
    request.thinking = False
    request.effort = "max"

    assert spec.effort_of(request) == "high", "disabled thinking above `high` is a 400"


def test_max_tokens_is_never_sent_below_the_floor(
    anthropic_provider: AnthropicProvider,
) -> None:
    request = a_request()
    request.max_tokens = 100

    assert anthropic_provider._params(request)["max_tokens"] == spec.MIN_MAX_TOKENS


def test_cache_control_carries_the_configured_ttl(
    anthropic_provider: AnthropicProvider,
) -> None:
    params = anthropic_provider._params(a_request())

    assert params["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_refusal_fallback_switches_to_the_beta_namespace(
    anthropic_provider: AnthropicProvider,
) -> None:
    plain, plain_extra = anthropic_provider._namespace(a_request())
    beta, beta_extra = anthropic_provider._namespace(a_request(**{spec.REFUSAL_FALLBACK: True}))

    assert plain_extra == {}
    assert beta is not plain
    assert beta_extra["fallbacks"] == "default"
    assert beta_extra["betas"] == ["server-side-fallback-2026-07-01"]


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (anthropic.APIConnectionError(request=None), True),  # type: ignore[arg-type]
        (RuntimeError("something else"), False),
    ],
)
def test_anthropic_errors_map_to_a_retryable_flag(
    anthropic_provider: AnthropicProvider, exc: Exception, retryable: bool
) -> None:
    mapped = anthropic_provider._error(a_request(), exc)

    assert isinstance(mapped, ProviderError)
    assert mapped.retryable is retryable


def test_openai_params_are_all_names_the_sdk_accepts(openai_provider: OpenAIProvider) -> None:
    params = openai_provider._params(a_request(**{spec.MODEL: "gpt-5.6-sol"}))

    accepted = set(inspect.signature(AsyncResponses.create).parameters)
    assert set(params) <= accepted, set(params) - accepted


def test_openai_never_stores_conversation_content(openai_provider: OpenAIProvider) -> None:
    params = openai_provider._params(a_request(**{spec.MODEL: "gpt-5.6-sol"}))

    assert params["store"] is False
    assert params["instructions"] == "Policy text."
    assert params["reasoning"] == {"effort": "high"}
    for name in BANNED:
        assert name not in params


def test_openai_maps_down_an_effort_the_model_lacks() -> None:
    limited = OpenAIProvider(
        client=openai.AsyncOpenAI(api_key="test-key-not-used"),
        effort_levels=("low", "medium", "high"),
    )
    request = a_request(**{spec.MODEL: "gpt-5.6-terra"})
    request.effort = "max"

    assert limited._params(request)["reasoning"] == {"effort": "high"}


# ---------------------------------------------- wire schemas work on both providers


@pytest.mark.parametrize(
    "schema",
    [
        value
        for _, value in inspect.getmembers(llm_io, inspect.isclass)
        if issubclass(value, pydantic.BaseModel)
        and value.__module__ == llm_io.__name__
        and value is not llm_io.Strict
    ],
    ids=lambda schema: schema.__name__,
)
def test_wire_schemas_are_closed_constraint_free_and_fully_required(
    schema: type[pydantic.BaseModel],
) -> None:
    wire = spec.json_schema_for(schema)

    _assert_wire_safe(wire)
    assert wire["additionalProperties"] is False
    assert set(wire["required"]) == set(wire["properties"])


def _assert_wire_safe(node: object) -> None:
    if isinstance(node, list):
        for item in node:
            _assert_wire_safe(item)
        return
    if not isinstance(node, dict):
        return
    for banned in ("minimum", "maximum", "minLength", "maxLength", "pattern", "minItems"):
        assert banned not in node, f"{banned} is stripped by the API and would fail the parse"
    if "properties" in node:
        assert node.get("additionalProperties") is False
    for value in node.values():
        _assert_wire_safe(value)
