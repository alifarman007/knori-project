"""Deterministic embeddings with real similarity structure, no network.

A hash of the whole string would be deterministic but useless: two nearly identical
sentences would land as far apart as two unrelated ones, and every cosine cutoff in
``config/thresholds.yaml`` would be untestable. So this uses the hashing trick
instead — each word and each character trigram is hashed to a dimension and added up,
then the vector is normalised.

The result: texts that share words score high, texts that share nothing score near
zero, and the same text always gives the same vector, in this process and the next.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

from ros.llm.base import Usage

DIMENSIONS = 1536
MODEL_ID = "fake-embedding-1536"

_WORD = re.compile(r"[a-z0-9']+")
_WORD_WEIGHT = 1.0
_TRIGRAM_WEIGHT = 0.35  # catches near-identical wording that shares few whole words


class FakeEmbeddingProvider:
    """Stands in for ``OpenAIEmbeddings`` whenever ``LLM_MODE=fake``."""

    def __init__(self, *, dimensions: int = DIMENSIONS, model_id: str = MODEL_ID) -> None:
        self.dimensions = dimensions
        self.model_id = model_id

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(text) for text in texts]

    async def embed_with_usage(self, texts: Sequence[str]) -> tuple[list[list[float]], Usage]:
        vectors = [self.vector(text) for text in texts]
        return vectors, Usage(input_tokens=sum(len(text) for text in texts) // 4)

    def vector(self, text: str) -> list[float]:
        weights = [0.0] * self.dimensions
        lowered = text.lower()

        for word in _WORD.findall(lowered):
            index, sign = _slot(word, self.dimensions)
            weights[index] += sign * _WORD_WEIGHT

        squeezed = " ".join(_WORD.findall(lowered))
        for start in range(max(len(squeezed) - 2, 0)):
            index, sign = _slot(squeezed[start : start + 3], self.dimensions)
            weights[index] += sign * _TRIGRAM_WEIGHT

        norm = math.sqrt(sum(value * value for value in weights))
        if norm == 0.0:
            # Empty input still has to be a unit vector, or cosine divides by zero.
            weights[0] = 1.0
            return weights
        return [value / norm for value in weights]


def _slot(token: str, dimensions: int) -> tuple[int, float]:
    """A stable dimension and sign for one token.

    Python's ``hash()`` is salted per process, so it cannot be used here — a fixture
    recorded today has to match a run tomorrow.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dimensions, 1.0 if value & (1 << 63) else -1.0


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Handy in tests; production similarity goes through the ``Retriever`` protocol."""
    return sum(a * b for a, b in zip(left, right, strict=True))
