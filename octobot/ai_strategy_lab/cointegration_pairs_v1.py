"""Frozen, research-only crypto futures cointegration-pairs protocol V1.

The evaluator deliberately has no exchange client and cannot place orders.
Pair discovery is repeated from trailing data only.  A family-level locked
period is evaluated only when both development and confirmation gates pass.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import itertools
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import trend as trend_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_futures_cointegration_pairs_v1"
PREREGISTRATION_DATE = "2026-08-28"
FORMATION_DAYS = 180
FORMATION_INTERVAL = "calendar_month_start"
MONTE_CARLO_SIMULATIONS = 20_000
MONTE_CARLO_SEED = 20260828
FDR_Q = 0.05
MINIMUM_BETA = 0.25
MAXIMUM_BETA = 4.0
MINIMUM_HALF_LIFE_DAYS = 2.0
MAXIMUM_HALF_LIFE_DAYS = 30.0
MINIMUM_ZERO_CROSSINGS = 6
MAXIMUM_PAIRS = 4
ENTRY_Z = 2.0
EXIT_Z = 0.5
STOP_Z = 4.0
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
DEVELOPMENT_START = datetime.date(2022, 11, 1)
DEVELOPMENT_END = datetime.date(2025, 1, 1)
CONFIRMATION_START = DEVELOPMENT_END
CONFIRMATION_END = datetime.date(2026, 1, 1)
LOCKED_START = CONFIRMATION_END
LOCKED_END = datetime.date(2026, 7, 1)
DEVELOPMENT_FOLDS = (
    (datetime.date(2022, 11, 1), datetime.date(2023, 7, 1)),
    (datetime.date(2023, 7, 1), datetime.date(2024, 1, 1)),
    (datetime.date(2024, 1, 1), datetime.date(2024, 7, 1)),
    (datetime.date(2024, 7, 1), datetime.date(2025, 1, 1)),
)


@dataclasses.dataclass(frozen=True)
class PairModel:
    first: int
    second: int
    alpha: float
    beta: float
    residual_mean: float
    residual_std: float
    adf_t: float
    p_value: float
    half_life_days: float
    zero_crossings: int

    @property
    def key(self) -> tuple[int, int]:
        return self.first, self.second


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, numpy.generic):
        return value.item()
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def frozen_protocol() -> dict:
    """Return the result-free protocol whose hash binds the evaluation."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_evaluation_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "hypothesis": {
            "name": "rolling_cointegrated_futures_spread_mean_reversion",
            "statement": (
                "pairs of liquid crypto perpetuals whose log prices reject an "
                "independent-random-walk null on trailing data can exhibit a "
                "temporary relative displacement that mean reverts after "
                "fees, slippage and signed funding"
            ),
            "economic_mechanism": (
                "relative-value convergence; no outright market forecast and "
                "no order-book direction signal"
            ),
            "one_configuration_only": True,
        },
        "formation": {
            "lookback_days": FORMATION_DAYS,
            "interval": FORMATION_INTERVAL,
            "test": (
                "Engle-Granger residual ADF(0) t statistic compared with a "
                "deterministic Monte Carlo independent-random-walk null"
            ),
            "monte_carlo_simulations": MONTE_CARLO_SIMULATIONS,
            "monte_carlo_seed": MONTE_CARLO_SEED,
            "multiple_testing": "Benjamini-Hochberg",
            "false_discovery_rate": FDR_Q,
            "beta_bounds": [MINIMUM_BETA, MAXIMUM_BETA],
            "half_life_days": [
                MINIMUM_HALF_LIFE_DAYS,
                MAXIMUM_HALF_LIFE_DAYS,
            ],
            "minimum_zero_crossings": MINIMUM_ZERO_CROSSINGS,
            "maximum_pairs": MAXIMUM_PAIRS,
            "pair_overlap_allowed": False,
            "ranking": "ascending Monte Carlo p-value then half-life then name",
        },
        "trading": {
            "entry_absolute_z": ENTRY_Z,
            "exit_absolute_z": EXIT_Z,
            "stop_absolute_z": STOP_Z,
            "stopped_pair_reentry": "next monthly formation only",
            "hedge": "positive OLS beta, gross-normalized two-leg weights",
            "allocation": "one quarter gross per selected pair",
            "maximum_portfolio_gross": 1.0,
            "decision_time": "daily close; target applies to next daily return",
            "monthly_refit": "close every old model before replacing it",
            "funding": "signed observed perpetual settlements",
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
        },
        "validation": {
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_end_exclusive": True,
            "walk_forward_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_end_exclusive": True,
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_end_exclusive": True,
            "locked_policy": (
                "do not compute locked-period pair selections, positions or "
                "outcomes unless every development and confirmation gate passes"
            ),
            "same_files_used_by_other_families": True,
            "family_outcomes_previously_observed": False,
        },
        "development_gate": {
            "minimum_closed_trades": 24,
            "positive_total_return": True,
            "minimum_profit_factor": 1.25,
            "minimum_sharpe": 0.75,
            "maximum_drawdown": 0.10,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_folds": 3,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "both_spread_directions_non_negative": True,
            "stress_total_return_positive": True,
            "minimum_stress_profit_factor": 1.05,
        },
        "confirmation_gate": {
            "minimum_closed_trades": 8,
            "positive_total_return": True,
            "minimum_profit_factor": 1.20,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.10,
            "minimum_positive_month_ratio": 0.50,
            "both_spread_directions_non_negative": True,
            "stress_total_return_positive": True,
            "minimum_stress_profit_factor": 1.00,
        },
        "locked_gate": {
            "minimum_closed_trades": 4,
            "positive_total_return": True,
            "minimum_profit_factor": 1.20,
            "minimum_sharpe": 0.50,
            "maximum_drawdown": 0.10,
            "stress_total_return_positive": True,
        },
        "multiple_testing_disclosure": (
            "one formation window, one Monte Carlo test, one FDR level, one "
            "pair cap and one entry/exit/stop configuration are evaluated"
        ),
        "promotion_consequence": (
            "a complete pass permits only manually approved orderless shadow; "
            "paper and real orders remain unauthorized"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted cointegration V1 protocol differs")
        return persisted
    _atomic_json(path, payload)
    return payload


def load_market(
    futures_collectors: typing.Iterable[typing.Union[str, pathlib.Path]],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
) -> tuple[dict, dict]:
    paths = [pathlib.Path(value).resolve() for value in futures_collectors]
    if not paths:
        raise ValueError("at least one futures collector is required")
    series = dataset_module.load_collector_series(
        paths, required_time_frames=("1h",)
    )
    funding = {}
    funding_artifacts = []
    for value in funding_paths:
        path = pathlib.Path(value).resolve()
        loaded = funding_module.load_funding(path)
        overlap = set(funding) & set(loaded)
        if overlap:
            raise ValueError(
                f"funding symbols appear in multiple inputs: {sorted(overlap)}"
            )
        funding.update(loaded)
        funding_artifacts.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    symbols = sorted(set(series) & set(funding))
    if len(symbols) < 7:
        raise ValueError("cointegration research requires at least seven assets")
    market = trend_module._build_daily_market(
        {symbol: series[symbol]["1h"] for symbol in symbols},
        {symbol: funding[symbol] for symbol in symbols},
    )
    artifacts = {
        "collectors": [
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in paths
        ],
        "funding": funding_artifacts,
    }
    return market, artifacts


def _adf0_t_statistic(residual: numpy.ndarray) -> tuple[float, float]:
    values = numpy.asarray(residual, dtype=numpy.float64)
    lagged = values[:-1]
    delta = numpy.diff(values)
    x = lagged - numpy.mean(lagged)
    y = delta - numpy.mean(delta)
    denominator = float(x @ x)
    if denominator <= 0:
        return math.inf, math.nan
    gamma = float(x @ y) / denominator
    errors = y - gamma * x
    degrees = len(errors) - 2
    if degrees <= 0:
        return math.inf, gamma
    variance = float(errors @ errors) / degrees
    standard_error = math.sqrt(max(variance, 0.0) / denominator)
    statistic = gamma / standard_error if standard_error > 0 else math.inf
    return statistic, gamma


def monte_carlo_null_t_statistics(
    simulations: int = MONTE_CARLO_SIMULATIONS,
    *,
    observations: int = FORMATION_DAYS,
    seed: int = MONTE_CARLO_SEED,
    chunk_size: int = 1000,
) -> numpy.ndarray:
    """Simulate the residual-ADF null for two independent random walks."""

    if simulations < 100 or observations < 30 or chunk_size < 1:
        raise ValueError("invalid Monte Carlo configuration")
    random = numpy.random.RandomState(seed)
    chunks = []
    remaining = simulations
    while remaining:
        count = min(chunk_size, remaining)
        first = numpy.cumsum(
            random.standard_normal((count, observations)), axis=1
        )
        second = numpy.cumsum(
            random.standard_normal((count, observations)), axis=1
        )
        first_centered = first - numpy.mean(first, axis=1, keepdims=True)
        second_centered = second - numpy.mean(second, axis=1, keepdims=True)
        denominator = numpy.sum(first_centered * first_centered, axis=1)
        beta = numpy.sum(
            first_centered * second_centered, axis=1
        ) / denominator
        residual = second_centered - beta[:, None] * first_centered
        lagged = residual[:, :-1]
        delta = numpy.diff(residual, axis=1)
        x = lagged - numpy.mean(lagged, axis=1, keepdims=True)
        y = delta - numpy.mean(delta, axis=1, keepdims=True)
        x_square = numpy.sum(x * x, axis=1)
        gamma = numpy.sum(x * y, axis=1) / x_square
        errors = y - gamma[:, None] * x
        variance = numpy.sum(errors * errors, axis=1) / (observations - 3)
        standard_error = numpy.sqrt(variance / x_square)
        chunks.append(gamma / standard_error)
        remaining -= count
    return numpy.sort(numpy.concatenate(chunks))


def _monte_carlo_p_value(statistic: float, null: numpy.ndarray) -> float:
    count = int(numpy.searchsorted(null, statistic, side="right"))
    return (count + 1.0) / (len(null) + 1.0)


def _fit_pair(
    log_closes: numpy.ndarray,
    first: int,
    second: int,
    null: numpy.ndarray,
) -> PairModel | None:
    x = log_closes[:, first]
    y = log_closes[:, second]
    centered_x = x - numpy.mean(x)
    denominator = float(centered_x @ centered_x)
    if denominator <= 0:
        return None
    beta = float(centered_x @ (y - numpy.mean(y))) / denominator
    if not MINIMUM_BETA <= beta <= MAXIMUM_BETA:
        return None
    alpha = float(numpy.mean(y) - beta * numpy.mean(x))
    residual = y - alpha - beta * x
    statistic, gamma = _adf0_t_statistic(residual)
    if not math.isfinite(statistic) or not math.isfinite(gamma):
        return None
    rho = 1.0 + gamma
    if not 0.0 < rho < 1.0:
        return None
    half_life = -math.log(2.0) / math.log(rho)
    centered = residual - numpy.mean(residual)
    crossings = int(numpy.sum(centered[1:] * centered[:-1] < 0))
    standard_deviation = float(numpy.std(residual, ddof=1))
    if standard_deviation <= 0 or not math.isfinite(standard_deviation):
        return None
    return PairModel(
        first=first,
        second=second,
        alpha=alpha,
        beta=beta,
        residual_mean=float(numpy.mean(residual)),
        residual_std=standard_deviation,
        adf_t=statistic,
        p_value=_monte_carlo_p_value(statistic, null),
        half_life_days=half_life,
        zero_crossings=crossings,
    )


def _benjamini_hochberg_threshold(p_values: list[float]) -> float | None:
    if not p_values:
        return None
    ordered = sorted(p_values)
    threshold = None
    count = len(ordered)
    for rank, value in enumerate(ordered, start=1):
        if value <= FDR_Q * rank / count:
            threshold = value
    return threshold


def select_pairs(
    closes: numpy.ndarray,
    symbols: list[str],
    index: int,
    null: numpy.ndarray,
) -> tuple[list[PairModel], dict]:
    if index + 1 < FORMATION_DAYS:
        return [], {"eligible": False, "reason": "formation_warmup"}
    formation = numpy.log(closes[index - FORMATION_DAYS + 1 : index + 1])
    fitted = []
    for first, second in itertools.combinations(range(len(symbols)), 2):
        candidate = _fit_pair(formation, first, second, null)
        if candidate is not None:
            fitted.append(candidate)
    threshold = _benjamini_hochberg_threshold(
        [candidate.p_value for candidate in fitted]
    )
    significant = (
        []
        if threshold is None
        else [candidate for candidate in fitted if candidate.p_value <= threshold]
    )
    stable = [
        candidate
        for candidate in significant
        if MINIMUM_HALF_LIFE_DAYS
        <= candidate.half_life_days
        <= MAXIMUM_HALF_LIFE_DAYS
        and candidate.zero_crossings >= MINIMUM_ZERO_CROSSINGS
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
    for candidate in ordered:
        if candidate.first in used or candidate.second in used:
            continue
        selected.append(candidate)
        used.update(candidate.key)
        if len(selected) >= MAXIMUM_PAIRS:
            break
    return selected, {
        "eligible": True,
        "tested_pairs": len(fitted),
        "bh_threshold": threshold,
        "significant_pairs": len(significant),
        "stable_pairs": len(stable),
        "selected_pairs": len(selected),
    }


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


def simulate_period(
    market: dict,
    start: datetime.date,
    end: datetime.date,
    null: numpy.ndarray,
    *,
    cost_multiplier: float = 1.0,
) -> dict:
    """Simulate one causal interval; ``end`` is exclusive."""

    if cost_multiplier < 1.0:
        raise ValueError("cost multiplier must be at least one")
    dates = market["dates"]
    indices = [index for index, date in enumerate(dates) if start <= date < end]
    if not indices:
        raise ValueError("evaluation interval is absent from the market")
    first_index, final_index = indices[0], indices[-1]
    if first_index < FORMATION_DAYS - 1:
        raise ValueError("evaluation lacks formation warmup")
    closes = market["closes"]
    returns = market["returns"]
    funding = market["funding"]
    symbols = market["symbols"]
    per_turnover_cost = cost_multiplier * (
        FEE_PER_TURNOVER + SLIPPAGE_PER_TURNOVER
    )
    weights = numpy.zeros(len(symbols), dtype=numpy.float64)
    equity = 1.0
    equity_values = []
    daily_values = []
    selected: dict[tuple[int, int], PairModel] = {}
    states: dict[tuple[int, int], int] = {}
    stopped: set[tuple[int, int]] = set()
    open_trades: dict[tuple[int, int], dict] = {}
    trades = []
    selection_audit = []
    pair_frequency: dict[str, int] = {}
    total_cost = 0.0
    total_funding = 0.0
    total_turnover = 0.0
    peak = 1.0

    def pair_name(model: PairModel) -> str:
        return f"{symbols[model.first]}|{symbols[model.second]}"

    def close_trade(key, date, reason, exit_cost):
        trade = open_trades.pop(key, None)
        if trade is None:
            return
        trade["cost_return"] += exit_cost
        trade["net_return"] -= exit_cost
        trade["exit_date"] = date.isoformat()
        trade["exit_reason"] = reason
        trades.append(trade)

    for index in range(first_index, final_index + 1):
        date = dates[index]
        before = equity
        price_by_symbol = weights * returns[index]
        funding_by_symbol = -weights * funding[index]
        gross_return = float(numpy.sum(price_by_symbol + funding_by_symbol))
        equity *= 1.0 + gross_return
        daily_funding = float(numpy.sum(funding_by_symbol))
        total_funding += daily_funding
        for key, trade in open_trades.items():
            model = selected[key]
            columns = [model.first, model.second]
            contribution = float(
                numpy.sum(price_by_symbol[columns] + funding_by_symbol[columns])
            )
            trade["net_return"] += contribution
            trade["gross_return"] += contribution
            trade["funding_return"] += float(
                numpy.sum(funding_by_symbol[columns])
            )

        formation = date.day == 1 or index == first_index
        exit_reasons: dict[tuple[int, int], str] = {}
        if formation:
            # Models are not spliced or cost-netted across formation windows:
            # every old pair is closed before a newly fitted pair can open.
            refit_turnover = float(numpy.sum(numpy.abs(weights)))
            refit_cost = refit_turnover * per_turnover_cost
            if refit_cost:
                equity *= 1.0 - refit_cost
                total_cost += refit_cost
                total_turnover += refit_turnover
            for key in list(open_trades):
                model = open_trades[key]["model"]
                pair_weights = numpy.asarray(
                    [weights[model.first], weights[model.second]]
                )
                exit_cost = (
                    float(numpy.sum(numpy.abs(pair_weights)))
                    * per_turnover_cost
                )
                close_trade(key, date, "monthly_refit", exit_cost)
            weights = numpy.zeros(len(symbols), dtype=numpy.float64)
            selected_values, audit = select_pairs(closes, symbols, index, null)
            selected = {model.key: model for model in selected_values}
            states = {key: 0 for key in selected}
            stopped = set()
            audit = {
                **audit,
                "date": date.isoformat(),
                "pairs": [pair_name(value) for value in selected_values],
            }
            selection_audit.append(audit)
            for model in selected_values:
                name = pair_name(model)
                pair_frequency[name] = pair_frequency.get(name, 0) + 1

        target = numpy.zeros(len(symbols), dtype=numpy.float64)
        pending_entries = []
        for key, model in selected.items():
            x = math.log(float(closes[index, model.first]))
            y = math.log(float(closes[index, model.second]))
            residual = y - model.alpha - model.beta * x
            z_score = (residual - model.residual_mean) / model.residual_std
            state = states.get(key, 0)
            if state:
                if abs(z_score) <= EXIT_Z:
                    exit_reasons[key] = "mean_reversion"
                    state = 0
                elif abs(z_score) >= STOP_Z:
                    exit_reasons[key] = "spread_stop"
                    stopped.add(key)
                    state = 0
            elif key not in stopped and abs(z_score) >= ENTRY_Z:
                state = -1 if z_score > 0 else 1
                pending_entries.append((key, model, state, z_score))
            states[key] = state
            if state:
                allocation = 1.0 / MAXIMUM_PAIRS
                normalizer = 1.0 + abs(model.beta)
                target[model.second] += state * allocation / normalizer
                target[model.first] -= (
                    state * model.beta * allocation / normalizer
                )

        delta = target - weights
        turnover = float(numpy.sum(numpy.abs(delta)))
        cost = turnover * per_turnover_cost
        if cost:
            equity *= 1.0 - cost
            total_cost += cost
            total_turnover += turnover

        for key, reason in exit_reasons.items():
            model = open_trades.get(key, {}).get("model")
            if model is None:
                continue
            old_pair_weights = numpy.asarray(
                [weights[model.first], weights[model.second]]
            )
            exit_cost = float(numpy.sum(numpy.abs(old_pair_weights))) * per_turnover_cost
            close_trade(key, date, reason, exit_cost)
        for key, model, state, z_score in pending_entries:
            allocation = 1.0 / MAXIMUM_PAIRS
            entry_cost = allocation * per_turnover_cost
            open_trades[key] = {
                "pair": pair_name(model),
                "model": model,
                "entry_date": date.isoformat(),
                "entry_z": float(z_score),
                "direction": int(state),
                "gross_return": 0.0,
                "funding_return": 0.0,
                "cost_return": entry_cost,
                "net_return": -entry_cost,
            }
        weights = target
        peak = max(peak, equity)
        equity_values.append(equity)
        daily_values.append(equity / before - 1.0)

    final_date = dates[final_index]
    closing_turnover = float(numpy.sum(numpy.abs(weights)))
    closing_cost = closing_turnover * per_turnover_cost
    if closing_cost:
        equity *= 1.0 - closing_cost
        total_cost += closing_cost
        total_turnover += closing_turnover
        previous_equity = equity_values[-2] if len(equity_values) > 1 else 1.0
        daily_values[-1] = equity / previous_equity - 1.0
        equity_values[-1] = equity
    for key in list(open_trades):
        model = open_trades[key]["model"]
        pair_weights = numpy.asarray(
            [weights[model.first], weights[model.second]]
        )
        exit_cost = float(numpy.sum(numpy.abs(pair_weights))) * per_turnover_cost
        close_trade(key, final_date, "period_end", exit_cost)

    clean_trades = []
    for trade in trades:
        clean_trades.append(
            {key: value for key, value in trade.items() if key != "model"}
        )
    trade_returns = numpy.asarray(
        [trade["net_return"] for trade in clean_trades], dtype=numpy.float64
    )
    gains = float(numpy.sum(trade_returns[trade_returns > 0]))
    losses = float(-numpy.sum(trade_returns[trade_returns < 0]))
    profit_factor = gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0)
    equity_array = numpy.asarray(equity_values, dtype=numpy.float64)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.ones(1), equity_array))
    )[1:]
    drawdown = 1.0 - equity_array / peaks
    daily_array = numpy.asarray(daily_values, dtype=numpy.float64)
    elapsed_years = max((final_date - dates[first_index]).days / 365.25, 0.0)
    monthly = _period_returns(
        dates[first_index : final_index + 1], equity_array, "%Y-%m"
    )
    by_direction = {}
    for direction in (-1, 1):
        values = [
            trade["net_return"]
            for trade in clean_trades
            if trade["direction"] == direction
        ]
        by_direction[str(direction)] = {
            "trades": len(values),
            "additive_net_return": float(sum(values)),
        }
    return {
        "start_date": dates[first_index].isoformat(),
        "end_date": final_date.isoformat(),
        "days": len(equity_array),
        "cost_multiplier": cost_multiplier,
        "total_return": float(equity - 1.0),
        "annualized_return": (
            float(equity ** (1.0 / elapsed_years) - 1.0)
            if elapsed_years > 0 and equity > 0
            else 0.0
        ),
        "maximum_drawdown": float(numpy.max(drawdown)),
        "sharpe_zero_rate": (
            float(numpy.mean(daily_array) / numpy.std(daily_array) * math.sqrt(365.0))
            if numpy.std(daily_array) > 0
            else 0.0
        ),
        "closed_trades": len(clean_trades),
        "winning_trades": int(numpy.sum(trade_returns > 0)),
        "win_rate": (
            float(numpy.mean(trade_returns > 0)) if len(trade_returns) else 0.0
        ),
        "profit_factor": float(profit_factor),
        "mean_trade_return": (
            float(numpy.mean(trade_returns)) if len(trade_returns) else 0.0
        ),
        "total_cost_return": float(total_cost),
        "total_funding_return": float(total_funding),
        "total_turnover": float(total_turnover),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly.values()) / len(monthly)
            if monthly
            else 0.0
        ),
        "monthly_returns": monthly,
        "by_spread_direction": by_direction,
        "formations": len(selection_audit),
        "formations_with_pairs": sum(
            value.get("selected_pairs", 0) > 0 for value in selection_audit
        ),
        "pair_selection_frequency": pair_frequency,
        "selection_audit": selection_audit,
        "trades": clean_trades,
        "trajectory_sha256": _json_hash(
            {
                "dates": [
                    value.isoformat()
                    for value in dates[first_index : final_index + 1]
                ],
                "equity": equity_values,
            }
        ),
    }


def _gate(report: dict, gate: dict, *, positive_folds: int | None = None) -> dict:
    checks = {
        "minimum_closed_trades": report["closed_trades"]
        >= gate["minimum_closed_trades"],
        "positive_total_return": report["total_return"] > 0,
        "minimum_profit_factor": report["profit_factor"]
        >= gate["minimum_profit_factor"],
        "minimum_sharpe": report["sharpe_zero_rate"] >= gate["minimum_sharpe"],
        "maximum_drawdown": report["maximum_drawdown"] <= gate["maximum_drawdown"],
    }
    if "minimum_positive_month_ratio" in gate:
        checks["minimum_positive_month_ratio"] = (
            report["positive_month_ratio"] >= gate["minimum_positive_month_ratio"]
        )
    if gate.get("both_spread_directions_non_negative"):
        checks["both_spread_directions_non_negative"] = all(
            report["by_spread_direction"][str(direction)]["trades"] > 0
            and report["by_spread_direction"][str(direction)]["additive_net_return"]
            >= 0
            for direction in (-1, 1)
        )
    if positive_folds is not None:
        checks["minimum_positive_folds"] = positive_folds >= gate["minimum_positive_folds"]
        checks["required_folds_present"] = gate["required_folds"] == len(DEVELOPMENT_FOLDS)
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def evaluate_prelock(
    protocol_value: typing.Union[str, pathlib.Path],
    futures_collectors: typing.Iterable[typing.Union[str, pathlib.Path]],
    funding_paths: typing.Iterable[typing.Union[str, pathlib.Path]],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    market, artifacts = load_market(futures_collectors, funding_paths)
    if market["dates"][0] > DEVELOPMENT_START - datetime.timedelta(days=FORMATION_DAYS):
        raise ValueError("market does not provide the frozen formation warmup")
    if market["dates"][-1] < LOCKED_END - datetime.timedelta(days=1):
        raise ValueError("market does not contain the declared locked interval")
    null = monte_carlo_null_t_statistics()
    null_hash = hashlib.sha256(null.tobytes()).hexdigest()
    development = simulate_period(
        market, DEVELOPMENT_START, DEVELOPMENT_END, null
    )
    development_stress = simulate_period(
        market,
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        null,
        cost_multiplier=STRESS_COST_MULTIPLIER,
    )
    folds = [
        simulate_period(market, start, end, null)
        for start, end in DEVELOPMENT_FOLDS
    ]
    positive_folds = sum(value["total_return"] > 0 for value in folds)
    development_gate = _gate(
        development,
        protocol["development_gate"],
        positive_folds=positive_folds,
    )
    stress_checks = {
        "stress_total_return_positive": development_stress["total_return"] > 0,
        "minimum_stress_profit_factor": development_stress["profit_factor"]
        >= protocol["development_gate"]["minimum_stress_profit_factor"],
    }
    development_gate["checks"].update(stress_checks)
    development_gate["passed_checks"] = sum(development_gate["checks"].values())
    development_gate["total_checks"] = len(development_gate["checks"])
    development_gate["passed"] = all(development_gate["checks"].values())

    confirmation = None
    confirmation_stress = None
    confirmation_gate = {
        "passed": False,
        "not_evaluated": not development_gate["passed"],
        "reason": "development_gate_failed" if not development_gate["passed"] else None,
    }
    if development_gate["passed"]:
        confirmation = simulate_period(
            market, CONFIRMATION_START, CONFIRMATION_END, null
        )
        confirmation_stress = simulate_period(
            market,
            CONFIRMATION_START,
            CONFIRMATION_END,
            null,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        confirmation_gate = _gate(
            confirmation, protocol["confirmation_gate"]
        )
        confirmation_gate["checks"].update(
            {
                "stress_total_return_positive": confirmation_stress["total_return"] > 0,
                "minimum_stress_profit_factor": confirmation_stress["profit_factor"]
                >= protocol["confirmation_gate"]["minimum_stress_profit_factor"],
            }
        )
        confirmation_gate["passed_checks"] = sum(
            confirmation_gate["checks"].values()
        )
        confirmation_gate["total_checks"] = len(confirmation_gate["checks"])
        confirmation_gate["passed"] = all(confirmation_gate["checks"].values())

    locked_authorized = development_gate["passed"] and confirmation_gate["passed"]
    locked = None
    locked_stress = None
    locked_gate = {
        "passed": False,
        "not_evaluated": not locked_authorized,
        "reason": "prelock_gate_failed" if not locked_authorized else None,
    }
    if locked_authorized:
        locked = simulate_period(market, LOCKED_START, LOCKED_END, null)
        locked_stress = simulate_period(
            market,
            LOCKED_START,
            LOCKED_END,
            null,
            cost_multiplier=STRESS_COST_MULTIPLIER,
        )
        locked_gate = _gate(locked, protocol["locked_gate"])
        locked_gate["checks"]["stress_total_return_positive"] = (
            locked_stress["total_return"] > 0
        )
        locked_gate["passed_checks"] = sum(locked_gate["checks"].values())
        locked_gate["total_checks"] = len(locked_gate["checks"])
        locked_gate["passed"] = all(locked_gate["checks"].values())

    passed = locked_authorized and locked_gate["passed"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": _sha256(protocol_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "source_artifacts": artifacts,
        "symbols": market["symbols"],
        "market": {
            "start_date": market["dates"][0].isoformat(),
            "end_date": market["dates"][-1].isoformat(),
            "days": len(market["dates"]),
        },
        "monte_carlo_null": {
            "simulations": len(null),
            "seed": MONTE_CARLO_SEED,
            "sha256": null_hash,
        },
        "development": development,
        "development_stress": development_stress,
        "development_folds": folds,
        "development_positive_folds": positive_folds,
        "development_gate": development_gate,
        "confirmation": confirmation,
        "confirmation_stress": confirmation_stress,
        "confirmation_gate": confirmation_gate,
        "locked_test": {
            "authorized_to_open": locked_authorized,
            "materialized": locked is not None,
            "report": locked,
            "stress_report": locked_stress,
            "gate": locked_gate,
        },
        "verdict": (
            "ELIGIBLE_FOR_MANUAL_ORDERLESS_SHADOW"
            if passed
            else (
                "REJECTED_LOCKED_TEST"
                if locked is not None
                else "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
            )
        ),
        "results_do_not_authorize_orders": True,
    }
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / (
        "cointegration-pairs-v1-"
        + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    experiment.mkdir(parents=True, exist_ok=False)
    report_path = experiment / "report.json"
    _atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "report_path": str(report_path),
        "report_sha256": _sha256(report_path),
        "locked_test_materialized": locked is not None,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = _json_hash(manifest)
    _atomic_json(experiment / "manifest.json", manifest)
    return {"report": report, "manifest": manifest, "directory": str(experiment)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    evaluate = subparsers.add_parser("evaluate-prelock")
    evaluate.add_argument("--protocol", required=True)
    evaluate.add_argument("--futures-collector", action="append", required=True)
    evaluate.add_argument("--funding-json", action="append", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "write-protocol":
        payload = write_or_verify_protocol(args.output)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    result = evaluate_prelock(
        args.protocol,
        args.futures_collector,
        args.funding_json,
        args.output_root,
    )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
