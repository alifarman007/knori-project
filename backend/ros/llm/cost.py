"""What every model call cost, and the caps that stop the bill running away.

Two jobs:

* price a call from ``config/pricing.yaml`` — always by the model in the **response**,
  which can differ from the one we asked for when the refusal fallback runs
  (CLAUDE.md → LLM API rules);
* write the ``llm_calls`` row and bump the per-user daily counter, so
  ``/admin/costs`` and the caps in ``config/limits.yaml`` have something to read.

Cache tokens are priced relative to input: a read is 0.1x, a 5-minute write 1.25x
and a 1-hour write 2x — which is why the 1-hour TTL only pays off above two reads
per write (plan.md §6.3).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ros.llm.base import Usage
from ros.llm.errors import LLMConfigError
from ros.persistence.models import LlmCall

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
PRICING_PATH = CONFIG_DIR / "pricing.yaml"
LIMITS_PATH = CONFIG_DIR / "limits.yaml"

CALL_STATUSES = ("ok", "error", "refused", "truncated")

log = structlog.get_logger(__name__)
_warned_models: set[str] = set()


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """US dollars per million tokens, plus the cache multipliers for this model."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_multiplier: float = 0.1
    cache_write_5m_multiplier: float = 1.25
    cache_write_1h_multiplier: float = 2.0

    def cost(self, usage: Usage, *, cache_ttl: str = "5m") -> float:
        per_input = self.input_per_mtok / 1_000_000
        per_output = self.output_per_mtok / 1_000_000
        write_multiplier = (
            self.cache_write_1h_multiplier if cache_ttl == "1h" else self.cache_write_5m_multiplier
        )
        return (
            usage.input_tokens * per_input
            + usage.output_tokens * per_output
            + usage.cache_read_tokens * per_input * self.cache_read_multiplier
            + usage.cache_write_tokens * per_input * write_multiplier
        )


class PricingTable:
    """Model id → price. Unknown models cost 0 and warn; they never fail a call."""

    def __init__(
        self, models: Mapping[str, ModelPrice], *, aliases: Mapping[str, str] | None = None
    ) -> None:
        self._models = dict(models)
        self._aliases = dict(aliases or {})

    @property
    def models(self) -> Mapping[str, ModelPrice]:
        return self._models

    def get(self, model: str) -> ModelPrice | None:
        if model in self._models:
            return self._models[model]
        aliased = self._aliases.get(model)
        if aliased and aliased in self._models:
            return self._models[aliased]
        # Dated snapshots ("claude-opus-5-20260401") price like their base model.
        prefixes = [known for known in self._models if model.startswith(known)]
        if prefixes:
            return self._models[max(prefixes, key=len)]
        return None

    def price(self, model: str, usage: Usage, *, cache_ttl: str = "5m") -> float:
        entry = self.get(model)
        if entry is None:
            if model not in _warned_models:
                _warned_models.add(model)
                log.warning("pricing.unknown_model", model=model)
            return 0.0
        return entry.cost(usage, cache_ttl=cache_ttl)


def load_pricing(path: Path | str | None = None) -> PricingTable:
    data = _read_yaml(path or PRICING_PATH)
    defaults = data.get("defaults") or {}
    models: dict[str, ModelPrice] = {}
    for name, entry in (data.get("models") or {}).items():
        if not isinstance(entry, dict):
            raise LLMConfigError(f"pricing.yaml: model {name!r} is not a mapping")
        merged = {**defaults, **entry}
        try:
            models[str(name)] = ModelPrice(
                input_per_mtok=float(merged["input_per_mtok"]),
                output_per_mtok=float(merged.get("output_per_mtok", 0.0)),
                cache_read_multiplier=float(merged.get("cache_read_multiplier", 0.1)),
                cache_write_5m_multiplier=float(merged.get("cache_write_5m_multiplier", 1.25)),
                cache_write_1h_multiplier=float(merged.get("cache_write_1h_multiplier", 2.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMConfigError(f"pricing.yaml: model {name!r} is malformed: {exc}") from exc
    aliases = {str(k): str(v) for k, v in (data.get("aliases") or {}).items()}
    return PricingTable(models, aliases=aliases)


@dataclass(frozen=True, slots=True)
class RateLimits:
    login_per_min_per_ip: int = 10
    register_per_hour_per_ip: int = 5
    messages_per_min_per_user: int = 30
    feedback_per_min_per_user: int = 60


@dataclass(frozen=True, slots=True)
class Limits:
    """Daily spend caps. ``beta`` is the tighter cap used during dogfood and beta."""

    per_user_daily_usd: float = 3.00
    beta_per_user_daily_usd: float = 2.00
    global_daily_usd: float = 15.00
    effort_downgrade_at: float = 0.80
    beta_caps_active: bool = True
    rate_limits: RateLimits = field(default_factory=RateLimits)

    def user_cap(self, *, beta: bool | None = None) -> float:
        use_beta = self.beta_caps_active if beta is None else beta
        return self.beta_per_user_daily_usd if use_beta else self.per_user_daily_usd

    def should_downgrade_effort(self, spent_usd: float, *, beta: bool | None = None) -> bool:
        """At 80% of the cap, chat drops to low effort at the next conversation start."""
        cap = self.user_cap(beta=beta)
        return cap > 0 and spent_usd >= cap * self.effort_downgrade_at


def load_limits(path: Path | str | None = None) -> Limits:
    data = _read_yaml(path or LIMITS_PATH)
    rates = data.get("rate_limits") or {}
    base = Limits()
    return replace(
        base,
        per_user_daily_usd=float(data.get("per_user_daily_usd", base.per_user_daily_usd)),
        beta_per_user_daily_usd=float(
            data.get("beta_per_user_daily_usd", base.beta_per_user_daily_usd)
        ),
        global_daily_usd=float(data.get("global_daily_usd", base.global_daily_usd)),
        effort_downgrade_at=float(data.get("effort_downgrade_at", base.effort_downgrade_at)),
        beta_caps_active=bool(data.get("beta_caps_active", base.beta_caps_active)),
        rate_limits=RateLimits(
            login_per_min_per_ip=int(rates.get("login_per_min_per_ip", 10)),
            register_per_hour_per_ip=int(rates.get("register_per_hour_per_ip", 5)),
            messages_per_min_per_user=int(rates.get("messages_per_min_per_user", 30)),
            feedback_per_min_per_user=int(rates.get("feedback_per_min_per_user", 60)),
        ),
    )


def _read_yaml(path: Path | str) -> dict[str, Any]:
    file = Path(path)
    if not file.is_file():
        raise LLMConfigError(f"missing config file: {file}")
    loaded = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise LLMConfigError(f"{file} must contain a mapping at the top level")
    return loaded


_pricing: PricingTable | None = None
_limits: Limits | None = None


def get_pricing() -> PricingTable:
    global _pricing
    if _pricing is None:
        _pricing = load_pricing()
    return _pricing


def get_limits() -> Limits:
    global _limits
    if _limits is None:
        _limits = load_limits()
    return _limits


def price(model: str, usage: Usage, *, cache_ttl: str = "5m") -> float:
    return get_pricing().price(model, usage, cache_ttl=cache_ttl)


# ------------------------------------------------------------------------ the ledger

# `user_daily_usage` is a product table (knori/db/models.py) and `ros` must never
# import `knori`, so the counter is bumped with plain SQL against the table name.
_BUMP_DAILY_USAGE = sql_text(
    """
    INSERT INTO user_daily_usage
        (user_id, day, cost_usd, input_tokens, output_tokens, chat_messages)
    VALUES
        (:user_id, :day, :cost_usd, :input_tokens, :output_tokens, :chat_messages)
    ON CONFLICT (user_id, day) DO UPDATE SET
        cost_usd      = user_daily_usage.cost_usd      + EXCLUDED.cost_usd,
        input_tokens  = user_daily_usage.input_tokens  + EXCLUDED.input_tokens,
        output_tokens = user_daily_usage.output_tokens + EXCLUDED.output_tokens,
        chat_messages = user_daily_usage.chat_messages + EXCLUDED.chat_messages
    """
)


async def record_call(
    session: AsyncSession,
    *,
    task: str,
    provider: str,
    model: str,
    status: str = "ok",
    usage: Usage | None = None,
    cost_usd: float | None = None,
    cache_ttl: str = "5m",
    prompt_name: str | None = None,
    prompt_version: str | None = None,
    prompt_hash: str | None = None,
    effort: str | None = None,
    latency_ms: int = 0,
    stop_reason: str | None = None,
    error: str | None = None,
    request_id: str | None = None,
    user_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    result: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    counts_as_chat_message: bool = False,
    pricing: PricingTable | None = None,
) -> LlmCall:
    """Write one ``llm_calls`` row and bump that user's daily counter.

    ``model`` must be the model that answered, not the one we asked for. The caller
    owns the transaction; this only flushes so the row gets an id.
    """
    if status not in CALL_STATUSES:
        raise ValueError(f"unknown llm_calls status: {status!r}")

    spent = usage or Usage()
    if cost_usd is None:
        cost_usd = (pricing or get_pricing()).price(model, spent, cache_ttl=cache_ttl)

    row = LlmCall(
        user_id=user_id,
        task=task,
        provider=provider,
        model=model,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
        effort=effort,
        input_tokens=spent.input_tokens,
        output_tokens=spent.output_tokens,
        cache_read_tokens=spent.cache_read_tokens,
        cache_write_tokens=spent.cache_write_tokens,
        cost_usd=round(cost_usd, 6),
        latency_ms=latency_ms,
        stop_reason=stop_reason,
        status=status,
        error=error,
        request_id=request_id,
        job_id=job_id,
        result=result or {},
    )
    session.add(row)
    await session.flush()

    if user_id is not None:
        await session.execute(
            _BUMP_DAILY_USAGE,
            {
                "user_id": user_id,
                "day": (occurred_at or datetime.now(UTC)).astimezone(UTC).date().isoformat(),
                "cost_usd": round(cost_usd, 6),
                "input_tokens": spent.input_tokens,
                "output_tokens": spent.output_tokens,
                "chat_messages": 1 if counts_as_chat_message else 0,
            },
        )
    return row


async def spent_today(
    session: AsyncSession, user_id: uuid.UUID, *, occurred_at: datetime | None = None
) -> float:
    """What this user has spent today, in dollars. 0 when there is no row yet."""
    day = (occurred_at or datetime.now(UTC)).astimezone(UTC).date().isoformat()
    value = await session.scalar(
        sql_text("SELECT cost_usd FROM user_daily_usage WHERE user_id = :user_id AND day = :day"),
        {"user_id": user_id, "day": day},
    )
    return float(value or 0.0)
