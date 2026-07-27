"""Two-stage causal forecaster inspired by the percentage perfect map.

The forecaster separates three questions that the hindsight map answers all at
once: whether a sizeable move is about to start, its conditional direction,
and the reachable protected-profit/horizon path.  Future candles are used only
for labels and economic evaluation.  The module is offline research only and
cannot authorize orders.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import functools
import json
import os
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import h2_backtest
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import percentage_probability_engine as probability_module
from octobot.ai_strategy_lab import perfect_map_precursor as precursor
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_eth_expansion_direction_path_v2"
PREREGISTRATION_DATE = "2026-07-27"
ASSETS = ("BTC", "ETH")
CANDLE_SECONDS = 900
EXPANSION_PCT = 0.75
MINIMUM_EXPANSION_OFFSET = 3
MAXIMUM_EXPANSION_OFFSET = 24
ECONOMIC_HORIZON_BARS = 96
TRAINING_STRIDE = 2
TRAINING_SEED = 20_260_727
JOINT_PROBABILITY_QUANTILES = (0.80, 0.90, 0.95, 0.975, 0.99)
MINIMUM_DIRECTION_PROBABILITIES = (0.55, 0.60, 0.65)
MINIMUM_EXPECTED_NET_VALUES_PCT = (0.00, 0.025, 0.05)
MINIMUM_DIRECTION_MARGIN_PCT = 0.03
MINIMUM_SELECTION_TRADES = 20
ROUND_TRIP_COST_PCT = 0.16
VISUAL_WATCH_THRESHOLD_RATIO = 0.80
SIMULATED_PATH_HORIZONS = (("4h", 16), ("8h", 32))
SIMULATED_PATH_VOLATILITY_WINDOW = 96
SIMULATED_PATH_ACCURACY_WINDOW = 96
SIMULATED_PATH_MINIMUM_ACCURACY_SAMPLES = 24
SIMULATED_PATH_BAND_Z_SCORE = 1.2815515655446004
MODEL_CONFIG = model_module.LogisticConfig(
    epochs=32,
    batch_size=4096,
    learning_rate=0.010,
    l2=0.003,
    seed=TRAINING_SEED,
)
SPLITS = {
    "train": ("2022-05-01", "2024-12-30"),
    "calibration": ("2025-01-02", "2025-03-30"),
    "threshold_selection": ("2025-04-02", "2025-06-29"),
    "binance_reused_2025": ("2025-07-02", "2025-12-30"),
    "binance_reused_2026": ("2026-01-02", "2026-06-29"),
    "kucoin_reused_2026": ("2026-01-02", "2026-07-20"),
}


@dataclasses.dataclass(frozen=True)
class ForecastDataset:
    features: numpy.ndarray
    base_features: numpy.ndarray
    expansion_labels: numpy.ndarray
    direction_labels: numpy.ndarray
    touch_offsets: numpy.ndarray
    timestamps: numpy.ndarray
    candle_indices: numpy.ndarray
    candles: numpy.ndarray

    def take(self, mask: numpy.ndarray) -> "ForecastDataset":
        return ForecastDataset(
            features=self.features[mask],
            base_features=self.base_features[mask],
            expansion_labels=self.expansion_labels[mask],
            direction_labels=self.direction_labels[mask],
            touch_offsets=self.touch_offsets[mask],
            timestamps=self.timestamps[mask],
            candle_indices=self.candle_indices[mask],
            candles=self.candles,
        )


@dataclasses.dataclass(frozen=True)
class AssetForecaster:
    asset: str
    expansion_model: model_module.NumpyLogisticModel
    expansion_calibrator: probability_module.QuantileIsotonicCalibrator
    direction_model: model_module.NumpyLogisticModel
    direction_calibrator: probability_module.QuantileIsotonicCalibrator
    path_model: v5.V5Model
    joint_probability_threshold: float
    minimum_direction_probability: float
    minimum_expected_net_pct: float

    def predict(
        self,
        features: numpy.ndarray,
        base_features: numpy.ndarray,
    ) -> dict[str, numpy.ndarray]:
        expansion_probability = self.expansion_calibrator.predict(
            self.expansion_model.predict_proba(features)
        )
        long_given_expansion = self.direction_calibrator.predict(
            self.direction_model.predict_proba(features)
        )
        long_given_expansion = numpy.clip(
            long_given_expansion, 0.0, 1.0
        )
        direction_probability = numpy.column_stack(
            (long_given_expansion, 1.0 - long_given_expansion)
        )
        joint_probability = (
            expansion_probability[:, None] * direction_probability
        )
        return {
            "expansion_probability": expansion_probability,
            "direction_probability": direction_probability,
            "joint_probability": joint_probability,
            **self.path_model.predict(base_features),
        }

    def save(
        self, directory_value: typing.Union[str, pathlib.Path]
    ) -> dict:
        directory = pathlib.Path(directory_value).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "expansion_model": self.expansion_model.save(
                directory / "expansion_model.npz"
            ),
            "direction_model": self.direction_model.save(
                directory / "direction_model.npz"
            ),
        }
        expansion_calibrator_path = directory / "expansion_calibrator.json"
        direction_calibrator_path = directory / "direction_calibrator.json"
        self.expansion_calibrator.save(expansion_calibrator_path)
        self.direction_calibrator.save(direction_calibrator_path)
        artifacts["expansion_calibrator"] = v1._artifact(
            expansion_calibrator_path
        )
        artifacts["direction_calibrator"] = v1._artifact(
            direction_calibrator_path
        )
        artifacts["path_model"] = v5._save_model(
            self.path_model, directory / "path_model"
        )
        metadata_path = directory / "model.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_version": PROTOCOL_VERSION,
                    "asset": self.asset,
                    "research_only": True,
                    "orders_authorized": False,
                    "automatic_promotion": False,
                    "feature_names": list(precursor.precursor_feature_names()),
                    "base_feature_names": list(v1.student_feature_names()),
                    "joint_probability_threshold": (
                        self.joint_probability_threshold
                    ),
                    "minimum_direction_probability": (
                        self.minimum_direction_probability
                    ),
                    "minimum_expected_net_pct": (
                        self.minimum_expected_net_pct
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        artifacts["metadata"] = v1._artifact(metadata_path)
        return artifacts

    @classmethod
    def load(
        cls, directory_value: typing.Union[str, pathlib.Path]
    ) -> "AssetForecaster":
        directory = pathlib.Path(directory_value).resolve()
        metadata = json.loads(
            (directory / "model.json").read_text(encoding="utf-8")
        )
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported V2 forecaster schema")
        if metadata.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported V2 forecaster protocol")
        if tuple(metadata.get("feature_names", ())) != (
            precursor.precursor_feature_names()
        ):
            raise ValueError("V2 forecaster feature schema differs")
        if tuple(metadata.get("base_feature_names", ())) != (
            v1.student_feature_names()
        ):
            raise ValueError("V2 path feature schema differs")
        return cls(
            asset=str(metadata["asset"]),
            expansion_model=model_module.NumpyLogisticModel.load(
                directory / "expansion_model.npz"
            ),
            expansion_calibrator=(
                probability_module.QuantileIsotonicCalibrator.load(
                    directory / "expansion_calibrator.json"
                )
            ),
            direction_model=model_module.NumpyLogisticModel.load(
                directory / "direction_model.npz"
            ),
            direction_calibrator=(
                probability_module.QuantileIsotonicCalibrator.load(
                    directory / "direction_calibrator.json"
                )
            ),
            path_model=v5.V5Model.load(directory / "path_model"),
            joint_probability_threshold=float(
                metadata["joint_probability_threshold"]
            ),
            minimum_direction_probability=float(
                metadata["minimum_direction_probability"]
            ),
            minimum_expected_net_pct=float(
                metadata["minimum_expected_net_pct"]
            ),
        )


def protocol_sha256(payload: dict) -> str:
    return v1._json_hash(payload)


def frozen_protocol() -> dict:
    """Return the result-free design frozen before the first calculation."""

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
            "assets": list(ASSETS),
            "separate_model_per_asset": True,
            "time_frame": "15m",
            "audit_inputs": {
                "BTC": {
                    "binance": "native 15m",
                    "kucoin": "5m aggregated causally to 15m",
                },
                "ETH": {
                    "binance": "native 15m",
                    "kucoin": "native 15m public collector",
                },
            },
            "features": "causal OHLCV and completed 1h/4h only",
            "book_used": False,
            "book_reason": (
                "official Level-5 collection is younger than the frozen "
                "30-day minimum"
            ),
        },
        "stage_a_expansion": {
            "event": (
                "first touch of either +0.75% or -0.75% from decision close"
            ),
            "minimum_offset_candles": MINIMUM_EXPANSION_OFFSET,
            "maximum_offset_candles": MAXIMUM_EXPANSION_OFFSET,
            "offset_minutes": [
                MINIMUM_EXPANSION_OFFSET * 15,
                MAXIMUM_EXPANSION_OFFSET * 15,
            ],
            "touch_before_minimum_offset": "negative_too_late",
            "same_candle_both_directions": (
                "positive expansion but unresolved direction"
            ),
            "model": "calibrated numpy logistic binary classifier",
        },
        "stage_b_direction": {
            "population": "resolved Stage-A expansion examples only",
            "classes": ["LONG", "SHORT"],
            "output": "P(direction | expansion)",
            "model": "calibrated numpy logistic binary classifier",
        },
        "stage_c_path": {
            "model": "V5 mutually exclusive STOP/TIMEOUT/TARGET surface",
            "directions": ["LONG", "SHORT"],
            "protected_profit_targets_pct": list(v5.TARGET_PROFITS_PCT),
            "horizon_hours": list(v5.HORIZON_HOURS),
            "initial_stop_pct": v5.INITIAL_STOP_PCT,
            "activation_buffer_pct": v5.ACTIVATION_BUFFER_PCT,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "same_candle_policy": "stop_wins",
        },
        "features": {
            "causal_at_decision_close": True,
            "schema": "precursor_v1_plus_completed_1h_4h",
            "feature_count": len(precursor.precursor_feature_names()),
            "base_path_feature_count": len(v1.student_feature_names()),
            "future_used_for_features": False,
        },
        "selection": {
            "joint_probability": (
                "P(expansion) * P(direction | expansion)"
            ),
            "joint_probability_quantiles_from_calibration": list(
                JOINT_PROBABILITY_QUANTILES
            ),
            "minimum_direction_probability_candidates": list(
                MINIMUM_DIRECTION_PROBABILITIES
            ),
            "minimum_path_expected_net_pct_candidates": list(
                MINIMUM_EXPECTED_NET_VALUES_PCT
            ),
            "minimum_path_direction_margin_pct": (
                MINIMUM_DIRECTION_MARGIN_PCT
            ),
            "minimum_closed_trades": MINIMUM_SELECTION_TRADES,
            "objective": (
                "compounded_net_return_pct minus maximum_drawdown_pct"
            ),
            "gate": {
                "minimum_profit_factor": 1.20,
                "positive_compounded_return": True,
                "positive_objective": True,
                "both_directions_required": True,
            },
        },
        "simulation": {
            "one_trade_at_a_time": True,
            "entry": "decision candle close",
            "dynamic_target_and_horizon": True,
            "protected_stop_active_from_next_candle": True,
            "funding_included": True,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        },
        "splits": SPLITS,
        "evidence_policy": {
            "all_post_selection_blocks": "diagnostic_reuse",
            "no_result_can_promote_to_paper": True,
            "new_forward_start_required_after": "2026-07-27",
            "minimum_new_forward_days": 60,
            "minimum_new_forward_closed_trades": 50,
            "no_mid_test_retuning": True,
        },
        "visualization": {
            "candidate_zone_not_exact_oracle_candle": True,
            "watch_floor_ratio_of_selected_joint_threshold": (
                VISUAL_WATCH_THRESHOLD_RATIO
            ),
            "signals_authorized": False,
        },
        "implementation_policy": {
            "protocol_must_exist_before_training": True,
            "persist_protocol_inputs_models_predictions_report": True,
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


def expansion_labels(
    candles: numpy.ndarray,
) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    """Label useful future expansion and its first unambiguous direction."""

    close = candles[:, 4].astype(float)
    high = candles[:, 2].astype(float)
    low = candles[:, 3].astype(float)
    upper = close * (1 + EXPANSION_PCT / 100)
    lower = close * (1 - EXPANSION_PCT / 100)
    resolved = numpy.zeros(len(candles), dtype=bool)
    labels = numpy.zeros(len(candles), dtype=numpy.int8)
    directions = numpy.zeros(len(candles), dtype=numpy.int8)
    offsets = numpy.full(len(candles), -1, dtype=numpy.int16)
    for offset in range(1, MAXIMUM_EXPANSION_OFFSET + 1):
        limit = len(candles) - offset
        if limit <= 0:
            break
        available = ~resolved[:limit]
        up = high[offset:] >= upper[:limit]
        down = low[offset:] <= lower[:limit]
        touched = available & (up | down)
        offsets[:limit][touched] = offset
        if offset >= MINIMUM_EXPANSION_OFFSET:
            labels[:limit][touched] = 1
            directions[:limit][touched & up & ~down] = v1.LONG
            directions[:limit][touched & down & ~up] = v1.SHORT
        resolved[:limit][touched] = True
    return labels, directions, offsets


def build_dataset(candles: numpy.ndarray) -> ForecastDataset:
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
        features, names = precursor.causal_features(block)
        if names != precursor.precursor_feature_names():
            raise ValueError("V2 forecaster feature schema is not deterministic")
        labels, directions, offsets = expansion_labels(block)
        indices = numpy.arange(
            len(block) - ECONOMIC_HORIZON_BARS, dtype=numpy.int64
        )
        indices = indices[
            numpy.all(numpy.isfinite(features[indices]), axis=1)
        ]
        if not len(indices):
            continue
        blocks.append(
            ForecastDataset(
                features=features[indices].astype(numpy.float32),
                base_features=features[
                    indices, : len(v1.student_feature_names())
                ].astype(numpy.float32),
                expansion_labels=labels[indices],
                direction_labels=directions[indices],
                touch_offsets=offsets[indices],
                timestamps=(
                    block[indices, 0].astype(numpy.int64) + CANDLE_SECONDS
                ),
                candle_indices=indices + int(start),
                candles=candles,
            )
        )
    if not blocks:
        raise ValueError("no complete V2 forecaster examples")
    return ForecastDataset(
        features=numpy.concatenate([block.features for block in blocks]),
        base_features=numpy.concatenate(
            [block.base_features for block in blocks]
        ),
        expansion_labels=numpy.concatenate(
            [block.expansion_labels for block in blocks]
        ),
        direction_labels=numpy.concatenate(
            [block.direction_labels for block in blocks]
        ),
        touch_offsets=numpy.concatenate(
            [block.touch_offsets for block in blocks]
        ),
        timestamps=numpy.concatenate(
            [block.timestamps for block in blocks]
        ),
        candle_indices=numpy.concatenate(
            [block.candle_indices for block in blocks]
        ),
        candles=candles,
    )


def _student_view(dataset: ForecastDataset) -> v1.StudentDataset:
    return v1.StudentDataset(
        features=dataset.base_features,
        labels=dataset.direction_labels,
        timestamps=dataset.timestamps,
        candle_indices=dataset.candle_indices,
        candles=dataset.candles,
    )


def fit_forecaster(
    asset: str, dataset: ForecastDataset
) -> tuple[AssetForecaster, dict, numpy.ndarray]:
    train_mask = v1._date_mask(dataset.timestamps, *SPLITS["train"])
    train_rows = numpy.flatnonzero(train_mask)[::TRAINING_STRIDE]
    calibration_mask = v1._date_mask(
        dataset.timestamps, *SPLITS["calibration"]
    )
    calibration_rows = numpy.flatnonzero(calibration_mask)
    if len(train_rows) < 5_000 or len(calibration_rows) < 1_000:
        raise ValueError(f"insufficient {asset} development examples")
    expansion_model = model_module.NumpyLogisticModel.fit(
        dataset.features[train_rows],
        dataset.expansion_labels[train_rows],
        precursor.precursor_feature_names(),
        dataclasses.replace(MODEL_CONFIG, seed=TRAINING_SEED),
    )
    expansion_calibrator = probability_module.QuantileIsotonicCalibrator.fit(
        expansion_model.predict_proba(dataset.features[calibration_rows]),
        dataset.expansion_labels[calibration_rows],
    )
    resolved_train = train_rows[
        (dataset.expansion_labels[train_rows] == 1)
        & (dataset.direction_labels[train_rows] != v1.WAIT)
    ]
    resolved_calibration = calibration_rows[
        (dataset.expansion_labels[calibration_rows] == 1)
        & (dataset.direction_labels[calibration_rows] != v1.WAIT)
    ]
    if len(resolved_train) < 1_000 or len(resolved_calibration) < 500:
        raise ValueError(f"insufficient {asset} resolved expansion examples")
    direction_model = model_module.NumpyLogisticModel.fit(
        dataset.features[resolved_train],
        (dataset.direction_labels[resolved_train] == v1.LONG).astype(
            numpy.int8
        ),
        precursor.precursor_feature_names(),
        dataclasses.replace(MODEL_CONFIG, seed=TRAINING_SEED + 1),
    )
    direction_calibrator = probability_module.QuantileIsotonicCalibrator.fit(
        direction_model.predict_proba(
            dataset.features[resolved_calibration]
        ),
        (
            dataset.direction_labels[resolved_calibration] == v1.LONG
        ).astype(numpy.int8),
    )
    student = _student_view(dataset)
    path_outcomes = v5.future_path_outcomes(student)
    path_model, path_fit = v5.fit_v5(student, path_outcomes)
    forecaster = AssetForecaster(
        asset=asset,
        expansion_model=expansion_model,
        expansion_calibrator=expansion_calibrator,
        direction_model=direction_model,
        direction_calibrator=direction_calibrator,
        path_model=path_model,
        joint_probability_threshold=0.0,
        minimum_direction_probability=(
            MINIMUM_DIRECTION_PROBABILITIES[0]
        ),
        minimum_expected_net_pct=MINIMUM_EXPECTED_NET_VALUES_PCT[0],
    )
    calibration_predictions = forecaster.predict(
        dataset.features[calibration_rows],
        dataset.base_features[calibration_rows],
    )
    maximum_joint = numpy.max(
        calibration_predictions["joint_probability"], axis=1
    )
    candidate_thresholds = {
        str(quantile): float(numpy.quantile(maximum_joint, quantile))
        for quantile in JOINT_PROBABILITY_QUANTILES
    }
    return (
        forecaster,
        {
            "asset": asset,
            "training_rows": len(train_rows),
            "calibration_rows": len(calibration_rows),
            "resolved_direction_training_rows": len(resolved_train),
            "resolved_direction_calibration_rows": len(
                resolved_calibration
            ),
            "candidate_joint_probability_thresholds": candidate_thresholds,
            "calibration": classification_diagnostics(
                dataset.take(calibration_mask),
                calibration_predictions,
            ),
            "path_fit": path_fit,
        },
        path_outcomes,
    )


def candidate_labels(
    predictions: dict[str, numpy.ndarray],
    *,
    joint_probability_threshold: float,
    minimum_direction_probability: float,
    minimum_expected_net_pct: float,
) -> numpy.ndarray:
    joint = predictions["joint_probability"]
    direction_probability = predictions["direction_probability"]
    expected_net = predictions["expected_net_pct"]
    selected_direction = numpy.argmax(joint, axis=1)
    rows = numpy.arange(len(joint))
    opposite = 1 - selected_direction
    eligible = (
        (joint[rows, selected_direction] >= joint_probability_threshold)
        & (
            direction_probability[rows, selected_direction]
            >= minimum_direction_probability
        )
        & (
            expected_net[rows, selected_direction]
            >= minimum_expected_net_pct
        )
        & (
            expected_net[rows, selected_direction]
            - expected_net[rows, opposite]
            >= MINIMUM_DIRECTION_MARGIN_PCT
        )
    )
    labels = numpy.zeros(len(joint), dtype=numpy.int8)
    labels[eligible & (selected_direction == 0)] = v1.LONG
    labels[eligible & (selected_direction == 1)] = v1.SHORT
    return labels


def select_thresholds(
    forecaster: AssetForecaster,
    dataset: ForecastDataset,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    candidate_thresholds: dict[str, float],
) -> tuple[AssetForecaster, list[dict], dict]:
    mask = v1._date_mask(
        dataset.timestamps, *SPLITS["threshold_selection"]
    )
    subset = dataset.take(mask)
    predictions = forecaster.predict(
        subset.features, subset.base_features
    )
    table = []
    for quantile in JOINT_PROBABILITY_QUANTILES:
        joint_threshold = float(candidate_thresholds[str(quantile)])
        for direction_threshold in MINIMUM_DIRECTION_PROBABILITIES:
            for expected_net_threshold in MINIMUM_EXPECTED_NET_VALUES_PCT:
                trades = simulate_predictions(
                    subset,
                    predictions,
                    funding_series,
                    joint_probability_threshold=joint_threshold,
                    minimum_direction_probability=direction_threshold,
                    minimum_expected_net_pct=expected_net_threshold,
                )
                metrics = h2_backtest._metrics(
                    trades, ROUND_TRIP_COST_PCT
                )
                objective = (
                    metrics["compounded_net_return_pct"]
                    - metrics["maximum_drawdown_pct"]
                )
                table.append(
                    {
                        "joint_probability_quantile": quantile,
                        "joint_probability_threshold": joint_threshold,
                        "minimum_direction_probability": (
                            direction_threshold
                        ),
                        "minimum_expected_net_pct": (
                            expected_net_threshold
                        ),
                        "eligible": (
                            metrics["trades"] >= MINIMUM_SELECTION_TRADES
                        ),
                        "objective": objective,
                        "metrics": metrics,
                    }
                )
    eligible = [row for row in table if row["eligible"]]
    selected = max(
        eligible or table,
        key=lambda row: (row["objective"], row["metrics"]["trades"]),
    )
    metrics = selected["metrics"]
    gate = {
        "minimum_trades": metrics["trades"] >= MINIMUM_SELECTION_TRADES,
        "profit_factor": (
            metrics["profit_factor"] is not None
            and metrics["profit_factor"] >= 1.20
        ),
        "positive_compounded_return": (
            metrics["compounded_net_return_pct"] > 0
        ),
        "positive_objective": selected["objective"] > 0,
        "both_directions": (
            metrics["by_direction"]["LONG"]["trades"] > 0
            and metrics["by_direction"]["SHORT"]["trades"] > 0
        ),
    }
    return (
        dataclasses.replace(
            forecaster,
            joint_probability_threshold=float(
                selected["joint_probability_threshold"]
            ),
            minimum_direction_probability=float(
                selected["minimum_direction_probability"]
            ),
            minimum_expected_net_pct=float(
                selected["minimum_expected_net_pct"]
            ),
        ),
        table,
        {
            "selected": {
                key: selected[key]
                for key in (
                    "joint_probability_quantile",
                    "joint_probability_threshold",
                    "minimum_direction_probability",
                    "minimum_expected_net_pct",
                    "objective",
                    "metrics",
                )
            },
            "results": gate,
            "passed": all(gate.values()),
        },
    )


def simulate_predictions(
    dataset: ForecastDataset,
    predictions: dict[str, numpy.ndarray],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    *,
    joint_probability_threshold: float,
    minimum_direction_probability: float,
    minimum_expected_net_pct: float,
) -> list[dict]:
    labels = candidate_labels(
        predictions,
        joint_probability_threshold=joint_probability_threshold,
        minimum_direction_probability=minimum_direction_probability,
        minimum_expected_net_pct=minimum_expected_net_pct,
    )
    close_times = (
        dataset.candles[:, 0].astype(numpy.int64) + CANDLE_SECONDS
    ).tolist()
    funding_timestamps, funding_rates = funding_series
    next_available = 0
    trades = []
    for row in numpy.flatnonzero(labels != v1.WAIT):
        entry_index = int(dataset.candle_indices[row])
        if entry_index < next_available:
            continue
        direction_index = 0 if labels[row] == v1.LONG else 1
        direction = v5.DIRECTIONS[direction_index]
        target_index = int(
            predictions["target_index"][row, direction_index]
        )
        horizon_index = int(
            predictions["horizon_index"][row, direction_index]
        )
        target_profit = v5.TARGET_PROFITS_PCT[target_index]
        horizon_hours = v5.HORIZON_HOURS[horizon_index]
        config = percentage_engine.PercentageEngineConfig(
            minimum_profit_pct=target_profit,
            activation_pct=target_profit + v5.ACTIVATION_BUFFER_PCT,
            initial_stop_pct=v5.INITIAL_STOP_PCT,
            horizon_candles=horizon_hours * 4,
            directions=(direction,),
            exclude_last_candle=False,
        )
        trade = percentage_engine.simulate_trade(
            close_times,
            dataset.candles[:, 2],
            dataset.candles[:, 3],
            dataset.candles[:, 4],
            entry_index,
            direction,
            len(dataset.candles) - 1,
            config,
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
        sign = 1 if direction == percentage_engine.LONG else -1
        funding_cost_pct = sign * float(
            numpy.sum(funding_rates[first:last])
        ) * 100
        trades.append(
            {
                "direction": direction,
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
                "maximum_favorable_excursion_pct": float(
                    trade["maximum_favorable_excursion_pct"]
                ),
                "maximum_adverse_excursion_pct": float(
                    trade["maximum_adverse_excursion_pct"]
                ),
                "expansion_probability_pct": float(
                    predictions["expansion_probability"][row] * 100
                ),
                "direction_probability_pct": float(
                    predictions["direction_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "joint_probability_pct": float(
                    predictions["joint_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "target_probability_pct": float(
                    predictions["target_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "expected_net_pct": float(
                    predictions["expected_net_pct"][
                        row, direction_index
                    ]
                ),
                "target_profit_pct": target_profit,
                "horizon_hours": horizon_hours,
            }
        )
        next_available = int(trade["exit_index"]) + 1
    return trades


def classification_diagnostics(
    dataset: ForecastDataset,
    predictions: dict[str, numpy.ndarray],
) -> dict:
    expansion_probability = predictions["expansion_probability"]
    expansion_labels_value = dataset.expansion_labels
    resolved = (
        (dataset.expansion_labels == 1)
        & (dataset.direction_labels != v1.WAIT)
    )
    if numpy.any(resolved):
        direction_labels = (
            dataset.direction_labels[resolved] == v1.LONG
        ).astype(numpy.int8)
        direction_probability = predictions["direction_probability"][
            resolved, 0
        ]
        direction = {
            "examples": int(numpy.sum(resolved)),
            "long_rate_pct": float(numpy.mean(direction_labels) * 100),
            "mean_long_probability_pct": float(
                numpy.mean(direction_probability) * 100
            ),
            "accuracy_pct": float(
                numpy.mean(
                    (direction_probability >= 0.5) == direction_labels
                )
                * 100
            ),
            "brier_score": float(
                numpy.mean(
                    (direction_probability - direction_labels) ** 2
                )
            ),
            "roc_auc": precursor._roc_auc(
                direction_labels, direction_probability
            ),
        }
    else:
        direction = {"examples": 0}
    return {
        "expansion": {
            "examples": len(expansion_labels_value),
            "base_rate_pct": float(
                numpy.mean(expansion_labels_value) * 100
            ),
            "mean_probability_pct": float(
                numpy.mean(expansion_probability) * 100
            ),
            "brier_score": float(
                numpy.mean(
                    (expansion_probability - expansion_labels_value) ** 2
                )
            ),
            "roc_auc": precursor._roc_auc(
                expansion_labels_value, expansion_probability
            ),
            "average_precision": precursor._average_precision(
                expansion_labels_value, expansion_probability
            ),
        },
        "direction_given_expansion": direction,
    }


def evaluate_block(
    *,
    name: str,
    exchange: str,
    evidence_role: str,
    forecaster: AssetForecaster,
    dataset: ForecastDataset,
    path_outcomes: numpy.ndarray,
    date_range: tuple[str, str],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> tuple[dict, list[dict], dict[str, numpy.ndarray]]:
    mask = v1._date_mask(dataset.timestamps, *date_range)
    subset = dataset.take(mask)
    predictions = forecaster.predict(
        subset.features, subset.base_features
    )
    trades = simulate_predictions(
        subset,
        predictions,
        funding_series,
        joint_probability_threshold=(
            forecaster.joint_probability_threshold
        ),
        minimum_direction_probability=(
            forecaster.minimum_direction_probability
        ),
        minimum_expected_net_pct=forecaster.minimum_expected_net_pct,
    )
    for trade in trades:
        trade["exchange"] = exchange
    metrics = h2_backtest._metrics(trades, ROUND_TRIP_COST_PCT)
    return (
        {
            "name": name,
            "exchange": exchange,
            "evidence_role": evidence_role,
            "start": date_range[0],
            "end": date_range[1],
            "classification": classification_diagnostics(
                subset, predictions
            ),
            "path_surface": v5.surface_diagnostics(
                path_outcomes[numpy.flatnonzero(mask)],
                predictions["probabilities"],
            ),
            "economic": metrics,
        },
        trades,
        {
            "timestamps": subset.timestamps,
            "observed_expansion": subset.expansion_labels,
            "observed_direction": subset.direction_labels,
            **predictions,
        },
    )


def _load_asset_15m(
    path: pathlib.Path, asset: str, source_time_frame: str
) -> numpy.ndarray:
    series = dataset_module.load_collector_series(
        [path], required_time_frames=(source_time_frame,)
    )
    matching = [
        frames[source_time_frame].values
        for symbol, frames in series.items()
        if symbol.startswith(f"{asset}/")
    ]
    if len(matching) != 1:
        raise ValueError(f"expected one {asset} series in {path}")
    if source_time_frame == "15m":
        return matching[0]
    if source_time_frame == "5m":
        return h2_backtest._aggregate_5m_to_15m(matching[0])
    raise ValueError("source time frame must be 5m or 15m")


def _load_asset_funding(
    path: pathlib.Path, asset: str
) -> tuple[numpy.ndarray, numpy.ndarray]:
    values = funding_module.load_funding(path)
    matching = [
        series
        for symbol, series in values.items()
        if symbol.startswith(f"{asset}/")
    ]
    if len(matching) != 1:
        raise ValueError(f"expected one {asset} funding series in {path}")
    return matching[0]


def run_study(
    *,
    inputs: dict[str, dict[str, typing.Union[str, pathlib.Path]]],
    output_directory: typing.Union[str, pathlib.Path],
) -> dict:
    output = pathlib.Path(output_directory).resolve()
    protocol_path = output / "protocol.json"
    if not protocol_path.is_file():
        raise FileNotFoundError("write protocol.json before running V2")
    protocol = frozen_protocol()
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != protocol_sha256(protocol):
        raise ValueError("persisted V2 protocol differs from frozen code")
    reports = {}
    all_trades = {}
    model_artifacts = {}
    input_artifacts = {}
    prediction_payload = {}
    replay_differences = {}
    for asset in ASSETS:
        config = inputs[asset]
        binance_path = pathlib.Path(
            config["binance_collector"]
        ).resolve()
        binance_funding_path = pathlib.Path(
            config["binance_funding"]
        ).resolve()
        kucoin_path = pathlib.Path(
            config["kucoin_collector"]
        ).resolve()
        kucoin_funding_path = pathlib.Path(
            config["kucoin_funding"]
        ).resolve()
        binance_dataset = build_dataset(
            _load_asset_15m(binance_path, asset, "15m")
        )
        kucoin_dataset = build_dataset(
            _load_asset_15m(
                kucoin_path,
                asset,
                str(config["kucoin_time_frame"]),
            )
        )
        binance_funding = _load_asset_funding(
            binance_funding_path, asset
        )
        kucoin_funding = _load_asset_funding(
            kucoin_funding_path, asset
        )
        unselected, fit_report, binance_path_outcomes = fit_forecaster(
            asset, binance_dataset
        )
        selected, threshold_table, selection_gate = select_thresholds(
            unselected,
            binance_dataset,
            binance_funding,
            fit_report["candidate_joint_probability_thresholds"],
        )
        kucoin_path_outcomes = v5.future_path_outcomes(
            _student_view(kucoin_dataset)
        )
        asset_reports = {}
        asset_trades = {}
        block_specs = (
            (
                "binance_reused_2025",
                "binance_usdm",
                binance_dataset,
                binance_path_outcomes,
                SPLITS["binance_reused_2025"],
                binance_funding,
            ),
            (
                "binance_reused_2026",
                "binance_usdm",
                binance_dataset,
                binance_path_outcomes,
                SPLITS["binance_reused_2026"],
                binance_funding,
            ),
            (
                "kucoin_reused_2026",
                "kucoin_futures",
                kucoin_dataset,
                kucoin_path_outcomes,
                SPLITS["kucoin_reused_2026"],
                kucoin_funding,
            ),
        )
        for (
            name,
            exchange,
            dataset,
            outcomes,
            date_range,
            funding,
        ) in block_specs:
            block_report, trades, predictions = evaluate_block(
                name=f"{asset.lower()}_{name}",
                exchange=exchange,
                evidence_role="diagnostic_reuse",
                forecaster=selected,
                dataset=dataset,
                path_outcomes=outcomes,
                date_range=date_range,
                funding_series=funding,
            )
            asset_reports[name] = block_report
            asset_trades[name] = trades
            for key, values in predictions.items():
                prediction_payload[
                    f"{asset.lower()}_{name}_{key}"
                ] = values
        asset_model_directory = output / "models" / asset.lower()
        model_artifacts[asset] = selected.save(asset_model_directory)
        reloaded = AssetForecaster.load(asset_model_directory)
        replay_rows = min(5_000, len(binance_dataset.features))
        original = selected.predict(
            binance_dataset.features[:replay_rows],
            binance_dataset.base_features[:replay_rows],
        )
        restored = reloaded.predict(
            binance_dataset.features[:replay_rows],
            binance_dataset.base_features[:replay_rows],
        )
        replay_difference = max(
            float(numpy.max(numpy.abs(original[key] - restored[key])))
            for key in original
        )
        if replay_difference != 0:
            raise ValueError(
                f"reloaded {asset} V2 predictions differ"
            )
        replay_differences[asset] = replay_difference
        reports[asset] = {
            "fit": fit_report,
            "threshold_selection": threshold_table,
            "selection_gate": selection_gate,
            "diagnostic_reuse_audits": asset_reports,
        }
        all_trades[asset] = asset_trades
        input_artifacts[asset] = {
            "binance_collector": v1._artifact(binance_path),
            "binance_funding": v1._artifact(binance_funding_path),
            "kucoin_collector": v1._artifact(kucoin_path),
            "kucoin_funding": v1._artifact(kucoin_funding_path),
        }
    predictions_path = output / "predictions.npz"
    numpy.savez_compressed(predictions_path, **prediction_payload)
    trades_path = output / "trades.json"
    trades_path.write_text(
        json.dumps(all_trades, indent=2, sort_keys=True) + "\n",
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
        "evidence_role": "diagnostic_reuse",
        "assets": reports,
        "model_replay_max_absolute_difference": replay_differences,
        "promotion_eligible": False,
        "promotion_blocker": (
            "All post-selection dates are reused; at least 60 untouched "
            "forward days and 50 closed trades are required."
        ),
        "artifacts": {
            "protocol": v1._artifact(protocol_path),
            "models": model_artifacts,
            "predictions": v1._artifact(predictions_path),
            "trades": v1._artifact(trades_path),
            "inputs": input_artifacts,
        },
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


@functools.lru_cache(maxsize=4)
def _load_chart_model(
    artifact_root: str, asset: str
) -> AssetForecaster:
    return AssetForecaster.load(
        pathlib.Path(artifact_root) / "models" / asset.lower()
    )


@functools.lru_cache(maxsize=2)
def _load_chart_report(artifact_root: str) -> dict:
    return json.loads(
        (pathlib.Path(artifact_root) / "report.json").read_text(
            encoding="utf-8"
        )
    )


def _advance_display_time(
    display_time: typing.Any, candle_offset: int
) -> str:
    value = str(display_time)
    parsed = datetime.datetime.strptime(value, "%y-%m-%d %H:%M:%S")
    return (
        parsed
        + datetime.timedelta(
            seconds=int(candle_offset) * CANDLE_SECONDS
        )
    ).strftime("%y-%m-%d %H:%M:%S")


def _path_scenario_at(
    *,
    closed: numpy.ndarray,
    candle_index: int,
    prediction_row: int,
    predictions: dict[str, numpy.ndarray],
    horizon_bars: int,
) -> typing.Optional[dict[str, float]]:
    first_return_index = max(
        1,
        candle_index - SIMULATED_PATH_VOLATILITY_WINDOW + 1,
    )
    prices = closed[first_return_index - 1 : candle_index + 1, 4]
    if len(prices) < 3 or numpy.any(prices <= 0):
        return None
    log_returns = numpy.diff(numpy.log(prices))
    realized_volatility = float(numpy.std(log_returns, ddof=1))
    if not numpy.isfinite(realized_volatility):
        return None
    joint = predictions["joint_probability"][prediction_row]
    joint_margin = float(joint[0] - joint[1])
    scale = numpy.sqrt(float(horizon_bars))
    median_log_return = joint_margin * realized_volatility * scale
    band_log_width = (
        SIMULATED_PATH_BAND_Z_SCORE
        * realized_volatility
        * scale
    )
    anchor_price = float(closed[candle_index, 4])
    return {
        "anchor_price": anchor_price,
        "median_price": float(
            anchor_price * numpy.exp(median_log_return)
        ),
        "lower_price": float(
            anchor_price
            * numpy.exp(median_log_return - band_log_width)
        ),
        "upper_price": float(
            anchor_price
            * numpy.exp(median_log_return + band_log_width)
        ),
        "median_return_pct": float(
            (numpy.exp(median_log_return) - 1.0) * 100
        ),
        "realized_volatility_pct": realized_volatility * 100,
        "joint_margin_pct": joint_margin * 100,
    }


def _rolling_path_accuracy(
    *,
    closed: numpy.ndarray,
    display_values: list[typing.Any],
    valid: numpy.ndarray,
    predictions: dict[str, numpy.ndarray],
    horizon_name: str,
    horizon_bars: int,
) -> dict:
    evaluated = []
    for prediction_row, candle_index_value in enumerate(valid):
        candle_index = int(candle_index_value)
        outcome_index = candle_index + horizon_bars
        if outcome_index >= len(closed):
            continue
        scenario = _path_scenario_at(
            closed=closed,
            candle_index=candle_index,
            prediction_row=prediction_row,
            predictions=predictions,
            horizon_bars=horizon_bars,
        )
        if scenario is None:
            continue
        anchor_price = scenario["anchor_price"]
        outcome_price = float(closed[outcome_index, 4])
        actual_log_return = float(
            numpy.log(outcome_price / anchor_price)
        )
        joint_margin = scenario["joint_margin_pct"] / 100
        if joint_margin == 0 or actual_log_return == 0:
            continue
        correct = bool(joint_margin * actual_log_return > 0)
        evaluated.append(
            {
                "decision_time": display_values[candle_index],
                "outcome_time": display_values[outcome_index],
                "correct": correct,
                "inside_band": bool(
                    scenario["lower_price"]
                    <= outcome_price
                    <= scenario["upper_price"]
                ),
                "absolute_error_pct": abs(
                    outcome_price - scenario["median_price"]
                )
                / anchor_price
                * 100,
            }
        )
    series = []
    for index in range(
        SIMULATED_PATH_MINIMUM_ACCURACY_SAMPLES - 1,
        len(evaluated),
    ):
        window_start = max(
            0, index - SIMULATED_PATH_ACCURACY_WINDOW + 1
        )
        window = evaluated[window_start : index + 1]
        series.append(
            {
                "time": evaluated[index]["outcome_time"],
                "accuracy_pct": (
                    sum(item["correct"] for item in window)
                    / len(window)
                    * 100
                ),
                "samples": len(window),
            }
        )
    sample_count = len(evaluated)
    return {
        "horizon": horizon_name,
        "horizon_candles": horizon_bars,
        "mature_forecasts": sample_count,
        "overall_directional_accuracy_pct": (
            sum(item["correct"] for item in evaluated)
            / sample_count
            * 100
            if sample_count
            else None
        ),
        "rolling_directional_accuracy_pct": (
            series[-1]["accuracy_pct"] if series else None
        ),
        "empirical_band_coverage_pct": (
            sum(item["inside_band"] for item in evaluated)
            / sample_count
            * 100
            if sample_count
            else None
        ),
        "median_absolute_error_pct": (
            float(
                numpy.median(
                    [
                        item["absolute_error_pct"]
                        for item in evaluated
                    ]
                )
            )
            if sample_count
            else None
        ),
        "series": series,
    }


def simulated_path_payload(
    *,
    closed: numpy.ndarray,
    display_values: list[typing.Any],
    valid: numpy.ndarray,
    predictions: dict[str, numpy.ndarray],
) -> dict:
    latest_row = len(valid) - 1
    latest_index = int(valid[latest_row])
    maximum_horizon = max(
        horizon_bars
        for _horizon_name, horizon_bars in SIMULATED_PATH_HORIZONS
    )
    x_values = []
    median_values = []
    lower_values = []
    upper_values = []
    for candle_offset in range(maximum_horizon + 1):
        if candle_offset:
            scenario = _path_scenario_at(
                closed=closed,
                candle_index=latest_index,
                prediction_row=latest_row,
                predictions=predictions,
                horizon_bars=candle_offset,
            )
            if scenario is None:
                continue
            median_values.append(scenario["median_price"])
            lower_values.append(scenario["lower_price"])
            upper_values.append(scenario["upper_price"])
        else:
            anchor_price = float(closed[latest_index, 4])
            median_values.append(anchor_price)
            lower_values.append(anchor_price)
            upper_values.append(anchor_price)
        x_values.append(
            _advance_display_time(
                display_values[latest_index], candle_offset
            )
        )
    endpoints = {}
    for horizon_name, horizon_bars in SIMULATED_PATH_HORIZONS:
        scenario = _path_scenario_at(
            closed=closed,
            candle_index=latest_index,
            prediction_row=latest_row,
            predictions=predictions,
            horizon_bars=horizon_bars,
        )
        if scenario is not None:
            endpoints[horizon_name] = {
                "time": _advance_display_time(
                    display_values[latest_index], horizon_bars
                ),
                **scenario,
            }
    accuracy = {
        horizon_name: _rolling_path_accuracy(
            closed=closed,
            display_values=display_values,
            valid=valid,
            predictions=predictions,
            horizon_name=horizon_name,
            horizon_bars=horizon_bars,
        )
        for horizon_name, horizon_bars in SIMULATED_PATH_HORIZONS
    }
    latest_joint = predictions["joint_probability"][latest_row]
    joint_margin = float(latest_joint[0] - latest_joint[1])
    return {
        "schema_version": 1,
        "mode": "v2_joint_margin_realized_volatility_scenario",
        "research_only": True,
        "orders_authorized": False,
        "forecast_uses_future_outcomes": False,
        "accuracy_uses_future_outcomes": True,
        "overlapping_forecasts": True,
        "time_frame": "15m",
        "formula": (
            "median log-return = (P joint LONG - P joint SHORT) "
            "* realized volatility * sqrt(horizon); uncertainty band "
            "= median +/- 1.2816 * realized volatility * sqrt(horizon)"
        ),
        "volatility_window_candles": (
            SIMULATED_PATH_VOLATILITY_WINDOW
        ),
        "rolling_accuracy_window_forecasts": (
            SIMULATED_PATH_ACCURACY_WINDOW
        ),
        "minimum_rolling_accuracy_samples": (
            SIMULATED_PATH_MINIMUM_ACCURACY_SAMPLES
        ),
        "nominal_band_coverage_pct": 80.0,
        "latest": {
            "anchor_time": display_values[latest_index],
            "anchor_price": float(closed[latest_index, 4]),
            "preferred_direction": (
                v5.DIRECTIONS[0]
                if joint_margin >= 0
                else v5.DIRECTIONS[1]
            ),
            "joint_margin_pct": joint_margin * 100,
            "x": x_values,
            "median": median_values,
            "lower": lower_values,
            "upper": upper_values,
            "endpoints": endpoints,
        },
        "accuracy": accuracy,
        "warning": (
            "This is a causal probabilistic scenario, not a predicted "
            "candlestick sequence. Accuracy is directional at fixed "
            "mature horizons and is not a trading win rate."
        ),
    }


def analyze_chart_forecast(
    *,
    times: typing.Iterable[typing.Any],
    display_times: typing.Iterable[typing.Any],
    opens: typing.Iterable[float],
    highs: typing.Iterable[float],
    lows: typing.Iterable[float],
    closes: typing.Iterable[float],
    volumes: typing.Iterable[float],
    symbol: str,
    artifact_root: typing.Optional[
        typing.Union[str, pathlib.Path]
    ] = None,
) -> dict:
    """Return causal V2 forecast markers for a live 15m chart."""

    columns = [
        list(times),
        list(opens),
        list(highs),
        list(lows),
        list(closes),
        list(volumes),
    ]
    display_values = list(display_times)
    lengths = {len(column) for column in columns} | {len(display_values)}
    if len(lengths) != 1 or not columns[0]:
        raise ValueError("chart candle arrays must be non-empty and aligned")
    asset = str(symbol).split("/", 1)[0].upper()
    if asset not in ASSETS:
        raise ValueError(f"V2 chart model does not support {asset}")
    candles = numpy.column_stack(
        [numpy.asarray(column, dtype=float) for column in columns]
    )
    closed_count = len(candles) - 1
    if closed_count < 320:
        raise ValueError(
            "V2 needs at least 320 closed 15m candles plus the open candle"
        )
    closed = candles[:closed_count]
    features, names = precursor.causal_features(closed)
    if names != precursor.precursor_feature_names():
        raise ValueError("V2 live feature schema differs")
    valid = numpy.flatnonzero(numpy.all(numpy.isfinite(features), axis=1))
    if not len(valid):
        raise ValueError("V2 has no complete live feature rows")
    root = str(
        pathlib.Path(
            artifact_root
            or os.environ.get(
                "PERFECT_MAP_FORECASTER_V2_ROOT",
                (
                    "/octobot/backtesting/research/"
                    "perfect_map_forecaster_v2"
                ),
            )
        ).resolve()
    )
    model = _load_chart_model(root, asset)
    predictions = model.predict(
        features[valid],
        features[valid, : len(v1.student_feature_names())],
    )
    labels = candidate_labels(
        predictions,
        joint_probability_threshold=model.joint_probability_threshold,
        minimum_direction_probability=model.minimum_direction_probability,
        minimum_expected_net_pct=model.minimum_expected_net_pct,
    )
    maximum_joint = numpy.max(predictions["joint_probability"], axis=1)
    selected_direction = numpy.argmax(
        predictions["joint_probability"], axis=1
    )
    watch_floor = (
        model.joint_probability_threshold
        * VISUAL_WATCH_THRESHOLD_RATIO
    )
    points = []
    for row in numpy.flatnonzero(maximum_joint >= watch_floor):
        candle_index = int(valid[row])
        direction_index = int(selected_direction[row])
        direction = v5.DIRECTIONS[direction_index]
        target_index = int(
            predictions["target_index"][row, direction_index]
        )
        horizon_index = int(
            predictions["horizon_index"][row, direction_index]
        )
        points.append(
            {
                "index": candle_index,
                "time": display_values[candle_index],
                "price": float(closed[candle_index, 4]),
                "direction": direction,
                "status": (
                    "candidate"
                    if labels[row] != v1.WAIT
                    else "watch"
                ),
                "expansion_probability_pct": float(
                    predictions["expansion_probability"][row] * 100
                ),
                "direction_probability_pct": float(
                    predictions["direction_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "joint_probability_pct": float(
                    predictions["joint_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "target_probability_pct": float(
                    predictions["target_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "expected_net_pct": float(
                    predictions["expected_net_pct"][
                        row, direction_index
                    ]
                ),
                "target_profit_pct": v5.TARGET_PROFITS_PCT[
                    target_index
                ],
                "horizon_hours": v5.HORIZON_HOURS[horizon_index],
            }
        )
    latest_row = len(valid) - 1
    latest_direction_index = int(selected_direction[latest_row])
    latest_target_index = int(
        predictions["target_index"][
            latest_row, latest_direction_index
        ]
    )
    latest_horizon_index = int(
        predictions["horizon_index"][
            latest_row, latest_direction_index
        ]
    )
    report = _load_chart_report(root)
    asset_report = report["assets"][asset]
    selection = asset_report["selection_gate"]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": PROTOCOL_VERSION,
        "research_only": True,
        "diagnostic_reuse": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "signal_uses_future_outcomes": False,
        "evaluation_uses_future_outcomes": True,
        "time_frame": "15m",
        "asset": asset,
        "event_timestamp_semantics": (
            "decision candle close when every feature is available"
        ),
        "thresholds": {
            "joint_probability_pct": (
                model.joint_probability_threshold * 100
            ),
            "visual_watch_probability_pct": watch_floor * 100,
            "minimum_direction_probability_pct": (
                model.minimum_direction_probability * 100
            ),
            "minimum_expected_net_pct": model.minimum_expected_net_pct,
        },
        "latest": {
            "time": display_values[int(valid[latest_row])],
            "expansion_probability_pct": float(
                predictions["expansion_probability"][latest_row] * 100
            ),
            "long_joint_probability_pct": float(
                predictions["joint_probability"][latest_row, 0] * 100
            ),
            "short_joint_probability_pct": float(
                predictions["joint_probability"][latest_row, 1] * 100
            ),
            "preferred_direction": v5.DIRECTIONS[
                latest_direction_index
            ],
            "direction_probability_pct": float(
                predictions["direction_probability"][
                    latest_row, latest_direction_index
                ]
                * 100
            ),
            "target_probability_pct": float(
                predictions["target_probability"][
                    latest_row, latest_direction_index
                ]
                * 100
            ),
            "expected_net_pct": float(
                predictions["expected_net_pct"][
                    latest_row, latest_direction_index
                ]
            ),
            "target_profit_pct": v5.TARGET_PROFITS_PCT[
                latest_target_index
            ],
            "horizon_hours": v5.HORIZON_HOURS[
                latest_horizon_index
            ],
            "candidate": bool(labels[latest_row] != v1.WAIT),
        },
        "points": points,
        "simulated_path": simulated_path_payload(
            closed=closed,
            display_values=display_values[:closed_count],
            valid=valid,
            predictions=predictions,
        ),
        "summary": {
            "visible_watch_zones": sum(
                point["status"] == "watch" for point in points
            ),
            "visible_candidate_zones": sum(
                point["status"] == "candidate" for point in points
            ),
            "selection_gate_passed": bool(selection["passed"]),
            "selection_metrics": selection["selected"]["metrics"],
            "fit_diagnostics": {
                "expansion_roc_auc": asset_report["fit"][
                    "calibration"
                ]["expansion"]["roc_auc"],
                "direction_roc_auc": asset_report["fit"][
                    "calibration"
                ]["direction_given_expansion"]["roc_auc"],
                "direction_accuracy_pct": asset_report["fit"][
                    "calibration"
                ]["direction_given_expansion"]["accuracy_pct"],
            },
        },
        "warning": (
            "V2 is a causal diagnostic on reused dates, not an approved "
            "signal. Percentages are model estimates, not certainties."
        ),
    }


def _input_mapping(args: argparse.Namespace) -> dict:
    return {
        "BTC": {
            "binance_collector": args.binance_btc_collector,
            "binance_funding": args.binance_btc_funding,
            "kucoin_collector": args.kucoin_btc_collector,
            "kucoin_funding": args.kucoin_btc_funding,
            "kucoin_time_frame": "5m",
        },
        "ETH": {
            "binance_collector": args.binance_eth_collector,
            "binance_funding": args.binance_eth_funding,
            "kucoin_collector": args.kucoin_eth_collector,
            "kucoin_funding": args.kucoin_eth_funding,
            "kucoin_time_frame": "15m",
        },
    }


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--write-protocol-only", action="store_true")
    for venue in ("binance", "kucoin"):
        for asset in ("btc", "eth"):
            parser.add_argument(f"--{venue}-{asset}-collector")
            parser.add_argument(f"--{venue}-{asset}-funding")
    args = parser.parse_args(argv)
    protocol_path = write_protocol(args.output_directory)
    if args.write_protocol_only:
        print(
            json.dumps(
                {
                    "protocol_path": str(protocol_path),
                    "protocol_sha256": protocol_sha256(
                        frozen_protocol()
                    ),
                },
                indent=2,
            )
        )
        return 0
    inputs = _input_mapping(args)
    if any(
        config[key] is None
        for config in inputs.values()
        for key in (
            "binance_collector",
            "binance_funding",
            "kucoin_collector",
            "kucoin_funding",
        )
    ):
        parser.error("all BTC/ETH collector and funding paths are required")
    result = run_study(
        inputs=inputs,
        output_directory=args.output_directory,
    )
    print(
        json.dumps(
            {
                "report_path": result["report_path"],
                "assets": {
                    asset: {
                        "selection_gate": values["selection_gate"],
                        "diagnostic_reuse_audits": {
                            name: audit["economic"]
                            for name, audit in values[
                                "diagnostic_reuse_audits"
                            ].items()
                        },
                    }
                    for asset, values in result["assets"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
