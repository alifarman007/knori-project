"""Failures the model layer can raise.

The provider-level errors (``ProviderError``, ``RefusalError``, ``TruncatedError``)
belong to the shared contract in ``ros/llm/base.py`` and are re-exported here so a
caller only needs one import. The rest are configuration and budget failures, which
are never retried: a wrong ``model_routing.yaml`` will still be wrong next minute.
"""

from __future__ import annotations

from ros.llm.base import ProviderError, RefusalError, TruncatedError

__all__ = [
    "BudgetExceededError",
    "LLMConfigError",
    "PromptNotFoundError",
    "PromptRenderError",
    "ProviderError",
    "RefusalError",
    "TruncatedError",
]


class LLMConfigError(RuntimeError):
    """Routing, pricing or credentials are wrong. Raised at boot, not per request."""


class PromptNotFoundError(LLMConfigError):
    """No ``ros/prompts/<name>/v<N>.md`` for the requested name or version."""

    def __init__(self, name: str, version: int | None = None) -> None:
        want = f"{name} v{version}" if version is not None else name
        super().__init__(f"no prompt file for {want}")
        self.name = name
        self.version = version


class PromptRenderError(LLMConfigError):
    """A prompt template referenced a variable the caller did not pass."""

    def __init__(self, name: str, version: int, reason: str) -> None:
        super().__init__(f"{name} v{version}: {reason}")
        self.name = name
        self.version = version


class BudgetExceededError(RuntimeError):
    """A daily cost cap from ``config/limits.yaml`` was already reached."""

    def __init__(self, scope: str, spent_usd: float, cap_usd: float) -> None:
        super().__init__(f"{scope} daily cap reached: ${spent_usd:.2f} of ${cap_usd:.2f}")
        self.scope = scope
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
