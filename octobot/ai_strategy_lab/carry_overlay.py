"""Idle-collateral carry overlay for the frozen V3 trend protocol."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import carry as carry_module
from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import trend as trend_module


OVERLAY_SCHEMA_VERSION = 3
OVERLAY_NAME = "idle_collateral_carry_overlay_v5"
TREND_CONFIG_NAME = (
    "bear_regime_short_filter_dual_momentum_30_120_weekly_v3"
)
RISK_BUDGETED_OVERLAY_NAME = "risk_budgeted_idle_carry_overlay_v14"
RISK_BUDGETED_TREND_CONFIG_NAME = "risk_budgeted_bear_regime_v13"
CARRY_CONFIG_NAME = "persistent_carry_v1"
COST_AWARE_OVERLAY_NAME = "cost_aware_idle_carry_overlay_v15"
COST_AWARE_STRESS_OVERLAY_NAME = (
    "cost_aware_idle_carry_overlay_v15_r1_half_funding"
)
COST_AWARE_CARRY_CONFIG_NAME = "cost_aware_persistent_v2"
EXECUTION_GUARDED_OVERLAY_NAME = (
    "execution_guarded_cost_aware_overlay_v16"
)
EXECUTION_GUARDED_STRESS_OVERLAY_NAME = (
    "execution_guarded_cost_aware_overlay_v16_r1_half_funding"
)
EXECUTION_GUARDED_CARRY_CONFIG_NAME = (
    "execution_guarded_cost_aware_v3"
)
ROTATING_OVERLAY_NAME = "rotating_cost_aware_carry_overlay_v17"
ROTATING_STRESS_OVERLAY_NAME = (
    "rotating_cost_aware_carry_overlay_v17_r1_half_funding"
)
RISK_BUDGETED_STRESS_OVERLAY_NAMES = {
    0.5: "risk_budgeted_idle_carry_overlay_v14_r1_half_funding",
    0.0: "risk_budgeted_idle_carry_overlay_v14_r1_zero_funding",
}


def evaluate_carry_overlay(
    futures_collectors: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    spot_collector: typing.Union[str, pathlib.Path],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    *,
    initial_capital: float = 10_000.0,
    trend_cost_stress_multiplier: float = 3.0,
    carry_cost_stress_multiplier: float = 3.0,
    max_overlay_fraction: float = 0.20,
) -> dict:
    return _evaluate_carry_overlay(
        futures_collectors,
        spot_collector,
        funding_paths,
        initial_capital=initial_capital,
        trend_cost_stress_multiplier=trend_cost_stress_multiplier,
        carry_cost_stress_multiplier=carry_cost_stress_multiplier,
        max_overlay_fraction=max_overlay_fraction,
        trend_config_name=TREND_CONFIG_NAME,
        overlay_name=OVERLAY_NAME,
    )


def evaluate_risk_budgeted_carry_overlay(
    futures_collectors: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    spot_collector: typing.Union[str, pathlib.Path],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    *,
    initial_capital: float = 10_000.0,
    trend_cost_stress_multiplier: float = 3.0,
    carry_cost_stress_multiplier: float = 3.0,
    max_overlay_fraction: float = 0.20,
    positive_funding_realization: float = 1.0,
    entry_delay_settlements: int = 0,
) -> dict:
    overlay_name = _risk_budgeted_overlay_name(
        carry_cost_stress_multiplier,
        positive_funding_realization,
        entry_delay_settlements,
    )
    return _evaluate_carry_overlay(
        futures_collectors,
        spot_collector,
        funding_paths,
        initial_capital=initial_capital,
        trend_cost_stress_multiplier=trend_cost_stress_multiplier,
        carry_cost_stress_multiplier=carry_cost_stress_multiplier,
        max_overlay_fraction=max_overlay_fraction,
        positive_funding_realization=positive_funding_realization,
        entry_delay_settlements=entry_delay_settlements,
        trend_config_name=RISK_BUDGETED_TREND_CONFIG_NAME,
        overlay_name=overlay_name,
    )


def evaluate_cost_aware_carry_overlay(
    futures_collectors: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    spot_collector: typing.Union[str, pathlib.Path],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    *,
    initial_capital: float = 10_000.0,
    trend_cost_stress_multiplier: float = 3.0,
    carry_cost_stress_multiplier: float = 3.0,
    max_overlay_fraction: float = 0.20,
    positive_funding_realization: float = 1.0,
) -> dict:
    if (
        carry_cost_stress_multiplier == 3.0
        and positive_funding_realization == 1.0
    ):
        overlay_name = COST_AWARE_OVERLAY_NAME
    elif (
        carry_cost_stress_multiplier == 5.0
        and positive_funding_realization == 0.5
    ):
        overlay_name = COST_AWARE_STRESS_OVERLAY_NAME
    else:
        raise ValueError(
            "V15 must match its pre-registered baseline or stress"
        )
    return _evaluate_carry_overlay(
        futures_collectors,
        spot_collector,
        funding_paths,
        initial_capital=initial_capital,
        trend_cost_stress_multiplier=trend_cost_stress_multiplier,
        carry_cost_stress_multiplier=carry_cost_stress_multiplier,
        max_overlay_fraction=max_overlay_fraction,
        positive_funding_realization=positive_funding_realization,
        entry_delay_settlements=1,
        trend_config_name=RISK_BUDGETED_TREND_CONFIG_NAME,
        overlay_name=overlay_name,
        carry_config_name=COST_AWARE_CARRY_CONFIG_NAME,
        track_active_allocation=True,
    )


def evaluate_execution_guarded_carry_overlay(
    futures_collectors: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    spot_collector: typing.Union[str, pathlib.Path],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    *,
    initial_capital: float = 10_000.0,
    trend_cost_stress_multiplier: float = 3.0,
    carry_cost_stress_multiplier: float = 3.0,
    max_overlay_fraction: float = 0.20,
    positive_funding_realization: float = 1.0,
) -> dict:
    if (
        carry_cost_stress_multiplier == 3.0
        and positive_funding_realization == 1.0
    ):
        overlay_name = EXECUTION_GUARDED_OVERLAY_NAME
    elif (
        carry_cost_stress_multiplier == 5.0
        and positive_funding_realization == 0.5
    ):
        overlay_name = EXECUTION_GUARDED_STRESS_OVERLAY_NAME
    else:
        raise ValueError(
            "V16 must match its pre-registered baseline or stress"
        )
    return _evaluate_carry_overlay(
        futures_collectors,
        spot_collector,
        funding_paths,
        initial_capital=initial_capital,
        trend_cost_stress_multiplier=trend_cost_stress_multiplier,
        carry_cost_stress_multiplier=carry_cost_stress_multiplier,
        max_overlay_fraction=max_overlay_fraction,
        positive_funding_realization=positive_funding_realization,
        entry_delay_settlements=1,
        trend_config_name=RISK_BUDGETED_TREND_CONFIG_NAME,
        overlay_name=overlay_name,
        carry_config_name=EXECUTION_GUARDED_CARRY_CONFIG_NAME,
        track_active_allocation=True,
    )


def evaluate_rotating_cost_aware_carry_overlay(
    futures_collectors: typing.Iterable[
        typing.Union[str, pathlib.Path]
    ],
    spot_collector: typing.Union[str, pathlib.Path],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    *,
    initial_capital: float = 10_000.0,
    trend_cost_stress_multiplier: float = 3.0,
    carry_cost_stress_multiplier: float = 3.0,
    max_overlay_fraction: float = 0.20,
    positive_funding_realization: float = 1.0,
) -> dict:
    if (
        carry_cost_stress_multiplier == 3.0
        and positive_funding_realization == 1.0
    ):
        overlay_name = ROTATING_OVERLAY_NAME
    elif (
        carry_cost_stress_multiplier == 5.0
        and positive_funding_realization == 0.5
    ):
        overlay_name = ROTATING_STRESS_OVERLAY_NAME
    else:
        raise ValueError(
            "V17 must match its pre-registered baseline or stress"
        )
    return _evaluate_carry_overlay(
        futures_collectors,
        spot_collector,
        funding_paths,
        initial_capital=initial_capital,
        trend_cost_stress_multiplier=trend_cost_stress_multiplier,
        carry_cost_stress_multiplier=carry_cost_stress_multiplier,
        max_overlay_fraction=max_overlay_fraction,
        positive_funding_realization=positive_funding_realization,
        entry_delay_settlements=1,
        trend_config_name=RISK_BUDGETED_TREND_CONFIG_NAME,
        overlay_name=overlay_name,
        carry_config_name=EXECUTION_GUARDED_CARRY_CONFIG_NAME,
        track_active_allocation=True,
        rotate_single_pair=True,
    )


def _evaluate_carry_overlay(
    futures_collectors,
    spot_collector,
    funding_paths,
    *,
    initial_capital,
    trend_cost_stress_multiplier,
    carry_cost_stress_multiplier,
    max_overlay_fraction,
    trend_config_name,
    overlay_name,
    positive_funding_realization=1.0,
    entry_delay_settlements=0,
    carry_config_name=CARRY_CONFIG_NAME,
    track_active_allocation=False,
    rotate_single_pair=False,
):
    if initial_capital <= 0:
        raise ValueError("initial capital must be positive")
    if trend_cost_stress_multiplier < 1 or carry_cost_stress_multiplier < 1:
        raise ValueError("cost stress multipliers must be at least one")
    if not 0 < max_overlay_fraction <= 1:
        raise ValueError("max overlay fraction must be in (0, 1]")
    if not 0 <= positive_funding_realization <= 1:
        raise ValueError("positive funding realization must be in [0, 1]")
    if entry_delay_settlements < 0:
        raise ValueError("entry delay settlements cannot be negative")

    future_paths = [
        pathlib.Path(value).resolve() for value in futures_collectors
    ]
    if not future_paths:
        raise ValueError("at least one futures collector is required")
    funding_values = [
        pathlib.Path(value).resolve() for value in funding_paths
    ]
    if not funding_values:
        raise ValueError("at least one funding input is required")

    futures = dataset_module.load_collector_series(
        future_paths, required_time_frames=("1h",)
    )
    spot = dataset_module.load_collector_series(
        [pathlib.Path(spot_collector).resolve()],
        required_time_frames=("1h",),
    )
    funding = _load_funding(funding_values)
    trend_symbols = sorted(set(futures) & set(funding))
    if not trend_symbols:
        raise ValueError("no futures symbol has signed funding history")

    market = trend_module._build_daily_market(
        {
            symbol: futures[symbol]["1h"]
            for symbol in trend_symbols
        },
        {symbol: funding[symbol] for symbol in trend_symbols},
    )
    trend_config = _stressed_trend_config(
        trend_cost_stress_multiplier,
        config_name=trend_config_name,
    )
    trend_report = trend_module._simulate(
        market,
        trend_config,
        initial_capital,
        include_trajectory=True,
    )

    pairs = carry_module._pair_symbols(futures, spot, funding)
    carry_config = _stressed_carry_config(
        carry_cost_stress_multiplier,
        positive_funding_realization=positive_funding_realization,
        entry_delay_settlements=entry_delay_settlements,
        config_name=carry_config_name,
    )
    if rotate_single_pair:
        rotation = carry_module._simulate_rotation(
            [
                (
                    base,
                    futures[futures_symbol]["1h"],
                    spot[spot_symbol]["1h"],
                    funding[futures_symbol],
                )
                for base, futures_symbol, spot_symbol in pairs
            ],
            carry_config,
        )
        carry_points = rotation["equity_points"]
        carry_active_points = rotation["active_points"]
    else:
        carry_sleeves = [
            carry_module._simulate_sleeve(
                base,
                futures[futures_symbol]["1h"],
                spot[spot_symbol]["1h"],
                funding[futures_symbol],
                carry_config,
            )
            for base, futures_symbol, spot_symbol in pairs
        ]
        carry_points = carry_module._portfolio_equity_points(
            carry_sleeves
        )
        carry_active_points = (
            carry_module._portfolio_active_fraction_points(carry_sleeves)
            if track_active_allocation
            else None
        )
    overlay_report = _combine_paths(
        trend_report["trajectory"],
        carry_points,
        initial_capital=initial_capital,
        max_overlay_fraction=max_overlay_fraction,
        carry_config=carry_config,
        carry_active_points=carry_active_points,
    )
    overlay_report["config"] = {
        "name": overlay_name,
        "trend": dataclasses.asdict(trend_config),
        "carry": dataclasses.asdict(carry_config),
        "max_overlay_fraction": max_overlay_fraction,
        "gross_exposure_cap": 1.0,
        "allocation_rule": (
            "min(max_overlay_fraction, 1 - prior_day_trend_gross)"
        ),
        "netting_assumed": False,
    }
    baseline = {
        key: value
        for key, value in trend_report.items()
        if key != "trajectory"
    }
    return {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "warning": (
            "Diagnostic reuse only. Spot/perpetual custody, taxes and "
            "future returns are not guaranteed or authorized for execution."
        ),
        "initial_capital": initial_capital,
        "trend_symbols": trend_symbols,
        "carry_pairs": [
            {
                "base": base,
                "futures_symbol": futures_symbol,
                "spot_symbol": spot_symbol,
            }
            for base, futures_symbol, spot_symbol in pairs
        ],
        "trend_cost_stress_multiplier": trend_cost_stress_multiplier,
        "carry_cost_stress_multiplier": carry_cost_stress_multiplier,
        "positive_funding_realization": positive_funding_realization,
        "entry_delay_settlements": entry_delay_settlements,
        "track_active_allocation": track_active_allocation,
        "carry_allocation": (
            "single highest point-in-time qualified pair"
            if rotate_single_pair
            else "equal weight across fixed pair sleeves"
        ),
        "max_overlay_fraction": max_overlay_fraction,
        "reports": {
            trend_config.name: baseline,
            overlay_name: overlay_report,
        },
    }


def _load_funding(paths):
    result = {}
    for path in paths:
        loaded = funding_module.load_funding(path)
        overlap = set(result) & set(loaded)
        if overlap:
            raise ValueError(
                f"funding symbols appear in multiple inputs: {sorted(overlap)}"
            )
        result.update(loaded)
    return result


def _stressed_trend_config(multiplier, *, config_name=TREND_CONFIG_NAME):
    config = next(
        value
        for value in trend_module.TREND_CONFIGS
        if value.name == config_name
    )
    return dataclasses.replace(
        config,
        name=f"{config.name}_cost_stress_{multiplier:g}x",
        fee_per_turnover=config.fee_per_turnover * multiplier,
        slippage_per_turnover=(
            config.slippage_per_turnover * multiplier
        ),
    )


def _stressed_carry_config(
    multiplier,
    *,
    positive_funding_realization=1.0,
    entry_delay_settlements=0,
    config_name=CARRY_CONFIG_NAME,
):
    config = next(
        value
        for value in carry_module.CARRY_CONFIGS
        if value.name == config_name
    )
    return dataclasses.replace(
        config,
        name=f"{config.name}_cost_stress_{multiplier:g}x",
        spot_fee_per_fill=config.spot_fee_per_fill * multiplier,
        futures_fee_per_fill=config.futures_fee_per_fill * multiplier,
        slippage_per_fill=config.slippage_per_fill * multiplier,
        positive_funding_realization=positive_funding_realization,
        entry_delay_settlements=entry_delay_settlements,
    )


def _risk_budgeted_overlay_name(
    carry_cost_stress_multiplier,
    positive_funding_realization,
    entry_delay_settlements,
):
    baseline = (
        carry_cost_stress_multiplier == 3.0
        and positive_funding_realization == 1.0
        and entry_delay_settlements == 0
    )
    if baseline:
        return RISK_BUDGETED_OVERLAY_NAME
    if (
        carry_cost_stress_multiplier == 5.0
        and entry_delay_settlements == 1
        and positive_funding_realization
        in RISK_BUDGETED_STRESS_OVERLAY_NAMES
    ):
        return RISK_BUDGETED_STRESS_OVERLAY_NAMES[
            positive_funding_realization
        ]
    raise ValueError(
        "non-baseline risk-budgeted overlays must match a "
        "pre-registered V14-R1 scenario"
    )


def _combine_paths(
    trend_trajectory,
    carry_points,
    *,
    initial_capital,
    max_overlay_fraction,
    carry_config,
    carry_active_points=None,
):
    dates = [
        datetime.date.fromisoformat(value)
        for value in trend_trajectory["dates"]
    ]
    trend_equity = numpy.asarray(
        trend_trajectory["equity"], dtype=numpy.float64
    )
    trend_gross = numpy.asarray(
        trend_trajectory["gross_exposure"], dtype=numpy.float64
    )
    if (
        not dates
        or len(dates) != len(trend_equity)
        or len(dates) != len(trend_gross)
    ):
        raise ValueError("invalid trend trajectory")
    carry_by_day = _carry_equity_by_day(carry_points)
    carry_equity = _align_carry_equity(dates, carry_by_day)

    trend_returns = numpy.diff(
        numpy.concatenate((numpy.ones(1), trend_equity))
    ) / numpy.concatenate((numpy.ones(1), trend_equity))[:-1]
    carry_returns = numpy.diff(carry_equity) / carry_equity[:-1]
    carry_returns = numpy.concatenate((numpy.zeros(1), carry_returns))
    active_fractions = (
        numpy.ones(len(dates), dtype=numpy.float64)
        if carry_active_points is None
        else _align_carry_activity(dates, carry_active_points)
    )

    combined_equity = numpy.empty(len(dates), dtype=numpy.float64)
    allocations = numpy.zeros(len(dates), dtype=numpy.float64)
    active_allocations = numpy.zeros(len(dates), dtype=numpy.float64)
    overlay_contribution = numpy.zeros(len(dates), dtype=numpy.float64)
    resize_costs = numpy.zeros(len(dates), dtype=numpy.float64)
    previous_equity = 1.0
    previous_allocation = 0.0
    one_way_resize_cost = (
        carry_config.leg_fraction
        * (
            carry_config.spot_fee_per_fill
            + carry_config.slippage_per_fill
        )
        + carry_config.leg_fraction
        * (
            carry_config.futures_fee_per_fill
            + carry_config.slippage_per_fill
        )
    )
    for index in range(len(dates)):
        allocation = min(
            max_overlay_fraction,
            max(0.0, 1.0 - trend_gross[index]),
        )
        resize_cost = (
            abs(allocation - previous_allocation)
            * active_fractions[index]
            * one_way_resize_cost
        )
        contribution = (
            previous_allocation * carry_returns[index] - resize_cost
        )
        portfolio_return = trend_returns[index] + contribution
        if portfolio_return <= -1:
            raise ValueError("combined portfolio equity became non-positive")
        previous_equity *= 1.0 + portfolio_return
        combined_equity[index] = previous_equity
        allocations[index] = allocation
        active_allocations[index] = allocation * active_fractions[index]
        overlay_contribution[index] = contribution
        resize_costs[index] = resize_cost
        previous_allocation = allocation

    daily_returns = numpy.diff(
        numpy.concatenate((numpy.ones(1), combined_equity))
    ) / numpy.concatenate((numpy.ones(1), combined_equity))[:-1]
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), combined_equity))
    )[1:]
    drawdowns = 1.0 - combined_equity / peaks
    monthly_returns = trend_module._period_returns(
        dates, combined_equity, "%Y-%m"
    )
    annual_returns = trend_module._period_returns(
        dates, combined_equity, "%Y"
    )
    rolling = _rolling_month_returns(monthly_returns, 12)
    elapsed_years = (dates[-1] - dates[0]).days / 365.25
    final_equity = float(combined_equity[-1])
    volatility = float(numpy.std(daily_returns) * numpy.sqrt(365.0))
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
        "annualized_volatility": volatility,
        "sharpe_zero_rate": (
            float(
                numpy.mean(daily_returns)
                / numpy.std(daily_returns)
                * numpy.sqrt(365.0)
            )
            if numpy.std(daily_returns) > 0
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
        "monthly_returns": monthly_returns,
        "calendar_year_returns": annual_returns,
        "worst_rolling_12_month_return": (
            min(rolling.values()) if rolling else None
        ),
        "rolling_12_month_returns": rolling,
        "average_overlay_allocation": float(numpy.mean(allocations)),
        "maximum_overlay_allocation": float(numpy.max(allocations)),
        "average_active_overlay_gross": float(
            numpy.mean(active_allocations)
        ),
        "maximum_active_overlay_gross": float(
            numpy.max(active_allocations)
        ),
        "overlay_active_day_ratio": float(numpy.mean(allocations > 0)),
        "maximum_conservative_gross_exposure": float(
            numpy.max(trend_gross + active_allocations)
        ),
        "overlay_additive_return_contribution": float(
            numpy.sum(overlay_contribution)
        ),
        "overlay_resize_cost_return": float(numpy.sum(resize_costs)),
        "daily_return_correlation": (
            float(numpy.corrcoef(trend_returns, carry_returns)[0, 1])
            if numpy.std(trend_returns) > 0
            and numpy.std(carry_returns) > 0
            else 0.0
        ),
    }


def _carry_equity_by_day(carry_points):
    if not carry_points:
        raise ValueError("carry trajectory is empty")
    result = {}
    for timestamp, equity in carry_points:
        day = datetime.datetime.fromtimestamp(
            timestamp, datetime.timezone.utc
        ).date()
        result[day] = float(equity)
    return result


def _align_carry_equity(dates, carry_by_day):
    points = sorted(carry_by_day.items())
    cursor = 0
    current = 1.0
    result = []
    for day in dates:
        while cursor < len(points) and points[cursor][0] <= day:
            current = points[cursor][1]
            cursor += 1
        result.append(current)
    values = numpy.asarray(result, dtype=numpy.float64)
    if numpy.any(values <= 0):
        raise ValueError("carry equity must remain positive")
    return values


def _align_carry_activity(dates, active_points):
    by_day = {}
    for timestamp, active_fraction in active_points:
        day = datetime.datetime.fromtimestamp(
            timestamp, datetime.timezone.utc
        ).date()
        by_day[day] = float(active_fraction)
    points = sorted(by_day.items())
    cursor = 0
    current = 0.0
    result = []
    for day in dates:
        while cursor < len(points) and points[cursor][0] <= day:
            current = points[cursor][1]
            cursor += 1
        result.append(current)
    values = numpy.asarray(result, dtype=numpy.float64)
    if numpy.any(values < 0) or numpy.any(values > 1):
        raise ValueError("carry active fractions must be in [0, 1]")
    return values


def _rolling_month_returns(monthly_returns, months):
    keys = sorted(monthly_returns)
    values = [monthly_returns[key] for key in keys]
    result = {}
    for index in range(months - 1, len(values)):
        result[keys[index]] = float(
            numpy.prod(
                1.0 + numpy.asarray(values[index - months + 1 : index + 1])
            )
            - 1.0
        )
    return result
