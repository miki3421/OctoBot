import datetime

import numpy
import pytest

from octobot.ai_strategy_lab import trend


def test_target_weights_respect_gross_and_asset_caps():
    config = trend.TREND_CONFIGS[0]
    weights = trend._target_weights(
        numpy.asarray([1.0, 1.0, -1.0]),
        numpy.diag(numpy.asarray([0.20, 0.40, 0.80]) ** 2),
        config,
    )
    assert numpy.sum(numpy.abs(weights)) <= 1.0 + 1e-12
    assert numpy.max(numpy.abs(weights)) <= 0.35 + 1e-12
    assert weights[0] > weights[1] > 0
    assert weights[2] < 0


def test_v13_scales_v3_risk_budget_uniformly():
    configs = {config.name: config for config in trend.TREND_CONFIGS}
    baseline = configs[
        "bear_regime_short_filter_dual_momentum_30_120_weekly_v3"
    ]
    candidate = configs["risk_budgeted_bear_regime_v13"]
    signal = numpy.asarray([1.0, 1.0, -1.0])
    covariance = numpy.asarray(
        [
            [0.10**2, 0.001, 0.001],
            [0.001, 0.20**2, 0.001],
            [0.001, 0.001, 0.30**2],
        ]
    )
    baseline_weights = trend._target_weights(
        signal, covariance, baseline
    )
    candidate_weights = trend._target_weights(
        signal, covariance, candidate
    )
    assert numpy.allclose(candidate_weights, baseline_weights * 0.90)
    assert numpy.sum(numpy.abs(candidate_weights)) <= 0.90 + 1e-12
    assert numpy.max(numpy.abs(candidate_weights)) <= 0.315 + 1e-12


def test_v18_keeps_v13_signal_budget_and_adds_fast_volatility_brake():
    configs = {config.name: config for config in trend.TREND_CONFIGS}
    baseline = configs["risk_budgeted_bear_regime_v13"]
    candidate = configs["fast_volatility_brake_bear_regime_v18"]

    assert candidate.fast_days == baseline.fast_days
    assert candidate.slow_days == baseline.slow_days
    assert candidate.target_annual_volatility == (
        baseline.target_annual_volatility
    )
    assert candidate.maximum_gross_exposure == (
        baseline.maximum_gross_exposure
    )
    assert candidate.maximum_asset_exposure == (
        baseline.maximum_asset_exposure
    )
    assert candidate.short_regime_symbol == baseline.short_regime_symbol
    assert candidate.volatility_lookback_days == 60
    assert candidate.volatility_brake_lookback_days == 20
    candidate.validate()


def test_volatility_brake_only_deleverages_above_target():
    assert trend._volatility_brake_multiplier(0.10, 0.135) == 1.0
    assert trend._volatility_brake_multiplier(0.135, 0.135) == 1.0
    assert numpy.isclose(
        trend._volatility_brake_multiplier(0.27, 0.135), 0.5
    )
    assert trend._volatility_brake_multiplier(numpy.nan, 0.135) == 0.0

    weights = numpy.asarray([0.25, -0.25])
    covariance = numpy.asarray([[0.16, 0.04], [0.04, 0.09]])
    expected = numpy.sqrt(float(weights @ covariance @ weights))
    assert numpy.isclose(
        trend._portfolio_volatility(weights, covariance), expected
    )


def test_dual_momentum_requires_fast_and_slow_agreement():
    closes = numpy.asarray(
        [[100.0], [90.0], [80.0], [85.0], [90.0], [95.0]]
    )
    config = trend.TrendConfig(
        name="test",
        signal_kind="dual_momentum",
        fast_days=2,
        slow_days=4,
        volatility_lookback_days=20,
    )
    signals = trend._signals(closes, config)
    # At the last point both 2-day and 4-day returns are positive.
    assert signals[-1, 0] == 1
    # One point earlier, fast is positive while slow is flat/negative.
    assert signals[-2, 0] == 0


def test_period_returns_compound_from_period_endpoints():
    dates = [
        datetime.date(2025, 1, 30),
        datetime.date(2025, 1, 31),
        datetime.date(2025, 2, 1),
        datetime.date(2025, 2, 28),
    ]
    values = numpy.asarray([1.01, 1.02, 1.03, 1.04])
    result = trend._period_returns(dates, values, "%Y-%m")
    assert numpy.isclose(result["2025-01"], 0.02)
    assert numpy.isclose(result["2025-02"], 1.04 / 1.02 - 1)


def test_rolling_period_returns_compound_exact_windows():
    returns = {
        "2025-01": 0.10,
        "2025-02": -0.05,
        "2025-03": 0.02,
    }
    result = trend._rolling_period_returns(returns, 2)
    assert list(result) == [
        "2025-01..2025-02",
        "2025-02..2025-03",
    ]
    assert numpy.isclose(result["2025-01..2025-02"], 1.10 * 0.95 - 1)
    assert numpy.isclose(result["2025-02..2025-03"], 0.95 * 1.02 - 1)
    with pytest.raises(ValueError, match="window"):
        trend._rolling_period_returns(returns, 0)


def test_breakout_uses_only_prior_closes():
    closes = numpy.asarray([[float(value)] for value in range(1, 70)])
    config = trend.TrendConfig(
        name="test",
        signal_kind="close_breakout",
        fast_days=20,
        slow_days=55,
        exit_days=20,
        volatility_lookback_days=20,
    )
    signals = trend._signals(closes, config)
    assert numpy.all(signals[:55] == 0)
    assert numpy.all(signals[55:] == 1)


def test_longest_streak_counts_consecutive_true_values():
    assert trend._longest_streak([False, True, True, False, True]) == 2
    assert trend._longest_streak([False, False]) == 0


def test_drop_market_column_keeps_arrays_aligned():
    market = {
        "dates": [datetime.date(2025, 1, 1)],
        "symbols": ["BTC", "ETH", "SOL"],
        "closes": numpy.asarray([[1.0, 2.0, 3.0]]),
        "returns": numpy.asarray([[0.1, 0.2, 0.3]]),
        "funding": numpy.asarray([[0.01, 0.02, 0.03]]),
    }
    dropped = trend._drop_market_column(market, 1)
    assert dropped["symbols"] == ["BTC", "SOL"]
    assert dropped["closes"].tolist() == [[1.0, 3.0]]
    assert dropped["funding"].tolist() == [[0.01, 0.03]]


def test_weekly_protocol_does_not_rebalance_on_every_signal_change():
    days = 300
    dates = [
        datetime.date(2025, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    first = 100 + 10 * numpy.sin(numpy.arange(days) / 3)
    second = 100 - 8 * numpy.sin(numpy.arange(days) / 4)
    closes = numpy.column_stack((first, second))
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1
    market = {
        "dates": dates,
        "symbols": ["A", "B"],
        "closes": closes,
        "returns": returns,
        "funding": numpy.zeros_like(closes),
    }
    config = trend.TrendConfig(
        name="weekly",
        signal_kind="dual_momentum",
        fast_days=2,
        slow_days=4,
        rebalance_days=7,
        volatility_lookback_days=20,
    )
    report = trend._simulate(market, config, 10_000)
    assert report["rebalance_events"] <= 41
    assert set(report["ending_weights"]) == {"A", "B"}
    assert set(report["latest_close"]) == {"A", "B"}
    assert set(report["latest_daily_funding"]) == {"A", "B"}
    assert (
        sum(abs(value) for value in report["ending_weights"].values())
        <= 1.0 + 1e-12
    )
    assert 0 <= report["days_until_next_rebalance"] <= 7


def test_evaluation_end_index_limits_report_dates_and_days():
    days = 80
    dates = [
        datetime.date(2025, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    closes = numpy.column_stack(
        (
            numpy.linspace(100, 140, days),
            numpy.linspace(90, 150, days),
        )
    )
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1
    market = {
        "dates": dates,
        "symbols": ["A", "B"],
        "closes": closes,
        "returns": returns,
        "funding": numpy.zeros_like(closes),
    }
    config = trend.TrendConfig(
        name="bounded",
        signal_kind="dual_momentum",
        fast_days=2,
        slow_days=4,
        rebalance_days=7,
        volatility_lookback_days=20,
    )

    report = trend._simulate(
        market,
        config,
        10_000,
        evaluation_start_index=25,
        evaluation_end_index=50,
    )

    assert report["evaluation_start_date"] == str(dates[25])
    assert report["evaluation_end_date"] == str(dates[49])
    assert report["evaluation_days"] == 25


def test_fast_volatility_brake_reduces_risk_between_weekly_rebalances():
    days = 180
    dates = [
        datetime.date(2025, 1, 1) + datetime.timedelta(days=index)
        for index in range(days)
    ]
    low_volatility = numpy.tile(
        numpy.asarray([0.001, -0.0005]), (days, 1)
    )
    high_volatility = numpy.asarray(
        [0.12 if index % 2 else -0.10 for index in range(20)]
    )
    low_volatility[-20:, 0] = high_volatility
    low_volatility[-20:, 1] = high_volatility * 0.8
    closes = 100 * numpy.cumprod(1.0 + low_volatility, axis=0)
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1
    market = {
        "dates": dates,
        "symbols": ["A", "B"],
        "closes": closes,
        "returns": returns,
        "funding": numpy.zeros_like(closes),
    }
    config = trend.TrendConfig(
        name="braked",
        signal_kind="dual_momentum",
        fast_days=2,
        slow_days=4,
        rebalance_days=7,
        volatility_lookback_days=60,
        volatility_brake_lookback_days=20,
        target_annual_volatility=0.10,
    )
    signal_override = numpy.ones_like(closes)

    report = trend._simulate(
        market,
        config,
        10_000,
        signal_override=signal_override,
        include_trajectory=True,
    )

    assert report["volatility_brake_events"] > 0
    assert report["volatility_brake_turnover"] > 0
    assert report["minimum_volatility_brake_multiplier"] < 1
    assert min(
        report["trajectory"]["volatility_brake_multiplier"][-20:]
    ) < 1


def test_market_regime_gate_removes_opposite_asset_signals():
    closes = numpy.column_stack(
        (
            numpy.linspace(100, 200, 200),
            numpy.linspace(200, 100, 200),
        )
    )
    config = trend.TrendConfig(
        name="regime",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        volatility_lookback_days=20,
        market_regime_symbol="BTC/USDT:USDT",
    )
    signals = trend._signals(
        closes,
        config,
        ["BTC/USDT:USDT", "ALT/USDT:USDT"],
    )
    assert signals[-1].tolist() == [1.0, 0.0]


def test_short_regime_gate_preserves_longs_and_filters_alt_shorts():
    closes = numpy.column_stack(
        (
            numpy.linspace(100, 200, 200),
            numpy.linspace(200, 100, 200),
            numpy.linspace(50, 150, 200),
        )
    )
    config = trend.TrendConfig(
        name="short-regime",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        volatility_lookback_days=20,
        short_regime_symbol="BTC/USDT:USDT",
    )
    signals = trend._signals(
        closes,
        config,
        ["BTC/USDT:USDT", "ALT/USDT:USDT", "LONG/USDT:USDT"],
    )
    assert signals[-1].tolist() == [1.0, 0.0, 1.0]


def test_drawdown_governor_uses_predeclared_risk_bands():
    config = trend.TrendConfig(
        name="governed",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        drawdown_soft_limit=0.05,
        drawdown_hard_limit=0.10,
        drawdown_soft_multiplier=0.50,
        drawdown_hard_multiplier=0.25,
    )
    config.validate()

    assert trend._drawdown_risk_multiplier(0.049, config) == 1.0
    assert trend._drawdown_risk_multiplier(0.05, config) == 0.50
    assert trend._drawdown_risk_multiplier(0.099, config) == 0.50
    assert trend._drawdown_risk_multiplier(0.10, config) == 0.25


def test_drawdown_governor_cannot_be_partially_configured():
    config = trend.TrendConfig(
        name="invalid-governor",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        drawdown_soft_multiplier=0.50,
    )

    with pytest.raises(ValueError, match="partially configured"):
        config.validate()


def test_breadth_confirmation_requires_activity_and_directional_coherence():
    config = trend.TrendConfig(
        name="breadth",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        minimum_active_signal_fraction=1 / 3,
        minimum_directional_coherence=0.75,
    )
    covariance = numpy.eye(6) * 0.04

    sparse = trend._target_weights(
        numpy.asarray([1, 0, 0, 0, 0, 0]), covariance, config
    )
    conflicted = trend._target_weights(
        numpy.asarray([1, -1, 0, 0, 0, 0]), covariance, config
    )
    confirmed = trend._target_weights(
        numpy.asarray([1, 1, 0, 0, 0, 0]), covariance, config
    )

    assert numpy.all(sparse == 0)
    assert numpy.all(conflicted == 0)
    assert numpy.sum(numpy.abs(confirmed)) > 0


def test_strength_ranking_keeps_strongest_half_per_direction():
    signals = numpy.asarray(
        [
            [1.0, 1.0, 1.0, -1.0, -1.0, -1.0],
            [1.0, 0.0, 0.0, -1.0, 0.0, 0.0],
        ]
    )
    slow_returns = numpy.asarray(
        [
            [0.10, 0.30, 0.20, -0.05, -0.40, -0.25],
            [0.15, 0.0, 0.0, -0.20, 0.0, 0.0],
        ]
    )

    ranked = trend._retain_strongest_signals(
        signals, slow_returns, 0.50
    )

    assert ranked[0].tolist() == [0.0, 1.0, 1.0, 0.0, -1.0, -1.0]
    assert ranked[1].tolist() == [1.0, 0.0, 0.0, -1.0, 0.0, 0.0]


def test_v8_strength_ranking_uses_only_current_and_past_closes():
    days = 140
    closes = numpy.column_stack(
        (
            numpy.linspace(100, 150, days),
            numpy.linspace(100, 250, days),
            numpy.linspace(200, 120, days),
            numpy.linspace(200, 50, days),
        )
    )
    config = trend.TrendConfig(
        name="ranked",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        volatility_lookback_days=20,
        strongest_signal_fraction=0.50,
    )

    signals = trend._signals(closes, config)

    assert signals[-1].tolist() == [0.0, 1.0, 0.0, -1.0]
    changed_future = numpy.vstack(
        (closes, numpy.asarray([[1.0, 1.0, 1_000.0, 1_000.0]]))
    )
    assert trend._signals(changed_future, config)[-2].tolist() == (
        signals[-1].tolist()
    )


def test_multi_horizon_momentum_requires_two_agreeing_votes():
    days = 140
    strong_up = numpy.linspace(100, 250, days)
    recent_reversal = numpy.concatenate(
        (numpy.linspace(100, 220, 110), numpy.linspace(220, 180, 30))
    )
    strong_down = numpy.linspace(250, 100, days)
    closes = numpy.column_stack(
        (strong_up, recent_reversal, strong_down)
    )
    config = trend.TrendConfig(
        name="multi",
        signal_kind="multi_horizon_dual_momentum",
        fast_days=15,
        slow_days=120,
        volatility_lookback_days=20,
        momentum_horizons=((15, 60), (30, 90), (45, 120)),
    )

    signals = trend._signals(closes, config)

    assert signals[-1, 0] == 1.0
    assert signals[-1, 1] == 0.0
    assert signals[-1, 2] == -1.0


def test_multi_horizon_config_rejects_partial_protocol():
    config = trend.TrendConfig(
        name="invalid-multi",
        signal_kind="multi_horizon_dual_momentum",
        fast_days=15,
        slow_days=120,
        momentum_horizons=((15, 60), (30, 90)),
    )

    with pytest.raises(ValueError, match="at least three"):
        config.validate()
