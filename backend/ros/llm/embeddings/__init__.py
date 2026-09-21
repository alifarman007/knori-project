"""Embedding providers. With `providers/`, the only package that may import `openai`.

Anthropic has no embeddings API, so the live path is always OpenAI. The real one is
exposed lazily so a keyless run never imports the SDK.
"""

from __future__ import annotations

from typing import Any

from ros.llm.embeddings.fake import FakeEmbeddingProvider

__all__ = ["FakeEmbeddingProvider", "OpenAIEmbeddings"]


def __getattr__(name: str) -> Any:
    if name == "OpenAIEmbeddings":
        from ros.llm.embeddings.openai_embeddings import OpenAIEmbeddings

        return OpenAIEmbeddings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
