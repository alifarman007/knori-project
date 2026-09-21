"""Cost maths, the shipped price list, and the caps.

The numbers here are what the daily caps and the /admin/costs page are built on, so
the cache multipliers in particular get checked by hand rather than by round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ros.llm.base import Usage
from ros.llm.cost import (
    CONFIG_DIR,
    Limits,
    ModelPrice,
    PricingTable,
    load_limits,
    load_pricing,
)
from ros.llm.errors import LLMConfigError

OPUS = ModelPrice(input_per_mtok=5.00, output_per_mtok=25.00)


def test_plain_input_and_output() -> None:
    cost = OPUS.cost(Usage(input_tokens=1_000_000, output_tokens=1_000_000))

    assert cost == pytest.approx(30.00)


def test_cache_reads_cost_a_tenth_of_input() -> None:
    cost = OPUS.cost(Usage(cache_read_tokens=1_000_000))

    assert cost == pytest.approx(0.50)


def test_five_minute_cache_writes_cost_1_25x_input() -> None:
    cost = OPUS.cost(Usage(cache_write_tokens=1_000_000), cache_ttl="5m")

    assert cost == pytest.approx(6.25)


def test_one_hour_cache_writes_cost_2x_input() -> None:
    cost = OPUS.cost(Usage(cache_write_tokens=1_000_000), cache_ttl="1h")

    assert cost == pytest.approx(10.00)


def test_a_realistic_chat_turn_lands_in_the_planned_range() -> None:
    """plan.md §6.6 budgets $0.09 to $0.13 for 6k new + 8k cached input, 2.5k output."""
    turn = Usage(
        input_tokens=6_000, cache_read_tokens=8_000, cache_write_tokens=3_000, output_tokens=2_500
    )

    cost = OPUS.cost(turn, cache_ttl="5m")

    assert 0.09 <= cost <= 0.13


def test_unknown_model_costs_nothing_and_does_not_raise() -> None:
    table = PricingTable({"claude-opus-5": OPUS})

    assert table.price("some-model-we-never-heard-of", Usage(input_tokens=1000)) == 0.0


def test_dated_snapshots_price_like_their_base_model() -> None:
    table = PricingTable({"claude-opus-5": OPUS})

    assert table.get("claude-opus-5-20260401") is OPUS


def test_aliases_resolve() -> None:
    table = PricingTable({"gpt-5.6-sol": OPUS}, aliases={"gpt-5.6": "gpt-5.6-sol"})

    assert table.get("gpt-5.6") is OPUS


# ----------------------------------------------------------------- shipped config


def test_shipped_pricing_covers_every_model_phase_1_can_route_to() -> None:
    table = load_pricing(CONFIG_DIR / "pricing.yaml")

    for model in ("claude-opus-5", "claude-sonnet-5", "text-embedding-3-small"):
        assert table.get(model) is not None, model


def test_shipped_pricing_matches_the_published_list_prices() -> None:
    table = load_pricing(CONFIG_DIR / "pricing.yaml")

    opus = table.get("claude-opus-5")
    sonnet = table.get("claude-sonnet-5")
    assert opus is not None and sonnet is not None
    assert (opus.input_per_mtok, opus.output_per_mtok) == (5.00, 25.00)
    assert (sonnet.input_per_mtok, sonnet.output_per_mtok) == (2.00, 10.00)
    assert opus.cache_read_multiplier == 0.1
    assert opus.cache_write_5m_multiplier == 1.25
    assert opus.cache_write_1h_multiplier == 2.0


def test_missing_pricing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(LLMConfigError):
        load_pricing(tmp_path / "nothing.yaml")


def test_malformed_pricing_file_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "pricing.yaml"
    path.write_text("models:\n  claude-opus-5: 5\n", encoding="utf-8")

    with pytest.raises(LLMConfigError):
        load_pricing(path)


# ------------------------------------------------------------------------- caps


def test_shipped_limits_match_the_plan() -> None:
    limits = load_limits(CONFIG_DIR / "limits.yaml")

    assert limits.per_user_daily_usd == 3.00
    assert limits.beta_per_user_daily_usd == 2.00
    assert limits.global_daily_usd == 15.00
    assert limits.rate_limits.messages_per_min_per_user == 30


def test_beta_cap_is_the_tighter_one() -> None:
    limits = Limits()

    assert limits.user_cap(beta=True) == 2.00
    assert limits.user_cap(beta=False) == 3.00


def test_effort_drops_at_eighty_percent_of_the_cap() -> None:
    limits = Limits()

    assert not limits.should_downgrade_effort(1.59, beta=True)
    assert limits.should_downgrade_effort(1.60, beta=True)
