"""Token buckets: allow the limit, block the rest, refill over time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from knori.core.errors import RateLimited
from knori.core.rate_limit import DEFAULT_RULES, RateLimiter, Rule, rules_from_config


class FakeClock:
    """Time only moves when a test says so."""

    def __init__(self, start: datetime | None = None) -> None:
        self.at = start or datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


def limiter(limit: int = 3, per_seconds: float = 60) -> tuple[RateLimiter, FakeClock]:
    clock = FakeClock()
    return RateLimiter({"test": Rule(limit, per_seconds)}, clock=clock), clock


def test_allows_up_to_the_limit_then_blocks() -> None:
    rl, _ = limiter(limit=3)

    assert [rl.check("test", "ip").allowed for _ in range(3)] == [True, True, True]
    blocked = rl.check("test", "ip")
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after >= 1


def test_remaining_counts_down() -> None:
    rl, _ = limiter(limit=3)
    assert rl.check("test", "ip").remaining == 2
    assert rl.check("test", "ip").remaining == 1
    assert rl.check("test", "ip").remaining == 0


def test_refills_over_time() -> None:
    rl, clock = limiter(limit=3, per_seconds=60)
    for _ in range(3):
        rl.check("test", "ip")
    assert rl.check("test", "ip").allowed is False

    clock.advance(21)  # one token back at 3 per minute
    assert rl.check("test", "ip").allowed is True
    assert rl.check("test", "ip").allowed is False


def test_refill_never_exceeds_the_limit() -> None:
    rl, clock = limiter(limit=3, per_seconds=60)
    rl.check("test", "ip")
    clock.advance(3600)
    assert [rl.check("test", "ip").allowed for _ in range(4)] == [True, True, True, False]


def test_blocked_requests_do_not_consume_tokens() -> None:
    """A client hammering while blocked must not push its own recovery further out."""
    rl, clock = limiter(limit=1, per_seconds=60)
    assert rl.check("test", "ip").allowed is True
    for _ in range(10):
        assert rl.check("test", "ip").allowed is False
    clock.advance(61)
    assert rl.check("test", "ip").allowed is True


def test_identities_are_independent() -> None:
    rl, _ = limiter(limit=1)
    assert rl.check("test", "a").allowed is True
    assert rl.check("test", "b").allowed is True
    assert rl.check("test", "a").allowed is False


def test_buckets_are_independent() -> None:
    clock = FakeClock()
    rl = RateLimiter({"one": Rule(1, 60), "two": Rule(1, 60)}, clock=clock)
    assert rl.check("one", "ip").allowed is True
    assert rl.check("two", "ip").allowed is True
    assert rl.check("one", "ip").allowed is False


def test_retry_after_matches_the_refill_rate() -> None:
    rl, _ = limiter(limit=6, per_seconds=60)  # one token every 10 s
    for _ in range(6):
        rl.check("test", "ip")
    assert rl.check("test", "ip").retry_after == 10


def test_hit_raises_rate_limited_with_retry_after() -> None:
    rl, _ = limiter(limit=1)
    rl.hit("test", "ip")
    with pytest.raises(RateLimited) as caught:
        rl.hit("test", "ip")
    assert caught.value.status == 429
    assert caught.value.retry_after >= 1
    assert caught.value.extra["bucket"] == "test"


def test_unknown_bucket_is_a_programming_error() -> None:
    rl, _ = limiter()
    with pytest.raises(ValueError, match="no rate limit rule"):
        rl.check("nope", "ip")


def test_reset_clears_one_bucket() -> None:
    rl, _ = limiter(limit=1)
    rl.check("test", "ip")
    assert rl.check("test", "ip").allowed is False
    rl.reset("test", "ip")
    assert rl.check("test", "ip").allowed is True


def test_documented_limits_are_the_ones_in_the_plan() -> None:
    assert (DEFAULT_RULES["login"].limit, DEFAULT_RULES["login"].per_seconds) == (10, 60)
    assert (DEFAULT_RULES["register"].limit, DEFAULT_RULES["register"].per_seconds) == (5, 3600)
    assert (DEFAULT_RULES["messages"].limit, DEFAULT_RULES["messages"].per_seconds) == (30, 60)
    assert (DEFAULT_RULES["feedback"].limit, DEFAULT_RULES["feedback"].per_seconds) == (60, 60)


def test_a_rule_needs_a_positive_window() -> None:
    with pytest.raises(ValueError, match="positive"):
        Rule(0, 60)
    with pytest.raises(ValueError, match="positive"):
        Rule(10, 0)


def test_memory_is_bounded() -> None:
    clock = FakeClock()
    rl = RateLimiter({"test": Rule(1, 60)}, clock=clock, max_entries=10)
    for i in range(40):
        rl.check("test", f"ip-{i}")
        clock.advance(61)  # every earlier bucket has refilled by now
    assert rl.size <= 10


def test_config_overrides_the_defaults() -> None:
    rules = rules_from_config({"login_per_min_per_ip": 2, "messages_per_min_per_user": 100})
    assert rules["login"] == Rule(2, 60)
    assert rules["messages"] == Rule(100, 60)
    assert rules["register"] == DEFAULT_RULES["register"]


def test_config_ignores_nonsense() -> None:
    rules = rules_from_config(
        {"login_per_min_per_ip": 0, "unknown_key": 5, "messages_per_min_per_user": "lots"}
    )
    assert rules["login"] == DEFAULT_RULES["login"]
    assert rules["messages"] == DEFAULT_RULES["messages"]


def test_the_shipped_limits_file_matches_the_plan() -> None:
    from knori.core.rate_limit import _load_configured_rules

    rules = _load_configured_rules()
    assert rules["login"] == Rule(10, 60)
    assert rules["register"] == Rule(5, 3600)
    assert rules["messages"] == Rule(30, 60)
    assert rules["feedback"] == Rule(60, 60)
