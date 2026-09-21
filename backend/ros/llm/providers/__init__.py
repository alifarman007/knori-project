"""Provider adapters. The only package in the repo that may import `anthropic` or `openai`.

Each adapter satisfies ``ros.llm.base.LLMProvider`` and nothing else in the system
knows which one answered. ``AnthropicProvider`` and ``OpenAIProvider`` are exposed
lazily so that ``LLM_MODE=fake`` never pays to import an SDK it will not call.
"""

from __future__ import annotations

from typing import Any

from ros.llm.providers.fake import FakeProvider

__all__ = ["AnthropicProvider", "FakeProvider", "OpenAIProvider"]


def __getattr__(name: str) -> Any:
    if name == "AnthropicProvider":
        from ros.llm.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider
    if name == "OpenAIProvider":
        from ros.llm.providers.openai_provider import OpenAIProvider

        return OpenAIProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
