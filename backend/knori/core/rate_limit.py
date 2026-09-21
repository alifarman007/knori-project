"""In-process token buckets.

Phase 1 runs a single API process (plan.md §3.1), so an in-memory limiter is the
correct and honest choice: no Redis, no shared state to get wrong. If the API is
ever scaled to more than one process this has to move into Postgres — that is
written down in plan.md §9 rather than hidden here.

The limiter is pure apart from the clock, which is injected, so the refill
behaviour can be tested without sleeping.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from knori.core.clock import now
from knori.core.config import settings
from knori.core.errors import RateLimited

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class Rule:
    """``limit`` requests per ``per_seconds``, refilling continuously."""

    limit: int
    per_seconds: float

    @property
    def refill_per_second(self) -> float:
        return self.limit / self.per_seconds

    def __post_init__(self) -> None:
        if self.limit <= 0 or self.per_seconds <= 0:
            raise ValueError("a rate limit rule needs a positive limit and window")


# plan.md §7. Buckets are named after the action, not the endpoint.
DEFAULT_RULES: dict[str, Rule] = {
    "login": Rule(10, 60),
    "register": Rule(5, 3600),
    "password_reset": Rule(5, 3600),
    "resend_verification": Rule(5, 3600),
    "messages": Rule(30, 60),
    "feedback": Rule(60, 60),
    "recognitions_run": Rule(5, 3600),
    "export": Rule(3, 3600),
}


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int

    def raise_if_blocked(self, bucket: str) -> None:
        if not self.allowed:
            raise RateLimited(
                "Too many requests. Please wait a moment.",
                retry_after=self.retry_after,
                limit=self.limit,
                bucket=bucket,
            )


class RateLimiter:
    """Token buckets keyed by ``(bucket, identity)``.

    ``identity`` is an IP for anonymous actions and a user id for the rest.
    """

    def __init__(
        self,
        rules: Mapping[str, Rule] | None = None,
        *,
        clock: Clock | None = None,
        max_entries: int = 50_000,
    ) -> None:
        self._rules: dict[str, Rule] = dict(rules if rules is not None else DEFAULT_RULES)
        self._clock: Clock = clock or now
        self._max_entries = max_entries
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    # -- configuration ----------------------------------------------------------

    def rule(self, bucket: str) -> Rule:
        try:
            return self._rules[bucket]
        except KeyError:
            raise ValueError(f"no rate limit rule named {bucket!r}") from None

    def set_rule(self, bucket: str, rule: Rule) -> None:
        self._rules[bucket] = rule

    # -- checking ---------------------------------------------------------------

    def check(self, bucket: str, identity: str, *, cost: float = 1.0) -> Decision:
        """Consume ``cost`` tokens if they are there. Only consumes when allowed."""
        rule = self.rule(bucket)
        stamp = self._clock().timestamp()
        key = (bucket, identity)

        entry = self._buckets.get(key)
        if entry is None:
            self._evict_if_needed(stamp)
            entry = _Bucket(tokens=float(rule.limit), updated_at=stamp)
            self._buckets[key] = entry
        else:
            elapsed = max(0.0, stamp - entry.updated_at)
            entry.tokens = min(float(rule.limit), entry.tokens + elapsed * rule.refill_per_second)
            entry.updated_at = stamp

        if entry.tokens >= cost:
            entry.tokens -= cost
            return Decision(
                allowed=True,
                limit=rule.limit,
                remaining=int(entry.tokens),
                retry_after=0,
            )

        missing = cost - entry.tokens
        retry_after = max(1, int(missing / rule.refill_per_second + 0.999))
        return Decision(allowed=False, limit=rule.limit, remaining=0, retry_after=retry_after)

    def hit(self, bucket: str, identity: str, *, cost: float = 1.0) -> Decision:
        """Like :meth:`check` but raises :class:`RateLimited` when blocked."""
        decision = self.check(bucket, identity, cost=cost)
        decision.raise_if_blocked(bucket)
        return decision

    def reset(self, bucket: str | None = None, identity: str | None = None) -> None:
        if bucket is None:
            self._buckets.clear()
            return
        for key in [
            k for k in self._buckets if k[0] == bucket and (identity is None or k[1] == identity)
        ]:
            del self._buckets[key]

    # -- housekeeping -----------------------------------------------------------

    def _evict_if_needed(self, stamp: float) -> None:
        """Drop buckets that have refilled completely, so memory stays bounded."""
        if len(self._buckets) < self._max_entries:
            return
        for key, entry in list(self._buckets.items()):
            rule = self._rules.get(key[0])
            if rule is None:
                del self._buckets[key]
                continue
            refilled = entry.tokens + (stamp - entry.updated_at) * rule.refill_per_second
            if refilled >= rule.limit:
                del self._buckets[key]
        if len(self._buckets) >= self._max_entries:
            # Still full: drop the oldest half rather than grow without limit.
            oldest = sorted(self._buckets.items(), key=lambda kv: kv[1].updated_at)
            for key, _ in oldest[: len(oldest) // 2]:
                del self._buckets[key]

    @property
    def size(self) -> int:
        return len(self._buckets)


# ------------------------------------------------------------------ configuration

# config/limits.yaml spells the limits out in words; these map onto the buckets.
_CONFIG_KEYS: dict[str, tuple[str, float]] = {
    "login_per_min_per_ip": ("login", 60),
    "register_per_hour_per_ip": ("register", 3600),
    "messages_per_min_per_user": ("messages", 60),
    "feedback_per_min_per_user": ("feedback", 60),
    "export_per_hour_per_user": ("export", 3600),
    "resend_verification_per_hour_per_ip": ("resend_verification", 3600),
    "password_reset_per_hour_per_ip": ("password_reset", 3600),
    "recognitions_run_per_10min_per_user": ("recognitions_run", 600),
}


def rules_from_config(section: Mapping[str, object]) -> dict[str, Rule]:
    """Overlay ``limits.yaml`` values on the defaults. Unknown keys are ignored."""
    rules = dict(DEFAULT_RULES)
    for key, (bucket, window) in _CONFIG_KEYS.items():
        value = section.get(key)
        if isinstance(value, int | float) and value > 0:
            rules[bucket] = Rule(int(value), window)
    return rules


def _load_configured_rules() -> dict[str, Rule]:
    path = settings.config_dir / "limits.yaml"
    try:
        import yaml

        with path.open(encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except (OSError, ImportError, ValueError):
        return dict(DEFAULT_RULES)
    section = loaded.get("rate_limits") if isinstance(loaded, dict) else None
    return rules_from_config(section) if isinstance(section, Mapping) else dict(DEFAULT_RULES)


@dataclass(slots=True)
class _Singleton:
    instance: RateLimiter | None = field(default=None)


_shared = _Singleton()


def get_rate_limiter() -> RateLimiter:
    """The limiter the API uses. One per process, by design."""
    if _shared.instance is None:
        _shared.instance = RateLimiter(_load_configured_rules())
    return _shared.instance


__all__ = [
    "DEFAULT_RULES",
    "Decision",
    "RateLimiter",
    "Rule",
    "get_rate_limiter",
    "rules_from_config",
]
