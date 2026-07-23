"""Leakage-resistant weekly meta-filter for the V3 trend protocol."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import trend as trend_module


META_SCHEMA_VERSION = 1
META_NAME = "v3_weekly_logistic_meta_v10"
BASE_STRATEGY_NAME = (
    "bear_regime_short_filter_dual_momentum_30_120_weekly_v3"
)
FEATURE_NAMES = (
    "directional_return_30d",
    "directional_return_120d",
    "fast_to_slow_momentum_ratio",
    "annualized_volatility_20d",
    "annualized_volatility_60d",
    "directional_btc_return_30d",
    "directional_btc_return_120d",
    "directional_relative_momentum_120d",
    "trailing_directional_funding_pnl_30d",
    "btc_correlation_60d",
    "active_signal_fraction",
    "directional_coherence",
)
PROBABILITY_THRESHOLD = 0.55
LABEL_HORIZON_DAYS = 7
WALK_FORWARD_FOLDS = 4
INITIAL_TRAIN_FRACTION = 0.50
LOGISTIC_CONFIG = model_module.LogisticConfig(
    epochs=40,
    batch_size=8192,
    learning_rate=0.01,
    l2=0.01,
    seed=42,
)


def evaluate_trend_meta(
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
    if not symbols:
        raise ValueError("no collector symbol has signed funding history")
    market = trend_module._build_daily_market(
        {symbol: series[symbol]["1h"] for symbol in symbols},
        {symbol: funding[symbol] for symbol in symbols},
    )
    return evaluate_market(
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
    config = _base_config(cost_stress_multiplier)
    samples = _build_samples(market, config)
    unique_indices = numpy.unique(samples["rebalance_index"])
    first_test_position = int(
        len(unique_indices) * INITIAL_TRAIN_FRACTION
    )
    if first_test_position < 20 or (
        len(unique_indices) - first_test_position
    ) < WALK_FORWARD_FOLDS:
        raise ValueError("not enough weekly dates for meta walk-forward")
    boundaries = numpy.linspace(
        first_test_position,
        len(unique_indices),
        WALK_FORWARD_FOLDS + 1,
        dtype=int,
    )
    base_signals = trend_module._signals(
        market["closes"], config, market["symbols"]
    )
    filtered_signals = numpy.zeros_like(base_signals)
    fold_reports = []
    prediction_rows = []
    for fold in range(WALK_FORWARD_FOLDS):
        test_dates = unique_indices[
            boundaries[fold] : boundaries[fold + 1]
        ]
        test_start = int(test_dates[0])
        test_end = int(test_dates[-1])
        train_rows = numpy.flatnonzero(
            samples["label_end_index"] < test_start
        )
        test_rows = numpy.flatnonzero(
            numpy.isin(samples["rebalance_index"], test_dates)
        )
        if not len(train_rows) or not len(test_rows):
            raise ValueError("empty meta walk-forward fold")
        model = model_module.NumpyLogisticModel.fit(
            samples["features"][train_rows],
            samples["labels"][train_rows],
            FEATURE_NAMES,
            LOGISTIC_CONFIG,
        )
        probabilities = model.predict_proba(
            samples["features"][test_rows]
        )
        accepted = probabilities >= PROBABILITY_THRESHOLD
        for row, probability, is_accepted in zip(
            test_rows, probabilities, accepted
        ):
            index = int(samples["rebalance_index"][row])
            column = int(samples["asset_column"][row])
            if is_accepted:
                filtered_signals[index, column] = base_signals[
                    index, column
                ]
            prediction_rows.append(
                (
                    index,
                    column,
                    float(probability),
                    bool(is_accepted),
                )
            )
        fold_mask = numpy.zeros_like(base_signals)
        fold_mask[test_start : test_end + 1] = filtered_signals[
            test_start : test_end + 1
        ]
        fold_candidate = trend_module._simulate(
            market,
            config,
            initial_capital,
            signal_override=fold_mask,
            evaluation_start_index=test_start,
            evaluation_end_index=min(
                len(market["dates"]), test_end + LABEL_HORIZON_DAYS + 1
            ),
        )
        fold_baseline = trend_module._simulate(
            market,
            config,
            initial_capital,
            evaluation_start_index=test_start,
            evaluation_end_index=min(
                len(market["dates"]), test_end + LABEL_HORIZON_DAYS + 1
            ),
        )
        accepted_returns = samples["net_return"][test_rows][accepted]
        fold_reports.append(
            {
                "fold": fold + 1,
                "train_rows": int(len(train_rows)),
                "test_rows": int(len(test_rows)),
                "accepted_setups": int(numpy.sum(accepted)),
                "test_start_date": str(market["dates"][test_start]),
                "test_end_date": str(market["dates"][test_end]),
                "positive_label_rate": float(
                    numpy.mean(samples["labels"][test_rows])
                ),
                "accepted_positive_rate": (
                    float(numpy.mean(
                        samples["labels"][test_rows][accepted]
                    ))
                    if numpy.any(accepted)
                    else 0.0
                ),
                "accepted_setup_net_return_sum": float(
                    numpy.sum(accepted_returns)
                ),
                "brier_score": float(
                    numpy.mean(
                        (
                            probabilities
                            - samples["labels"][test_rows]
                        )
                        ** 2
                    )
                ),
                "candidate_total_return": fold_candidate[
                    "total_return"
                ],
                "baseline_total_return": fold_baseline["total_return"],
            }
        )

    first_oos_index = int(
        unique_indices[first_test_position]
    )
    candidate = trend_module._simulate(
        market,
        config,
        initial_capital,
        signal_override=filtered_signals,
        evaluation_start_index=first_oos_index,
    )
    baseline = trend_module._simulate(
        market,
        config,
        initial_capital,
        evaluation_start_index=first_oos_index,
    )
    accepted_count = sum(value[3] for value in prediction_rows)
    return {
        "schema_version": META_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "pre_registered_protocol": True,
        "name": META_NAME,
        "base_strategy": BASE_STRATEGY_NAME,
        "symbols": list(market["symbols"]),
        "feature_names": list(FEATURE_NAMES),
        "probability_threshold": PROBABILITY_THRESHOLD,
        "label_horizon_days": LABEL_HORIZON_DAYS,
        "cost_stress_multiplier": cost_stress_multiplier,
        "logistic_config": dataclasses.asdict(LOGISTIC_CONFIG),
        "walk_forward": {
            "folds": WALK_FORWARD_FOLDS,
            "initial_train_fraction": INITIAL_TRAIN_FRACTION,
            "purge_days": LABEL_HORIZON_DAYS,
            "samples": int(len(samples["labels"])),
            "positive_label_rate": float(
                numpy.mean(samples["labels"])
            ),
            "oos_prediction_rows": len(prediction_rows),
            "accepted_setups": int(accepted_count),
            "fold_reports": fold_reports,
        },
        "market": {
            "start_date": str(market["dates"][0]),
            "end_date": str(market["dates"][-1]),
            "oos_start_date": str(market["dates"][first_oos_index]),
        },
        "reports": {
            f"{META_NAME}_oos": candidate,
            f"{BASE_STRATEGY_NAME}_same_oos_baseline": baseline,
        },
        "automatic_promotion": False,
    }


def _base_config(cost_stress_multiplier):
    for config in trend_module.TREND_CONFIGS:
        if config.name == BASE_STRATEGY_NAME:
            return dataclasses.replace(
                config,
                name=(
                    f"{config.name}_meta_cost_stress_"
                    f"{cost_stress_multiplier:g}x"
                ),
                fee_per_turnover=(
                    config.fee_per_turnover * cost_stress_multiplier
                ),
                slippage_per_turnover=(
                    config.slippage_per_turnover
                    * cost_stress_multiplier
                ),
            )
    raise ValueError("V3 base strategy is not registered")


def _build_samples(market, config):
    closes = market["closes"]
    returns = market["returns"]
    funding = market["funding"]
    signals = trend_module._signals(
        closes, config, market["symbols"]
    )
    btc_symbol = config.short_regime_symbol
    if btc_symbol not in market["symbols"]:
        raise ValueError("V3 BTC regime symbol is missing")
    btc_column = market["symbols"].index(btc_symbol)
    round_trip_cost = 2.0 * (
        config.fee_per_turnover + config.slippage_per_turnover
    )
    rows = {
        "features": [],
        "labels": [],
        "net_return": [],
        "rebalance_index": [],
        "label_end_index": [],
        "asset_column": [],
    }
    start_index = max(
        config.slow_days, config.volatility_lookback_days
    )
    for index in range(
        start_index,
        len(market["dates"]) - LABEL_HORIZON_DAYS,
        config.rebalance_days,
    ):
        signal_row = signals[index]
        active_count = int(numpy.count_nonzero(signal_row))
        breadth = active_count / len(signal_row)
        coherence = (
            abs(float(numpy.sum(numpy.sign(signal_row)))) / active_count
            if active_count
            else 0.0
        )
        btc_return_30 = closes[index, btc_column] / closes[
            index - 30, btc_column
        ] - 1.0
        btc_return_120 = closes[index, btc_column] / closes[
            index - 120, btc_column
        ] - 1.0
        for column in numpy.flatnonzero(signal_row):
            direction = float(numpy.sign(signal_row[column]))
            fast_return = closes[index, column] / closes[
                index - 30, column
            ] - 1.0
            slow_return = closes[index, column] / closes[
                index - 120, column
            ] - 1.0
            volatility_20 = float(
                numpy.std(returns[index - 19 : index + 1, column])
                * numpy.sqrt(365.0)
            )
            volatility_60 = float(
                numpy.std(returns[index - 59 : index + 1, column])
                * numpy.sqrt(365.0)
            )
            correlation = _safe_correlation(
                returns[index - 59 : index + 1, column],
                returns[index - 59 : index + 1, btc_column],
            )
            trailing_funding_pnl = float(
                -direction
                * numpy.sum(funding[index - 29 : index + 1, column])
            )
            future_price_return = direction * (
                closes[index + LABEL_HORIZON_DAYS, column]
                / closes[index, column]
                - 1.0
            )
            future_funding_pnl = float(
                -direction
                * numpy.sum(
                    funding[
                        index + 1 : index + LABEL_HORIZON_DAYS + 1,
                        column,
                    ]
                )
            )
            net_return = (
                future_price_return
                + future_funding_pnl
                - round_trip_cost
            )
            features = (
                direction * fast_return,
                direction * slow_return,
                direction * fast_return / (abs(slow_return) + 0.01),
                volatility_20,
                volatility_60,
                direction * btc_return_30,
                direction * btc_return_120,
                direction * (slow_return - btc_return_120),
                trailing_funding_pnl,
                correlation,
                breadth,
                coherence,
            )
            if not numpy.all(numpy.isfinite(features)):
                raise ValueError("meta features contain non-finite values")
            rows["features"].append(features)
            rows["labels"].append(int(net_return > 0))
            rows["net_return"].append(net_return)
            rows["rebalance_index"].append(index)
            rows["label_end_index"].append(
                index + LABEL_HORIZON_DAYS
            )
            rows["asset_column"].append(int(column))
    if not rows["labels"]:
        raise ValueError("V3 generated no weekly meta samples")
    return {
        "features": numpy.asarray(rows["features"], dtype=numpy.float64),
        "labels": numpy.asarray(rows["labels"], dtype=numpy.int8),
        "net_return": numpy.asarray(
            rows["net_return"], dtype=numpy.float64
        ),
        "rebalance_index": numpy.asarray(
            rows["rebalance_index"], dtype=numpy.int64
        ),
        "label_end_index": numpy.asarray(
            rows["label_end_index"], dtype=numpy.int64
        ),
        "asset_column": numpy.asarray(
            rows["asset_column"], dtype=numpy.int64
        ),
    }


def _safe_correlation(first, second):
    if numpy.std(first) < 1e-12 or numpy.std(second) < 1e-12:
        return 0.0
    value = float(numpy.corrcoef(first, second)[0, 1])
    return value if numpy.isfinite(value) else 0.0
