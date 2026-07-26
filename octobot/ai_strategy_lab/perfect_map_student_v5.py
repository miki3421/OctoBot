"""Multi-target, multi-horizon future-path student of the perfect map.

V5 predicts a causal probability surface for mutually exclusive STOP,
TIMEOUT, and TARGET outcomes. A deterministic planner chooses direction,
minimum protected profit, and horizon from expected net return. This module is
offline research only and cannot authorize orders.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import h2_backtest
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2
from octobot.ai_strategy_lab import perfect_map_student_v3 as v3
from octobot.ai_strategy_lab import perfect_map_student_v4 as v4


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_future_path_surface_student_v5"
CLASS_NAMES = ("STOP", "TIMEOUT", "TARGET")
STOP_CLASS = 0
TIMEOUT_CLASS = 1
TARGET_CLASS = 2
DIRECTIONS = (percentage_engine.LONG, percentage_engine.SHORT)
TARGET_PROFITS_PCT = (0.50, 0.75, 1.00, 1.20, 1.50)
HORIZON_HOURS = (1, 2, 4, 8, 24)
HORIZON_BARS = tuple(value * 4 for value in HORIZON_HOURS)
ACTIVATION_BUFFER_PCT = 0.20
INITIAL_STOP_PCT = 1.00
ROUND_TRIP_COST_PCT = v1.ROUND_TRIP_COST_PCT
MINIMUM_DIRECTION_MARGIN_PCT = 0.03
EXPECTED_NET_THRESHOLDS_PCT = (0.00, 0.025, 0.05, 0.075, 0.10, 0.15, 0.20)
MINIMUM_SELECTION_TRADES = 15
TRAINING_STRIDE = v1.TRAINING_STRIDE
SPLITS = v3.SPLITS
PRIMARY_CONFIG = {
    "epochs": 28,
    "batch_size": 4096,
    "learning_rate": 0.009,
    "l2": 0.002,
    "seed": 20_260_729,
}
CALIBRATION_CONFIG = {
    "epochs": 80,
    "batch_size": 4096,
    "learning_rate": 0.012,
    "l2": 0.01,
    "seed": 20_260_730,
}


@dataclasses.dataclass(frozen=True)
class HeadSpec:
    direction: str
    target_profit_pct: float
    activation_pct: float
    horizon_hours: int
    horizon_bars: int

    @property
    def name(self) -> str:
        direction = self.direction.lower()
        target = str(self.target_profit_pct).replace(".", "p")
        return f"{direction}_target_{target}_horizon_{self.horizon_hours}h"


HEAD_SPECS = tuple(
    HeadSpec(
        direction=direction,
        target_profit_pct=target,
        activation_pct=target + ACTIVATION_BUFFER_PCT,
        horizon_hours=hours,
        horizon_bars=bars,
    )
    for direction in DIRECTIONS
    for target in TARGET_PROFITS_PCT
    for hours, bars in zip(HORIZON_HOURS, HORIZON_BARS)
)


@dataclasses.dataclass
class NumpyGroupedSoftmaxModel:
    feature_names: tuple[str, ...]
    head_names: tuple[str, ...]
    class_names: tuple[str, ...]
    mean: numpy.ndarray
    scale: numpy.ndarray
    weights: numpy.ndarray
    intercept: numpy.ndarray
    config: dict

    @classmethod
    def fit(
        cls,
        features: numpy.ndarray,
        labels: numpy.ndarray,
        feature_names: tuple[str, ...],
        head_names: tuple[str, ...],
        class_names: tuple[str, ...],
        config: dict,
    ) -> "NumpyGroupedSoftmaxModel":
        _validate_grouped_training(features, labels, head_names, class_names)
        mean = numpy.mean(features, axis=0, dtype=numpy.float64)
        scale = numpy.std(features, axis=0, dtype=numpy.float64)
        scale[scale < 1e-9] = 1.0
        standardized = numpy.clip(
            (features.astype(numpy.float64) - mean) / scale,
            -12.0,
            12.0,
        ).astype(numpy.float32)
        head_count = len(head_names)
        class_count = len(class_names)
        weights = numpy.zeros(
            (standardized.shape[1], head_count, class_count),
            dtype=numpy.float64,
        )
        counts = numpy.stack(
            [
                numpy.bincount(labels[:, head], minlength=class_count)
                for head in range(head_count)
            ]
        ).astype(float)
        priors = numpy.maximum(counts / len(labels), 1e-9)
        intercept = numpy.log(priors)
        _fit_grouped_parameters(
            standardized,
            labels,
            weights,
            intercept,
            config,
            regularization_target=numpy.zeros_like(weights),
        )
        return cls(
            feature_names=feature_names,
            head_names=head_names,
            class_names=class_names,
            mean=mean,
            scale=scale,
            weights=weights,
            intercept=intercept,
            config=dict(config),
        )

    def predict_logits(self, features: numpy.ndarray) -> numpy.ndarray:
        if features.shape[1] != len(self.feature_names):
            raise ValueError("V5 grouped feature schema differs")
        standardized = numpy.clip(
            (features.astype(numpy.float64) - self.mean) / self.scale,
            -12.0,
            12.0,
        )
        return (
            numpy.einsum("bf,fhc->bhc", standardized, self.weights)
            + self.intercept
        )

    def predict_proba(self, features: numpy.ndarray) -> numpy.ndarray:
        return _softmax(self.predict_logits(features))

    def save(
        self, path_value: typing.Union[str, pathlib.Path]
    ) -> dict:
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        numpy.savez_compressed(
            path,
            schema_version=numpy.asarray([SCHEMA_VERSION]),
            feature_names=numpy.asarray(self.feature_names),
            head_names=numpy.asarray(self.head_names),
            class_names=numpy.asarray(self.class_names),
            mean=self.mean,
            scale=self.scale,
            weights=self.weights,
            intercept=self.intercept,
            config=numpy.asarray([json.dumps(self.config, sort_keys=True)]),
        )
        return v2._artifact(path)

    @classmethod
    def load(
        cls, path_value: typing.Union[str, pathlib.Path]
    ) -> "NumpyGroupedSoftmaxModel":
        path = pathlib.Path(path_value).resolve()
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported V5 grouped model schema")
            return cls(
                feature_names=tuple(
                    str(value) for value in values["feature_names"]
                ),
                head_names=tuple(
                    str(value) for value in values["head_names"]
                ),
                class_names=tuple(
                    str(value) for value in values["class_names"]
                ),
                mean=values["mean"],
                scale=values["scale"],
                weights=values["weights"],
                intercept=values["intercept"],
                config=json.loads(str(values["config"][0])),
            )


@dataclasses.dataclass
class NumpyGroupedSoftmaxCalibrator:
    head_names: tuple[str, ...]
    class_names: tuple[str, ...]
    weights: numpy.ndarray
    intercept: numpy.ndarray
    config: dict

    @classmethod
    def fit(
        cls,
        logits: numpy.ndarray,
        labels: numpy.ndarray,
        head_names: tuple[str, ...],
        class_names: tuple[str, ...],
        config: dict,
    ) -> "NumpyGroupedSoftmaxCalibrator":
        if logits.shape != (
            len(labels),
            len(head_names),
            len(class_names),
        ):
            raise ValueError("V5 calibration logits are misaligned")
        weights = numpy.repeat(
            numpy.eye(len(class_names), dtype=numpy.float64)[None, :, :],
            len(head_names),
            axis=0,
        )
        intercept = numpy.zeros(
            (len(head_names), len(class_names)), dtype=numpy.float64
        )
        _fit_calibration_parameters(
            logits.astype(numpy.float64),
            labels,
            weights,
            intercept,
            config,
        )
        return cls(
            head_names=head_names,
            class_names=class_names,
            weights=weights,
            intercept=intercept,
            config=dict(config),
        )

    def predict_proba(self, logits: numpy.ndarray) -> numpy.ndarray:
        if logits.shape[1:] != (
            len(self.head_names),
            len(self.class_names),
        ):
            raise ValueError("V5 calibration schema differs")
        calibrated = (
            numpy.einsum("bhi,hij->bhj", logits, self.weights)
            + self.intercept
        )
        return _softmax(calibrated)

    def save(
        self, path_value: typing.Union[str, pathlib.Path]
    ) -> dict:
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        numpy.savez_compressed(
            path,
            schema_version=numpy.asarray([SCHEMA_VERSION]),
            head_names=numpy.asarray(self.head_names),
            class_names=numpy.asarray(self.class_names),
            weights=self.weights,
            intercept=self.intercept,
            config=numpy.asarray([json.dumps(self.config, sort_keys=True)]),
        )
        return v2._artifact(path)

    @classmethod
    def load(
        cls, path_value: typing.Union[str, pathlib.Path]
    ) -> "NumpyGroupedSoftmaxCalibrator":
        path = pathlib.Path(path_value).resolve()
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported V5 calibration schema")
            return cls(
                head_names=tuple(
                    str(value) for value in values["head_names"]
                ),
                class_names=tuple(
                    str(value) for value in values["class_names"]
                ),
                weights=values["weights"],
                intercept=values["intercept"],
                config=json.loads(str(values["config"][0])),
            )


@dataclasses.dataclass(frozen=True)
class V5Model:
    primary_model: NumpyGroupedSoftmaxModel
    calibrator: NumpyGroupedSoftmaxCalibrator
    expected_net_threshold_pct: float

    def predict(self, features: numpy.ndarray) -> dict[str, numpy.ndarray]:
        raw_logits = self.primary_model.predict_logits(features)
        probabilities = self.calibrator.predict_proba(raw_logits)
        probabilities = coherent_probability_surface(probabilities)
        decisions = path_decisions(probabilities)
        return {"probabilities": probabilities, **decisions}

    @classmethod
    def load(
        cls, directory_value: typing.Union[str, pathlib.Path]
    ) -> "V5Model":
        directory = pathlib.Path(directory_value).resolve()
        metadata = json.loads(
            (directory / "model.json").read_text(encoding="utf-8")
        )
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported V5 model schema")
        if metadata.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported V5 model protocol")
        primary = NumpyGroupedSoftmaxModel.load(directory / "primary.npz")
        calibrator = NumpyGroupedSoftmaxCalibrator.load(
            directory / "calibrator.npz"
        )
        if tuple(metadata.get("feature_names", ())) != primary.feature_names:
            raise ValueError("V5 persisted feature schema differs")
        if tuple(metadata.get("head_names", ())) != primary.head_names:
            raise ValueError("V5 persisted head schema differs")
        if calibrator.head_names != primary.head_names:
            raise ValueError("V5 calibration heads differ")
        return cls(
            primary_model=primary,
            calibrator=calibrator,
            expected_net_threshold_pct=float(
                metadata["expected_net_threshold_pct"]
            ),
        )


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "prediction_target": {
            "type": "mutually_exclusive_future_path_surface",
            "classes": list(CLASS_NAMES),
            "directions": list(DIRECTIONS),
            "protected_profit_targets_pct": list(TARGET_PROFITS_PCT),
            "activation_buffer_pct": ACTIVATION_BUFFER_PCT,
            "initial_stop_pct": INITIAL_STOP_PCT,
            "horizon_hours": list(HORIZON_HOURS),
            "same_candle_policy": "stop_wins",
            "future_used_for_labels_only": True,
        },
        "model": {
            "type": "shared_numpy_grouped_softmax",
            "heads": len(HEAD_SPECS),
            "primary_config": PRIMARY_CONFIG,
            "calibration": {
                "type": "per_head_joint_softmax_on_logits",
                "config": CALIBRATION_CONFIG,
            },
            "logical_projection": {
                "target_probability": (
                    "nonincreasing with target and nondecreasing with horizon"
                ),
                "non_target_split": (
                    "preserve calibrated STOP/TIMEOUT conditional ratio"
                ),
                "normalization": "STOP + TIMEOUT + TARGET equals one",
            },
        },
        "decision": {
            "expected_net_pct": (
                "P(TARGET)*protected_profit_pct "
                "- P(STOP)*initial_stop_pct - round_trip_cost_pct"
            ),
            "choose": (
                "maximum expected net configuration and direction per candle"
            ),
            "threshold_candidates_pct": list(
                EXPECTED_NET_THRESHOLDS_PCT
            ),
            "minimum_direction_margin_pct": (
                MINIMUM_DIRECTION_MARGIN_PCT
            ),
            "minimum_selection_trades": MINIMUM_SELECTION_TRADES,
            "one_trade_at_a_time": True,
            "selection_objective": (
                "compounded_net_return_pct minus maximum_drawdown_pct"
            ),
            "selection_gate": {
                "profit_factor": 1.10,
                "positive_compounded_return": True,
                "positive_objective": True,
                "at_least_one_trade_per_direction": True,
            },
        },
        "simulation": {
            "dynamic_protected_profit_and_horizon": True,
            "activation_pct": "protected profit target plus 0.20%",
            "protected_stop_active_from_next_candle": True,
            "funding_included": True,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        },
        "features": {
            "schema": "perfect_map_student_v1_99_causal_features",
            "feature_count": len(v1.student_feature_names()),
            "training_stride": TRAINING_STRIDE,
        },
        "splits": SPLITS,
        "evidence_policy": {
            "post_selection_periods": "diagnostic_reuse",
            "promotion_possible": False,
            "new_forward_dates_required": True,
        },
    }


def write_protocol(output_value: typing.Union[str, pathlib.Path]) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    path = output / "protocol.json"
    path.write_text(
        json.dumps(
            {**protocol, "protocol_sha256": _json_hash(protocol)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def future_path_outcomes(dataset: v1.StudentDataset) -> numpy.ndarray:
    """Return STOP/TIMEOUT/TARGET for every causal row and frozen head."""

    indices = dataset.candle_indices
    closes = dataset.candles[:, 4]
    highs = dataset.candles[:, 2]
    lows = dataset.candles[:, 3]
    entries = closes[indices]
    maximum_bars = max(HORIZON_BARS)
    stop_offsets = {}
    target_offsets = {}
    for direction in DIRECTIONS:
        sign = 1 if direction == percentage_engine.LONG else -1
        stop_level = entries * (1 - sign * INITIAL_STOP_PCT / 100)
        stop_offsets[direction] = _first_level_touch_offsets(
            indices,
            highs,
            lows,
            stop_level,
            direction,
            favorable=False,
            maximum_bars=maximum_bars,
        )
        for target in TARGET_PROFITS_PCT:
            activation = target + ACTIVATION_BUFFER_PCT
            target_level = entries * (1 + sign * activation / 100)
            target_offsets[(direction, target)] = (
                _first_level_touch_offsets(
                    indices,
                    highs,
                    lows,
                    target_level,
                    direction,
                    favorable=True,
                    maximum_bars=maximum_bars,
                )
            )
    outcomes = numpy.full(
        (len(dataset.labels), len(HEAD_SPECS)),
        TIMEOUT_CLASS,
        dtype=numpy.int8,
    )
    for head, spec in enumerate(HEAD_SPECS):
        stop = stop_offsets[spec.direction]
        target = target_offsets[
            (spec.direction, spec.target_profit_pct)
        ]
        stop_first = (
            (stop <= target) & (stop <= spec.horizon_bars)
        )
        target_first = (
            (target < stop) & (target <= spec.horizon_bars)
        )
        outcomes[stop_first, head] = STOP_CLASS
        outcomes[target_first, head] = TARGET_CLASS
    return outcomes


def coherent_probability_surface(
    probabilities: numpy.ndarray,
) -> numpy.ndarray:
    """Project path probabilities onto frozen target/horizon relationships."""

    expected_shape = (len(HEAD_SPECS), len(CLASS_NAMES))
    if probabilities.ndim != 3 or probabilities.shape[1:] != expected_shape:
        raise ValueError("V5 probability surface shape differs")
    reshaped = probabilities.reshape(
        len(probabilities),
        len(DIRECTIONS),
        len(TARGET_PROFITS_PCT),
        len(HORIZON_HOURS),
        len(CLASS_NAMES),
    )
    target_probability = reshaped[..., TARGET_CLASS].copy()
    target_probability = numpy.minimum.accumulate(
        target_probability, axis=2
    )
    target_probability = numpy.maximum.accumulate(
        target_probability, axis=3
    )
    non_target = (
        reshaped[..., STOP_CLASS] + reshaped[..., TIMEOUT_CLASS]
    )
    stop_share = numpy.divide(
        reshaped[..., STOP_CLASS],
        non_target,
        out=numpy.full_like(non_target, 0.5),
        where=non_target > 0,
    )
    stop_probability = (1.0 - target_probability) * stop_share
    timeout_probability = (
        1.0 - target_probability - stop_probability
    )
    result = numpy.empty_like(reshaped)
    result[..., TARGET_CLASS] = target_probability
    result[..., STOP_CLASS] = stop_probability
    result[..., TIMEOUT_CLASS] = timeout_probability
    return result.reshape(probabilities.shape)


def path_decisions(probabilities: numpy.ndarray) -> dict[str, numpy.ndarray]:
    reshaped = probabilities.reshape(
        len(probabilities),
        len(DIRECTIONS),
        len(TARGET_PROFITS_PCT),
        len(HORIZON_HOURS),
        len(CLASS_NAMES),
    )
    targets = numpy.asarray(TARGET_PROFITS_PCT)[None, None, :, None]
    expected_net = (
        reshaped[..., TARGET_CLASS] * targets
        - reshaped[..., STOP_CLASS] * INITIAL_STOP_PCT
        - ROUND_TRIP_COST_PCT
    )
    flattened = expected_net.reshape(
        len(probabilities), len(DIRECTIONS), -1
    )
    best_configuration = numpy.argmax(flattened, axis=2)
    best_expected_net = numpy.take_along_axis(
        flattened, best_configuration[..., None], axis=2
    )[..., 0]
    target_index = best_configuration // len(HORIZON_HOURS)
    horizon_index = best_configuration % len(HORIZON_HOURS)
    rows = numpy.arange(len(probabilities))[:, None]
    directions = numpy.arange(len(DIRECTIONS))[None, :]
    selected = reshaped[
        rows,
        directions,
        target_index,
        horizon_index,
    ]
    return {
        "expected_net_pct": best_expected_net,
        "target_index": target_index.astype(numpy.int8),
        "horizon_index": horizon_index.astype(numpy.int8),
        "target_probability": selected[..., TARGET_CLASS],
        "stop_probability": selected[..., STOP_CLASS],
        "timeout_probability": selected[..., TIMEOUT_CLASS],
    }


def decision_labels(
    predictions: dict[str, numpy.ndarray],
    threshold_pct: float,
) -> numpy.ndarray:
    scores = predictions["expected_net_pct"]
    labels = numpy.zeros(len(scores), dtype=numpy.int8)
    margin = numpy.abs(scores[:, 0] - scores[:, 1])
    eligible = (
        numpy.max(scores, axis=1) >= threshold_pct
    ) & (margin >= MINIMUM_DIRECTION_MARGIN_PCT)
    labels[eligible & (scores[:, 0] > scores[:, 1])] = v1.LONG
    labels[eligible & (scores[:, 1] > scores[:, 0])] = v1.SHORT
    return labels


def fit_v5(
    dataset: v1.StudentDataset,
    outcomes: numpy.ndarray,
) -> tuple[V5Model, dict]:
    train_mask = v1._date_mask(dataset.timestamps, *SPLITS["train"])
    train_rows = numpy.flatnonzero(train_mask)[::TRAINING_STRIDE]
    calibration_mask = v1._date_mask(
        dataset.timestamps, *SPLITS["calibration"]
    )
    calibration_rows = numpy.flatnonzero(calibration_mask)
    head_names = tuple(spec.name for spec in HEAD_SPECS)
    primary = NumpyGroupedSoftmaxModel.fit(
        dataset.features[train_rows],
        outcomes[train_rows],
        v1.student_feature_names(),
        head_names,
        CLASS_NAMES,
        PRIMARY_CONFIG,
    )
    calibration_logits = primary.predict_logits(
        dataset.features[calibration_rows]
    )
    calibrator = NumpyGroupedSoftmaxCalibrator.fit(
        calibration_logits,
        outcomes[calibration_rows],
        head_names,
        CLASS_NAMES,
        CALIBRATION_CONFIG,
    )
    calibrated = coherent_probability_surface(
        calibrator.predict_proba(calibration_logits)
    )
    return (
        V5Model(
            primary_model=primary,
            calibrator=calibrator,
            expected_net_threshold_pct=EXPECTED_NET_THRESHOLDS_PCT[0],
        ),
        {
            "training_rows": len(train_rows),
            "calibration_rows": len(calibration_rows),
            "heads": len(HEAD_SPECS),
            "calibration": surface_diagnostics(
                outcomes[calibration_rows], calibrated
            ),
            "outcome_rates_pct": _outcome_rates(
                outcomes[calibration_rows]
            ),
        },
    )


def select_threshold(
    model: V5Model,
    dataset: v1.StudentDataset,
    outcomes: numpy.ndarray,
    oracle: v2.SparseOracle,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> tuple[float, list[dict], dict]:
    mask = v1._date_mask(
        dataset.timestamps, *SPLITS["threshold_selection"]
    )
    rows = numpy.flatnonzero(mask)
    subset = dataset.take(mask)
    predictions = model.predict(subset.features)
    table = []
    for threshold in EXPECTED_NET_THRESHOLDS_PCT:
        trades = simulate_predictions(
            subset, predictions, threshold, funding_series
        )
        metrics = h2_backtest._metrics(trades, ROUND_TRIP_COST_PCT)
        objective = (
            metrics["compounded_net_return_pct"]
            - metrics["maximum_drawdown_pct"]
        )
        table.append(
            {
                "threshold_pct": threshold,
                "eligible": metrics["trades"] >= MINIMUM_SELECTION_TRADES,
                "objective": objective,
                "metrics": metrics,
            }
        )
    eligible = [value for value in table if value["eligible"]]
    selected = max(
        eligible or table,
        key=lambda value: (value["objective"], value["metrics"]["trades"]),
    )
    metrics = selected["metrics"]
    gate = {
        "minimum_trades": metrics["trades"] >= MINIMUM_SELECTION_TRADES,
        "profit_factor": (
            metrics["profit_factor"] is not None
            and metrics["profit_factor"] >= 1.10
        ),
        "positive_compounded_return": (
            metrics["compounded_net_return_pct"] > 0
        ),
        "positive_objective": selected["objective"] > 0,
        "at_least_one_trade_per_direction": (
            metrics["by_direction"]["LONG"]["trades"] > 0
            and metrics["by_direction"]["SHORT"]["trades"] > 0
        ),
    }
    predicted = decision_labels(
        predictions, float(selected["threshold_pct"])
    )
    zones = v3.anticipatory_zone_labels(
        dataset, oracle, SPLITS["threshold_selection"]
    )
    return (
        float(selected["threshold_pct"]),
        table,
        {
            "results": gate,
            "passed": all(gate.values()),
            "surface": surface_diagnostics(
                outcomes[rows], predictions["probabilities"]
            ),
            "zone_classification": v2.sparse_classification_metrics(
                zones[rows], predicted
            ),
            "decision_distribution": decision_diagnostics(
                predictions, predicted
            ),
        },
    )


def simulate_predictions(
    dataset: v1.StudentDataset,
    predictions: dict[str, numpy.ndarray],
    threshold_pct: float,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> list[dict]:
    labels = decision_labels(predictions, threshold_pct)
    candidates = []
    for row in numpy.flatnonzero(labels != v1.WAIT):
        direction_index = 0 if labels[row] == v1.LONG else 1
        target_index = int(
            predictions["target_index"][row, direction_index]
        )
        horizon_index = int(
            predictions["horizon_index"][row, direction_index]
        )
        candidates.append(
            {
                "entry_index": int(dataset.candle_indices[row]),
                "direction": DIRECTIONS[direction_index],
                "expected_net_pct": float(
                    predictions["expected_net_pct"][row, direction_index]
                ),
                "opposite_expected_net_pct": float(
                    predictions["expected_net_pct"][row, 1 - direction_index]
                ),
                "target_probability_pct": float(
                    predictions["target_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "stop_probability_pct": float(
                    predictions["stop_probability"][row, direction_index]
                    * 100
                ),
                "timeout_probability_pct": float(
                    predictions["timeout_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "target_profit_pct": TARGET_PROFITS_PCT[target_index],
                "horizon_hours": HORIZON_HOURS[horizon_index],
            }
        )
    close_times = (
        dataset.candles[:, 0].astype(numpy.int64) + v1.CANDLE_SECONDS
    ).tolist()
    funding_timestamps, funding_rates = funding_series
    next_available = 0
    trades = []
    for candidate in candidates:
        entry_index = candidate["entry_index"]
        if entry_index < next_available:
            continue
        config = percentage_engine.PercentageEngineConfig(
            minimum_profit_pct=candidate["target_profit_pct"],
            activation_pct=(
                candidate["target_profit_pct"] + ACTIVATION_BUFFER_PCT
            ),
            initial_stop_pct=INITIAL_STOP_PCT,
            horizon_candles=candidate["horizon_hours"] * 4,
            directions=(candidate["direction"],),
            exclude_last_candle=False,
        )
        trade = percentage_engine.simulate_trade(
            close_times,
            dataset.candles[:, 2],
            dataset.candles[:, 3],
            dataset.candles[:, 4],
            entry_index,
            candidate["direction"],
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
        sign = (
            1 if trade["direction"] == percentage_engine.LONG else -1
        )
        funding_cost_pct = sign * float(
            numpy.sum(funding_rates[first:last])
        ) * 100
        trades.append(
            {
                "direction": trade["direction"],
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
                **{
                    name: value
                    for name, value in candidate.items()
                    if name != "entry_index"
                },
            }
        )
        next_available = int(trade["exit_index"]) + 1
    return trades


def evaluate_audit(
    *,
    name: str,
    model: V5Model,
    dataset: v1.StudentDataset,
    outcomes: numpy.ndarray,
    oracle: v2.SparseOracle,
    date_range: tuple[str, str],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    exchange: str,
) -> tuple[dict, list[dict], dict]:
    mask = v1._date_mask(dataset.timestamps, *date_range)
    rows = numpy.flatnonzero(mask)
    subset = dataset.take(mask)
    predictions = model.predict(subset.features)
    trades = simulate_predictions(
        subset,
        predictions,
        model.expected_net_threshold_pct,
        funding_series,
    )
    for trade in trades:
        trade["exchange"] = exchange
    predicted = decision_labels(
        predictions, model.expected_net_threshold_pct
    )
    zones = v3.anticipatory_zone_labels(dataset, oracle, date_range)
    metrics = h2_backtest._metrics(trades, ROUND_TRIP_COST_PCT)
    metrics.update(v4._excursion_metrics(trades))
    return (
        {
            "name": name,
            "evidence_role": "diagnostic_reuse",
            "start": date_range[0],
            "end": date_range[1],
            "surface": surface_diagnostics(
                outcomes[rows], predictions["probabilities"]
            ),
            "zone_classification": v2.sparse_classification_metrics(
                zones[rows], predicted
            ),
            "decision_distribution": decision_diagnostics(
                predictions, predicted
            ),
            "economic": metrics,
        },
        trades,
        {
            "timestamps": subset.timestamps,
            "observed": outcomes[rows],
            "predicted_direction": predicted,
            **predictions,
        },
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
        raise FileNotFoundError("write protocol.json before running V5")
    protocol = frozen_protocol()
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(protocol):
        raise ValueError("persisted V5 protocol differs from frozen code")
    binance_path = pathlib.Path(binance_collector).resolve()
    binance_funding_path = pathlib.Path(binance_funding).resolve()
    kucoin_path = pathlib.Path(kucoin_collector).resolve()
    kucoin_funding_path = pathlib.Path(kucoin_funding).resolve()
    binance_dataset = v1.build_dataset(
        h2_backtest._load_btc_15m(binance_path, "15m")
    )
    kucoin_dataset = v1.build_dataset(
        h2_backtest._load_btc_15m(kucoin_path, "5m")
    )
    binance_outcomes = future_path_outcomes(binance_dataset)
    kucoin_outcomes = future_path_outcomes(kucoin_dataset)
    binance_funding_values = v1._btc_funding(binance_funding_path)
    kucoin_funding_values = v1._btc_funding(kucoin_funding_path)
    binance_oracles = {
        name: v2.sparse_oracle(binance_dataset, date_range)
        for name, date_range in SPLITS.items()
        if name != "kucoin_reused_audit"
    }
    kucoin_oracle = v2.sparse_oracle(
        kucoin_dataset, SPLITS["kucoin_reused_audit"]
    )
    base_model, fit_report = fit_v5(
        binance_dataset, binance_outcomes
    )
    threshold, threshold_table, selection_gate = select_threshold(
        base_model,
        binance_dataset,
        binance_outcomes,
        binance_oracles["threshold_selection"],
        binance_funding_values,
    )
    model = dataclasses.replace(
        base_model, expected_net_threshold_pct=threshold
    )
    binance_audit, binance_trades, binance_predictions = evaluate_audit(
        name="binance_reused_2025_v5",
        model=model,
        dataset=binance_dataset,
        outcomes=binance_outcomes,
        oracle=binance_oracles["binance_reused_audit"],
        date_range=SPLITS["binance_reused_audit"],
        funding_series=binance_funding_values,
        exchange="binance_usdm",
    )
    kucoin_audit, kucoin_trades, kucoin_predictions = evaluate_audit(
        name="kucoin_reused_2026_v5",
        model=model,
        dataset=kucoin_dataset,
        outcomes=kucoin_outcomes,
        oracle=kucoin_oracle,
        date_range=SPLITS["kucoin_reused_audit"],
        funding_series=kucoin_funding_values,
        exchange="kucoin_futures",
    )
    output.mkdir(parents=True, exist_ok=True)
    model_artifacts = _save_model(model, output / "model")
    predictions_path = output / "predictions.npz"
    numpy.savez_compressed(
        predictions_path,
        **{
            f"binance_{name}": values
            for name, values in binance_predictions.items()
        },
        **{
            f"kucoin_{name}": values
            for name, values in kucoin_predictions.items()
        },
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
        "fit": fit_report,
        "selected_expected_net_threshold_pct": threshold,
        "threshold_selection": threshold_table,
        "selection_gate": selection_gate,
        "diagnostic_reuse_audits": {
            "binance": binance_audit,
            "kucoin": kucoin_audit,
        },
        "promotion_eligible": False,
        "promotion_blocker": (
            "All post-selection dates were consumed by V1-V4; new forward "
            "dates are required."
        ),
        "artifacts": {
            "protocol": v2._artifact(protocol_path),
            "model": model_artifacts,
            "predictions": v2._artifact(predictions_path),
            "inputs": {
                "binance_collector": v2._artifact(binance_path),
                "binance_funding": v2._artifact(binance_funding_path),
                "kucoin_collector": v2._artifact(kucoin_path),
                "kucoin_funding": v2._artifact(kucoin_funding_path),
            },
        },
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
                "binance_diagnostic_reuse": binance_trades,
                "kucoin_diagnostic_reuse": kucoin_trades,
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


def surface_diagnostics(
    observed: numpy.ndarray, probabilities: numpy.ndarray
) -> dict:
    clipped = numpy.clip(probabilities, 1e-12, 1.0)
    rows = numpy.arange(len(observed))[:, None]
    heads = numpy.arange(observed.shape[1])[None, :]
    selected = clipped[rows, heads, observed]
    one_hot = numpy.eye(len(CLASS_NAMES))[observed]
    predicted = numpy.argmax(probabilities, axis=2)
    return {
        "examples": len(observed),
        "heads": observed.shape[1],
        "accuracy_pct": float(numpy.mean(predicted == observed) * 100),
        "log_loss": float(-numpy.mean(numpy.log(selected))),
        "multiclass_brier_score": float(
            numpy.mean(numpy.sum((probabilities - one_hot) ** 2, axis=2))
        ),
        "mean_target_probability_pct": float(
            numpy.mean(probabilities[..., TARGET_CLASS]) * 100
        ),
        "observed_target_rate_pct": float(
            numpy.mean(observed == TARGET_CLASS) * 100
        ),
        "mean_stop_probability_pct": float(
            numpy.mean(probabilities[..., STOP_CLASS]) * 100
        ),
        "observed_stop_rate_pct": float(
            numpy.mean(observed == STOP_CLASS) * 100
        ),
    }


def decision_diagnostics(
    predictions: dict[str, numpy.ndarray],
    labels: numpy.ndarray,
) -> dict:
    selected = labels != v1.WAIT
    if not numpy.any(selected):
        return {
            "signals": 0,
            "long_signals": 0,
            "short_signals": 0,
            "target_profit_pct": {},
            "horizon_hours": {},
        }
    direction_indices = numpy.where(labels[selected] == v1.LONG, 0, 1)
    selected_rows = numpy.flatnonzero(selected)
    target_indices = predictions["target_index"][
        selected_rows, direction_indices
    ]
    horizon_indices = predictions["horizon_index"][
        selected_rows, direction_indices
    ]
    return {
        "signals": int(numpy.sum(selected)),
        "long_signals": int(numpy.sum(labels == v1.LONG)),
        "short_signals": int(numpy.sum(labels == v1.SHORT)),
        "mean_expected_net_pct": float(
            numpy.mean(
                predictions["expected_net_pct"][
                    selected_rows, direction_indices
                ]
            )
        ),
        "mean_target_probability_pct": float(
            numpy.mean(
                predictions["target_probability"][
                    selected_rows, direction_indices
                ]
            )
            * 100
        ),
        "target_profit_pct": {
            str(target): int(numpy.sum(target_indices == index))
            for index, target in enumerate(TARGET_PROFITS_PCT)
        },
        "horizon_hours": {
            str(hours): int(numpy.sum(horizon_indices == index))
            for index, hours in enumerate(HORIZON_HOURS)
        },
    }


def _save_model(model: V5Model, directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "primary": model.primary_model.save(directory / "primary.npz"),
        "calibrator": model.calibrator.save(
            directory / "calibrator.npz"
        ),
    }
    metadata_path = directory / "model.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "research_only": True,
                "orders_authorized": False,
                "feature_names": list(model.primary_model.feature_names),
                "head_names": list(model.primary_model.head_names),
                "class_names": list(CLASS_NAMES),
                "expected_net_threshold_pct": (
                    model.expected_net_threshold_pct
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts["metadata"] = v2._artifact(metadata_path)
    return artifacts


def _first_level_touch_offsets(
    indices: numpy.ndarray,
    highs: numpy.ndarray,
    lows: numpy.ndarray,
    levels: numpy.ndarray,
    direction: str,
    *,
    favorable: bool,
    maximum_bars: int,
) -> numpy.ndarray:
    missing = maximum_bars + 1
    offsets = numpy.full(len(indices), missing, dtype=numpy.int16)
    for offset in range(1, maximum_bars + 1):
        unresolved = offsets == missing
        if not numpy.any(unresolved):
            break
        future_indices = indices[unresolved] + offset
        if favorable:
            touched = (
                highs[future_indices] >= levels[unresolved]
                if direction == percentage_engine.LONG
                else lows[future_indices] <= levels[unresolved]
            )
        else:
            touched = (
                lows[future_indices] <= levels[unresolved]
                if direction == percentage_engine.LONG
                else highs[future_indices] >= levels[unresolved]
            )
        unresolved_rows = numpy.flatnonzero(unresolved)
        offsets[unresolved_rows[touched]] = offset
    return offsets


def _validate_grouped_training(
    features: numpy.ndarray,
    labels: numpy.ndarray,
    head_names: tuple[str, ...],
    class_names: tuple[str, ...],
) -> None:
    if features.ndim != 2 or labels.ndim != 2 or not len(labels):
        raise ValueError("V5 grouped training data is empty")
    if len(features) != len(labels) or labels.shape[1] != len(head_names):
        raise ValueError("V5 grouped training data is misaligned")
    for head in range(len(head_names)):
        if set(numpy.unique(labels[:, head])) != set(
            range(len(class_names))
        ):
            raise ValueError("every V5 head must contain every class")


def _fit_grouped_parameters(
    features: numpy.ndarray,
    labels: numpy.ndarray,
    weights: numpy.ndarray,
    intercept: numpy.ndarray,
    config: dict,
    *,
    regularization_target: numpy.ndarray,
) -> None:
    first_weight = numpy.zeros_like(weights)
    second_weight = numpy.zeros_like(weights)
    first_intercept = numpy.zeros_like(intercept)
    second_intercept = numpy.zeros_like(intercept)
    generator = numpy.random.default_rng(int(config["seed"]))
    step = 0
    head_rows = numpy.arange(labels.shape[1])[None, :]
    for _ in range(int(config["epochs"])):
        permutation = generator.permutation(len(labels))
        for start in range(0, len(labels), int(config["batch_size"])):
            indices = permutation[
                start : start + int(config["batch_size"])
            ]
            batch = features[indices].astype(numpy.float64, copy=False)
            errors = _softmax(
                numpy.einsum("bf,fhc->bhc", batch, weights) + intercept
            )
            batch_rows = numpy.arange(len(indices))[:, None]
            errors[batch_rows, head_rows, labels[indices]] -= 1
            errors /= len(indices) * labels.shape[1]
            weight_gradient = (
                numpy.einsum("bf,bhc->fhc", batch, errors)
                + float(config["l2"])
                * (weights - regularization_target)
            )
            intercept_gradient = numpy.sum(errors, axis=0)
            step += 1
            _adam_update(
                weights,
                weight_gradient,
                first_weight,
                second_weight,
                step,
                float(config["learning_rate"]),
            )
            _adam_update(
                intercept,
                intercept_gradient,
                first_intercept,
                second_intercept,
                step,
                float(config["learning_rate"]),
            )


def _fit_calibration_parameters(
    logits: numpy.ndarray,
    labels: numpy.ndarray,
    weights: numpy.ndarray,
    intercept: numpy.ndarray,
    config: dict,
) -> None:
    first_weight = numpy.zeros_like(weights)
    second_weight = numpy.zeros_like(weights)
    first_intercept = numpy.zeros_like(intercept)
    second_intercept = numpy.zeros_like(intercept)
    identity = numpy.repeat(
        numpy.eye(weights.shape[1])[None, :, :],
        weights.shape[0],
        axis=0,
    )
    generator = numpy.random.default_rng(int(config["seed"]))
    step = 0
    head_rows = numpy.arange(labels.shape[1])[None, :]
    for _ in range(int(config["epochs"])):
        permutation = generator.permutation(len(labels))
        for start in range(0, len(labels), int(config["batch_size"])):
            indices = permutation[
                start : start + int(config["batch_size"])
            ]
            batch = logits[indices]
            errors = _softmax(
                numpy.einsum("bhi,hij->bhj", batch, weights) + intercept
            )
            batch_rows = numpy.arange(len(indices))[:, None]
            errors[batch_rows, head_rows, labels[indices]] -= 1
            errors /= len(indices) * labels.shape[1]
            weight_gradient = (
                numpy.einsum("bhi,bhj->hij", batch, errors)
                + float(config["l2"]) * (weights - identity)
            )
            intercept_gradient = numpy.sum(errors, axis=0)
            step += 1
            _adam_update(
                weights,
                weight_gradient,
                first_weight,
                second_weight,
                step,
                float(config["learning_rate"]),
            )
            _adam_update(
                intercept,
                intercept_gradient,
                first_intercept,
                second_intercept,
                step,
                float(config["learning_rate"]),
            )


def _adam_update(
    values: numpy.ndarray,
    gradient: numpy.ndarray,
    first: numpy.ndarray,
    second: numpy.ndarray,
    step: int,
    learning_rate: float,
) -> None:
    first *= 0.9
    first += 0.1 * gradient
    second *= 0.999
    second += 0.001 * gradient * gradient
    corrected_first = first / (1 - 0.9**step)
    corrected_second = second / (1 - 0.999**step)
    values -= (
        learning_rate
        * corrected_first
        / (numpy.sqrt(corrected_second) + 1e-8)
    )


def _softmax(logits: numpy.ndarray) -> numpy.ndarray:
    shifted = logits - numpy.max(logits, axis=-1, keepdims=True)
    exponentials = numpy.exp(numpy.clip(shifted, -60.0, 0.0))
    return exponentials / numpy.sum(
        exponentials, axis=-1, keepdims=True
    )


def _outcome_rates(outcomes: numpy.ndarray) -> dict:
    return {
        name: float(numpy.mean(outcomes == index) * 100)
        for index, name in enumerate(CLASS_NAMES)
    }


def _json_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binance-collector")
    parser.add_argument("--binance-funding")
    parser.add_argument("--kucoin-collector")
    parser.add_argument("--kucoin-funding")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--write-protocol-only", action="store_true")
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
        parser.error("all collector and funding paths are required")
    result = run_study(
        binance_collector=args.binance_collector,
        binance_funding=args.binance_funding,
        kucoin_collector=args.kucoin_collector,
        kucoin_funding=args.kucoin_funding,
        output_directory=args.output_directory,
    )
    print(
        json.dumps(
            {
                "report_path": result["report_path"],
                "selected_expected_net_threshold_pct": result[
                    "selected_expected_net_threshold_pct"
                ],
                "selection_gate": result["selection_gate"],
                "diagnostic_reuse_audits": result[
                    "diagnostic_reuse_audits"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
