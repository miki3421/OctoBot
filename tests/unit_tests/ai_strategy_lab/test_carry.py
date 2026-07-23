import dataclasses

import numpy

from octobot.ai_strategy_lab import carry
from octobot.ai_strategy_lab import dataset


def test_constant_positive_funding_produces_profitable_hedged_sleeve():
    hours = 40 * 8 + 1
    timestamps = numpy.arange(hours, dtype=float) * 3600 + 1_700_000_000
    futures = _series("BTC/USDT:USDT", timestamps, 101.0)
    spot = _series("BTC/USDT", timestamps, 100.0)
    funding_times = (
        timestamps[7::8].astype(numpy.int64) + 3600
    )
    config = carry.CarryConfig(
        name="test",
        lookback_settlements=3,
        entry_average_rate=0.0001,
        entry_min_monthly_gross=0.001,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=5,
    )
    result = carry._simulate_sleeve(
        "BTC",
        futures,
        spot,
        (funding_times, numpy.full(len(funding_times), 0.001)),
        config,
    )
    assert result["trades"]
    assert result["final_equity"] > 1.0
    assert all(trade["funding_cash"] > 0 for trade in result["trades"])
    assert result["position_open_at_end"] is True
    assert result["latest_settlement_timestamp"] == int(funding_times[-1])


def test_positive_funding_realization_haircut_reduces_receipts_only():
    config = carry.CarryConfig(
        name="stress",
        lookback_settlements=3,
        entry_average_rate=0.0001,
        entry_min_monthly_gross=0.001,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=5,
        positive_funding_realization=0.5,
    )

    assert carry._realized_funding_rate(0.001, config) == 0.0005
    assert carry._realized_funding_rate(-0.001, config) == -0.001


def test_entry_delay_uses_next_settlement_and_misses_its_payment():
    hours = 20 * 8 + 1
    timestamps = numpy.arange(hours, dtype=float) * 3600 + 1_700_000_000
    futures = _series("BTC/USDT:USDT", timestamps, 101.0)
    spot = _series("BTC/USDT", timestamps, 100.0)
    funding_times = timestamps[7::8].astype(numpy.int64) + 3600
    rates = numpy.full(len(funding_times), 0.001)
    immediate = carry.CarryConfig(
        name="immediate",
        lookback_settlements=3,
        entry_average_rate=0.0001,
        entry_min_monthly_gross=0.001,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=30,
    )
    delayed = dataclasses.replace(
        immediate,
        name="delayed",
        entry_delay_settlements=1,
    )

    immediate_result = carry._simulate_sleeve(
        "BTC", futures, spot, (funding_times, rates), immediate
    )
    delayed_result = carry._simulate_sleeve(
        "BTC", futures, spot, (funding_times, rates), delayed
    )

    first = delayed_result["trades"][0]
    assert first["entry_timestamp"] - first["signal_timestamp"] == 8 * 3600
    assert (
        delayed_result["trades"][0]["funding_cash"]
        < immediate_result["trades"][0]["funding_cash"]
    )


def test_cost_aware_v2_requires_stressed_round_trip_payback():
    config = next(
        value
        for value in carry.CARRY_CONFIGS
        if value.name == "cost_aware_persistent_v2"
    )

    assert config.lookback_settlements == 30
    assert config.entry_delay_settlements == 1
    assert carry._stressed_cost_payback_days(0.01, config) == 60.0
    assert carry._stressed_cost_payback_days(0.005, config) == 120.0


def test_execution_guard_cancels_stale_signal_when_basis_turns_negative():
    hours = 4 * 8 + 1
    timestamps = numpy.arange(hours, dtype=float) * 3600 + 1_700_000_000
    futures = _series("BTC/USDT:USDT", timestamps, 101.0)
    futures.values[31, 1:5] = 99.0
    spot = _series("BTC/USDT", timestamps, 100.0)
    funding_times = timestamps[7::8].astype(numpy.int64) + 3600
    rates = numpy.full(len(funding_times), 0.001)
    guarded = dataclasses.replace(
        next(
            value
            for value in carry.CARRY_CONFIGS
            if value.name == "execution_guarded_cost_aware_v3"
        ),
        lookback_settlements=3,
        entry_round_trip_cost_rate=0.0,
        maximum_cost_payback_days=0.0,
    )
    stale = dataclasses.replace(
        guarded,
        name="stale",
        revalidate_entry_at_execution=False,
    )

    guarded_result = carry._simulate_sleeve(
        "BTC", futures, spot, (funding_times, rates), guarded
    )
    stale_result = carry._simulate_sleeve(
        "BTC", futures, spot, (funding_times, rates), stale
    )

    assert guarded_result["trades"] == []
    assert stale_result["trades"][0]["entry_basis"] < 0


def test_round_trip_cost_includes_both_legs():
    config = carry.CARRY_CONFIGS[0]
    one_side = carry._fill_cost(
        1.0, config, spot_ratio=1.0, futures_ratio=1.0
    )
    assert one_side == 0.001
    assert 2 * one_side == 0.002


def test_historical_fixed_withdrawal_preserves_requested_floor():
    result = carry._historical_fixed_withdrawal(
        [0.01] * 12,
        10_000,
        warmup_months=0,
        minimum_capital_fraction=1.0,
    )
    assert result["maximum_fixed_monthly_amount"] > 90
    assert result["final_balance"] >= 10_000 - 1e-6
    assert result["minimum_balance"] >= 10_000
    assert result["feasible_without_withdrawals"] is True


def test_fixed_withdrawal_is_infeasible_when_core_dips_without_withdrawals():
    result = carry._historical_fixed_withdrawal(
        [-0.01, 0.10],
        10_000,
        warmup_months=1,
        minimum_capital_fraction=1.0,
    )
    assert result["feasible_without_withdrawals"] is False
    assert result["maximum_fixed_monthly_amount"] == 0.0


def test_rotation_selects_highest_eligible_carry():
    hours = 20 * 8 + 1
    timestamps = numpy.arange(hours, dtype=float) * 3600 + 1_700_000_000
    funding_times = timestamps[7::8].astype(numpy.int64) + 3600
    config = carry.CarryConfig(
        name="rotation_test",
        lookback_settlements=3,
        entry_average_rate=0.0001,
        entry_min_monthly_gross=0.001,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=3,
    )
    rotation = carry._simulate_rotation(
        [
            (
                "BTC",
                _series("BTC/USDT:USDT", timestamps, 101.0),
                _series("BTC/USDT", timestamps, 100.0),
                (funding_times, numpy.full(len(funding_times), 0.0005)),
            ),
            (
                "ETH",
                _series("ETH/USDT:USDT", timestamps, 101.0),
                _series("ETH/USDT", timestamps, 100.0),
                (funding_times, numpy.full(len(funding_times), 0.001)),
            ),
        ],
        config,
    )
    assert rotation["trades"]
    assert {trade["base"] for trade in rotation["trades"]} == {"ETH"}
    assert rotation["final_equity"] > 1.0


def _series(symbol, timestamps, price):
    values = numpy.column_stack(
        (
            timestamps,
            numpy.full(len(timestamps), price),
            numpy.full(len(timestamps), price),
            numpy.full(len(timestamps), price),
            numpy.full(len(timestamps), price),
            numpy.ones(len(timestamps)),
        )
    )
    return dataset.CandleSeries(symbol, "1h", values)
