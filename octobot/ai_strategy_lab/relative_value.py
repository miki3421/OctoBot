"""Market-neutral cross-sectional futures research."""

from __future__ import annotations

import dataclasses
import datetime
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import trend as trend_module


RELATIVE_VALUE_SCHEMA_VERSION = 1
STRATEGY_NAME = "btc_residual_cross_sectional_momentum_v11"
COMBINATION_NAME = "v3_75pct_residual_momentum_25pct_v11"
REVERSAL_NAME = "btc_residual_cross_sectional_reversal_v12"
REVERSAL_COMBINATION_NAME = "v3_75pct_residual_reversal_25pct_v12"
BTC_SYMBOL = "BTC/USDT:USDT"
MOMENTUM_LOOKBACK_DAYS = 90
MOMENTUM_SKIP_DAYS = 7
BETA_LOOKBACK_DAYS = 60
VOLATILITY_LOOKBACK_DAYS = 60
REBALANCE_DAYS = 7
SELECTION_FRACTION = 0.25
SIDE_GROSS_EXPOSURE = 0.25
MAXIMUM_ASSET_EXPOSURE = 0.10
V3_ALLOCATION = 0.75
RELATIVE_VALUE_ALLOCATION = 0.25


@dataclasses.dataclass(frozen=True)
class RelativeValueConfig:
    fee_per_turnover: float = 0.0006
    slippage_per_turnover: float = 0.0002

    def validate(self):
        if self.fee_per_turnover < 0 or self.slippage_per_turnover < 0:
            raise ValueError("relative-value costs cannot be negative")


def evaluate_relative_value(
    futures_collectors: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
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
    paths = [
        pathlib.Path(value).resolve() for value in futures_collectors
    ]
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
    if BTC_SYMBOL not in symbols:
        raise ValueError("BTC is required as the residual benchmark")
    if len(symbols) < 9:
        raise ValueError("relative-value research requires BTC plus eight alts")
    market = trend_module._build_daily_market(
        {symbol: series[symbol]["1h"] for symbol in symbols},
        {symbol: funding[symbol] for symbol in symbols},
    )
    return evaluate_market(
        market,
        initial_capital=initial_capital,
        cost_stress_multiplier=cost_stress_multiplier,
    )


def evaluate_residual_reversal(
    futures_collectors: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    funding_path: typing.Union[
        str,
        pathlib.Path,
        typing.Iterable[typing.Union[str, pathlib.Path]],
    ],
    *,
    initial_capital: float = 10_000.0,
    cost_stress_multiplier: float = 3.0,
) -> dict:
    paths = [
        pathlib.Path(value).resolve() for value in futures_collectors
    ]
    if initial_capital <= 0 or not paths:
        raise ValueError("capital and collectors are required")
    if cost_stress_multiplier < 1:
        raise ValueError("cost stress multiplier must be at least one")
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
    if BTC_SYMBOL not in symbols or len(symbols) < 9:
        raise ValueError("reversal research requires BTC plus eight alts")
    market = trend_module._build_daily_market(
        {symbol: series[symbol]["1h"] for symbol in symbols},
        {symbol: funding[symbol] for symbol in symbols},
    )
    return evaluate_reversal_market(
        market,
        initial_capital=initial_capital,
        cost_stress_multiplier=cost_stress_multiplier,
    )


def evaluate_market(
    market,
    *,
    initial_capital=10_000.0,
    cost_stress_multiplier=3.0,
):
    config = RelativeValueConfig(
        fee_per_turnover=0.0006 * cost_stress_multiplier,
        slippage_per_turnover=0.0002 * cost_stress_multiplier,
    )
    config.validate()
    relative = _simulate_relative_value(
        market, config, initial_capital
    )
    v3_config = _v3_config(cost_stress_multiplier)
    v3 = trend_module._simulate(
        market,
        v3_config,
        initial_capital,
        include_trajectory=True,
    )
    combination = _combine_trajectories(
        v3,
        relative,
        initial_capital=initial_capital,
    )
    return {
        "schema_version": RELATIVE_VALUE_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "pre_registered_protocol": True,
        "cost_stress_multiplier": cost_stress_multiplier,
        "symbols": list(market["symbols"]),
        "configuration": {
            "strategy_name": STRATEGY_NAME,
            "btc_symbol": BTC_SYMBOL,
            "momentum_lookback_days": MOMENTUM_LOOKBACK_DAYS,
            "momentum_skip_days": MOMENTUM_SKIP_DAYS,
            "beta_lookback_days": BETA_LOOKBACK_DAYS,
            "volatility_lookback_days": VOLATILITY_LOOKBACK_DAYS,
            "rebalance_days": REBALANCE_DAYS,
            "selection_fraction": SELECTION_FRACTION,
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "maximum_asset_exposure": MAXIMUM_ASSET_EXPOSURE,
            "combination_allocations": {
                "v3": V3_ALLOCATION,
                "relative_value": RELATIVE_VALUE_ALLOCATION,
            },
            "cost_netting_assumed": False,
        },
        "market": {
            "start_date": str(market["dates"][0]),
            "end_date": str(market["dates"][-1]),
            "days": len(market["dates"]),
        },
        "reports": {
            STRATEGY_NAME: _without_internal_trajectory(relative),
            f"{trend_module.TREND_CONFIGS[4].name}_same_period_baseline": (
                _without_internal_trajectory(v3)
            ),
            COMBINATION_NAME: combination,
        },
        "automatic_promotion": False,
    }


def evaluate_reversal_market(
    market,
    *,
    initial_capital=10_000.0,
    cost_stress_multiplier=3.0,
):
    config = RelativeValueConfig(
        fee_per_turnover=0.0006 * cost_stress_multiplier,
        slippage_per_turnover=0.0002 * cost_stress_multiplier,
    )
    config.validate()
    reversal = _simulate_relative_value(
        market,
        config,
        initial_capital,
        target_function=_reversal_target_weights,
        strategy_name=REVERSAL_NAME,
        start_index=max(
            BETA_LOOKBACK_DAYS,
            VOLATILITY_LOOKBACK_DAYS,
            7,
        ),
    )
    v3 = trend_module._simulate(
        market,
        _v3_config(cost_stress_multiplier),
        initial_capital,
        include_trajectory=True,
    )
    combination = _combine_trajectories(
        v3,
        reversal,
        initial_capital=initial_capital,
        name=REVERSAL_COMBINATION_NAME,
    )
    return {
        "schema_version": RELATIVE_VALUE_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "pre_registered_protocol": True,
        "cost_stress_multiplier": cost_stress_multiplier,
        "symbols": list(market["symbols"]),
        "configuration": {
            "strategy_name": REVERSAL_NAME,
            "residual_return_days": 7,
            "beta_lookback_days": BETA_LOOKBACK_DAYS,
            "volatility_lookback_days": VOLATILITY_LOOKBACK_DAYS,
            "rebalance_days": REBALANCE_DAYS,
            "selection_fraction": SELECTION_FRACTION,
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "maximum_asset_exposure": MAXIMUM_ASSET_EXPOSURE,
            "combination_allocations": {
                "v3": V3_ALLOCATION,
                "relative_value": RELATIVE_VALUE_ALLOCATION,
            },
            "cost_netting_assumed": False,
        },
        "market": {
            "start_date": str(market["dates"][0]),
            "end_date": str(market["dates"][-1]),
            "days": len(market["dates"]),
        },
        "reports": {
            REVERSAL_NAME: _without_internal_trajectory(reversal),
            (
                "bear_regime_short_filter_dual_momentum_30_120_"
                "weekly_v3_same_period_baseline"
            ): _without_internal_trajectory(v3),
            REVERSAL_COMBINATION_NAME: combination,
        },
        "automatic_promotion": False,
    }


def _simulate_relative_value(
    market,
    config,
    initial_capital,
    *,
    target_function=None,
    strategy_name=STRATEGY_NAME,
    start_index=None,
):
    dates = market["dates"]
    closes = market["closes"]
    returns = market["returns"]
    funding = market["funding"]
    if BTC_SYMBOL not in market["symbols"]:
        raise ValueError("BTC benchmark is missing")
    btc_column = market["symbols"].index(BTC_SYMBOL)
    if target_function is None:
        target_function = _target_weights
    if start_index is None:
        start_index = max(
            MOMENTUM_LOOKBACK_DAYS,
            BETA_LOOKBACK_DAYS + MOMENTUM_SKIP_DAYS,
            VOLATILITY_LOOKBACK_DAYS,
        )
    weights = numpy.zeros(closes.shape[1], dtype=numpy.float64)
    equity = 1.0
    equities = []
    applied_weights = []
    total_cost = 0.0
    total_funding = 0.0
    total_turnover = 0.0
    rebalance_events = 0
    contribution = numpy.zeros(closes.shape[1], dtype=numpy.float64)
    last_rebalance = -REBALANCE_DAYS
    for index in range(start_index, len(dates)):
        price_by_symbol = weights * returns[index]
        funding_by_symbol = -weights * funding[index]
        daily_funding = float(numpy.sum(funding_by_symbol))
        equity *= 1.0 + float(
            numpy.sum(price_by_symbol) + daily_funding
        )
        contribution += price_by_symbol + funding_by_symbol
        total_funding += daily_funding
        if index - last_rebalance >= REBALANCE_DAYS:
            target = target_function(
                closes,
                returns,
                index,
                btc_column=btc_column,
            )
            turnover = float(numpy.sum(numpy.abs(target - weights)))
            cost = turnover * (
                config.fee_per_turnover
                + config.slippage_per_turnover
            )
            equity *= 1.0 - cost
            total_cost += cost
            total_turnover += turnover
            if turnover:
                rebalance_events += 1
                contribution -= (
                    numpy.abs(target - weights)
                    / turnover
                    * cost
                )
            weights = target
            last_rebalance = index
        if equity <= 0:
            raise ValueError("relative-value equity became non-positive")
        equities.append(equity)
        applied_weights.append(weights.copy())
    trajectory_dates = dates[start_index:]
    equity_values = numpy.asarray(equities, dtype=numpy.float64)
    weight_values = numpy.asarray(applied_weights, dtype=numpy.float64)
    report = _metrics(
        trajectory_dates,
        equity_values,
        initial_capital=initial_capital,
    )
    report.update(
        {
            "name": strategy_name,
            "total_turnover": total_turnover,
            "total_cost_return": total_cost,
            "total_funding_return": total_funding,
            "rebalance_events": rebalance_events,
            "average_gross_exposure": float(
                numpy.mean(
                    numpy.sum(numpy.abs(weight_values), axis=1)
                )
            ),
            "maximum_observed_gross_exposure": float(
                numpy.max(
                    numpy.sum(numpy.abs(weight_values), axis=1)
                )
            ),
            "average_net_exposure": float(
                numpy.mean(numpy.sum(weight_values, axis=1))
            ),
            "maximum_absolute_net_exposure": float(
                numpy.max(numpy.abs(numpy.sum(weight_values, axis=1)))
            ),
            "ending_weights": {
                symbol: float(value)
                for symbol, value in zip(
                    market["symbols"], weight_values[-1]
                )
            },
            "by_symbol_additive_contribution": {
                symbol: float(value)
                for symbol, value in zip(
                    market["symbols"], contribution
                )
            },
            "_trajectory": {
                "dates": trajectory_dates,
                "equity": equity_values,
            },
        }
    )
    return report


def _target_weights(closes, returns, index, *, btc_column):
    asset_columns = [
        column for column in range(closes.shape[1])
        if column != btc_column
    ]
    momentum_end = index - MOMENTUM_SKIP_DAYS
    btc_momentum = (
        closes[momentum_end, btc_column]
        / closes[index - MOMENTUM_LOOKBACK_DAYS, btc_column]
        - 1.0
    )
    btc_beta_returns = returns[
        momentum_end - BETA_LOOKBACK_DAYS + 1 : momentum_end + 1,
        btc_column,
    ]
    btc_variance = float(numpy.var(btc_beta_returns, ddof=1))
    residuals = []
    volatilities = {}
    for column in asset_columns:
        asset_momentum = (
            closes[momentum_end, column]
            / closes[index - MOMENTUM_LOOKBACK_DAYS, column]
            - 1.0
        )
        asset_beta_returns = returns[
            momentum_end - BETA_LOOKBACK_DAYS + 1 : momentum_end + 1,
            column,
        ]
        beta = (
            float(
                numpy.cov(
                    asset_beta_returns, btc_beta_returns, ddof=1
                )[0, 1]
            )
            / btc_variance
            if btc_variance > 1e-12
            else 0.0
        )
        residuals.append((asset_momentum - beta * btc_momentum, column))
        volatility = float(
            numpy.std(
                returns[
                    index - VOLATILITY_LOOKBACK_DAYS + 1 : index + 1,
                    column,
                ],
                ddof=1,
            )
        )
        volatilities[column] = volatility
    return _ranked_neutral_target(
        closes.shape[1],
        residuals,
        volatilities,
        reverse=False,
    )


def _reversal_target_weights(closes, returns, index, *, btc_column):
    asset_columns = [
        column for column in range(closes.shape[1])
        if column != btc_column
    ]
    btc_window = returns[index - 59 : index + 1, btc_column]
    btc_variance = float(numpy.var(btc_window, ddof=1))
    btc_return = (
        closes[index, btc_column] / closes[index - 7, btc_column] - 1.0
    )
    residuals = []
    volatilities = {}
    for column in asset_columns:
        asset_window = returns[index - 59 : index + 1, column]
        beta = (
            float(numpy.cov(asset_window, btc_window, ddof=1)[0, 1])
            / btc_variance
            if btc_variance > 1e-12
            else 0.0
        )
        asset_return = (
            closes[index, column] / closes[index - 7, column] - 1.0
        )
        residuals.append((asset_return - beta * btc_return, column))
        volatilities[column] = float(
            numpy.std(asset_window, ddof=1)
        )
    return _ranked_neutral_target(
        closes.shape[1],
        residuals,
        volatilities,
        reverse=True,
    )


def _ranked_neutral_target(
    asset_count,
    residuals,
    volatilities,
    *,
    reverse,
):
    residuals.sort(key=lambda value: (value[0], value[1]))
    selection_count = max(
        1, int(math.ceil(len(residuals) * SELECTION_FRACTION))
    )
    lower = [column for _, column in residuals[:selection_count]]
    upper = [column for _, column in residuals[-selection_count:]]
    long_columns, short_columns = (
        (lower, upper) if reverse else (upper, lower)
    )
    target = numpy.zeros(asset_count, dtype=numpy.float64)
    _assign_side(
        target,
        long_columns,
        volatilities,
        direction=1.0,
    )
    _assign_side(
        target,
        short_columns,
        volatilities,
        direction=-1.0,
    )
    long_gross = float(numpy.sum(numpy.maximum(target, 0.0)))
    short_gross = float(numpy.sum(numpy.maximum(-target, 0.0)))
    matched_gross = min(long_gross, short_gross)
    if long_gross > 0:
        target[target > 0] *= matched_gross / long_gross
    if short_gross > 0:
        target[target < 0] *= matched_gross / short_gross
    return target


def _assign_side(target, columns, volatilities, *, direction):
    inverse_volatility = numpy.asarray(
        [
            (
                1.0 / volatilities[column]
                if volatilities[column] > 1e-12
                else 0.0
            )
            for column in columns
        ],
        dtype=numpy.float64,
    )
    total = float(numpy.sum(inverse_volatility))
    if total <= 0:
        return
    allocations = SIDE_GROSS_EXPOSURE * inverse_volatility / total
    allocations = numpy.minimum(
        allocations, MAXIMUM_ASSET_EXPOSURE
    )
    for column, allocation in zip(columns, allocations):
        target[column] = direction * allocation


def _v3_config(cost_stress_multiplier):
    name = "bear_regime_short_filter_dual_momentum_30_120_weekly_v3"
    for config in trend_module.TREND_CONFIGS:
        if config.name == name:
            return dataclasses.replace(
                config,
                name=f"{name}_relative_value_baseline",
                fee_per_turnover=(
                    config.fee_per_turnover * cost_stress_multiplier
                ),
                slippage_per_turnover=(
                    config.slippage_per_turnover
                    * cost_stress_multiplier
                ),
            )
    raise ValueError("V3 configuration is missing")


def _combine_trajectories(
    v3,
    relative,
    *,
    initial_capital,
    name=COMBINATION_NAME,
):
    v3_dates = [
        datetime.date.fromisoformat(value)
        for value in v3["trajectory"]["dates"]
    ]
    v3_equity = numpy.asarray(
        v3["trajectory"]["equity"], dtype=numpy.float64
    )
    relative_dates = relative["_trajectory"]["dates"]
    relative_equity = relative["_trajectory"]["equity"]
    relative_returns = _returns_by_date(
        relative_dates, relative_equity
    )
    v3_returns = numpy.diff(
        numpy.concatenate((numpy.ones(1), v3_equity))
    ) / numpy.concatenate((numpy.ones(1), v3_equity))[:-1]
    combined_returns = numpy.asarray(
        [
            V3_ALLOCATION * v3_return
            + RELATIVE_VALUE_ALLOCATION
            * relative_returns.get(date, 0.0)
            for date, v3_return in zip(v3_dates, v3_returns)
        ],
        dtype=numpy.float64,
    )
    combined_equity = numpy.cumprod(1.0 + combined_returns)
    report = _metrics(
        v3_dates,
        combined_equity,
        initial_capital=initial_capital,
    )
    aligned_relative = numpy.asarray(
        [relative_returns.get(date, 0.0) for date in v3_dates],
        dtype=numpy.float64,
    )
    correlation = (
        float(numpy.corrcoef(v3_returns, aligned_relative)[0, 1])
        if numpy.std(v3_returns) > 0
        and numpy.std(aligned_relative) > 0
        else 0.0
    )
    report.update(
        {
            "name": name,
            "sleeve_allocations": {
                "v3": V3_ALLOCATION,
                "relative_value": RELATIVE_VALUE_ALLOCATION,
            },
            "cost_netting_assumed": False,
            "daily_return_correlation": correlation,
            "maximum_conservative_gross_exposure": (
                V3_ALLOCATION
                + RELATIVE_VALUE_ALLOCATION
                * 2.0
                * SIDE_GROSS_EXPOSURE
            ),
        }
    )
    return report


def _metrics(dates, equity, *, initial_capital):
    daily_returns = numpy.diff(
        numpy.concatenate((numpy.ones(1), equity))
    ) / numpy.concatenate((numpy.ones(1), equity))[:-1]
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity))
    )[1:]
    drawdowns = 1.0 - equity / peaks
    monthly = trend_module._period_returns(dates, equity, "%Y-%m")
    annual = trend_module._period_returns(dates, equity, "%Y")
    rolling = _rolling_month_returns(monthly, 12)
    elapsed_years = (dates[-1] - dates[0]).days / 365.25
    final_equity = float(equity[-1])
    return {
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
            numpy.std(daily_returns) * numpy.sqrt(365.0)
        ),
        "sharpe_zero_rate": (
            float(
                numpy.mean(daily_returns)
                / numpy.std(daily_returns)
                * numpy.sqrt(365.0)
            )
            if numpy.std(daily_returns) > 0
            else 0.0
        ),
        "positive_months": sum(value > 0 for value in monthly.values()),
        "negative_months": sum(value < 0 for value in monthly.values()),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
        ),
        "median_month_return": float(numpy.median(list(monthly.values()))),
        "worst_month_return": min(monthly.values()),
        "best_month_return": max(monthly.values()),
        "monthly_returns": monthly,
        "calendar_year_returns": annual,
        "worst_rolling_12_month_return": (
            min(rolling.values()) if rolling else None
        ),
        "rolling_12_month_returns": rolling,
        "longest_drawdown_days": trend_module._longest_streak(
            drawdowns > 0
        ),
    }


def _returns_by_date(dates, equity):
    returns = numpy.diff(
        numpy.concatenate((numpy.ones(1), equity))
    ) / numpy.concatenate((numpy.ones(1), equity))[:-1]
    return {
        date: float(value) for date, value in zip(dates, returns)
    }


def _rolling_month_returns(monthly, months):
    values = list(monthly.items())
    result = {}
    for index in range(months - 1, len(values)):
        window = values[index - months + 1 : index + 1]
        result[f"{window[0][0]}..{window[-1][0]}"] = float(
            numpy.prod([1.0 + value for _, value in window]) - 1.0
        )
    return result


def _without_internal_trajectory(report):
    return {
        key: value for key, value in report.items()
        if key not in {"trajectory", "_trajectory"}
    }
