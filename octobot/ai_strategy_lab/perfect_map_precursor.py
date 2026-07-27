"""Pre-registered causal search for late perfect-map LONG precursors.

The target is deliberately narrower than a generic profitable trade: from the
decision close, +1.2% must be touched before -1.0%, and its first touch must
occur 18 through 22 closed 15-minute candles later. Future candles construct
labels and evaluation only. This offline module cannot authorize orders.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import h2_backtest
from octobot.ai_strategy_lab import indicators
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import percentage_probability_engine as probability_module
from octobot.ai_strategy_lab import perfect_map_student as v1


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_late_long_precursor_v1"
PREREGISTRATION_DATE = "2026-07-27"
CANDLE_SECONDS = 900
MINIMUM_TARGET_OFFSET = 18
MAXIMUM_TARGET_OFFSET = 22
ECONOMIC_HORIZON_BARS = 96
ACTIVATION_PCT = 1.2
INITIAL_STOP_PCT = 1.0
PROTECTED_STOP_PCT = 1.0
ROUND_TRIP_COST_PCT = 0.16
TRAINING_NEGATIVE_RATIO = 4
TRAINING_STRIDE = 2
TRAINING_SEED = 20_260_727
SCORE_QUANTILES = (0.90, 0.95, 0.975, 0.99, 0.995)
MINIMUM_SELECTION_TRADES = 30
MINIMUM_SELECTION_PROFIT_FACTOR = 1.20
MINIMUM_SELECTION_PRECISION_LIFT = 1.25
MODEL_CONFIG = model_module.LogisticConfig(
    epochs=30,
    batch_size=4096,
    learning_rate=0.012,
    l2=0.003,
    seed=TRAINING_SEED,
)
SPLITS = {
    "train": ("2022-05-01", "2024-12-30"),
    "calibration": ("2025-01-02", "2025-03-30"),
    "threshold_selection": ("2025-04-02", "2025-06-29"),
    "binance_reused_2025_h2": ("2025-07-02", "2025-12-30"),
    "binance_reused_2026_h1": ("2026-01-02", "2026-06-29"),
    "kucoin_reused_2026": ("2026-01-02", "2026-07-20"),
}
EXPLICIT_FEATURE_NAMES = (
    "volume_log_change_1",
    "volume_log_acceleration",
    "volume_zscore_change_1",
    "volume_zscore_acceleration",
    "return_1_acceleration",
    "return_4_acceleration",
    "ema_slope_acceleration",
    "macd_hist_change_1",
    "atr_compression_8",
    "atr_compression_32",
    "bb_width_compression_8",
    "bb_width_compression_32",
    "range_compression_8",
    "range_compression_32",
)
HIGHER_TIME_FRAMES = {"1h": 3600, "4h": 14_400}


@dataclasses.dataclass(frozen=True)
class PrecursorDataset:
    features: numpy.ndarray
    labels: numpy.ndarray
    target_offsets: numpy.ndarray
    timestamps: numpy.ndarray
    candle_indices: numpy.ndarray
    candles: numpy.ndarray

    def take(self, mask: numpy.ndarray) -> "PrecursorDataset":
        return PrecursorDataset(
            features=self.features[mask],
            labels=self.labels[mask],
            target_offsets=self.target_offsets[mask],
            timestamps=self.timestamps[mask],
            candle_indices=self.candle_indices[mask],
            candles=self.candles,
        )


@dataclasses.dataclass(frozen=True)
class PrecursorModel:
    base_model: model_module.NumpyLogisticModel
    calibrator: probability_module.QuantileIsotonicCalibrator
    raw_score_threshold: float
    threshold_quantile: float

    def predict(
        self, features: numpy.ndarray
    ) -> tuple[numpy.ndarray, numpy.ndarray]:
        raw_scores = self.base_model.predict_proba(features)
        return raw_scores, self.calibrator.predict(raw_scores)


def protocol_sha256(payload: dict) -> str:
    return v1._json_hash(payload)


def frozen_protocol() -> dict:
    """Return the result-free protocol frozen before the first study run."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "preregistered_design_only",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "scope": {
            "symbol": "BTC perpetual",
            "direction": "LONG_only",
            "time_frame": "15m",
            "book_used_for_fit": False,
            "book_reason": (
                "Level-5 collection is younger than the pre-existing "
                "30-day minimum evidence window"
            ),
        },
        "target": {
            "positive": (
                "+1.2% first touch before -1.0%, with the first +1.2% "
                "touch at offset 18 through 22 inclusive"
            ),
            "offset_unit": "closed_15m_candles_after_decision_close",
            "minimum_offset": MINIMUM_TARGET_OFFSET,
            "maximum_offset": MAXIMUM_TARGET_OFFSET,
            "same_candle_policy": "stop_wins",
            "early_target_touch": "negative",
            "future_used_for_labels_only": True,
        },
        "features": {
            "causal_at_decision_close": True,
            "base_schema": "perfect_map_student_v1_99_features",
            "explicit_families": [
                "volume_change_and_acceleration",
                "price_and_indicator_acceleration",
                "ATR_compression",
                "Bollinger_width_compression",
                "candle_range_compression",
            ],
            "higher_time_frames": {
                "1h": "last_fully_closed_candle_only",
                "4h": "last_fully_closed_candle_only",
            },
            "feature_count": len(precursor_feature_names()),
        },
        "model": {
            "type": "numpy_logistic_binary_classifier",
            "config": dataclasses.asdict(MODEL_CONFIG),
            "training_stride": TRAINING_STRIDE,
            "negative_to_positive_training_ratio": TRAINING_NEGATIVE_RATIO,
            "negative_sampling_seed": TRAINING_SEED,
            "calibration": "quantile_isotonic_on_calibration_only",
        },
        "threshold_selection": {
            "candidate_raw_score_quantiles_from_calibration": list(
                SCORE_QUANTILES
            ),
            "selection_split_only": True,
            "minimum_closed_trades": MINIMUM_SELECTION_TRADES,
            "minimum_profit_factor": MINIMUM_SELECTION_PROFIT_FACTOR,
            "minimum_precision_lift_over_base": (
                MINIMUM_SELECTION_PRECISION_LIFT
            ),
            "positive_compounded_return": True,
            "positive_return_minus_drawdown_objective": True,
            "objective": (
                "compounded_net_return_pct minus maximum_drawdown_pct"
            ),
        },
        "economic_simulation": {
            "entry": "decision candle close",
            "one_trade_at_a_time": True,
            "activation_pct": ACTIVATION_PCT,
            "initial_stop_pct": INITIAL_STOP_PCT,
            "protected_stop_pct": PROTECTED_STOP_PCT,
            "protected_stop_active_from_next_candle": True,
            "maximum_holding_hours": 24,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "funding_included": True,
        },
        "splits": SPLITS,
        "embargo": {
            "minimum_between_development_splits_hours": 48,
            "label_horizon_hours": MAXIMUM_TARGET_OFFSET / 4,
            "economic_horizon_hours": 24,
        },
        "evidence_policy": {
            "all_available_evaluation_blocks_are_reused_diagnostic_data": True,
            "no_result_can_promote_to_paper": True,
            "new_forward_start_required_after": "2026-07-27",
            "minimum_new_forward_days": 30,
            "minimum_new_forward_closed_trades": 30,
            "no_mid_test_retuning": True,
        },
        "implementation_policy": {
            "protocol_must_exist_before_training": True,
            "persist_protocol_and_input_hashes": True,
            "persist_model_predictions_and_report": True,
            "reloaded_predictions_must_match_exactly": True,
            "results_in_this_protocol": False,
        },
    }


def write_protocol(
    output_value: typing.Union[str, pathlib.Path]
) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    path = output / "protocol.json"
    path.write_text(
        json.dumps(
            {**protocol, "protocol_sha256": protocol_sha256(protocol)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def precursor_feature_names() -> tuple[str, ...]:
    names = list(v1.student_feature_names())
    names.extend(EXPLICIT_FEATURE_NAMES)
    for time_frame in HIGHER_TIME_FRAMES:
        names.extend(
            f"{time_frame}_{name}"
            for name in probability_module.FEATURE_NAMES
        )
    return tuple(names)


def causal_features(
    candles: numpy.ndarray,
) -> tuple[numpy.ndarray, tuple[str, ...]]:
    """Build features using the decision candle and earlier closed candles."""

    base, base_names = v1.sequence_features(candles)
    if base_names != v1.student_feature_names():
        raise ValueError("unexpected base feature schema")
    arrays = indicators.compute_feature_arrays(candles)
    volume = numpy.maximum(
        candles[:, 5].astype(float), numpy.finfo(float).tiny
    )
    volume_change = v1._lag_difference(numpy.log(volume), 1)
    volume_zscore_change = v1._lag_difference(
        arrays["volume_zscore"], 1
    )
    candle_range = (
        candles[:, 2].astype(float) - candles[:, 3].astype(float)
    ) / numpy.maximum(candles[:, 4].astype(float), numpy.finfo(float).tiny)
    explicit = numpy.column_stack(
        (
            volume_change,
            v1._lag_difference(volume_change, 1),
            volume_zscore_change,
            v1._lag_difference(volume_zscore_change, 1),
            v1._lag_difference(arrays["return_1"], 1),
            v1._lag_difference(arrays["return_4"], 1),
            v1._lag_difference(arrays["ema_slope_pct"], 1),
            v1._lag_difference(arrays["macd_hist_pct"], 1),
            _compression(arrays["atr_pct"], 8),
            _compression(arrays["atr_pct"], 32),
            _compression(arrays["bb_width_pct"], 8),
            _compression(arrays["bb_width_pct"], 32),
            _compression(candle_range, 8),
            _compression(candle_range, 32),
        )
    )
    higher_columns = []
    for candle_seconds in HIGHER_TIME_FRAMES.values():
        higher_columns.extend(
            _completed_higher_time_frame_features(candles, candle_seconds)
        )
    values = numpy.column_stack((base, explicit, *higher_columns))
    names = precursor_feature_names()
    if values.shape[1] != len(names):
        raise ValueError("precursor feature schema is misaligned")
    return values, names


def _compression(values: numpy.ndarray, window: int) -> numpy.ndarray:
    mean, _ = v1._rolling_mean_std(values, window)
    return numpy.divide(
        values,
        mean,
        out=numpy.full(len(values), numpy.nan),
        where=mean != 0,
    ) - 1


def _completed_higher_time_frame_features(
    candles: numpy.ndarray, candle_seconds: int
) -> list[numpy.ndarray]:
    higher = _aggregate_complete_candles(candles, candle_seconds)
    empty = [
        numpy.full(len(candles), numpy.nan, dtype=float)
        for _ in probability_module.FEATURE_NAMES
    ]
    if not len(higher):
        return empty
    arrays = indicators.compute_feature_arrays(higher)
    base_close_times = candles[:, 0].astype(numpy.int64) + CANDLE_SECONDS
    higher_close_times = higher[:, 0].astype(numpy.int64) + candle_seconds
    indices = numpy.searchsorted(
        higher_close_times, base_close_times, side="right"
    ) - 1
    available = indices >= 0
    result = []
    for name in probability_module.FEATURE_NAMES:
        column = numpy.full(len(candles), numpy.nan, dtype=float)
        column[available] = arrays[name][indices[available]]
        result.append(column)
    return result


def _aggregate_complete_candles(
    candles: numpy.ndarray, candle_seconds: int
) -> numpy.ndarray:
    rows_per_candle = candle_seconds // CANDLE_SECONDS
    if candle_seconds % CANDLE_SECONDS or rows_per_candle < 2:
        raise ValueError("higher timeframe must be a multiple of 15m")
    result = []
    for start in range(0, len(candles)):
        timestamp = int(candles[start, 0])
        if timestamp % candle_seconds:
            continue
        end = start + rows_per_candle
        if end > len(candles):
            break
        rows = candles[start:end]
        expected = timestamp + numpy.arange(rows_per_candle) * CANDLE_SECONDS
        if not numpy.array_equal(rows[:, 0].astype(numpy.int64), expected):
            continue
        result.append(
            [
                timestamp,
                float(rows[0, 1]),
                float(numpy.max(rows[:, 2])),
                float(numpy.min(rows[:, 3])),
                float(rows[-1, 4]),
                float(numpy.sum(rows[:, 5])),
            ]
        )
    if not result:
        return numpy.empty((0, 6), dtype=float)
    return numpy.asarray(result, dtype=float)


def late_long_labels(
    candles: numpy.ndarray,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return binary labels and first target offsets with stop-first semantics."""

    close = candles[:, 4].astype(float)
    high = candles[:, 2].astype(float)
    low = candles[:, 3].astype(float)
    stop = close * (1 - INITIAL_STOP_PCT / 100)
    target = close * (1 + ACTIVATION_PCT / 100)
    resolved = numpy.zeros(len(candles), dtype=bool)
    labels = numpy.zeros(len(candles), dtype=numpy.int8)
    offsets = numpy.full(len(candles), -1, dtype=numpy.int16)
    for offset in range(1, MAXIMUM_TARGET_OFFSET + 1):
        limit = len(candles) - offset
        if limit <= 0:
            break
        available = ~resolved[:limit]
        stop_touch = low[offset:] <= stop[:limit]
        target_touch = high[offset:] >= target[:limit]
        target_first = available & target_touch & ~stop_touch
        offsets[:limit][target_first] = offset
        in_window = (
            MINIMUM_TARGET_OFFSET <= offset <= MAXIMUM_TARGET_OFFSET
        )
        if in_window:
            labels[:limit][target_first] = 1
        resolved[:limit][target_first | (available & stop_touch)] = True
    return labels, offsets


def build_dataset(candles: numpy.ndarray) -> PrecursorDataset:
    if candles.ndim != 2 or candles.shape[1] < 6:
        raise ValueError("candles must be an OHLCV matrix")
    gaps = numpy.flatnonzero(
        numpy.diff(candles[:, 0].astype(numpy.int64)) != CANDLE_SECONDS
    )
    starts = numpy.concatenate((numpy.asarray([0]), gaps + 1))
    ends = numpy.concatenate((gaps + 1, numpy.asarray([len(candles)])))
    blocks = []
    for start, end in zip(starts, ends):
        if int(end) - int(start) <= ECONOMIC_HORIZON_BARS + 300:
            continue
        block = candles[int(start) : int(end)]
        values, names = causal_features(block)
        if names != precursor_feature_names():
            raise ValueError("precursor feature schema is not deterministic")
        labels, offsets = late_long_labels(block)
        indices = numpy.arange(
            len(block) - ECONOMIC_HORIZON_BARS, dtype=numpy.int64
        )
        finite = numpy.all(numpy.isfinite(values[indices]), axis=1)
        indices = indices[finite]
        if len(indices):
            blocks.append(
                PrecursorDataset(
                    features=values[indices].astype(numpy.float32),
                    labels=labels[indices],
                    target_offsets=offsets[indices],
                    timestamps=(
                        block[indices, 0].astype(numpy.int64)
                        + CANDLE_SECONDS
                    ),
                    candle_indices=indices + int(start),
                    candles=candles,
                )
            )
    if not blocks:
        raise ValueError("no complete precursor examples")
    return PrecursorDataset(
        features=numpy.concatenate([block.features for block in blocks]),
        labels=numpy.concatenate([block.labels for block in blocks]),
        target_offsets=numpy.concatenate(
            [block.target_offsets for block in blocks]
        ),
        timestamps=numpy.concatenate(
            [block.timestamps for block in blocks]
        ),
        candle_indices=numpy.concatenate(
            [block.candle_indices for block in blocks]
        ),
        candles=candles,
    )


def fit_model(
    dataset: PrecursorDataset,
) -> tuple[PrecursorModel, dict]:
    train_mask = v1._date_mask(dataset.timestamps, *SPLITS["train"])
    train_rows = numpy.flatnonzero(train_mask)[::TRAINING_STRIDE]
    positives = train_rows[dataset.labels[train_rows] == 1]
    negatives = train_rows[dataset.labels[train_rows] == 0]
    if len(positives) < 500:
        raise ValueError("insufficient positive training examples")
    random = numpy.random.RandomState(TRAINING_SEED)
    negative_count = min(
        len(negatives), len(positives) * TRAINING_NEGATIVE_RATIO
    )
    sampled_negatives = random.choice(
        negatives, size=negative_count, replace=False
    )
    fitted_rows = numpy.sort(
        numpy.concatenate((positives, sampled_negatives))
    )
    base_model = model_module.NumpyLogisticModel.fit(
        dataset.features[fitted_rows],
        dataset.labels[fitted_rows],
        precursor_feature_names(),
        MODEL_CONFIG,
    )
    calibration_mask = v1._date_mask(
        dataset.timestamps, *SPLITS["calibration"]
    )
    calibration_rows = numpy.flatnonzero(calibration_mask)
    calibration_scores = base_model.predict_proba(
        dataset.features[calibration_rows]
    )
    calibrator = probability_module.QuantileIsotonicCalibrator.fit(
        calibration_scores,
        dataset.labels[calibration_rows],
        minimum_rows_per_bin=100,
    )
    thresholds = {
        quantile: float(numpy.quantile(calibration_scores, quantile))
        for quantile in SCORE_QUANTILES
    }
    model = PrecursorModel(
        base_model=base_model,
        calibrator=calibrator,
        raw_score_threshold=thresholds[SCORE_QUANTILES[0]],
        threshold_quantile=SCORE_QUANTILES[0],
    )
    diagnostics = {
        "natural_train_rows": int(numpy.sum(train_mask)),
        "natural_train_positive_rate_pct": float(
            numpy.mean(dataset.labels[train_mask]) * 100
        ),
        "fitted_rows": len(fitted_rows),
        "fitted_positive_rows": len(positives),
        "fitted_negative_rows": len(sampled_negatives),
        "calibration_rows": len(calibration_rows),
        "calibration_positive_rate_pct": float(
            numpy.mean(dataset.labels[calibration_rows]) * 100
        ),
        "candidate_thresholds": {
            str(quantile): thresholds[quantile]
            for quantile in SCORE_QUANTILES
        },
    }
    return model, diagnostics


def select_threshold(
    model: PrecursorModel,
    dataset: PrecursorDataset,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    thresholds: dict[float, float],
) -> tuple[PrecursorModel, list[dict], dict]:
    mask = v1._date_mask(
        dataset.timestamps, *SPLITS["threshold_selection"]
    )
    subset = dataset.take(mask)
    raw_scores, probabilities = model.predict(subset.features)
    values = []
    for quantile in SCORE_QUANTILES:
        threshold = thresholds[quantile]
        trades = simulate_predictions(
            subset, raw_scores, probabilities, threshold, funding_series
        )
        metrics = h2_backtest._metrics(trades, ROUND_TRIP_COST_PCT)
        classification = _classification_metrics(
            subset.labels, raw_scores, probabilities, threshold
        )
        objective = (
            metrics["compounded_net_return_pct"]
            - metrics["maximum_drawdown_pct"]
        )
        eligible = (
            metrics["trades"] >= MINIMUM_SELECTION_TRADES
            and metrics["profit_factor"] is not None
            and metrics["profit_factor"] >= MINIMUM_SELECTION_PROFIT_FACTOR
            and metrics["compounded_net_return_pct"] > 0
            and objective > 0
            and classification["precision_lift_over_base"]
            >= MINIMUM_SELECTION_PRECISION_LIFT
        )
        values.append(
            {
                "calibration_score_quantile": quantile,
                "raw_score_threshold": threshold,
                "eligible": eligible,
                "objective": objective,
                "classification": classification,
                "economic": metrics,
            }
        )
    eligible = [value for value in values if value["eligible"]]
    selected = max(
        eligible or values,
        key=lambda value: (
            value["objective"],
            value["classification"]["precision_lift_over_base"],
            value["economic"]["trades"],
        ),
    )
    selected_model = dataclasses.replace(
        model,
        raw_score_threshold=float(selected["raw_score_threshold"]),
        threshold_quantile=float(selected["calibration_score_quantile"]),
    )
    gate = {
        "preregistered": True,
        "passed": bool(selected["eligible"]),
        "selected_quantile": selected["calibration_score_quantile"],
        "selected_raw_score_threshold": selected["raw_score_threshold"],
        "criteria": frozen_protocol()["threshold_selection"],
    }
    return selected_model, values, gate


def simulate_predictions(
    dataset: PrecursorDataset,
    raw_scores: numpy.ndarray,
    probabilities: numpy.ndarray,
    threshold: float,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> list[dict]:
    if not (
        len(dataset.labels) == len(raw_scores) == len(probabilities)
    ):
        raise ValueError("prediction arrays are misaligned")
    trade_config = percentage_engine.PercentageEngineConfig(
        minimum_profit_pct=PROTECTED_STOP_PCT,
        activation_pct=ACTIVATION_PCT,
        initial_stop_pct=INITIAL_STOP_PCT,
        horizon_candles=ECONOMIC_HORIZON_BARS,
        directions=(percentage_engine.LONG,),
        exclude_last_candle=False,
    )
    close_times = (
        dataset.candles[:, 0].astype(numpy.int64) + CANDLE_SECONDS
    ).tolist()
    funding_timestamps, funding_rates = funding_series
    next_available = 0
    trades = []
    for row in numpy.flatnonzero(raw_scores >= threshold):
        entry_index = int(dataset.candle_indices[row])
        if entry_index < next_available:
            continue
        trade = percentage_engine.simulate_trade(
            close_times,
            dataset.candles[:, 2],
            dataset.candles[:, 3],
            dataset.candles[:, 4],
            entry_index,
            percentage_engine.LONG,
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
        funding_cost_pct = float(
            numpy.sum(funding_rates[first:last])
        ) * 100
        trades.append(
            {
                "direction": percentage_engine.LONG,
                "exchange": "dataset",
                "entry_time_utc": v1._timestamp_iso(entry_timestamp),
                "entry_timestamp": entry_timestamp,
                "exit_time_utc": v1._timestamp_iso(exit_timestamp),
                "exit_timestamp": exit_timestamp,
                "entry_price": float(trade["entry_price"]),
                "exit_price": float(trade["exit_price"]),
                "exit_reason": trade["exit_reason"],
                "duration_hours": (
                    exit_timestamp - entry_timestamp
                )
                / 3600,
                "gross_return_pct": float(trade["gross_return_pct"]),
                "funding_cost_pct": funding_cost_pct,
                "raw_score": float(raw_scores[row]),
                "probability_pct": float(probabilities[row] * 100),
                "observed_precursor_target": bool(dataset.labels[row]),
                "observed_target_offset": int(dataset.target_offsets[row]),
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


def _classification_metrics(
    labels: numpy.ndarray,
    raw_scores: numpy.ndarray,
    probabilities: numpy.ndarray,
    threshold: float,
) -> dict:
    selected = raw_scores >= threshold
    base = float(numpy.mean(labels)) if len(labels) else 0.0
    precision = float(numpy.mean(labels[selected])) if numpy.any(selected) else 0.0
    positives = int(numpy.sum(labels))
    true_positives = int(numpy.sum(labels[selected]))
    return {
        "examples": len(labels),
        "positive_examples": positives,
        "base_rate_pct": base * 100,
        "selected_examples": int(numpy.sum(selected)),
        "selected_rate_pct": float(numpy.mean(selected) * 100),
        "precision_pct": precision * 100,
        "precision_lift_over_base": precision / base if base else 0.0,
        "recall_pct": true_positives * 100 / positives if positives else 0.0,
        "brier_score": float(numpy.mean((probabilities - labels) ** 2)),
        "roc_auc": _roc_auc(labels, raw_scores),
        "average_precision": _average_precision(labels, raw_scores),
    }


def _roc_auc(labels: numpy.ndarray, scores: numpy.ndarray) -> float:
    positives = int(numpy.sum(labels == 1))
    negatives = int(numpy.sum(labels == 0))
    if not positives or not negatives:
        return 0.0
    order = numpy.argsort(scores, kind="stable")
    ordered = scores[order]
    ranks = numpy.arange(1, len(scores) + 1, dtype=float)
    starts = numpy.concatenate(
        ([0], numpy.flatnonzero(numpy.diff(ordered) != 0) + 1)
    )
    ends = numpy.concatenate((starts[1:], [len(scores)]))
    for start, end in zip(starts, ends):
        ranks[start:end] = numpy.mean(ranks[start:end])
    positive_rank_sum = float(numpy.sum(ranks[labels[order] == 1]))
    return (
        positive_rank_sum - positives * (positives + 1) / 2
    ) / (positives * negatives)


def _average_precision(labels: numpy.ndarray, scores: numpy.ndarray) -> float:
    positives = int(numpy.sum(labels == 1))
    if not positives:
        return 0.0
    order = numpy.argsort(-scores, kind="stable")
    ordered_labels = labels[order]
    cumulative = numpy.cumsum(ordered_labels)
    precision = cumulative / numpy.arange(1, len(labels) + 1)
    return float(numpy.sum(precision * ordered_labels) / positives)


def evaluate_block(
    name: str,
    exchange: str,
    evidence_role: str,
    model: PrecursorModel,
    dataset: PrecursorDataset,
    date_range: tuple[str, str],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> tuple[dict, list[dict], dict]:
    subset = dataset.take(
        v1._date_mask(dataset.timestamps, *date_range)
    )
    raw_scores, probabilities = model.predict(subset.features)
    trades = simulate_predictions(
        subset,
        raw_scores,
        probabilities,
        model.raw_score_threshold,
        funding_series,
    )
    for trade in trades:
        trade["exchange"] = exchange
    return (
        {
            "name": name,
            "exchange": exchange,
            "evidence_role": evidence_role,
            "start": date_range[0],
            "end": date_range[1],
            "classification": _classification_metrics(
                subset.labels,
                raw_scores,
                probabilities,
                model.raw_score_threshold,
            ),
            "economic": h2_backtest._metrics(
                trades, ROUND_TRIP_COST_PCT
            ),
        },
        trades,
        {
            "timestamps": subset.timestamps,
            "labels": subset.labels,
            "target_offsets": subset.target_offsets,
            "raw_scores": raw_scores,
            "probabilities": probabilities,
        },
    )


def feature_relationships(
    model: PrecursorModel,
    dataset: PrecursorDataset,
) -> list[dict]:
    mask = v1._date_mask(dataset.timestamps, *SPLITS["calibration"])
    features = dataset.features[mask]
    labels = dataset.labels[mask]
    relationships = []
    for index, name in enumerate(precursor_feature_names()):
        values = features[:, index].astype(float)
        low, high = numpy.quantile(values, (0.10, 0.90))
        low_rate = float(numpy.mean(labels[values <= low]) * 100)
        high_rate = float(numpy.mean(labels[values >= high]) * 100)
        relationships.append(
            {
                "feature": name,
                "standardized_coefficient": float(
                    model.base_model.weights[index]
                ),
                "absolute_standardized_coefficient": float(
                    abs(model.base_model.weights[index])
                ),
                "calibration_low_decile_event_rate_pct": low_rate,
                "calibration_high_decile_event_rate_pct": high_rate,
                "high_minus_low_event_rate_points": high_rate - low_rate,
            }
        )
    return sorted(
        relationships,
        key=lambda value: value["absolute_standardized_coefficient"],
        reverse=True,
    )


def _save_model(
    model: PrecursorModel, directory: pathlib.Path
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    base_path = directory / "base_model.npz"
    base = model.base_model.save(base_path)
    calibrator_path = directory / "calibrator.json"
    model.calibrator.save(calibrator_path)
    metadata_path = directory / "model.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "protocol_sha256": protocol_sha256(frozen_protocol()),
                "research_only": True,
                "orders_authorized": False,
                "feature_names": list(precursor_feature_names()),
                "raw_score_threshold": model.raw_score_threshold,
                "threshold_quantile": model.threshold_quantile,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "base_model": base,
        "calibrator": v1._artifact(calibrator_path),
        "metadata": v1._artifact(metadata_path),
    }


def load_model(
    directory_value: typing.Union[str, pathlib.Path]
) -> PrecursorModel:
    directory = pathlib.Path(directory_value).resolve()
    metadata = json.loads(
        (directory / "model.json").read_text(encoding="utf-8")
    )
    if metadata.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("unsupported precursor model protocol")
    if tuple(metadata.get("feature_names", [])) != precursor_feature_names():
        raise ValueError("precursor feature schema differs")
    return PrecursorModel(
        base_model=model_module.NumpyLogisticModel.load(
            directory / "base_model.npz"
        ),
        calibrator=probability_module.QuantileIsotonicCalibrator.load(
            directory / "calibrator.json"
        ),
        raw_score_threshold=float(metadata["raw_score_threshold"]),
        threshold_quantile=float(metadata["threshold_quantile"]),
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
    if persisted.get("protocol_sha256") != protocol_sha256(protocol):
        raise ValueError("persisted protocol differs from frozen precursor code")

    binance_path = pathlib.Path(binance_collector).resolve()
    binance_funding_path = pathlib.Path(binance_funding).resolve()
    kucoin_path = pathlib.Path(kucoin_collector).resolve()
    kucoin_funding_path = pathlib.Path(kucoin_funding).resolve()
    binance_candles = h2_backtest._load_btc_15m(
        binance_path, "15m"
    )
    kucoin_candles = h2_backtest._load_btc_15m(kucoin_path, "5m")
    binance_dataset = build_dataset(binance_candles)
    kucoin_dataset = build_dataset(kucoin_candles)
    binance_funding_series = v1._btc_funding(binance_funding_path)
    kucoin_funding_series = v1._btc_funding(kucoin_funding_path)

    unselected, fit_diagnostics = fit_model(binance_dataset)
    thresholds = {
        float(quantile): float(value)
        for quantile, value in (
            (float(key), value)
            for key, value in fit_diagnostics[
                "candidate_thresholds"
            ].items()
        )
    }
    model, threshold_table, selection_gate = select_threshold(
        unselected,
        binance_dataset,
        binance_funding_series,
        thresholds,
    )
    block_specs = (
        (
            "binance_reused_2025_h2",
            "binance_usdm",
            "diagnostic_reuse",
            binance_dataset,
            SPLITS["binance_reused_2025_h2"],
            binance_funding_series,
        ),
        (
            "binance_reused_2026_h1",
            "binance_usdm",
            "diagnostic_reuse",
            binance_dataset,
            SPLITS["binance_reused_2026_h1"],
            binance_funding_series,
        ),
        (
            "kucoin_reused_2026",
            "kucoin_futures",
            "external_diagnostic_reuse",
            kucoin_dataset,
            SPLITS["kucoin_reused_2026"],
            kucoin_funding_series,
        ),
    )
    reports = {}
    trades = {}
    predictions = {}
    for (
        name,
        exchange,
        evidence_role,
        block_dataset,
        dates,
        funding_series,
    ) in block_specs:
        block_report, block_trades, block_predictions = evaluate_block(
            name,
            exchange,
            evidence_role,
            model,
            block_dataset,
            dates,
            funding_series,
        )
        reports[name] = block_report
        trades[name] = block_trades
        predictions[name] = block_predictions

    output.mkdir(parents=True, exist_ok=True)
    model_artifacts = _save_model(model, output / "model")
    reloaded = load_model(output / "model")
    replay_rows = binance_dataset.features[: min(10_000, len(binance_dataset.features))]
    original_replay = model.predict(replay_rows)
    restored_replay = reloaded.predict(replay_rows)
    replay_difference = max(
        float(numpy.max(numpy.abs(original - restored)))
        for original, restored in zip(original_replay, restored_replay)
    )
    if replay_difference != 0:
        raise ValueError("reloaded precursor predictions differ")

    prediction_path = output / "predictions.npz"
    prediction_payload = {}
    for name, values in predictions.items():
        for key, value in values.items():
            prediction_payload[f"{name}_{key}"] = value
    numpy.savez_compressed(prediction_path, **prediction_payload)
    trades_path = output / "trades.json"
    trades_path.write_text(
        json.dumps(trades, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256(protocol),
        "created_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "future_used_for_features": False,
        "future_used_for_labels_and_evaluation": True,
        "feature_count": len(precursor_feature_names()),
        "fit": fit_diagnostics,
        "selected_threshold_quantile": model.threshold_quantile,
        "selected_raw_score_threshold": model.raw_score_threshold,
        "threshold_selection": threshold_table,
        "selection_gate": selection_gate,
        "diagnostic_blocks": reports,
        "top_feature_relationships": feature_relationships(
            model, binance_dataset
        )[:20],
        "model_replay_max_absolute_difference": replay_difference,
        "artifacts": {
            "protocol": v1._artifact(protocol_path),
            "models": model_artifacts,
            "predictions": v1._artifact(prediction_path),
            "trades": v1._artifact(trades_path),
            "inputs": {
                "binance_collector": v1._artifact(binance_path),
                "binance_funding": v1._artifact(binance_funding_path),
                "kucoin_collector": v1._artifact(kucoin_path),
                "kucoin_funding": v1._artifact(kucoin_funding_path),
            },
        },
        "conclusion_policy": (
            "All available evaluation dates were already seen by previous "
            "research. Even a passed diagnostic gate requires untouched "
            "forward evidence starting after 2026-07-27."
        ),
    }
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        **report,
        "report_path": str(report_path),
        "trades_path": str(trades_path),
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
                "selection_gate": report["selection_gate"],
                "diagnostic_blocks": {
                    name: {
                        "classification": value["classification"],
                        "economic": value["economic"],
                    }
                    for name, value in report["diagnostic_blocks"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
