"""Pre-registered multi-horizon futures trend ensemble research."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import trend as trend_module
from octobot.ai_strategy_lab import withdrawal as withdrawal_module


ENSEMBLE_SCHEMA_VERSION = 1
ENSEMBLE_NAME = "equal_v3_dual_momentum_breakout_v4"
SLEEVE_ALLOCATIONS = (0.5, 0.5)
SLEEVE_NAMES = (
    "bear_regime_short_filter_dual_momentum_30_120_weekly_v3",
    "close_breakout_55_20_daily_v1",
)


def evaluate_ensemble(
    futures_collectors: typing.Iterable[typing.Union[str, pathlib.Path]],
    funding_path: typing.Union[
        str,
        pathlib.Path,
        typing.Iterable[typing.Union[str, pathlib.Path]],
    ],
    *,
    initial_capital: float = 10_000.0,
    cost_stress_multiplier: float = 3.0,
) -> dict:
    if initial_capital <= 0:
        raise ValueError("initial capital must be positive")
    if cost_stress_multiplier < 1:
        raise ValueError("cost stress multiplier must be at least one")
    paths = [pathlib.Path(value).resolve() for value in futures_collectors]
    if not paths:
        raise ValueError("at least one futures collector is required")
    series = dataset_module.load_collector_series(
        paths, required_time_frames=("1h",)
    )
    funding_values = (
        [funding_path]
        if isinstance(funding_path, (str, pathlib.Path))
        else list(funding_path)
    )
    funding = {}
    for value in funding_values:
        loaded = funding_module.load_funding(value)
        overlap = set(funding) & set(loaded)
        if overlap:
            raise ValueError(
                f"funding symbols appear in multiple inputs: {sorted(overlap)}"
            )
        funding.update(loaded)
    symbols = sorted(set(series) & set(funding))
    if not symbols:
        raise ValueError("no collector symbol has signed funding history")
    market = trend_module._build_daily_market(
        {symbol: series[symbol]["1h"] for symbol in symbols},
        {symbol: funding[symbol] for symbol in symbols},
    )
    base_configs = tuple(_config_by_name(value) for value in SLEEVE_NAMES)
    reports = {}
    for multiplier in (1.0, cost_stress_multiplier):
        suffix = (
            ""
            if multiplier == 1.0
            else f"_cost_stress_{multiplier:g}x"
        )
        configs = tuple(
            dataclasses.replace(
                value,
                name=f"{value.name}{suffix}",
                fee_per_turnover=value.fee_per_turnover * multiplier,
                slippage_per_turnover=(
                    value.slippage_per_turnover * multiplier
                ),
            )
            for value in base_configs
        )
        name = f"{ENSEMBLE_NAME}{suffix}"
        report = _simulate_ensemble(
            market,
            configs,
            initial_capital=initial_capital,
            name=name,
        )
        if multiplier > 1 and len(symbols) > 2:
            leave_one_out = {}
            required_symbols = {
                value.market_regime_symbol
                for value in configs
                if value.market_regime_symbol
            } | {
                value.short_regime_symbol
                for value in configs
                if value.short_regime_symbol
            }
            for column, symbol in enumerate(symbols):
                if symbol in required_symbols:
                    continue
                candidate = _simulate_ensemble(
                    trend_module._drop_market_column(market, column),
                    configs,
                    initial_capital=initial_capital,
                    name=name,
                )
                leave_one_out[symbol] = {
                    key: candidate[key]
                    for key in (
                        "total_return",
                        "annualized_return",
                        "max_drawdown",
                        "sharpe_zero_rate",
                        "positive_month_ratio",
                        "worst_rolling_12_month_return",
                    )
                }
            report["leave_one_asset_out"] = leave_one_out
            report["positive_leave_one_asset_out"] = sum(
                value["total_return"] > 0
                for value in leave_one_out.values()
            )
        reports[name] = report
        reports[f"{name}_v3_baseline"] = trend_module._simulate(
            market, configs[0], initial_capital
        )
    return {
        "schema_version": ENSEMBLE_SCHEMA_VERSION,
        "research_only": True,
        "pre_registered_protocol": True,
        "initial_capital": initial_capital,
        "cost_stress_multiplier": cost_stress_multiplier,
        "symbols": symbols,
        "market": {
            "start_date": str(market["dates"][0]),
            "end_date": str(market["dates"][-1]),
            "days": len(market["dates"]),
        },
        "ensemble": {
            "name": ENSEMBLE_NAME,
            "sleeve_names": list(SLEEVE_NAMES),
            "sleeve_allocations": list(SLEEVE_ALLOCATIONS),
            "cost_netting_assumed": False,
        },
        "reports": reports,
    }


def _config_by_name(name):
    for value in trend_module.TREND_CONFIGS:
        if value.name == name:
            return value
    raise ValueError(f"missing registered trend config: {name}")


def _simulate_ensemble(market, configs, *, initial_capital, name):
    if len(configs) != len(SLEEVE_ALLOCATIONS):
        raise ValueError("sleeve configuration mismatch")
    for config in configs:
        config.validate()
    closes = market["closes"]
    daily_returns = market["returns"]
    funding = market["funding"]
    covariances = [
        trend_module._rolling_covariance(
            daily_returns, config.volatility_lookback_days
        )
        for config in configs
    ]
    signals = [
        trend_module._signals(closes, config, market["symbols"])
        for config in configs
    ]
    start_index = max(
        max(config.slow_days for config in configs),
        max(config.volatility_lookback_days for config in configs),
    )
    sleeve_weights = [
        numpy.zeros(closes.shape[1], dtype=numpy.float64)
        for _ in configs
    ]
    last_rebalances = [
        -config.rebalance_days for config in configs
    ]
    equity = 1.0
    equities = []
    aggregate_weights = []
    sleeve_daily_returns = [[] for _ in configs]
    sleeve_turnover = [0.0 for _ in configs]
    sleeve_cost = [0.0 for _ in configs]
    sleeve_funding = [0.0 for _ in configs]
    sleeve_rebalances = [0 for _ in configs]
    contribution = numpy.zeros(closes.shape[1], dtype=numpy.float64)
    long_contribution = 0.0
    short_contribution = 0.0

    for index in range(start_index, len(market["dates"])):
        aggregate = sum(
            allocation * weights
            for allocation, weights in zip(
                SLEEVE_ALLOCATIONS, sleeve_weights
            )
        )
        price_by_symbol = aggregate * daily_returns[index]
        funding_by_symbol = -aggregate * funding[index]
        gross_return = float(
            numpy.sum(price_by_symbol + funding_by_symbol)
        )
        contribution += price_by_symbol + funding_by_symbol
        long_contribution += float(
            numpy.sum(
                (price_by_symbol + funding_by_symbol)[aggregate > 0]
            )
        )
        short_contribution += float(
            numpy.sum(
                (price_by_symbol + funding_by_symbol)[aggregate < 0]
            )
        )
        for sleeve_index, (allocation, weights) in enumerate(
            zip(SLEEVE_ALLOCATIONS, sleeve_weights)
        ):
            sleeve_gross = float(
                numpy.sum(
                    weights * daily_returns[index]
                    - weights * funding[index]
                )
            )
            sleeve_daily_returns[sleeve_index].append(sleeve_gross)
            sleeve_funding[sleeve_index] += float(
                allocation * numpy.sum(-weights * funding[index])
            )
        equity *= 1.0 + gross_return

        total_daily_cost = 0.0
        for sleeve_index, (allocation, config) in enumerate(
            zip(SLEEVE_ALLOCATIONS, configs)
        ):
            if (
                index - last_rebalances[sleeve_index]
                < config.rebalance_days
            ):
                continue
            target = trend_module._target_weights(
                signals[sleeve_index][index],
                covariances[sleeve_index][index],
                config,
            )
            turnover = float(
                numpy.sum(
                    numpy.abs(target - sleeve_weights[sleeve_index])
                )
            )
            cost = allocation * turnover * (
                config.fee_per_turnover
                + config.slippage_per_turnover
            )
            total_daily_cost += cost
            sleeve_turnover[sleeve_index] += allocation * turnover
            sleeve_cost[sleeve_index] += cost
            if turnover:
                sleeve_rebalances[sleeve_index] += 1
                contribution -= (
                    allocation
                    * numpy.abs(target - sleeve_weights[sleeve_index])
                    / turnover
                    * (turnover * (
                        config.fee_per_turnover
                        + config.slippage_per_turnover
                    ))
                )
            sleeve_weights[sleeve_index] = target
            last_rebalances[sleeve_index] = index
        equity *= 1.0 - total_daily_cost
        equities.append(equity)
        aggregate_weights.append(
            sum(
                allocation * weights
                for allocation, weights in zip(
                    SLEEVE_ALLOCATIONS, sleeve_weights
                )
            )
        )

    if not equities:
        raise ValueError("ensemble simulation contains no evaluable days")
    dates = market["dates"][start_index:]
    equity_values = numpy.asarray(equities, dtype=numpy.float64)
    weight_values = numpy.asarray(aggregate_weights)
    daily_portfolio_returns = numpy.diff(
        numpy.concatenate((numpy.ones(1), equity_values))
    ) / numpy.concatenate((numpy.ones(1), equity_values))[:-1]
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity_values))
    )[1:]
    drawdowns = 1.0 - equity_values / peaks
    monthly_returns = trend_module._period_returns(
        dates, equity_values, "%Y-%m"
    )
    annual_returns = trend_module._period_returns(
        dates, equity_values, "%Y"
    )
    rolling_12 = _rolling_month_returns(monthly_returns, 12)
    final_equity = float(equity_values[-1])
    elapsed_years = (dates[-1] - dates[0]).days / 365.25
    latest_targets = [
        trend_module._target_weights(
            sleeve_signals[-1],
            sleeve_covariances[-1],
            config,
        )
        for sleeve_signals, sleeve_covariances, config in zip(
            signals, covariances, configs
        )
    ]
    latest_target = sum(
        allocation * target
        for allocation, target in zip(
            SLEEVE_ALLOCATIONS, latest_targets
        )
    )
    withdrawal = withdrawal_module._simulate_guarded_withdrawal(
        list(monthly_returns.values()),
        initial_capital=initial_capital,
        monthly_amount=25.0,
        warmup_months=12,
        safety_floor_fraction=0.80,
    )
    sleeve_return_arrays = [
        numpy.asarray(value, dtype=numpy.float64)
        for value in sleeve_daily_returns
    ]
    correlation = (
        float(numpy.corrcoef(*sleeve_return_arrays)[0, 1])
        if all(numpy.std(value) > 0 for value in sleeve_return_arrays)
        else 0.0
    )
    return {
        "name": name,
        "sleeve_configs": [
            dataclasses.asdict(value) for value in configs
        ],
        "sleeve_allocations": list(SLEEVE_ALLOCATIONS),
        "evaluation_start_date": str(dates[0]),
        "evaluation_end_date": str(dates[-1]),
        "evaluation_days": len(dates),
        "total_return": final_equity - 1.0,
        "annualized_return": (
            final_equity ** (1.0 / elapsed_years) - 1.0
            if elapsed_years > 0 and final_equity > 0
            else 0.0
        ),
        "final_capital": initial_capital * final_equity,
        "max_drawdown": float(numpy.max(drawdowns)),
        "annualized_volatility": float(
            numpy.std(daily_portfolio_returns) * numpy.sqrt(365.0)
        ),
        "sharpe_zero_rate": (
            float(
                numpy.mean(daily_portfolio_returns)
                / numpy.std(daily_portfolio_returns)
                * numpy.sqrt(365.0)
            )
            if numpy.std(daily_portfolio_returns) > 0
            else 0.0
        ),
        "positive_months": sum(
            value > 0 for value in monthly_returns.values()
        ),
        "negative_months": sum(
            value < 0 for value in monthly_returns.values()
        ),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly_returns.values())
            / len(monthly_returns)
        ),
        "median_month_return": float(
            numpy.median(list(monthly_returns.values()))
        ),
        "worst_month_return": min(monthly_returns.values()),
        "best_month_return": max(monthly_returns.values()),
        "worst_rolling_12_month_return": (
            min(rolling_12.values()) if rolling_12 else None
        ),
        "rolling_12_month_returns": rolling_12,
        "monthly_returns": monthly_returns,
        "calendar_year_returns": annual_returns,
        "longest_drawdown_days": trend_module._longest_streak(
            drawdowns > 0
        ),
        "longest_negative_month_streak": trend_module._longest_streak(
            numpy.asarray(list(monthly_returns.values())) < 0
        ),
        "average_gross_exposure": float(
            numpy.mean(numpy.sum(numpy.abs(weight_values), axis=1))
        ),
        "maximum_observed_gross_exposure": float(
            numpy.max(numpy.sum(numpy.abs(weight_values), axis=1))
        ),
        "average_net_exposure": float(
            numpy.mean(numpy.sum(weight_values, axis=1))
        ),
        "long_additive_contribution": long_contribution,
        "short_additive_contribution": short_contribution,
        "total_turnover": sum(sleeve_turnover),
        "total_cost_return": sum(sleeve_cost),
        "total_funding_return": sum(sleeve_funding),
        "sleeve_turnover": dict(zip(SLEEVE_NAMES, sleeve_turnover)),
        "sleeve_cost_return": dict(zip(SLEEVE_NAMES, sleeve_cost)),
        "sleeve_funding_return": dict(zip(SLEEVE_NAMES, sleeve_funding)),
        "sleeve_rebalance_events": dict(
            zip(SLEEVE_NAMES, sleeve_rebalances)
        ),
        "sleeve_daily_return_correlation": correlation,
        "ending_weights": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], weight_values[-1])
        },
        "latest_rebalance_target_weights": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], latest_target)
        },
        "by_symbol_additive_contribution": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], contribution)
        },
        "guarded_fixed_withdrawal_25": withdrawal,
    }


def _rolling_month_returns(monthly_returns, months):
    values = list(monthly_returns.items())
    result = {}
    for index in range(months - 1, len(values)):
        window = values[index - months + 1 : index + 1]
        compounded = float(
            numpy.prod([1.0 + value for _, value in window]) - 1.0
        )
        result[f"{window[0][0]}..{window[-1][0]}"] = compounded
    return result
