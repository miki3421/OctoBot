"""Low-frequency long/short trend portfolio research."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import carry as carry_module
from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import indicators


TREND_SCHEMA_VERSION = 2


@dataclasses.dataclass(frozen=True)
class TrendConfig:
    name: str
    signal_kind: str
    fast_days: int
    slow_days: int
    exit_days: int = 0
    rebalance_days: int = 7
    volatility_lookback_days: int = 60
    volatility_brake_lookback_days: int = 0
    target_annual_volatility: float = 0.15
    maximum_gross_exposure: float = 1.0
    maximum_asset_exposure: float = 0.35
    fee_per_turnover: float = 0.0006
    slippage_per_turnover: float = 0.0002
    market_regime_symbol: str = ""
    short_regime_symbol: str = ""
    drawdown_soft_limit: float = 0.0
    drawdown_hard_limit: float = 0.0
    drawdown_soft_multiplier: float = 1.0
    drawdown_hard_multiplier: float = 1.0
    minimum_active_signal_fraction: float = 0.0
    minimum_directional_coherence: float = 0.0
    strongest_signal_fraction: float = 1.0
    momentum_horizons: typing.Tuple[
        typing.Tuple[int, int], ...
    ] = ()

    def validate(self) -> None:
        if self.signal_kind not in {
            "ema_cross",
            "dual_momentum",
            "multi_horizon_dual_momentum",
            "close_breakout",
        }:
            raise ValueError("unknown trend signal kind")
        if not 1 <= self.fast_days < self.slow_days:
            raise ValueError("fast_days must be below slow_days")
        if self.signal_kind == "close_breakout" and not (
            1 <= self.exit_days < self.slow_days
        ):
            raise ValueError("breakout exit_days must be below slow_days")
        if self.rebalance_days < 1 or self.volatility_lookback_days < 20:
            raise ValueError("invalid rebalance or volatility lookback")
        if self.volatility_brake_lookback_days and not (
            10
            <= self.volatility_brake_lookback_days
            < self.volatility_lookback_days
        ):
            raise ValueError(
                "volatility brake lookback must be shorter than the base lookback"
            )
        if not 0 < self.target_annual_volatility <= 1:
            raise ValueError("invalid target volatility")
        if not 0 < self.maximum_gross_exposure <= 1:
            raise ValueError("maximum gross exposure must be in (0, 1]")
        if not 0 < self.maximum_asset_exposure <= 1:
            raise ValueError("maximum asset exposure must be in (0, 1]")
        if self.fee_per_turnover < 0 or self.slippage_per_turnover < 0:
            raise ValueError("costs cannot be negative")
        if self.drawdown_soft_limit == 0:
            if (
                self.drawdown_hard_limit != 0
                or self.drawdown_soft_multiplier != 1
                or self.drawdown_hard_multiplier != 1
            ):
                raise ValueError("drawdown governor is partially configured")
        elif not (
            0 < self.drawdown_soft_limit < self.drawdown_hard_limit < 1
            and 0
            < self.drawdown_hard_multiplier
            <= self.drawdown_soft_multiplier
            <= 1
        ):
            raise ValueError("invalid drawdown governor")
        if not (
            0 <= self.minimum_active_signal_fraction <= 1
            and 0 <= self.minimum_directional_coherence <= 1
        ):
            raise ValueError("invalid breadth confirmation")
        if not 0 < self.strongest_signal_fraction <= 1:
            raise ValueError("strongest signal fraction must be in (0, 1]")
        if self.signal_kind == "multi_horizon_dual_momentum":
            if len(self.momentum_horizons) < 3:
                raise ValueError(
                    "multi-horizon momentum requires at least three horizons"
                )
            if any(
                not 1 <= fast < slow <= self.slow_days
                for fast, slow in self.momentum_horizons
            ):
                raise ValueError("invalid momentum horizon")
        elif self.momentum_horizons:
            raise ValueError(
                "momentum horizons require multi-horizon signal kind"
            )


# Fixed before the first portfolio report is read. New research must append a
# version rather than altering these definitions in place.
TREND_CONFIGS = (
    TrendConfig(
        name="ema_20_100_weekly_v1",
        signal_kind="ema_cross",
        fast_days=20,
        slow_days=100,
        rebalance_days=7,
    ),
    TrendConfig(
        name="dual_momentum_30_120_weekly_v1",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
    ),
    TrendConfig(
        name="close_breakout_55_20_daily_v1",
        signal_kind="close_breakout",
        fast_days=20,
        slow_days=55,
        exit_days=20,
        rebalance_days=1,
    ),
    TrendConfig(
        name="regime_gated_dual_momentum_30_120_weekly_v2",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
        market_regime_symbol="BTC/USDT:USDT",
    ),
    TrendConfig(
        name="bear_regime_short_filter_dual_momentum_30_120_weekly_v3",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
        short_regime_symbol="BTC/USDT:USDT",
    ),
    TrendConfig(
        name="drawdown_governed_bear_regime_v6",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
        short_regime_symbol="BTC/USDT:USDT",
        drawdown_soft_limit=0.05,
        drawdown_hard_limit=0.10,
        drawdown_soft_multiplier=0.50,
        drawdown_hard_multiplier=0.25,
    ),
    TrendConfig(
        name="breadth_confirmed_bear_regime_v7",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
        short_regime_symbol="BTC/USDT:USDT",
        minimum_active_signal_fraction=1.0 / 3.0,
        minimum_directional_coherence=0.75,
    ),
    TrendConfig(
        name="strength_ranked_bear_regime_v8",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
        short_regime_symbol="BTC/USDT:USDT",
        strongest_signal_fraction=0.50,
    ),
    TrendConfig(
        name="multi_horizon_bear_regime_v9",
        signal_kind="multi_horizon_dual_momentum",
        fast_days=15,
        slow_days=120,
        rebalance_days=7,
        short_regime_symbol="BTC/USDT:USDT",
        momentum_horizons=((15, 60), (30, 90), (45, 120)),
    ),
    TrendConfig(
        name="risk_budgeted_bear_regime_v13",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
        target_annual_volatility=0.135,
        maximum_gross_exposure=0.90,
        maximum_asset_exposure=0.315,
        short_regime_symbol="BTC/USDT:USDT",
    ),
    TrendConfig(
        name="fast_volatility_brake_bear_regime_v18",
        signal_kind="dual_momentum",
        fast_days=30,
        slow_days=120,
        rebalance_days=7,
        volatility_lookback_days=60,
        volatility_brake_lookback_days=20,
        target_annual_volatility=0.135,
        maximum_gross_exposure=0.90,
        maximum_asset_exposure=0.315,
        short_regime_symbol="BTC/USDT:USDT",
    ),
)


def evaluate_trend(
    futures_collectors: typing.Iterable[typing.Union[str, pathlib.Path]],
    funding_path: typing.Union[
        str,
        pathlib.Path,
        typing.Iterable[typing.Union[str, pathlib.Path]],
    ],
    *,
    initial_capital: float = 10_000.0,
    cost_stress_multiplier: float = 1.5,
    config_names: typing.Optional[typing.Iterable[str]] = None,
    include_leave_one_asset_out: bool = True,
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
    market = _build_daily_market(
        {symbol: series[symbol]["1h"] for symbol in symbols},
        {symbol: funding[symbol] for symbol in symbols},
    )
    requested_names = (
        set(config_names) if config_names is not None else None
    )
    configs = [
        value
        for value in TREND_CONFIGS
        if requested_names is None or value.name in requested_names
    ]
    if requested_names is not None:
        unknown = requested_names - {value.name for value in configs}
        if unknown:
            raise ValueError(f"unknown trend configs: {sorted(unknown)}")
    if not configs:
        raise ValueError("at least one trend config is required")
    reports = {}
    for config in configs:
        config.validate()
        for evaluated in (
            config,
            dataclasses.replace(
                config,
                name=f"{config.name}_cost_stress_{cost_stress_multiplier:g}x",
                fee_per_turnover=(
                    config.fee_per_turnover * cost_stress_multiplier
                ),
                slippage_per_turnover=(
                    config.slippage_per_turnover * cost_stress_multiplier
                ),
            ),
        ):
            report = _simulate(
                market, evaluated, initial_capital
            )
            if (
                include_leave_one_asset_out
                and "_cost_stress_" in evaluated.name
                and len(symbols) > 2
            ):
                leave_one_out = {}
                for column, symbol in enumerate(symbols):
                    required_regime_symbols = {
                        evaluated.market_regime_symbol,
                        evaluated.short_regime_symbol,
                    }
                    if symbol in required_regime_symbols:
                        continue
                    candidate = _simulate(
                        _drop_market_column(market, column),
                        evaluated,
                        initial_capital,
                    )
                    leave_one_out[symbol] = {
                        key: candidate[key]
                        for key in (
                            "total_return",
                            "annualized_return",
                            "max_drawdown",
                            "sharpe_zero_rate",
                            "positive_month_ratio",
                        )
                    }
                report["leave_one_asset_out"] = leave_one_out
                report["positive_leave_one_asset_out"] = sum(
                    value["total_return"] > 0
                    for value in leave_one_out.values()
                )
            reports[evaluated.name] = report
    return {
        "schema_version": TREND_SCHEMA_VERSION,
        "research_only": True,
        "initial_capital": initial_capital,
        "cost_stress_multiplier": cost_stress_multiplier,
        "symbols": symbols,
        "configs": [dataclasses.asdict(value) for value in configs],
        "market": {
            "start_date": str(market["dates"][0]),
            "end_date": str(market["dates"][-1]),
            "days": len(market["dates"]),
        },
        "reports": reports,
    }


def _build_daily_market(series_by_symbol, funding_by_symbol):
    daily_by_symbol = {
        symbol: _daily_closes(series)
        for symbol, series in series_by_symbol.items()
    }
    common_dates = sorted(
        set.intersection(
            *(set(values) for values in daily_by_symbol.values())
        )
    )
    if len(common_dates) < 250:
        raise ValueError("fewer than 250 common daily observations")
    symbols = sorted(daily_by_symbol)
    closes = numpy.asarray(
        [
            [daily_by_symbol[symbol][date] for symbol in symbols]
            for date in common_dates
        ],
        dtype=numpy.float64,
    )
    if numpy.any(closes <= 0) or not numpy.all(numpy.isfinite(closes)):
        raise ValueError("daily close matrix is invalid")
    returns = numpy.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    funding = numpy.zeros_like(closes)
    date_index = {date: index for index, date in enumerate(common_dates)}
    for column, symbol in enumerate(symbols):
        timestamps, rates = funding_by_symbol[symbol]
        for timestamp, rate in zip(timestamps, rates):
            # A settlement at 00:00 belongs to the position held through the
            # day that just ended.
            date = datetime.datetime.fromtimestamp(
                int(timestamp) - 1, datetime.timezone.utc
            ).date()
            index = date_index.get(date)
            if index is not None:
                funding[index, column] += float(rate)
    return {
        "dates": common_dates,
        "symbols": symbols,
        "closes": closes,
        "returns": returns,
        "funding": funding,
    }


def _daily_closes(series):
    result = {}
    for candle, close_timestamp in zip(series.values, series.close_times):
        date = datetime.datetime.fromtimestamp(
            int(close_timestamp) - 1, datetime.timezone.utc
        ).date()
        result[date] = float(candle[4])
    return result


def _drop_market_column(market, column):
    keep = [
        index
        for index in range(len(market["symbols"]))
        if index != column
    ]
    return {
        "dates": market["dates"],
        "symbols": [market["symbols"][index] for index in keep],
        "closes": market["closes"][:, keep],
        "returns": market["returns"][:, keep],
        "funding": market["funding"][:, keep],
    }


def _simulate(
    market,
    config,
    initial_capital,
    *,
    include_trajectory=False,
    signal_override=None,
    evaluation_start_index=None,
    evaluation_end_index=None,
):
    closes = market["closes"]
    daily_returns = market["returns"]
    funding = market["funding"]
    signals = (
        _signals(closes, config, market["symbols"])
        if signal_override is None
        else numpy.asarray(signal_override, dtype=numpy.float64)
    )
    if signals.shape != closes.shape:
        raise ValueError("signal override does not match the market")
    covariances = _rolling_covariance(
        daily_returns, config.volatility_lookback_days
    )
    brake_covariances = (
        _rolling_covariance(
            daily_returns, config.volatility_brake_lookback_days
        )
        if config.volatility_brake_lookback_days
        else None
    )
    weights = numpy.zeros(closes.shape[1], dtype=numpy.float64)
    equity = 1.0
    equities = []
    applied_weights = []
    total_cost = 0.0
    total_funding = 0.0
    total_turnover = 0.0
    rebalance_events = 0
    long_contribution = 0.0
    short_contribution = 0.0
    contribution = numpy.zeros(closes.shape[1], dtype=numpy.float64)
    peak_equity = 1.0
    risk_multiplier = 1.0
    risk_multipliers = []
    volatility_brake_multipliers = []
    volatility_brake_events = 0
    volatility_brake_turnover = 0.0
    fast_ex_ante_volatilities = []
    minimum_start_index = max(
        config.slow_days,
        config.volatility_lookback_days,
        config.volatility_brake_lookback_days,
    )
    start_index = max(
        minimum_start_index,
        (
            minimum_start_index
            if evaluation_start_index is None
            else int(evaluation_start_index)
        ),
    )
    end_index = (
        len(market["dates"])
        if evaluation_end_index is None
        else min(len(market["dates"]), int(evaluation_end_index))
    )
    if end_index <= start_index:
        raise ValueError("trend evaluation interval is empty")
    last_rebalance = -config.rebalance_days
    for index in range(start_index, end_index):
        price_pnl_by_symbol = weights * daily_returns[index]
        funding_pnl_by_symbol = -weights * funding[index]
        daily_funding = float(numpy.sum(funding_pnl_by_symbol))
        gross_return = float(
            numpy.sum(price_pnl_by_symbol) + daily_funding
        )
        equity *= 1.0 + gross_return
        contribution += price_pnl_by_symbol + funding_pnl_by_symbol
        long_contribution += float(
            numpy.sum(
                (price_pnl_by_symbol + funding_pnl_by_symbol)[weights > 0]
            )
        )
        short_contribution += float(
            numpy.sum(
                (price_pnl_by_symbol + funding_pnl_by_symbol)[weights < 0]
            )
        )
        total_funding += daily_funding

        peak_equity = max(peak_equity, equity)
        current_drawdown = 1.0 - equity / peak_equity
        target_risk_multiplier = _drawdown_risk_multiplier(
            current_drawdown, config
        )
        risk_changed = target_risk_multiplier != risk_multiplier
        scheduled_rebalance = (
            index - last_rebalance >= config.rebalance_days
            or risk_changed
        )
        target = weights
        volatility_brake_multiplier = 1.0
        fast_ex_ante_volatility = 0.0
        brake_rebalance = False
        if scheduled_rebalance:
            target = _target_weights(
                signals[index],
                covariances[index],
                config,
            )
            target *= target_risk_multiplier
        pre_brake_target = target.copy()
        if brake_covariances is not None:
            fast_ex_ante_volatility = _portfolio_volatility(
                target,
                brake_covariances[index],
            )
            volatility_brake_multiplier = _volatility_brake_multiplier(
                fast_ex_ante_volatility,
                config.target_annual_volatility,
            )
            if volatility_brake_multiplier < 1.0:
                target = target * volatility_brake_multiplier
                brake_rebalance = True
        should_rebalance = scheduled_rebalance or brake_rebalance
        if should_rebalance:
            turnover = float(numpy.sum(numpy.abs(target - weights)))
            cost = turnover * (
                config.fee_per_turnover + config.slippage_per_turnover
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
            brake_turnover = float(
                numpy.sum(numpy.abs(target - pre_brake_target))
            )
            if brake_turnover:
                volatility_brake_events += 1
                volatility_brake_turnover += brake_turnover
            weights = target
            if scheduled_rebalance:
                last_rebalance = index
            risk_multiplier = target_risk_multiplier
        peak_equity = max(peak_equity, equity)
        equities.append(equity)
        applied_weights.append(weights.copy())
        risk_multipliers.append(risk_multiplier)
        volatility_brake_multipliers.append(
            volatility_brake_multiplier
        )
        fast_ex_ante_volatilities.append(fast_ex_ante_volatility)

    if not equities:
        raise ValueError("trend simulation contains no evaluable days")
    equity_values = numpy.asarray(equities, dtype=numpy.float64)
    weight_values = numpy.asarray(applied_weights)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity_values))
    )[1:]
    drawdowns = 1.0 - equity_values / peaks
    dates = market["dates"][start_index:end_index]
    monthly_returns = _period_returns(dates, equity_values, "%Y-%m")
    annual_returns = _period_returns(dates, equity_values, "%Y")
    rolling_12_month_returns = _rolling_period_returns(
        monthly_returns, 12
    )
    daily_portfolio_returns = numpy.diff(
        numpy.concatenate((numpy.ones(1), equity_values))
    ) / numpy.concatenate((numpy.ones(1), equity_values))[:-1]
    elapsed_years = (
        (dates[-1] - dates[0]).days / 365.25
    )
    final_equity = float(equity_values[-1])
    latest_index = end_index - 1
    latest_target = _target_weights(
        signals[latest_index], covariances[latest_index], config
    ) * risk_multiplier
    if brake_covariances is not None:
        latest_target *= _volatility_brake_multiplier(
            _portfolio_volatility(
                latest_target,
                brake_covariances[latest_index],
            ),
            config.target_annual_volatility,
        )
    last_market_index = latest_index
    days_since_last_rebalance = last_market_index - last_rebalance
    longest_drawdown_days = _longest_streak(drawdowns > 0)
    longest_negative_month_streak = _longest_streak(
        numpy.asarray(list(monthly_returns.values())) < 0
    )
    withdrawal_scenarios = {
        str(warmup): carry_module._historical_fixed_withdrawal(
            list(monthly_returns.values()),
            initial_capital,
            warmup_months=warmup,
            minimum_capital_fraction=1.0,
        )
        for warmup in (0, 12)
        if warmup < len(monthly_returns)
    }
    report = {
        "config": dataclasses.asdict(config),
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
        "total_turnover": total_turnover,
        "rebalance_events": rebalance_events,
        "total_cost_return": total_cost,
        "total_funding_return": total_funding,
        "long_additive_contribution": long_contribution,
        "short_additive_contribution": short_contribution,
        "average_gross_exposure": float(
            numpy.mean(numpy.sum(numpy.abs(weight_values), axis=1))
        ),
        "average_net_exposure": float(
            numpy.mean(numpy.sum(weight_values, axis=1))
        ),
        "average_long_exposure": float(
            numpy.mean(
                numpy.sum(numpy.maximum(weight_values, 0.0), axis=1)
            )
        ),
        "average_short_exposure": float(
            numpy.mean(
                numpy.sum(numpy.maximum(-weight_values, 0.0), axis=1)
            )
        ),
        "average_risk_multiplier": float(numpy.mean(risk_multipliers)),
        "minimum_risk_multiplier": float(numpy.min(risk_multipliers)),
        "reduced_risk_days": int(
            numpy.sum(numpy.asarray(risk_multipliers) < 1.0)
        ),
        "volatility_brake_events": volatility_brake_events,
        "volatility_brake_turnover": volatility_brake_turnover,
        "average_volatility_brake_multiplier": float(
            numpy.mean(volatility_brake_multipliers)
        ),
        "minimum_volatility_brake_multiplier": float(
            numpy.min(volatility_brake_multipliers)
        ),
        "average_fast_ex_ante_volatility": float(
            numpy.mean(fast_ex_ante_volatilities)
        ),
        "ending_weights": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], weight_values[-1])
        },
        "latest_rebalance_target_weights": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], latest_target)
        },
        "latest_signal": {
            symbol: int(value)
            for symbol, value in zip(
                market["symbols"], signals[latest_index]
            )
        },
        "latest_close": {
            symbol: float(value)
            for symbol, value in zip(
                market["symbols"], closes[latest_index]
            )
        },
        "latest_daily_funding": {
            symbol: float(value)
            for symbol, value in zip(
                market["symbols"], funding[latest_index]
            )
        },
        "days_since_last_rebalance": days_since_last_rebalance,
        "days_until_next_rebalance": max(
            0, config.rebalance_days - days_since_last_rebalance
        ),
        "longest_drawdown_days": longest_drawdown_days,
        "longest_negative_month_streak": longest_negative_month_streak,
        "positive_months": sum(value > 0 for value in monthly_returns.values()),
        "negative_months": sum(value < 0 for value in monthly_returns.values()),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly_returns.values())
            / len(monthly_returns)
        ),
        "median_month_return": float(
            numpy.median(list(monthly_returns.values()))
        ),
        "worst_month_return": min(monthly_returns.values()),
        "best_month_return": max(monthly_returns.values()),
        "monthly_returns": monthly_returns,
        "rolling_12_month_returns": rolling_12_month_returns,
        "worst_rolling_12_month_return": (
            min(rolling_12_month_returns.values())
            if rolling_12_month_returns
            else None
        ),
        "calendar_year_returns": annual_returns,
        "by_symbol_additive_contribution": {
            symbol: float(value)
            for symbol, value in zip(market["symbols"], contribution)
        },
        "historical_fixed_withdrawal": {
            "warning": (
                "Backtest capacity only; it is not a guaranteed future payment."
            ),
            "minimum_capital_fraction": 1.0,
            "scenarios_by_warmup_months": withdrawal_scenarios,
        },
    }
    if include_trajectory:
        report["trajectory"] = {
            "dates": [str(value) for value in dates],
            "equity": equity_values.tolist(),
            "gross_exposure": numpy.sum(
                numpy.abs(weight_values), axis=1
            ).tolist(),
            "volatility_brake_multiplier": volatility_brake_multipliers,
            "fast_ex_ante_volatility": fast_ex_ante_volatilities,
        }
    return report


def _drawdown_risk_multiplier(drawdown, config):
    if config.drawdown_soft_limit == 0:
        return 1.0
    if drawdown >= config.drawdown_hard_limit:
        return config.drawdown_hard_multiplier
    if drawdown >= config.drawdown_soft_limit:
        return config.drawdown_soft_multiplier
    return 1.0


def _portfolio_volatility(weights, covariance):
    if covariance.ndim == 0:
        covariance = numpy.asarray([[float(covariance)]])
    finite_covariance = numpy.nan_to_num(
        covariance, nan=0.0, posinf=0.0, neginf=0.0
    )
    variance = float(weights @ finite_covariance @ weights)
    return float(numpy.sqrt(max(0.0, variance)))


def _volatility_brake_multiplier(predicted_volatility, target_volatility):
    if not numpy.isfinite(predicted_volatility):
        return 0.0
    if predicted_volatility <= target_volatility:
        return 1.0
    return target_volatility / predicted_volatility


def _signals(closes, config, symbols=None):
    result = numpy.zeros_like(closes)
    slow_returns = None
    if config.signal_kind == "ema_cross":
        for column in range(closes.shape[1]):
            fast = indicators.ema(closes[:, column], config.fast_days)
            slow = indicators.ema(closes[:, column], config.slow_days)
            valid = numpy.isfinite(fast) & numpy.isfinite(slow)
            result[valid, column] = numpy.sign(fast[valid] - slow[valid])
    elif config.signal_kind == "dual_momentum":
        fast_returns = numpy.full_like(closes, numpy.nan)
        slow_returns = numpy.full_like(closes, numpy.nan)
        fast_returns[config.fast_days :] = (
            closes[config.fast_days :] / closes[: -config.fast_days] - 1.0
        )
        slow_returns[config.slow_days :] = (
            closes[config.slow_days :] / closes[: -config.slow_days] - 1.0
        )
        agreement = numpy.sign(fast_returns) == numpy.sign(slow_returns)
        valid = (
            agreement
            & numpy.isfinite(fast_returns)
            & numpy.isfinite(slow_returns)
        )
        result[valid] = numpy.sign(slow_returns[valid])
    elif config.signal_kind == "multi_horizon_dual_momentum":
        votes = numpy.zeros_like(closes)
        for fast_days, slow_days in config.momentum_horizons:
            fast_returns = numpy.full_like(closes, numpy.nan)
            horizon_slow_returns = numpy.full_like(closes, numpy.nan)
            fast_returns[fast_days:] = (
                closes[fast_days:] / closes[:-fast_days] - 1.0
            )
            horizon_slow_returns[slow_days:] = (
                closes[slow_days:] / closes[:-slow_days] - 1.0
            )
            valid = (
                (numpy.sign(fast_returns) == numpy.sign(horizon_slow_returns))
                & numpy.isfinite(fast_returns)
                & numpy.isfinite(horizon_slow_returns)
            )
            votes[valid] += numpy.sign(horizon_slow_returns[valid])
        minimum_votes = len(config.momentum_horizons) // 2 + 1
        agreed = numpy.abs(votes) >= minimum_votes
        result[agreed] = votes[agreed] / len(config.momentum_horizons)
    else:
        for column in range(closes.shape[1]):
            state = 0.0
            for index in range(config.slow_days, len(closes)):
                previous_entry = closes[
                    index - config.slow_days : index, column
                ]
                previous_exit = closes[
                    index - config.exit_days : index, column
                ]
                price = closes[index, column]
                if price > numpy.max(previous_entry):
                    state = 1.0
                elif price < numpy.min(previous_entry):
                    state = -1.0
                elif state > 0 and price < numpy.min(previous_exit):
                    state = 0.0
                elif state < 0 and price > numpy.max(previous_exit):
                    state = 0.0
                result[index, column] = state
    if config.market_regime_symbol:
        if symbols is None or config.market_regime_symbol not in symbols:
            raise ValueError(
                f"missing market regime symbol: {config.market_regime_symbol}"
            )
        regime_column = symbols.index(config.market_regime_symbol)
        regime = result[:, regime_column]
        aligned = (
            ((result > 0) & (regime[:, None] > 0))
            | ((result < 0) & (regime[:, None] < 0))
        )
        result = numpy.where(aligned, result, 0.0)
    if config.short_regime_symbol:
        if symbols is None or config.short_regime_symbol not in symbols:
            raise ValueError(
                f"missing short regime symbol: {config.short_regime_symbol}"
            )
        regime_column = symbols.index(config.short_regime_symbol)
        bearish_regime = result[:, regime_column] < 0
        result = numpy.where(
            (result >= 0) | bearish_regime[:, None],
            result,
            0.0,
        )
    if config.strongest_signal_fraction < 1:
        if slow_returns is None:
            raise ValueError(
                "strength ranking requires dual momentum returns"
            )
        result = _retain_strongest_signals(
            result,
            slow_returns,
            config.strongest_signal_fraction,
        )
    return result


def _retain_strongest_signals(signals, slow_returns, fraction):
    ranked = signals.copy()
    for index in range(len(ranked)):
        for direction in (-1.0, 1.0):
            candidates = numpy.flatnonzero(ranked[index] == direction)
            if len(candidates) <= 1:
                continue
            keep_count = max(
                1, int(numpy.ceil(len(candidates) * fraction))
            )
            ordered = sorted(
                candidates.tolist(),
                key=lambda column: (
                    -abs(float(slow_returns[index, column])),
                    column,
                ),
            )
            ranked[index, ordered[keep_count:]] = 0.0
    return ranked


def _rolling_covariance(returns, lookback):
    result = numpy.full(
        (len(returns), returns.shape[1], returns.shape[1]),
        numpy.nan,
        dtype=numpy.float64,
    )
    for index in range(lookback, len(returns)):
        result[index] = numpy.cov(
            returns[index - lookback + 1 : index + 1],
            rowvar=False,
            ddof=1,
        ) * 365.0
    return result


def _target_weights(signal, covariance, config):
    if covariance.ndim == 0:
        covariance = numpy.asarray([[float(covariance)]])
    diagonal = numpy.diag(covariance)
    signal_count = int(numpy.count_nonzero(signal))
    active_signal_fraction = signal_count / len(signal)
    directional_coherence = (
        abs(float(numpy.sum(signal))) / signal_count
        if signal_count
        else 0.0
    )
    if (
        active_signal_fraction < config.minimum_active_signal_fraction
        or directional_coherence < config.minimum_directional_coherence
    ):
        return numpy.zeros_like(signal, dtype=numpy.float64)
    active = (
        (signal != 0)
        & numpy.isfinite(diagonal)
        & (diagonal > 0)
    )
    if not numpy.any(active):
        return numpy.zeros_like(signal, dtype=numpy.float64)
    volatility = numpy.sqrt(diagonal)
    inverse_volatility = numpy.zeros_like(signal, dtype=numpy.float64)
    inverse_volatility[active] = 1.0 / volatility[active]
    unit = signal * inverse_volatility
    unit /= numpy.sum(numpy.abs(unit))
    active_covariance = numpy.nan_to_num(
        covariance, nan=0.0, posinf=0.0, neginf=0.0
    )
    predicted_variance = float(unit @ active_covariance @ unit)
    predicted_volatility = numpy.sqrt(max(0.0, predicted_variance))
    scale = min(
        config.maximum_gross_exposure,
        (
            config.target_annual_volatility / predicted_volatility
            if predicted_volatility > 0
            else 0.0
        ),
    )
    weights = unit * scale
    weights = numpy.clip(
        weights,
        -config.maximum_asset_exposure,
        config.maximum_asset_exposure,
    )
    gross = float(numpy.sum(numpy.abs(weights)))
    if gross > config.maximum_gross_exposure:
        weights *= config.maximum_gross_exposure / gross
    return weights


def _period_returns(dates, equity, format_value):
    endpoints = {}
    for date, value in zip(dates, equity):
        endpoints[date.strftime(format_value)] = float(value)
    result = {}
    previous = 1.0
    for period, value in sorted(endpoints.items()):
        result[period] = value / previous - 1.0
        previous = value
    return result


def _rolling_period_returns(period_returns, window):
    if window < 1:
        raise ValueError("rolling period window must be positive")
    items = list(period_returns.items())
    result = {}
    for end in range(window - 1, len(items)):
        selected = items[end - window + 1 : end + 1]
        compounded = float(
            numpy.prod([1.0 + value for _, value in selected]) - 1.0
        )
        result[f"{selected[0][0]}..{selected[-1][0]}"] = compounded
    return result


def _longest_streak(values):
    longest = 0
    current = 0
    for value in values:
        current = current + 1 if bool(value) else 0
        longest = max(longest, current)
    return longest
