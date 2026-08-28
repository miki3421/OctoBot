"""Offline evaluator for frozen expanded Cointegration Pairs V2.

The evaluator reuses one immutable public-data bundle, has no exchange client
or credential path, and cannot create shadow, paper or real orders.  Historical
windows are diagnostic reuse and are opened strictly in sequence.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import itertools
import json
import math
import os
import pathlib
import shutil
import tempfile
import typing

import numpy

from octobot.ai_strategy_lab import category_momentum_v1_research as source
from octobot.ai_strategy_lab import cointegration_pairs_v1 as parent
from octobot.ai_strategy_lab import cointegration_pairs_v2 as protocol_module


SCHEMA_VERSION = 1
UTC = datetime.timezone.utc


class DataQualityError(ValueError):
    """Raised when a frozen input or causal outcome is incomplete."""


def _load_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    frozen = protocol_module.frozen_protocol()
    expected = {**frozen, "protocol_sha256": parent._json_hash(frozen)}
    if persisted != expected:
        raise ValueError("Cointegration Pairs V2 protocol is not frozen")
    return persisted


def _load_market(
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
) -> tuple[pathlib.Path, dict, pathlib.Path, dict, dict]:
    category_frozen = source.protocol_module.frozen_protocol()
    category_protocol_sha256 = parent._json_hash(category_frozen)
    snapshot_root, snapshot_manifest, universe, _taxonomy = source._load_snapshot(
        snapshot_value,
        category_protocol_sha256,
    )
    if (
        snapshot_manifest["source_bundle_sha256"]
        != protocol_module.SOURCE_SNAPSHOT_BUNDLE_SHA256
    ):
        raise ValueError("V2 source snapshot bundle is not the frozen bundle")
    if universe["selected_contracts"] != protocol_module.UNIVERSE_ASSETS:
        raise ValueError("V2 frozen universe does not contain exactly 120 assets")
    history_root, history_manifest, panel = source._load_history(
        history_value,
        category_protocol_sha256,
        snapshot_manifest["source_bundle_sha256"],
    )
    if (
        history_manifest["history_bundle_sha256"]
        != protocol_module.HISTORY_BUNDLE_SHA256
    ):
        raise ValueError("V2 history is not the frozen history bundle")

    timestamps = numpy.asarray(panel["timestamps"], dtype=numpy.int64)
    symbols = [str(value) for value in panel["symbols"]]
    universe_symbols = [
        str(value["symbol"]) for value in universe["symbols"]
    ]
    closes = numpy.asarray(panel["closes"], dtype=numpy.float64)
    funding = numpy.asarray(panel["funding_rates"], dtype=numpy.float64)
    funding_counts = numpy.asarray(panel["funding_counts"], dtype=numpy.int16)
    expected_shape = (len(timestamps), protocol_module.UNIVERSE_ASSETS)
    if (
        timestamps.ndim != 1
        or len(timestamps) < parent.FORMATION_DAYS
        or closes.shape != expected_shape
        or funding.shape != expected_shape
        or funding_counts.shape != expected_shape
    ):
        raise DataQualityError("unexpected frozen market shape")
    if symbols != universe_symbols or len(set(symbols)) != len(symbols):
        raise DataQualityError("history symbols differ from the frozen universe")
    if numpy.any(numpy.diff(timestamps) != 86_400):
        raise DataQualityError("frozen market dates are not contiguous UTC days")
    if numpy.any(numpy.isfinite(closes) & (closes <= 0)) or numpy.any(
        numpy.isinf(closes)
    ):
        raise DataQualityError("frozen market contains an invalid close")
    if numpy.any(funding_counts < 0) or numpy.any(
        (funding_counts > 0) & ~numpy.isfinite(funding)
    ):
        raise DataQualityError("frozen market contains invalid funding")
    returns = numpy.zeros_like(closes)
    complete = (
        numpy.isfinite(closes[1:])
        & numpy.isfinite(closes[:-1])
        & (closes[1:] > 0)
        & (closes[:-1] > 0)
    )
    calculated = numpy.zeros_like(closes[1:])
    calculated[complete] = closes[1:][complete] / closes[:-1][complete] - 1.0
    returns[1:] = calculated
    market = {
        "dates": [
            datetime.datetime.fromtimestamp(int(value), UTC).date()
            for value in timestamps
        ],
        "timestamps": timestamps,
        "symbols": symbols,
        "closes": closes,
        "returns": returns,
        "return_complete": numpy.vstack(
            (numpy.zeros((1, closes.shape[1]), dtype=bool), complete)
        ),
        "funding": funding,
        "funding_counts": funding_counts,
    }
    return (
        snapshot_root,
        snapshot_manifest,
        history_root,
        history_manifest,
        market,
    )


def monte_carlo_null_t_statistics(
    simulations: int = protocol_module.MONTE_CARLO_SIMULATIONS,
    *,
    observations: int = parent.FORMATION_DAYS,
    seed: int = protocol_module.MONTE_CARLO_SEED,
    chunk_size: int = 2000,
) -> numpy.ndarray:
    """Build the frozen high-resolution Engle--Granger residual null."""

    return parent.monte_carlo_null_t_statistics(
        simulations,
        observations=observations,
        seed=seed,
        chunk_size=chunk_size,
    )


def _eligible_columns(market: dict, index: int) -> list[int]:
    required = parent.FORMATION_DAYS
    if index + 1 < required:
        return []
    window = market["closes"][index - required + 1 : index + 1]
    eligible = numpy.all(numpy.isfinite(window) & (window > 0), axis=0)
    return [int(value) for value in numpy.flatnonzero(eligible)]


def _bh_threshold(p_values: list[float], total_tests: int) -> float | None:
    """Return BH threshold using every eligible hypothesis in the denominator."""

    if total_tests < len(p_values) or total_tests < 1:
        raise ValueError("invalid Benjamini-Hochberg hypothesis count")
    threshold = None
    for rank, value in enumerate(sorted(p_values), start=1):
        if value <= parent.FDR_Q * rank / total_tests:
            threshold = value
    return threshold


def fit_formation(
    market: dict,
    index: int,
    null: numpy.ndarray,
) -> dict:
    """Fit every valid candidate once using only the trailing formation rows."""

    eligible = _eligible_columns(market, index)
    total_tests = math.comb(len(eligible), 2) if len(eligible) >= 2 else 0
    formation = numpy.log(
        market["closes"][index - parent.FORMATION_DAYS + 1 : index + 1]
    )
    candidates = []
    for first, second in itertools.combinations(eligible, 2):
        candidate = parent._fit_pair(formation, first, second, null)
        if candidate is not None:
            candidates.append(candidate)
    return {
        "index": index,
        "date": market["dates"][index],
        "eligible_columns": eligible,
        "total_tests": total_tests,
        "candidates": candidates,
    }


def build_formation_cache(
    market: dict,
    start: datetime.date,
    end: datetime.date,
    null: numpy.ndarray,
) -> dict[int, dict]:
    """Fit only formations belonging to one currently authorized period."""

    indices = [
        index
        for index, date in enumerate(market["dates"])
        if start <= date < end and date.day == 1
    ]
    if not indices:
        raise ValueError("authorized period has no monthly formation")
    return {index: fit_formation(market, index, null) for index in indices}


def select_pairs(
    formation: dict,
    symbols: list[str],
    *,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
) -> tuple[list[parent.PairModel], dict]:
    """Apply frozen FDR and stability filters to one cached formation."""

    excluded_columns = {
        index for index, symbol in enumerate(symbols) if symbol in excluded_symbols
    }
    eligible = [
        value
        for value in formation["eligible_columns"]
        if value not in excluded_columns
    ]
    total_tests = math.comb(len(eligible), 2) if len(eligible) >= 2 else 0
    candidates = [
        value
        for value in formation["candidates"]
        if value.first not in excluded_columns
        and value.second not in excluded_columns
    ]
    threshold = (
        _bh_threshold([value.p_value for value in candidates], total_tests)
        if total_tests
        else None
    )
    significant = (
        []
        if threshold is None
        else [value for value in candidates if value.p_value <= threshold]
    )
    stable = [
        value
        for value in significant
        if parent.MINIMUM_HALF_LIFE_DAYS
        <= value.half_life_days
        <= parent.MAXIMUM_HALF_LIFE_DAYS
        and value.zero_crossings >= parent.MINIMUM_ZERO_CROSSINGS
    ]
    ordered = sorted(
        stable,
        key=lambda value: (
            value.p_value,
            value.half_life_days,
            symbols[value.first],
            symbols[value.second],
        ),
    )
    selected = []
    used = set()
    for value in ordered:
        if value.first in used or value.second in used:
            continue
        selected.append(value)
        used.update(value.key)
        if len(selected) >= parent.MAXIMUM_PAIRS:
            break
    return selected, {
        "date": formation["date"].isoformat(),
        "eligible_assets": len(eligible),
        "tested_pairs": total_tests,
        "fitted_candidates": len(candidates),
        "bh_threshold": threshold,
        "significant_pairs": len(significant),
        "stable_pairs": len(stable),
        "selected_pairs": len(selected),
        "pairs": [
            f"{symbols[value.first]}|{symbols[value.second]}"
            for value in selected
        ],
    }


def _period_compound_returns(
    dates: list[datetime.date], values: numpy.ndarray, format_value: str
) -> dict:
    groups: dict[str, list[float]] = {}
    for date, value in zip(dates, values):
        groups.setdefault(date.strftime(format_value), []).append(float(value))
    return {
        key: float(numpy.prod(1.0 + numpy.asarray(group)) - 1.0)
        for key, group in sorted(groups.items())
    }


def _pair_name(model: parent.PairModel, symbols: list[str]) -> str:
    return f"{symbols[model.first]}|{symbols[model.second]}"


def simulate_period(
    market: dict,
    formation_cache: dict[int, dict],
    start: datetime.date,
    end: datetime.date,
    *,
    cost_multiplier: float = 1.0,
    excluded_symbols: typing.AbstractSet[str] = frozenset(),
    include_trajectory: bool = False,
    include_details: bool = True,
) -> dict:
    """Simulate one half-open period, always opening and closing from flat."""

    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    indices = [
        index
        for index, date in enumerate(market["dates"])
        if start <= date < end
    ]
    if not indices:
        raise ValueError("evaluation interval is absent from the market")
    first_index, final_index = indices[0], indices[-1]
    if first_index not in formation_cache:
        raise ValueError("period start has no authorized formation cache")

    symbols = market["symbols"]
    symbol_count = len(symbols)
    weights = numpy.zeros(symbol_count, dtype=numpy.float64)
    selected: dict[tuple[int, int], parent.PairModel] = {}
    states: dict[tuple[int, int], int] = {}
    stopped: set[tuple[int, int]] = set()
    open_trades: dict[tuple[int, int], dict] = {}
    trades = []
    selection_audit = []
    pair_frequency: dict[str, int] = {}
    pair_contributions: dict[str, float] = {}
    ever_traded_symbols = set()
    cost_rate = cost_multiplier * (
        parent.FEE_PER_TURNOVER + parent.SLIPPAGE_PER_TURNOVER
    )
    equity = 1.0
    total_cost = 0.0
    total_funding = 0.0
    total_turnover = 0.0
    daily_values = []
    market_values = []
    evaluation_dates = []
    gross_values = []

    def close_trade(
        key: tuple[int, int],
        date: datetime.date,
        reason: str,
        exit_cost: float,
    ) -> None:
        trade = open_trades.pop(key, None)
        if trade is None:
            return
        trade["cost_return"] += exit_cost
        trade["net_return"] -= exit_cost
        trade["exit_date"] = date.isoformat()
        trade["exit_reason"] = reason
        trades.append(trade)
        pair = trade["pair"]
        pair_contributions[pair] = (
            pair_contributions.get(pair, 0.0) + trade["net_return"]
        )

    for index in indices:
        date = market["dates"][index]
        before = equity
        targeted = numpy.flatnonzero(numpy.abs(weights) > 1e-15)
        if len(targeted) and (
            not numpy.all(market["return_complete"][index, targeted])
            or not numpy.all(market["funding_counts"][index, targeted] > 0)
        ):
            raise DataQualityError(
                "an open pair has an incomplete price or funding outcome"
            )
        price_by_symbol = weights * market["returns"][index]
        funding_by_symbol = -weights * market["funding"][index]
        gross_return = float(numpy.sum(price_by_symbol + funding_by_symbol))
        if gross_return <= -1.0:
            raise DataQualityError(
                "daily gross return is at or below minus 100 percent"
            )
        equity *= 1.0 + gross_return
        total_funding += float(numpy.sum(funding_by_symbol))
        for key, trade in open_trades.items():
            model = selected[key]
            columns = [model.first, model.second]
            contribution = float(
                numpy.sum(price_by_symbol[columns] + funding_by_symbol[columns])
            )
            trade["gross_return"] += contribution
            trade["net_return"] += contribution
            trade["funding_return"] += float(
                numpy.sum(funding_by_symbol[columns])
            )

        complete_market = market["return_complete"][index]
        market_return = (
            float(numpy.mean(market["returns"][index, complete_market]))
            if numpy.any(complete_market)
            else 0.0
        )

        # The last row only realizes the position selected on the prior row.
        # Opening a new target here would create a cost with no authorized
        # next-day outcome, so the period is closed immediately from its old
        # weights instead.
        if index == final_index:
            closing_turnover = float(numpy.sum(numpy.abs(weights)))
            closing_cost = closing_turnover * cost_rate
            if closing_cost:
                equity *= 1.0 - closing_cost
                total_cost += closing_cost
                total_turnover += closing_turnover
            for key in list(open_trades):
                model = open_trades[key]["model"]
                pair_weights = numpy.asarray(
                    [weights[model.first], weights[model.second]]
                )
                exit_cost = float(numpy.sum(numpy.abs(pair_weights))) * cost_rate
                close_trade(key, date, "period_end", exit_cost)
            weights = numpy.zeros(symbol_count, dtype=numpy.float64)
            daily_values.append(equity / before - 1.0)
            market_values.append(market_return)
            evaluation_dates.append(date)
            gross_values.append(0.0)
            continue

        if index in formation_cache:
            refit_turnover = float(numpy.sum(numpy.abs(weights)))
            refit_cost = refit_turnover * cost_rate
            if refit_cost:
                equity *= 1.0 - refit_cost
                total_cost += refit_cost
                total_turnover += refit_turnover
            for key in list(open_trades):
                model = open_trades[key]["model"]
                pair_weights = numpy.asarray(
                    [weights[model.first], weights[model.second]]
                )
                exit_cost = float(numpy.sum(numpy.abs(pair_weights))) * cost_rate
                close_trade(key, date, "monthly_refit", exit_cost)
            weights = numpy.zeros(symbol_count, dtype=numpy.float64)
            selected_values, audit = select_pairs(
                formation_cache[index],
                symbols,
                excluded_symbols=excluded_symbols,
            )
            selected = {value.key: value for value in selected_values}
            states = {key: 0 for key in selected}
            stopped = set()
            selection_audit.append(audit)
            for value in selected_values:
                name = _pair_name(value, symbols)
                pair_frequency[name] = pair_frequency.get(name, 0) + 1

        target = numpy.zeros(symbol_count, dtype=numpy.float64)
        exit_reasons: dict[tuple[int, int], str] = {}
        pending_entries = []
        for key, model in selected.items():
            x = math.log(float(market["closes"][index, model.first]))
            y = math.log(float(market["closes"][index, model.second]))
            residual = y - model.alpha - model.beta * x
            z_score = (residual - model.residual_mean) / model.residual_std
            state = states.get(key, 0)
            if state:
                if abs(z_score) <= parent.EXIT_Z:
                    exit_reasons[key] = "mean_reversion"
                    state = 0
                elif abs(z_score) >= parent.STOP_Z:
                    exit_reasons[key] = "spread_stop"
                    stopped.add(key)
                    state = 0
            elif key not in stopped and abs(z_score) >= parent.ENTRY_Z:
                state = -1 if z_score > 0 else 1
                pending_entries.append((key, model, state, z_score))
            states[key] = state
            if state:
                allocation = 1.0 / parent.MAXIMUM_PAIRS
                normalizer = 1.0 + abs(model.beta)
                target[model.second] += state * allocation / normalizer
                target[model.first] -= (
                    state * model.beta * allocation / normalizer
                )

        delta = target - weights
        turnover = float(numpy.sum(numpy.abs(delta)))
        transaction_cost = turnover * cost_rate
        if transaction_cost:
            equity *= 1.0 - transaction_cost
            total_cost += transaction_cost
            total_turnover += turnover
        for key, reason in exit_reasons.items():
            model = open_trades.get(key, {}).get("model")
            if model is None:
                continue
            old_pair_weights = numpy.asarray(
                [weights[model.first], weights[model.second]]
            )
            exit_cost = float(numpy.sum(numpy.abs(old_pair_weights))) * cost_rate
            close_trade(key, date, reason, exit_cost)
        for key, model, state, z_score in pending_entries:
            allocation = 1.0 / parent.MAXIMUM_PAIRS
            entry_cost = allocation * cost_rate
            name = _pair_name(model, symbols)
            open_trades[key] = {
                "pair": name,
                "model": model,
                "entry_date": date.isoformat(),
                "entry_z": float(z_score),
                "direction": int(state),
                "gross_return": 0.0,
                "funding_return": 0.0,
                "cost_return": entry_cost,
                "net_return": -entry_cost,
            }
            ever_traded_symbols.update(
                (symbols[model.first], symbols[model.second])
            )
        weights = target
        daily_values.append(equity / before - 1.0)
        market_values.append(market_return)
        evaluation_dates.append(date)
        gross_values.append(float(numpy.sum(numpy.abs(weights))))

    if open_trades or numpy.any(numpy.abs(weights) > 1e-15):
        raise RuntimeError("period did not close its final positions")
    daily = numpy.asarray(daily_values, dtype=numpy.float64)
    benchmark = numpy.asarray(market_values, dtype=numpy.float64)
    equity_values = numpy.cumprod(1.0 + daily)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity_values))
    )[1:]
    drawdown = 1.0 - equity_values / peaks
    trade_returns = numpy.asarray(
        [value["net_return"] for value in trades], dtype=numpy.float64
    )
    gains = float(numpy.sum(trade_returns[trade_returns > 0]))
    losses = float(-numpy.sum(trade_returns[trade_returns < 0]))
    variance = float(numpy.var(benchmark))
    market_beta = (
        float(
            numpy.mean(
                (daily - numpy.mean(daily))
                * (benchmark - numpy.mean(benchmark))
            )
        )
        / variance
        if variance > 0
        else 0.0
    )
    monthly = _period_compound_returns(evaluation_dates, daily, "%Y-%m")
    by_direction = {}
    for direction in (-1, 1):
        values = [
            value["net_return"]
            for value in trades
            if value["direction"] == direction
        ]
        by_direction[str(direction)] = {
            "trades": len(values),
            "additive_net_return": float(sum(values)),
        }
    concentration_denominator = float(
        sum(abs(value) for value in pair_contributions.values())
    )
    elapsed_years = len(daily) / 365.25
    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": len(daily),
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity_values[-1] - 1.0),
        "annualized_return": (
            float(equity_values[-1] ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity_values[-1] > 0
            else -1.0
        ),
        "sharpe_zero_rate": (
            float(numpy.mean(daily) / numpy.std(daily) * math.sqrt(365.0))
            if numpy.std(daily) > 0
            else 0.0
        ),
        "profit_factor": (
            gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0)
        ),
        "maximum_drawdown": float(numpy.max(drawdown)),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "market_beta": market_beta,
        "closed_trades": len(trades),
        "winning_trades": int(numpy.sum(trade_returns > 0)),
        "win_rate": (
            float(numpy.mean(trade_returns > 0)) if len(trade_returns) else 0.0
        ),
        "mean_trade_return": (
            float(numpy.mean(trade_returns)) if len(trade_returns) else 0.0
        ),
        "total_cost_return": total_cost,
        "total_funding_return": total_funding,
        "total_turnover": total_turnover,
        "average_gross_exposure": float(numpy.mean(gross_values)),
        "maximum_gross_exposure": float(numpy.max(gross_values)),
        "months": monthly,
        "by_spread_direction": by_direction,
        "formations": len(selection_audit),
        "formations_with_pairs": sum(
            value["selected_pairs"] > 0 for value in selection_audit
        ),
        "pair_selection_frequency": pair_frequency,
        "pair_additive_contributions": pair_contributions,
        "maximum_pair_absolute_contribution_share": (
            max(abs(value) for value in pair_contributions.values())
            / concentration_denominator
            if concentration_denominator > 0
            else 0.0
        ),
        "ever_traded_symbols": sorted(ever_traded_symbols),
    }
    if include_details:
        report["selection_audit"] = selection_audit
        report["trades"] = [
            {key: value for key, value in trade.items() if key != "model"}
            for trade in trades
        ]
    if include_trajectory:
        report["_trajectory"] = {
            "dates": [value.isoformat() for value in evaluation_dates],
            "daily_return": daily.tolist(),
            "market_return": benchmark.tolist(),
            "equity": equity_values.tolist(),
            "gross_exposure": gross_values,
        }
    return report


def _without_trajectory(report: dict) -> dict:
    return {key: value for key, value in report.items() if key != "_trajectory"}


def _compact_report(report: dict) -> dict:
    excluded = {
        "selection_audit",
        "trades",
        "months",
        "pair_selection_frequency",
        "pair_additive_contributions",
        "_trajectory",
    }
    return {key: value for key, value in report.items() if key not in excluded}


def _development_gate(
    report: dict,
    stress: dict,
    positive_folds: int,
    positive_loo_ratio: float,
) -> dict:
    gate = protocol_module.frozen_protocol()["development_gate"]
    checks = {
        "minimum_closed_trades": bool(
            report["closed_trades"] >= gate["minimum_closed_trades"]
        ),
        "positive_total_return": bool(report["total_return"] > 0),
        "stress_total_return_positive": bool(stress["total_return"] > 0),
        "minimum_annualized_return": bool(
            report["annualized_return"] >= gate["minimum_annualized_return"]
        ),
        "minimum_profit_factor": bool(
            report["profit_factor"] >= gate["minimum_profit_factor"]
        ),
        "minimum_stress_profit_factor": bool(
            stress["profit_factor"] >= gate["minimum_stress_profit_factor"]
        ),
        "minimum_sharpe": bool(
            report["sharpe_zero_rate"] >= gate["minimum_sharpe"]
        ),
        "maximum_drawdown": bool(
            report["maximum_drawdown"] <= gate["maximum_drawdown"]
        ),
        "minimum_positive_month_ratio": bool(
            report["positive_month_ratio"]
            >= gate["minimum_positive_month_ratio"]
        ),
        "minimum_positive_folds": bool(
            positive_folds >= gate["minimum_positive_folds"]
        ),
        "required_folds_present": bool(
            len(parent.DEVELOPMENT_FOLDS) == gate["required_folds"]
        ),
        "both_spread_directions_non_negative": bool(
            all(
                report["by_spread_direction"][str(direction)]["trades"] > 0
                and report["by_spread_direction"][str(direction)][
                    "additive_net_return"
                ]
                >= 0
                for direction in (-1, 1)
            )
        ),
        "maximum_absolute_market_beta": bool(
            abs(report["market_beta"])
            <= gate["maximum_absolute_market_beta"]
        ),
        "maximum_pair_absolute_contribution_share": bool(
            report["maximum_pair_absolute_contribution_share"]
            <= gate["maximum_pair_absolute_contribution_share"]
        ),
        "minimum_positive_leave_one_symbol_out_ratio": bool(
            positive_loo_ratio
            >= gate["minimum_positive_leave_one_symbol_out_ratio"]
        ),
    }
    return {"checks": checks, "passed": bool(all(checks.values()))}


def _later_gate(report: dict, stress: dict, gate_name: str) -> dict:
    gate = protocol_module.frozen_protocol()[gate_name]
    checks = {
        "minimum_closed_trades": bool(
            report["closed_trades"] >= gate["minimum_closed_trades"]
        ),
        "positive_total_return": bool(report["total_return"] > 0),
        "stress_total_return_positive": bool(stress["total_return"] > 0),
        "minimum_annualized_return": bool(
            report["annualized_return"] >= gate["minimum_annualized_return"]
        ),
        "minimum_profit_factor": bool(
            report["profit_factor"] >= gate["minimum_profit_factor"]
        ),
        "minimum_stress_profit_factor": bool(
            stress["profit_factor"] >= gate["minimum_stress_profit_factor"]
        ),
        "minimum_sharpe": bool(
            report["sharpe_zero_rate"] >= gate["minimum_sharpe"]
        ),
        "maximum_drawdown": bool(
            report["maximum_drawdown"] <= gate["maximum_drawdown"]
        ),
        "both_spread_directions_non_negative": bool(
            all(
                report["by_spread_direction"][str(direction)]["trades"] > 0
                and report["by_spread_direction"][str(direction)][
                    "additive_net_return"
                ]
                >= 0
                for direction in (-1, 1)
            )
        ),
        "maximum_absolute_market_beta": bool(
            abs(report["market_beta"])
            <= gate["maximum_absolute_market_beta"]
        ),
    }
    if "minimum_positive_month_ratio" in gate:
        checks["minimum_positive_month_ratio"] = bool(
            report["positive_month_ratio"]
            >= gate["minimum_positive_month_ratio"]
        )
    return {"checks": checks, "passed": bool(all(checks.values()))}


def _source_file_artifacts() -> list[dict]:
    paths = [
        pathlib.Path(protocol_module.__file__).resolve(),
        pathlib.Path(__file__).resolve(),
        pathlib.Path(parent.__file__).resolve(),
        pathlib.Path(source.__file__).resolve(),
    ]
    return [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": parent._sha256(path),
        }
        for path in paths
    ]


def evaluate(
    protocol_value: typing.Union[str, pathlib.Path],
    snapshot_value: typing.Union[str, pathlib.Path],
    history_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    *,
    null: numpy.ndarray | None = None,
) -> dict:
    """Run the single frozen historical diagnostic in strict sequence."""

    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = _load_protocol(protocol_path)
    output_root = pathlib.Path(output_root_value).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    prefix = f"expanded-cointegration-pairs-v2-{protocol['protocol_sha256'][:12]}-*"
    source._require_no_official_artifact(
        output_root, prefix, "official V2 evaluation"
    )
    (
        snapshot_root,
        snapshot_manifest,
        history_root,
        history_manifest,
        market,
    ) = _load_market(snapshot_value, history_value)
    if null is None:
        null = monte_carlo_null_t_statistics()
    null = numpy.asarray(null, dtype=numpy.float64)
    if (
        len(null) != protocol_module.MONTE_CARLO_SIMULATIONS
        or numpy.any(~numpy.isfinite(null))
        or numpy.any(numpy.diff(null) < 0)
    ):
        raise ValueError("Monte Carlo null is not the frozen sorted null")
    null_sha256 = hashlib.sha256(null.tobytes()).hexdigest()

    development_cache = build_formation_cache(
        market,
        parent.DEVELOPMENT_START,
        parent.DEVELOPMENT_END,
        null,
    )
    development_with_trajectory = simulate_period(
        market,
        development_cache,
        parent.DEVELOPMENT_START,
        parent.DEVELOPMENT_END,
        include_trajectory=True,
    )
    development = _without_trajectory(development_with_trajectory)
    development_stress = simulate_period(
        market,
        development_cache,
        parent.DEVELOPMENT_START,
        parent.DEVELOPMENT_END,
        cost_multiplier=parent.STRESS_COST_MULTIPLIER,
    )
    folds = [
        simulate_period(market, development_cache, start, end)
        for start, end in parent.DEVELOPMENT_FOLDS
    ]
    positive_folds = sum(value["total_return"] > 0 for value in folds)

    leave_one_symbol_out = []
    for symbol in development["ever_traded_symbols"]:
        value = simulate_period(
            market,
            development_cache,
            parent.DEVELOPMENT_START,
            parent.DEVELOPMENT_END,
            excluded_symbols={symbol},
            include_details=False,
        )
        leave_one_symbol_out.append(
            {"excluded_symbol": symbol, "report": _compact_report(value)}
        )
    positive_loo_ratio = (
        sum(
            value["report"]["total_return"] > 0
            for value in leave_one_symbol_out
        )
        / len(leave_one_symbol_out)
        if leave_one_symbol_out
        else 0.0
    )
    development_gate = _development_gate(
        development,
        development_stress,
        positive_folds,
        positive_loo_ratio,
    )

    confirmation = confirmation_stress = confirmation_gate = None
    locked = locked_stress = locked_gate = None
    confirmation_cache = locked_cache = None
    if development_gate["passed"]:
        confirmation_cache = build_formation_cache(
            market,
            parent.CONFIRMATION_START,
            parent.CONFIRMATION_END,
            null,
        )
        confirmation = simulate_period(
            market,
            confirmation_cache,
            parent.CONFIRMATION_START,
            parent.CONFIRMATION_END,
        )
        confirmation_stress = simulate_period(
            market,
            confirmation_cache,
            parent.CONFIRMATION_START,
            parent.CONFIRMATION_END,
            cost_multiplier=parent.STRESS_COST_MULTIPLIER,
        )
        confirmation_gate = _later_gate(
            confirmation, confirmation_stress, "confirmation_gate"
        )
        if confirmation_gate["passed"]:
            locked_cache = build_formation_cache(
                market,
                parent.LOCKED_START,
                parent.LOCKED_END,
                null,
            )
            locked = simulate_period(
                market,
                locked_cache,
                parent.LOCKED_START,
                parent.LOCKED_END,
            )
            locked_stress = simulate_period(
                market,
                locked_cache,
                parent.LOCKED_START,
                parent.LOCKED_END,
                cost_multiplier=parent.STRESS_COST_MULTIPLIER,
            )
            locked_gate = _later_gate(locked, locked_stress, "locked_gate")

    historical_candidate = bool(
        development_gate["passed"]
        and confirmation_gate
        and confirmation_gate["passed"]
        and locked_gate
        and locked_gate["passed"]
    )
    source_files = _source_file_artifacts()
    evaluator_sha256 = next(
        value["sha256"]
        for value in source_files
        if value["name"] == pathlib.Path(__file__).name
    )
    experiment_key = parent._json_hash(
        {
            "protocol_sha256": protocol["protocol_sha256"],
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "evaluator_sha256": evaluator_sha256,
            "null_sha256": null_sha256,
        }
    )
    experiment = output_root / (
        f"expanded-cointegration-pairs-v2-{protocol['protocol_sha256'][:12]}-"
        f"{experiment_key[:12]}"
    )
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=".expanded-cointegration-v2.", dir=str(output_root))
    )
    try:
        null_path = temporary / "monte-carlo-null.npy"
        numpy.save(null_path, null, allow_pickle=False)
        trajectory_path = temporary / "development-trajectory.json"
        parent._atomic_json(
            trajectory_path,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_sha256": protocol["protocol_sha256"],
                **development_with_trajectory["_trajectory"],
            },
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": protocol_module.PROTOCOL_VERSION,
            "created_at": datetime.datetime.now(UTC).isoformat(),
            "research_only": True,
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "protocol_path": str(protocol_path),
            "protocol_file_sha256": parent._sha256(protocol_path),
            "protocol_sha256": protocol["protocol_sha256"],
            "source_snapshot_path": str(snapshot_root),
            "source_snapshot_bundle_sha256": snapshot_manifest[
                "source_bundle_sha256"
            ],
            "history_path": str(history_root),
            "history_bundle_sha256": history_manifest["history_bundle_sha256"],
            "source_files": source_files,
            "monte_carlo_null": {
                "simulations": len(null),
                "seed": protocol_module.MONTE_CARLO_SEED,
                "sha256": null_sha256,
                "path": null_path.name,
                "file_sha256": parent._sha256(null_path),
            },
            "development": development,
            "development_stress": development_stress,
            "development_folds": folds,
            "development_positive_folds": positive_folds,
            "development_leave_one_symbol_out": leave_one_symbol_out,
            "development_positive_leave_one_symbol_out_ratio": (
                positive_loo_ratio
            ),
            "development_gate": development_gate,
            "confirmation": confirmation,
            "confirmation_stress": confirmation_stress,
            "confirmation_gate": confirmation_gate,
            "locked_test": locked,
            "locked_test_stress": locked_stress,
            "locked_gate": locked_gate,
            "formation_cache_counts": {
                "development": len(development_cache),
                "confirmation": (
                    len(confirmation_cache) if confirmation_cache else 0
                ),
                "locked": len(locked_cache) if locked_cache else 0,
            },
            "historical_candidate": historical_candidate,
            "historical_status": (
                "diagnostic_reuse_current_survivor_universe_and_known_prices"
            ),
            "forward_validation": {
                **protocol["forward_gate"],
                "started": False,
                "passed": False,
                "automatic_promotion": False,
            },
            "development_trajectory": {
                "path": trajectory_path.name,
                "sha256": parent._sha256(trajectory_path),
            },
            "verdict": (
                "HISTORICAL_CANDIDATE_REQUIRES_180D_FORWARD"
                if historical_candidate
                else (
                    "REJECTED_LOCKED_TEST"
                    if locked is not None
                    else (
                        "REJECTED_CONFIRMATION_LOCK_REMAINS_SEALED"
                        if confirmation is not None
                        else "REJECTED_DEVELOPMENT_LATER_WINDOWS_UNMATERIALIZED"
                    )
                )
            ),
            "results_do_not_authorize_orders": True,
        }
        report_path = temporary / "report.json"
        parent._atomic_json(report_path, report)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "experiment_key": experiment_key,
            "report_sha256": parent._sha256(report_path),
            "trajectory_sha256": parent._sha256(trajectory_path),
            "null_file_sha256": parent._sha256(null_path),
            "historical_candidate": historical_candidate,
            "confirmation_materialized": confirmation is not None,
            "locked_test_materialized": locked is not None,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        }
        manifest["content_sha256"] = parent._json_hash(manifest)
        parent._atomic_json(temporary / "manifest.json", manifest)
        if experiment.exists():
            raise FileExistsError(f"official V2 evaluation exists: {experiment}")
        os.replace(temporary, experiment)
        return {"directory": str(experiment), "report": report, "manifest": manifest}
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    result = evaluate(
        args.protocol,
        args.snapshot,
        args.history,
        args.output_root,
    )
    report = result["report"]
    summary = {
        "directory": result["directory"],
        "verdict": report["verdict"],
        "development": _compact_report(report["development"]),
        "development_gate": report["development_gate"],
        "report_sha256": result["manifest"]["report_sha256"],
        "orders_authorized": False,
    }
    print(json.dumps(parent._json_safe(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
