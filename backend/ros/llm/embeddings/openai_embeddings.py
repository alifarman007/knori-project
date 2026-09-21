"""OpenAI embeddings. Anthropic has no embeddings API, so this is the only live one.

``text-embedding-3-small`` at 1536 dimensions, matching the ``vector(1536)`` columns.
Every row also stores ``embedding_model``, and the similarity cutoffs in
``config/thresholds.yaml`` are keyed by it — so changing the model here means adding
a cutoff there, never silently reusing the old one.
"""

from __future__ import annotations

from collections.abc import Sequence

import openai
import structlog
from openai import AsyncOpenAI

from ros.llm.base import ProviderError, Usage

log = structlog.get_logger(__name__)

MAX_BATCH = 64
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSIONS = 1536


class OpenAIEmbeddings:
    """Batched, order-preserving embeddings."""

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
        batch_size: int = MAX_BATCH,
        max_retries: int = 2,
        timeout: float = 60.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model_id = model
        self.dimensions = dimensions
        self.batch_size = max(1, min(batch_size, MAX_BATCH))
        self._client = client or AsyncOpenAI(
            api_key=api_key or None, max_retries=max_retries, timeout=timeout
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors, _ = await self.embed_with_usage(texts)
        return vectors

    async def embed_with_usage(self, texts: Sequence[str]) -> tuple[list[list[float]], Usage]:
        """Same as ``embed``, plus the token count so the call can be priced."""
        if not texts:
            return [], Usage()

        vectors: list[list[float]] = []
        usage = Usage()
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            try:
                response = await self._client.embeddings.create(
                    model=self.model_id, input=batch, dimensions=self.dimensions
                )
            except (openai.APIStatusError, openai.APIConnectionError, openai.APIError) as exc:
                raise _error(exc) from exc

            # The API may return items out of order; `index` is what puts them back.
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(list(item.embedding) for item in ordered)
            usage.input_tokens += int(getattr(response.usage, "prompt_tokens", 0) or 0)

        if len(vectors) != len(texts):
            raise ProviderError(
                f"asked for {len(texts)} embeddings, got {len(vectors)}", retryable=False
            )
        return vectors, usage


def _error(exc: Exception) -> ProviderError:
    request_id = getattr(exc, "request_id", None)
    status = getattr(exc, "status_code", None)
    log.warning("embeddings.call_failed", status=status, request_id=request_id)
    if isinstance(exc, openai.RateLimitError):
        return ProviderError(
            f"embeddings rate limited: {exc}", retryable=True, request_id=request_id
        )
    if isinstance(exc, openai.APIStatusError):
        return ProviderError(
            f"embeddings {status}: {exc}",
            retryable=bool(status and status >= 500),
            request_id=request_id,
        )
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError(f"cannot reach openai: {exc}", retryable=True)
    return ProviderError(str(exc), retryable=False, request_id=request_id)
