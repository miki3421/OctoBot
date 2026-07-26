"""Causal LONG/SHORT/WAIT student trained from perfect-map future labels.

Future candles are used only to construct supervised labels and economic
evaluation. Every feature and prediction is available at the decision close.
The module is offline, research-only, and cannot authorize orders.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import h2_backtest
from octobot.ai_strategy_lab import indicators
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import percentage_probability_engine as probability_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_perfect_map_student_v1"
CANDLE_SECONDS = 900
HORIZON_BARS = 96
ACTIVATION_PCT = 1.2
INITIAL_STOP_PCT = 1.0
PROTECTED_STOP_PCT = 1.0
ROUND_TRIP_COST_PCT = 0.16
TRAINING_STRIDE = 4
MINIMUM_DIRECTION_MARGIN = 0.03
THRESHOLD_CANDIDATES = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
MINIMUM_SELECTION_TRADES = 30
WINDOWS = (1, 2, 4, 8, 16, 32, 64)
CANDLE_LAGS = (0, 1, 2, 3, 4, 7, 15, 31)
WAIT = 0
LONG = 1
SHORT = -1
MODEL_CONFIG = model_module.LogisticConfig(
    epochs=24,
    batch_size=8192,
    learning_rate=0.015,
    l2=0.002,
    seed=20_260_724,
)
SPLITS = {
    "train": ("2022-05-01", "2024-12-30"),
    "calibration": ("2025-01-02", "2025-03-30"),
    "threshold_selection": ("2025-04-02", "2025-06-29"),
    "locked_test": ("2025-07-02", "2025-12-30"),
    "external_reused_kucoin": ("2026-01-02", "2026-07-20"),
}


@dataclasses.dataclass(frozen=True)
class StudentDataset:
    features: numpy.ndarray
    labels: numpy.ndarray
    timestamps: numpy.ndarray
    candle_indices: numpy.ndarray
    candles: numpy.ndarray

    def take(self, mask: numpy.ndarray) -> "StudentDataset":
        return StudentDataset(
            features=self.features[mask],
            labels=self.labels[mask],
            timestamps=self.timestamps[mask],
            candle_indices=self.candle_indices[mask],
            candles=self.candles,
        )


@dataclasses.dataclass(frozen=True)
class StudentModel:
    long_model: model_module.NumpyLogisticModel
    short_model: model_module.NumpyLogisticModel
    long_calibrator: probability_module.QuantileIsotonicCalibrator
    short_calibrator: probability_module.QuantileIsotonicCalibrator
    threshold: float

    def predict(self, features: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
        long_values = self.long_calibrator.predict(
            self.long_model.predict_proba(features)
        )
        short_values = self.short_calibrator.predict(
            self.short_model.predict_proba(features)
        )
        return long_values, short_values


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "target": {
            "classes": ["LONG", "SHORT", "WAIT"],
            "long": "+1.2% before -1.0% within 24h",
            "short": "-1.2% before +1.0% within 24h",
            "same_candle_policy": "stop_wins",
            "both_directional_wins": "earliest_activation_wins",
            "future_used_for_labels_only": True,
        },
        "features": {
            "causal": True,
            "maximum_candle_lookback": 64,
            "windows": list(WINDOWS),
            "candle_lags": list(CANDLE_LAGS),
            "families": [
                "point_in_time_indicators",
                "multi_scale_returns_and_ranges",
                "realized_volatility",
                "relative_volume",
                "lagged_body_range_and_wicks",
                "cyclical_time",
            ],
        },
        "model": {
            "type": "two_one_vs_rest_numpy_logistic_models",
            "config": dataclasses.asdict(MODEL_CONFIG),
            "calibration": "quantile_isotonic",
            "training_stride": TRAINING_STRIDE,
            "minimum_direction_margin": MINIMUM_DIRECTION_MARGIN,
        },
        "trade": {
            "one_trade_at_a_time": True,
            "directions_must_alternate": False,
            "entry": "decision candle close",
            "activation_pct": ACTIVATION_PCT,
            "initial_stop_pct": INITIAL_STOP_PCT,
            "protected_stop_pct": PROTECTED_STOP_PCT,
            "protected_stop_active_from_next_candle": True,
            "maximum_holding_hours": 24,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "funding_included": True,
        },
        "selection": {
            "threshold_candidates": list(THRESHOLD_CANDIDATES),
            "minimum_trades": MINIMUM_SELECTION_TRADES,
            "objective": (
                "maximize compounded_net_return_pct minus "
                "maximum_drawdown_pct on threshold_selection only"
            ),
        },
        "splits": SPLITS,
        "evidence_policy": {
            "locked_test": "new_for_this_student_protocol_but_not_globally_virgin",
            "external_kucoin": "diagnostic_reuse_not_promotion_evidence",
        },
    }


def write_protocol(output_value: typing.Union[str, pathlib.Path]) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    path = output / "protocol.json"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def build_dataset(candles: numpy.ndarray) -> StudentDataset:
    """Build causal sequence features and perfect-map future labels."""

    if candles.ndim != 2 or candles.shape[1] < 6:
        raise ValueError("candles must be an OHLCV matrix")
    gaps = numpy.flatnonzero(numpy.diff(candles[:, 0]) != CANDLE_SECONDS)
    starts = numpy.concatenate((numpy.asarray([0]), gaps + 1))
    ends = numpy.concatenate((gaps + 1, numpy.asarray([len(candles)])))
    blocks = [
        _build_contiguous_dataset(
            candles[int(start) : int(end)],
            index_offset=int(start),
            all_candles=candles,
        )
        for start, end in zip(starts, ends)
        if int(end) - int(start) > HORIZON_BARS + max(WINDOWS)
    ]
    blocks = [block for block in blocks if len(block.labels)]
    if not blocks:
        raise ValueError("no complete student examples")
    # Candle indices are translated back to the merged source so simulations
    # cannot mistake a post-gap row for a pre-gap row.
    return StudentDataset(
        features=numpy.concatenate([block.features for block in blocks]),
        labels=numpy.concatenate([block.labels for block in blocks]),
        timestamps=numpy.concatenate([block.timestamps for block in blocks]),
        candle_indices=numpy.concatenate(
            [block.candle_indices for block in blocks]
        ),
        candles=candles,
    )


def _build_contiguous_dataset(
    candles: numpy.ndarray,
    *,
    index_offset: int = 0,
    all_candles: typing.Optional[numpy.ndarray] = None,
) -> StudentDataset:
    feature_values, feature_names = sequence_features(candles)
    if feature_names != student_feature_names():
        raise ValueError("student feature schema is not deterministic")
    labels = perfect_map_labels(candles)
    final_index = len(candles) - HORIZON_BARS
    indices = numpy.arange(final_index, dtype=numpy.int64)
    valid = numpy.all(numpy.isfinite(feature_values[indices]), axis=1)
    indices = indices[valid]
    return StudentDataset(
        features=feature_values[indices].astype(numpy.float32),
        labels=labels[indices],
        timestamps=(
            candles[indices, 0].astype(numpy.int64) + CANDLE_SECONDS
        ),
        candle_indices=indices + index_offset,
        candles=candles if all_candles is None else all_candles,
    )


def student_feature_names() -> tuple[str, ...]:
    names = list(probability_module.FEATURE_NAMES)
    for window in WINDOWS:
        names.extend(
            (
                f"return_{window}",
                f"window_high_{window}",
                f"window_low_{window}",
                f"realized_volatility_{window}",
                f"relative_volume_{window}",
            )
        )
    for lag in CANDLE_LAGS:
        names.extend(
            (
                f"body_lag_{lag}",
                f"range_lag_{lag}",
                f"upper_wick_lag_{lag}",
                f"lower_wick_lag_{lag}",
                f"log_return_lag_{lag}",
                f"volume_zscore_lag_{lag}",
            )
        )
    names.extend(("hour_sin", "hour_cos", "weekday_sin", "weekday_cos"))
    return tuple(names)


def sequence_features(
    candles: numpy.ndarray,
) -> tuple[numpy.ndarray, tuple[str, ...]]:
    """Represent the previous 64 candles without observing a future row."""

    open_values = candles[:, 1].astype(float)
    high = candles[:, 2].astype(float)
    low = candles[:, 3].astype(float)
    close = candles[:, 4].astype(float)
    volume = candles[:, 5].astype(float)
    log_close = numpy.log(numpy.maximum(close, numpy.finfo(float).tiny))
    log_return = _lag_difference(log_close, 1)
    indicator_values = indicators.compute_feature_arrays(candles)
    columns = [
        indicator_values[name] for name in probability_module.FEATURE_NAMES
    ]

    for window in WINDOWS:
        columns.append(_ratio_to_lag(close, window))
        rolling_high = _rolling_reduce(high, window, numpy.max)
        rolling_low = _rolling_reduce(low, window, numpy.min)
        columns.append(rolling_high / close - 1)
        columns.append(rolling_low / close - 1)
        _, volatility = _rolling_mean_std(log_return, window)
        columns.append(volatility)
        volume_mean, _ = _rolling_mean_std(volume, window)
        columns.append(
            numpy.divide(
                volume,
                volume_mean,
                out=numpy.full(len(volume), numpy.nan),
                where=volume_mean != 0,
            )
            - 1
        )

    denominator = numpy.maximum(open_values, numpy.finfo(float).tiny)
    body = (close - open_values) / denominator
    candle_range = (high - low) / denominator
    upper_wick = (high - numpy.maximum(open_values, close)) / denominator
    lower_wick = (numpy.minimum(open_values, close) - low) / denominator
    for lag in CANDLE_LAGS:
        for values in (
            body,
            candle_range,
            upper_wick,
            lower_wick,
            log_return,
            indicator_values["volume_zscore"],
        ):
            columns.append(_lag(values, lag))

    close_times = candles[:, 0].astype(numpy.int64) + CANDLE_SECONDS
    datetimes = [
        datetime.datetime.fromtimestamp(
            int(value), datetime.timezone.utc
        )
        for value in close_times
    ]
    hours = numpy.asarray(
        [value.hour + value.minute / 60 for value in datetimes], dtype=float
    )
    weekdays = numpy.asarray([value.weekday() for value in datetimes], dtype=float)
    columns.extend(
        (
            numpy.sin(2 * numpy.pi * hours / 24),
            numpy.cos(2 * numpy.pi * hours / 24),
            numpy.sin(2 * numpy.pi * weekdays / 7),
            numpy.cos(2 * numpy.pi * weekdays / 7),
        )
    )
    return numpy.column_stack(columns), student_feature_names()


def perfect_map_labels(candles: numpy.ndarray) -> numpy.ndarray:
    """Return WAIT/LONG/SHORT labels using conservative first-touch paths."""

    long_wins, long_offsets = _first_touch(candles, LONG)
    short_wins, short_offsets = _first_touch(candles, SHORT)
    labels = numpy.zeros(len(candles), dtype=numpy.int8)
    only_long = long_wins & ~short_wins
    only_short = short_wins & ~long_wins
    labels[only_long] = LONG
    labels[only_short] = SHORT
    both = long_wins & short_wins
    labels[both & (long_offsets < short_offsets)] = LONG
    labels[both & (short_offsets < long_offsets)] = SHORT
    return labels


def _first_touch(
    candles: numpy.ndarray, direction: int
) -> tuple[numpy.ndarray, numpy.ndarray]:
    close = candles[:, 4].astype(float)
    high = candles[:, 2].astype(float)
    low = candles[:, 3].astype(float)
    stop = close * (1 - direction * INITIAL_STOP_PCT / 100)
    target = close * (1 + direction * ACTIVATION_PCT / 100)
    resolved = numpy.zeros(len(candles), dtype=bool)
    wins = numpy.zeros(len(candles), dtype=bool)
    offsets = numpy.full(len(candles), HORIZON_BARS + 1, dtype=numpy.int16)
    for offset in range(1, HORIZON_BARS + 1):
        limit = len(candles) - offset
        if limit <= 0:
            break
        available = ~resolved[:limit]
        if direction == LONG:
            stop_touch = low[offset:] <= stop[:limit]
            target_touch = high[offset:] >= target[:limit]
        else:
            stop_touch = high[offset:] >= stop[:limit]
            target_touch = low[offset:] <= target[:limit]
        success = available & target_touch & ~stop_touch
        failure = available & stop_touch
        wins[:limit][success] = True
        offsets[:limit][success] = offset
        resolved[:limit][success | failure] = True
    return wins, offsets


def fit_student(
    dataset: StudentDataset,
) -> tuple[StudentModel, dict]:
    masks = {
        name: _date_mask(dataset.timestamps, *dates)
        for name, dates in SPLITS.items()
        if name != "external_reused_kucoin"
    }
    train_indices = numpy.flatnonzero(masks["train"])[::TRAINING_STRIDE]
    if len(train_indices) < 1_000:
        raise ValueError("insufficient training examples")
    long_model = model_module.NumpyLogisticModel.fit(
        dataset.features[train_indices],
        (dataset.labels[train_indices] == LONG).astype(numpy.int8),
        student_feature_names(),
        MODEL_CONFIG,
    )
    short_model = model_module.NumpyLogisticModel.fit(
        dataset.features[train_indices],
        (dataset.labels[train_indices] == SHORT).astype(numpy.int8),
        student_feature_names(),
        dataclasses.replace(MODEL_CONFIG, seed=MODEL_CONFIG.seed + 1),
    )
    calibration = numpy.flatnonzero(masks["calibration"])
    long_calibrator = probability_module.QuantileIsotonicCalibrator.fit(
        long_model.predict_proba(dataset.features[calibration]),
        (dataset.labels[calibration] == LONG).astype(numpy.int8),
    )
    short_calibrator = probability_module.QuantileIsotonicCalibrator.fit(
        short_model.predict_proba(dataset.features[calibration]),
        (dataset.labels[calibration] == SHORT).astype(numpy.int8),
    )
    unselected = StudentModel(
        long_model,
        short_model,
        long_calibrator,
        short_calibrator,
        threshold=THRESHOLD_CANDIDATES[0],
    )
    diagnostics = {
        "split_examples": {
            name: int(numpy.sum(mask)) for name, mask in masks.items()
        },
        "train_class_distribution": _class_distribution(
            dataset.labels[train_indices]
        ),
    }
    return unselected, diagnostics


def select_threshold(
    model: StudentModel,
    dataset: StudentDataset,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> tuple[float, list[dict]]:
    mask = _date_mask(
        dataset.timestamps, *SPLITS["threshold_selection"]
    )
    subset = dataset.take(mask)
    long_probabilities, short_probabilities = model.predict(subset.features)
    values = []
    for threshold in THRESHOLD_CANDIDATES:
        trades = simulate_predictions(
            subset,
            long_probabilities,
            short_probabilities,
            threshold,
            funding_series,
        )
        metrics = h2_backtest._metrics(trades, ROUND_TRIP_COST_PCT)
        objective = (
            metrics["compounded_net_return_pct"]
            - metrics["maximum_drawdown_pct"]
        )
        values.append(
            {
                "threshold": threshold,
                "objective": objective,
                "eligible": metrics["trades"] >= MINIMUM_SELECTION_TRADES,
                "metrics": metrics,
            }
        )
    eligible = [value for value in values if value["eligible"]]
    selected = max(
        eligible or values,
        key=lambda value: (value["objective"], value["metrics"]["trades"]),
    )
    return float(selected["threshold"]), values


def simulate_predictions(
    dataset: StudentDataset,
    long_probabilities: numpy.ndarray,
    short_probabilities: numpy.ndarray,
    threshold: float,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> list[dict]:
    if not (
        len(dataset.labels)
        == len(long_probabilities)
        == len(short_probabilities)
    ):
        raise ValueError("prediction arrays are misaligned")
    candidates = []
    for row, candle_index in enumerate(dataset.candle_indices):
        long_probability = float(long_probabilities[row])
        short_probability = float(short_probabilities[row])
        if max(long_probability, short_probability) < threshold:
            continue
        if abs(long_probability - short_probability) < MINIMUM_DIRECTION_MARGIN:
            continue
        direction = (
            percentage_engine.LONG
            if long_probability > short_probability
            else percentage_engine.SHORT
        )
        candidates.append(
            {
                "entry_index": int(candle_index),
                "direction": direction,
                "probability_pct": max(long_probability, short_probability) * 100,
                "opposite_probability_pct": min(
                    long_probability, short_probability
                )
                * 100,
            }
        )
    trade_config = percentage_engine.PercentageEngineConfig(
        minimum_profit_pct=PROTECTED_STOP_PCT,
        activation_pct=ACTIVATION_PCT,
        initial_stop_pct=INITIAL_STOP_PCT,
        horizon_candles=HORIZON_BARS,
        directions=(percentage_engine.LONG, percentage_engine.SHORT),
        exclude_last_candle=False,
    )
    close_times = (
        dataset.candles[:, 0].astype(numpy.int64) + CANDLE_SECONDS
    ).tolist()
    next_available = 0
    trades = []
    funding_timestamps, funding_rates = funding_series
    for candidate in candidates:
        entry_index = candidate["entry_index"]
        if entry_index < next_available:
            continue
        trade = percentage_engine.simulate_trade(
            close_times,
            dataset.candles[:, 2],
            dataset.candles[:, 3],
            dataset.candles[:, 4],
            entry_index,
            candidate["direction"],
            len(dataset.candles) - 1,
            trade_config,
        )
        entry_timestamp = int(trade["entry_time"])
        exit_timestamp = int(trade["exit_time"])
        first = int(
            numpy.searchsorted(
                funding_timestamps, entry_timestamp, side="right"
            )
        )
        last = int(
            numpy.searchsorted(
                funding_timestamps, exit_timestamp, side="right"
            )
        )
        sign = 1 if trade["direction"] == percentage_engine.LONG else -1
        funding_cost_pct = sign * float(
            numpy.sum(funding_rates[first:last])
        ) * 100
        trades.append(
            {
                "direction": trade["direction"],
                "exchange": "dataset",
                "entry_time_utc": _timestamp_iso(entry_timestamp),
                "entry_timestamp": entry_timestamp,
                "exit_time_utc": _timestamp_iso(exit_timestamp),
                "exit_timestamp": exit_timestamp,
                "entry_price": float(trade["entry_price"]),
                "exit_price": float(trade["exit_price"]),
                "exit_reason": trade["exit_reason"],
                "duration_hours": (exit_timestamp - entry_timestamp) / 3600,
                "gross_return_pct": float(trade["gross_return_pct"]),
                "funding_cost_pct": funding_cost_pct,
                "probability_pct": candidate["probability_pct"],
                "opposite_probability_pct": candidate[
                    "opposite_probability_pct"
                ],
                "maximum_favorable_excursion_pct": float(
                    trade["maximum_favorable_excursion_pct"]
                ),
                "maximum_adverse_excursion_pct": float(
                    trade["maximum_adverse_excursion_pct"]
                ),
            }
        )
        next_available = int(trade["exit_index"]) + 1
    return trades


def evaluate_block(
    name: str,
    model: StudentModel,
    dataset: StudentDataset,
    date_range: tuple[str, str],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    exchange: str,
    evidence_role: str,
) -> tuple[dict, list[dict], dict]:
    subset = dataset.take(_date_mask(dataset.timestamps, *date_range))
    long_probabilities, short_probabilities = model.predict(subset.features)
    trades = simulate_predictions(
        subset,
        long_probabilities,
        short_probabilities,
        model.threshold,
        funding_series,
    )
    for trade in trades:
        trade["exchange"] = exchange
    predicted_labels = _prediction_labels(
        long_probabilities, short_probabilities, model.threshold
    )
    comparison = _classification_metrics(subset.labels, predicted_labels)
    predictions = {
        "timestamps": subset.timestamps,
        "labels": subset.labels,
        "long_probabilities": long_probabilities,
        "short_probabilities": short_probabilities,
        "predicted_labels": predicted_labels,
    }
    return (
        {
            "name": name,
            "exchange": exchange,
            "evidence_role": evidence_role,
            "start": date_range[0],
            "end": date_range[1],
            "examples": len(subset.labels),
            "class_distribution": _class_distribution(subset.labels),
            "classification": comparison,
            "economic": h2_backtest._metrics(
                trades, ROUND_TRIP_COST_PCT
            ),
        },
        trades,
        predictions,
    )


def run_study(
    *,
    binance_collector: typing.Union[str, pathlib.Path],
    binance_funding: typing.Union[str, pathlib.Path],
    kucoin_collector: typing.Union[str, pathlib.Path],
    kucoin_funding: typing.Union[str, pathlib.Path],
    output_directory: typing.Union[str, pathlib.Path],
) -> dict:
    output = pathlib.Path(output_directory).resolve()
    protocol_path = output / "protocol.json"
    if not protocol_path.is_file():
        raise FileNotFoundError("write protocol.json before running the study")
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol = frozen_protocol()
    if persisted.get("protocol_sha256") != _json_hash(protocol):
        raise ValueError("persisted protocol differs from frozen student code")

    binance_path = pathlib.Path(binance_collector).resolve()
    binance_funding_path = pathlib.Path(binance_funding).resolve()
    kucoin_path = pathlib.Path(kucoin_collector).resolve()
    kucoin_funding_path = pathlib.Path(kucoin_funding).resolve()
    binance_candles = h2_backtest._load_btc_15m(binance_path, "15m")
    kucoin_candles = h2_backtest._load_btc_15m(kucoin_path, "5m")
    binance_dataset = build_dataset(binance_candles)
    kucoin_dataset = build_dataset(kucoin_candles)
    binance_funding_series = _btc_funding(binance_funding_path)
    kucoin_funding_series = _btc_funding(kucoin_funding_path)

    base_model, fit_diagnostics = fit_student(binance_dataset)
    threshold, threshold_table = select_threshold(
        base_model, binance_dataset, binance_funding_series
    )
    selected_threshold_report = next(
        value
        for value in threshold_table
        if value["threshold"] == threshold
    )
    selected_metrics = selected_threshold_report["metrics"]
    selection_diagnostic_gate = {
        "preregistered": False,
        "note": (
            "Added after the exploratory run to state explicitly that a "
            "negative selection block must not promote the candidate."
        ),
        "criteria": {
            "minimum_trades": MINIMUM_SELECTION_TRADES,
            "profit_factor_above_one": True,
            "positive_compounded_return": True,
            "positive_selection_objective": True,
        },
        "passed": (
            selected_metrics["trades"] >= MINIMUM_SELECTION_TRADES
            and selected_metrics["profit_factor"] is not None
            and selected_metrics["profit_factor"] > 1
            and selected_metrics["compounded_net_return_pct"] > 0
            and selected_threshold_report["objective"] > 0
        ),
    }
    student = dataclasses.replace(base_model, threshold=threshold)
    locked_report, locked_trades, locked_predictions = evaluate_block(
        "binance_locked_test_2025_h2_student",
        student,
        binance_dataset,
        SPLITS["locked_test"],
        binance_funding_series,
        "binance_usdm",
        "student_locked_test_not_globally_virgin",
    )
    external_report, external_trades, external_predictions = evaluate_block(
        "kucoin_external_reused_2026_h2_student",
        student,
        kucoin_dataset,
        SPLITS["external_reused_kucoin"],
        kucoin_funding_series,
        "kucoin_futures",
        "diagnostic_reuse",
    )

    output.mkdir(parents=True, exist_ok=True)
    model_artifacts = _save_model(student, output / "model")
    prediction_path = output / "predictions.npz"
    numpy.savez_compressed(
        prediction_path,
        locked_timestamps=locked_predictions["timestamps"],
        locked_labels=locked_predictions["labels"],
        locked_long_probabilities=locked_predictions["long_probabilities"],
        locked_short_probabilities=locked_predictions["short_probabilities"],
        locked_predicted_labels=locked_predictions["predicted_labels"],
        external_timestamps=external_predictions["timestamps"],
        external_labels=external_predictions["labels"],
        external_long_probabilities=external_predictions[
            "long_probabilities"
        ],
        external_short_probabilities=external_predictions[
            "short_probabilities"
        ],
        external_predicted_labels=external_predictions["predicted_labels"],
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": _json_hash(protocol),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "future_used_for_features": False,
        "future_used_for_labels_and_evaluation": True,
        "feature_count": len(student_feature_names()),
        "fit": fit_diagnostics,
        "selected_threshold": threshold,
        "threshold_selection": threshold_table,
        "selection_diagnostic_gate": selection_diagnostic_gate,
        "locked_test": locked_report,
        "external_reused_test": external_report,
        "artifacts": {
            "protocol": _artifact(protocol_path),
            "models": model_artifacts,
            "predictions": _artifact(prediction_path),
            "inputs": {
                "binance_collector": _artifact(binance_path),
                "binance_funding": _artifact(binance_funding_path),
                "kucoin_collector": _artifact(kucoin_path),
                "kucoin_funding": _artifact(kucoin_funding_path),
            },
        },
        "conclusion_policy": (
            "This first student is exploratory. No result can promote it to "
            "paper trading because all currently available final periods have "
            "already been inspected by prior research."
        ),
    }
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trades_path = output / "trades.json"
    trades_path.write_text(
        json.dumps(
            {
                "locked_test": locked_trades,
                "external_reused_test": external_trades,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        **report,
        "report_path": str(report_path),
        "trades_path": str(trades_path),
    }


def _prediction_labels(
    long_probabilities: numpy.ndarray,
    short_probabilities: numpy.ndarray,
    threshold: float,
) -> numpy.ndarray:
    labels = numpy.zeros(len(long_probabilities), dtype=numpy.int8)
    margin = numpy.abs(long_probabilities - short_probabilities)
    eligible = (
        numpy.maximum(long_probabilities, short_probabilities) >= threshold
    ) & (margin >= MINIMUM_DIRECTION_MARGIN)
    labels[eligible & (long_probabilities > short_probabilities)] = LONG
    labels[eligible & (short_probabilities > long_probabilities)] = SHORT
    return labels


def _classification_metrics(
    observed: numpy.ndarray, predicted: numpy.ndarray
) -> dict:
    labels = (SHORT, WAIT, LONG)
    matrix = {
        str(actual): {
            str(value): int(numpy.sum((observed == actual) & (predicted == value)))
            for value in labels
        }
        for actual in labels
    }
    directional = predicted != WAIT
    correct_direction = directional & (predicted == observed)
    class_counts = [int(numpy.sum(observed == value)) for value in labels]
    return {
        "accuracy_pct": float(numpy.mean(predicted == observed) * 100),
        "majority_class_baseline_accuracy_pct": (
            max(class_counts) * 100 / len(observed)
        ),
        "directional_signal_rate_pct": float(numpy.mean(directional) * 100),
        "directional_precision_pct": (
            float(numpy.sum(correct_direction) * 100 / numpy.sum(directional))
            if numpy.any(directional)
            else 0.0
        ),
        "confusion_matrix_actual_then_predicted": matrix,
    }


def _save_model(model: StudentModel, directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    long_path = directory / "long_model.npz"
    short_path = directory / "short_model.npz"
    long = model.long_model.save(long_path)
    short = model.short_model.save(short_path)
    long_calibrator_path = directory / "long_calibrator.json"
    short_calibrator_path = directory / "short_calibrator.json"
    model.long_calibrator.save(long_calibrator_path)
    model.short_calibrator.save(short_calibrator_path)
    metadata_path = directory / "model.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "research_only": True,
                "orders_authorized": False,
                "feature_names": list(student_feature_names()),
                "threshold": model.threshold,
                "minimum_direction_margin": MINIMUM_DIRECTION_MARGIN,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "long_model": long,
        "short_model": short,
        "long_calibrator": _artifact(long_calibrator_path),
        "short_calibrator": _artifact(short_calibrator_path),
        "metadata": _artifact(metadata_path),
    }


def _class_distribution(labels: numpy.ndarray) -> dict:
    return {
        "WAIT": int(numpy.sum(labels == WAIT)),
        "LONG": int(numpy.sum(labels == LONG)),
        "SHORT": int(numpy.sum(labels == SHORT)),
    }


def _date_mask(
    timestamps: numpy.ndarray, start: str, end: str
) -> numpy.ndarray:
    start_timestamp = _date_timestamp(datetime.date.fromisoformat(start))
    end_timestamp = _date_timestamp(
        datetime.date.fromisoformat(end) + datetime.timedelta(days=1)
    )
    return (timestamps >= start_timestamp) & (timestamps < end_timestamp)


def _btc_funding(
    path: pathlib.Path,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    values = funding_module.load_funding(path)
    matching = [
        series for symbol, series in values.items() if symbol.startswith("BTC/")
    ]
    if len(matching) != 1:
        raise ValueError(f"expected one BTC funding series in {path}")
    return matching[0]


def _rolling_reduce(
    values: numpy.ndarray,
    window: int,
    reducer: typing.Callable[..., numpy.ndarray],
) -> numpy.ndarray:
    result = numpy.full(len(values), numpy.nan, dtype=float)
    if len(values) >= window:
        windows = numpy.lib.stride_tricks.as_strided(
            values,
            shape=(len(values) - window + 1, window),
            strides=(values.strides[0], values.strides[0]),
            writeable=False,
        )
        result[window - 1 :] = reducer(windows, axis=1)
    return result


def _rolling_mean_std(
    values: numpy.ndarray, window: int
) -> tuple[numpy.ndarray, numpy.ndarray]:
    finite = numpy.isfinite(values)
    clean = numpy.where(finite, values, 0.0)
    sums = numpy.concatenate(([0.0], numpy.cumsum(clean, dtype=float)))
    squares = numpy.concatenate(
        ([0.0], numpy.cumsum(clean * clean, dtype=float))
    )
    counts = numpy.concatenate(
        ([0], numpy.cumsum(finite.astype(numpy.int64)))
    )
    means = numpy.full(len(values), numpy.nan, dtype=float)
    standard_deviations = numpy.full(len(values), numpy.nan, dtype=float)
    if len(values) < window:
        return means, standard_deviations
    window_sums = sums[window:] - sums[:-window]
    window_squares = squares[window:] - squares[:-window]
    window_counts = counts[window:] - counts[:-window]
    valid = window_counts == window
    local_means = numpy.full(len(window_sums), numpy.nan, dtype=float)
    local_deviations = numpy.full(len(window_sums), numpy.nan, dtype=float)
    local_means[valid] = window_sums[valid] / window
    variance = numpy.maximum(
        window_squares[valid] / window - local_means[valid] ** 2,
        0.0,
    )
    local_deviations[valid] = numpy.sqrt(variance)
    means[window - 1 :] = local_means
    standard_deviations[window - 1 :] = local_deviations
    return means, standard_deviations


def _ratio_to_lag(values: numpy.ndarray, lag: int) -> numpy.ndarray:
    result = numpy.full(len(values), numpy.nan, dtype=float)
    if lag < len(values):
        result[lag:] = values[lag:] / values[:-lag] - 1
    return result


def _lag_difference(values: numpy.ndarray, lag: int) -> numpy.ndarray:
    result = numpy.full(len(values), numpy.nan, dtype=float)
    result[lag:] = values[lag:] - values[:-lag]
    return result


def _lag(values: numpy.ndarray, lag: int) -> numpy.ndarray:
    if lag == 0:
        return values.copy()
    result = numpy.full(len(values), numpy.nan, dtype=float)
    result[lag:] = values[:-lag]
    return result


def _date_timestamp(value: datetime.date) -> int:
    return int(
        datetime.datetime.combine(
            value, datetime.time.min, datetime.timezone.utc
        ).timestamp()
    )


def _timestamp_iso(value: int) -> str:
    return datetime.datetime.fromtimestamp(
        value, datetime.timezone.utc
    ).isoformat()


def _json_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: pathlib.Path) -> dict:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--write-protocol-only", action="store_true")
    parser.add_argument("--binance-collector")
    parser.add_argument("--binance-funding")
    parser.add_argument("--kucoin-collector")
    parser.add_argument("--kucoin-funding")
    args = parser.parse_args(argv)
    protocol_path = write_protocol(args.output_directory)
    if args.write_protocol_only:
        print(json.dumps({"protocol_path": str(protocol_path)}, indent=2))
        return 0
    required = (
        args.binance_collector,
        args.binance_funding,
        args.kucoin_collector,
        args.kucoin_funding,
    )
    if any(value is None for value in required):
        parser.error("all collector and funding arguments are required")
    report = run_study(
        binance_collector=args.binance_collector,
        binance_funding=args.binance_funding,
        kucoin_collector=args.kucoin_collector,
        kucoin_funding=args.kucoin_funding,
        output_directory=args.output_directory,
    )
    print(
        json.dumps(
            {
                "report_path": report["report_path"],
                "selected_threshold": report["selected_threshold"],
                "locked_test": report["locked_test"]["economic"],
                "external_reused_test": report["external_reused_test"][
                    "economic"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
