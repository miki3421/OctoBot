"""Coupled, base-rate-normalized V4 student of the perfect percentage map.

V4 replaces independent directional zone models with one portable NumPy
softmax WAIT/LONG/SHORT model and a joint softmax calibration layer. Auxiliary
quality and speed probabilities contribute only as lift over their own
calibration base rates. The experiment is offline and cannot authorize orders.
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

from octobot.ai_strategy_lab import h2_backtest
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_probability_engine as probability_module
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2
from octobot.ai_strategy_lab import perfect_map_student_v3 as v3


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_perfect_map_coupled_student_v4"
CLASS_NAMES = ("WAIT", "LONG_ZONE", "SHORT_ZONE")
WAIT_CLASS = 0
LONG_CLASS = 1
SHORT_CLASS = 2
PRIMARY_CONFIG = {
    "epochs": 30,
    "batch_size": 4096,
    "learning_rate": 0.012,
    "l2": 0.002,
    "seed": 20_260_727,
}
CALIBRATION_CONFIG = {
    "epochs": 80,
    "batch_size": 4096,
    "learning_rate": 0.01,
    "l2": 0.01,
    "seed": 20_260_728,
}
SUPPORT_WEIGHTS = {
    "base": 0.65,
    "quality_lift": 0.25,
    "fast_lift": 0.10,
}
MAXIMUM_AUXILIARY_LIFT = 2.0
MINIMUM_DIRECTION_MARGIN = 0.01
THRESHOLD_CANDIDATES = (0.03, 0.05, 0.075, 0.10, 0.125, 0.15, 0.20, 0.25)
MINIMUM_SELECTION_TRADES = 15
SPLITS = v3.SPLITS


@dataclasses.dataclass
class NumpySoftmaxModel:
    feature_names: tuple[str, ...]
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
        class_names: tuple[str, ...],
        config: dict,
    ) -> "NumpySoftmaxModel":
        if len(features) != len(labels) or not len(labels):
            raise ValueError("softmax training data is empty or misaligned")
        class_count = len(class_names)
        if set(numpy.unique(labels)) != set(range(class_count)):
            raise ValueError("softmax training labels must contain every class")
        mean = numpy.mean(features, axis=0, dtype=numpy.float64)
        scale = numpy.std(features, axis=0, dtype=numpy.float64)
        scale[scale < 1e-9] = 1.0
        standardized = numpy.clip(
            (features.astype(numpy.float64) - mean) / scale,
            -12.0,
            12.0,
        ).astype(numpy.float32)
        weights = numpy.zeros(
            (standardized.shape[1], class_count), dtype=numpy.float64
        )
        counts = numpy.bincount(labels, minlength=class_count).astype(float)
        priors = numpy.maximum(counts / len(labels), 1e-9)
        intercept = numpy.log(priors)
        weight_first = numpy.zeros_like(weights)
        weight_second = numpy.zeros_like(weights)
        intercept_first = numpy.zeros_like(intercept)
        intercept_second = numpy.zeros_like(intercept)
        beta_one = 0.9
        beta_two = 0.999
        epsilon = 1e-8
        step = 0
        generator = numpy.random.default_rng(int(config["seed"]))
        for _ in range(int(config["epochs"])):
            permutation = generator.permutation(len(labels))
            for start in range(
                0, len(labels), int(config["batch_size"])
            ):
                indices = permutation[
                    start : start + int(config["batch_size"])
                ]
                batch = standardized[indices].astype(
                    numpy.float64, copy=False
                )
                probabilities = _softmax(batch @ weights + intercept)
                probabilities[
                    numpy.arange(len(indices)), labels[indices]
                ] -= 1
                probabilities /= len(indices)
                weight_gradient = (
                    batch.T @ probabilities
                    + float(config["l2"]) * weights
                )
                intercept_gradient = numpy.sum(probabilities, axis=0)
                step += 1
                weight_first = (
                    beta_one * weight_first
                    + (1 - beta_one) * weight_gradient
                )
                weight_second = (
                    beta_two * weight_second
                    + (1 - beta_two) * weight_gradient * weight_gradient
                )
                intercept_first = (
                    beta_one * intercept_first
                    + (1 - beta_one) * intercept_gradient
                )
                intercept_second = (
                    beta_two * intercept_second
                    + (1 - beta_two)
                    * intercept_gradient
                    * intercept_gradient
                )
                corrected_weight_first = weight_first / (
                    1 - beta_one**step
                )
                corrected_weight_second = weight_second / (
                    1 - beta_two**step
                )
                corrected_intercept_first = intercept_first / (
                    1 - beta_one**step
                )
                corrected_intercept_second = intercept_second / (
                    1 - beta_two**step
                )
                weights -= (
                    float(config["learning_rate"])
                    * corrected_weight_first
                    / (numpy.sqrt(corrected_weight_second) + epsilon)
                )
                intercept -= (
                    float(config["learning_rate"])
                    * corrected_intercept_first
                    / (numpy.sqrt(corrected_intercept_second) + epsilon)
                )
        return cls(
            feature_names=feature_names,
            class_names=class_names,
            mean=mean,
            scale=scale,
            weights=weights,
            intercept=intercept,
            config=dict(config),
        )

    def predict_logits(self, features: numpy.ndarray) -> numpy.ndarray:
        if features.shape[1] != len(self.feature_names):
            raise ValueError("softmax feature schema differs")
        standardized = numpy.clip(
            (features.astype(numpy.float64) - self.mean) / self.scale,
            -12.0,
            12.0,
        )
        return standardized @ self.weights + self.intercept

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
    ) -> "NumpySoftmaxModel":
        path = pathlib.Path(path_value).resolve()
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported V4 softmax schema")
            return cls(
                feature_names=tuple(
                    str(value) for value in values["feature_names"]
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


@dataclasses.dataclass(frozen=True)
class V4Model:
    primary_model: NumpySoftmaxModel
    calibration_model: NumpySoftmaxModel
    auxiliary_models: dict[str, model_module.NumpyLogisticModel]
    auxiliary_calibrators: dict[
        str, probability_module.QuantileIsotonicCalibrator
    ]
    auxiliary_base_rates: dict[str, float]
    threshold: float

    @classmethod
    def load(
        cls, directory_value: typing.Union[str, pathlib.Path]
    ) -> "V4Model":
        directory = pathlib.Path(directory_value).resolve()
        metadata = json.loads(
            (directory / "model.json").read_text(encoding="utf-8")
        )
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported V4 model schema")
        if metadata.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported V4 model protocol")
        if tuple(metadata.get("class_names", ())) != CLASS_NAMES:
            raise ValueError("V4 model class schema differs")
        primary_model = NumpySoftmaxModel.load(
            directory / "primary_model.npz"
        )
        if tuple(metadata.get("feature_names", ())) != (
            primary_model.feature_names
        ):
            raise ValueError("V4 model feature schema differs")
        calibration_model = NumpySoftmaxModel.load(
            directory / "calibration_model.npz"
        )
        auxiliary_names = (
            "long_quality",
            "short_quality",
            "long_fast",
            "short_fast",
        )
        auxiliary_models = {
            name: model_module.NumpyLogisticModel.load(
                directory / f"{name}_model.npz"
            )
            for name in auxiliary_names
        }
        if any(
            child.feature_names != primary_model.feature_names
            for child in auxiliary_models.values()
        ):
            raise ValueError("V4 auxiliary feature schema differs")
        return cls(
            primary_model=primary_model,
            calibration_model=calibration_model,
            auxiliary_models=auxiliary_models,
            auxiliary_calibrators={
                name: probability_module.QuantileIsotonicCalibrator.load(
                    directory / f"{name}_calibrator.json"
                )
                for name in auxiliary_names
            },
            auxiliary_base_rates={
                name: float(metadata["auxiliary_base_rates"][name])
                for name in auxiliary_names
            },
            threshold=float(metadata["threshold"]),
        )

    def predict(self, features: numpy.ndarray) -> dict[str, numpy.ndarray]:
        primary_logits = self.primary_model.predict_logits(features)
        primary = self.calibration_model.predict_proba(primary_logits)
        heads = {
            name: self.auxiliary_calibrators[name].predict(
                model.predict_proba(features)
            )
            for name, model in self.auxiliary_models.items()
        }
        long_score, short_score = normalized_scores(
            primary, heads, self.auxiliary_base_rates
        )
        return {
            "primary": primary,
            "long_score": long_score,
            "short_score": short_score,
            **heads,
        }


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "target": {
            "source": "V3 anticipatory zones",
            "classes": list(CLASS_NAMES),
            "zone_lead_bars": v3.ZONE_LEAD_BARS,
            "future_used_for_labels_only": True,
        },
        "primary_model": {
            "type": "portable_numpy_multiclass_softmax",
            "config": PRIMARY_CONFIG,
            "joint_calibration": {
                "type": "softmax_on_primary_logits",
                "config": CALIBRATION_CONFIG,
                "purpose": (
                    "joint prior and directional-confusion correction"
                ),
            },
        },
        "auxiliary_heads": {
            "targets": [
                "long_quality",
                "short_quality",
                "long_fast",
                "short_fast",
            ],
            "model_config": dataclasses.asdict(
                v3.AUXILIARY_MODEL_CONFIG
            ),
            "normalization": "probability divided by same-head calibration rate",
            "maximum_lift": MAXIMUM_AUXILIARY_LIFT,
        },
        "decision": {
            "score": "joint zone probability times normalized support",
            "support_weights": SUPPORT_WEIGHTS,
            "threshold_candidates": list(THRESHOLD_CANDIDATES),
            "minimum_direction_margin": MINIMUM_DIRECTION_MARGIN,
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
        "features": {
            "schema": "perfect_map_student_v1_99_causal_features",
            "feature_count": len(v1.student_feature_names()),
        },
        "economics": {
            "round_trip_cost_pct": v1.ROUND_TRIP_COST_PCT,
            "funding_included": True,
            "same_conservative_exit_as_percentage_map": True,
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


def fit_v4(
    dataset: v1.StudentDataset,
    train_oracle: v2.SparseOracle,
    calibration_oracle: v2.SparseOracle,
) -> tuple[V4Model, dict]:
    train_zone = v3.anticipatory_zone_labels(
        dataset, train_oracle, SPLITS["train"]
    )
    calibration_zone = v3.anticipatory_zone_labels(
        dataset, calibration_oracle, SPLITS["calibration"]
    )
    train_mask = v1._date_mask(dataset.timestamps, *SPLITS["train"])
    zone_rows = v3.sample_zone_training_rows(
        train_zone, train_oracle, train_mask
    )
    zone_classes = _zone_classes(train_zone)
    primary_model = NumpySoftmaxModel.fit(
        dataset.features[zone_rows],
        zone_classes[zone_rows],
        v1.student_feature_names(),
        CLASS_NAMES,
        PRIMARY_CONFIG,
    )
    calibration_mask = v1._date_mask(
        dataset.timestamps, *SPLITS["calibration"]
    )
    calibration_rows = numpy.flatnonzero(calibration_mask)
    primary_logits = primary_model.predict_logits(
        dataset.features[calibration_rows]
    )
    calibration_model = NumpySoftmaxModel.fit(
        primary_logits,
        _zone_classes(calibration_zone)[calibration_rows],
        ("wait_logit", "long_logit", "short_logit"),
        CLASS_NAMES,
        CALIBRATION_CONFIG,
    )

    paths = v3.path_targets(dataset)
    auxiliary_labels = {
        "long_quality": paths.long_quality,
        "short_quality": paths.short_quality,
        "long_fast": paths.long_fast,
        "short_fast": paths.short_fast,
    }
    auxiliary_rows = numpy.flatnonzero(train_mask)[::v1.TRAINING_STRIDE]
    auxiliary_models = {}
    auxiliary_calibrators = {}
    auxiliary_base_rates = {}
    for offset, (name, labels) in enumerate(auxiliary_labels.items()):
        model = model_module.NumpyLogisticModel.fit(
            dataset.features[auxiliary_rows],
            labels[auxiliary_rows],
            v1.student_feature_names(),
            dataclasses.replace(
                v3.AUXILIARY_MODEL_CONFIG,
                seed=v3.AUXILIARY_MODEL_CONFIG.seed + 20 + offset,
            ),
        )
        calibrator = probability_module.QuantileIsotonicCalibrator.fit(
            model.predict_proba(dataset.features[calibration_rows]),
            labels[calibration_rows],
            minimum_rows_per_bin=100,
        )
        auxiliary_models[name] = model
        auxiliary_calibrators[name] = calibrator
        auxiliary_base_rates[name] = float(
            numpy.mean(labels[calibration_rows])
        )
    model = V4Model(
        primary_model=primary_model,
        calibration_model=calibration_model,
        auxiliary_models=auxiliary_models,
        auxiliary_calibrators=auxiliary_calibrators,
        auxiliary_base_rates=auxiliary_base_rates,
        threshold=THRESHOLD_CANDIDATES[0],
    )
    calibrated_primary = calibration_model.predict_proba(primary_logits)
    return model, {
        "zone_training_rows": len(zone_rows),
        "zone_training_distribution": v1._class_distribution(
            train_zone[zone_rows]
        ),
        "calibration_rows": len(calibration_rows),
        "calibration_zone_distribution": v1._class_distribution(
            calibration_zone[calibration_rows]
        ),
        "auxiliary_training_rows": len(auxiliary_rows),
        "auxiliary_base_rates_pct": {
            name: value * 100
            for name, value in auxiliary_base_rates.items()
        },
        "primary_calibration": multiclass_diagnostics(
            _zone_classes(calibration_zone)[calibration_rows],
            calibrated_primary,
        ),
    }


def normalized_scores(
    primary_probabilities: numpy.ndarray,
    heads: dict[str, numpy.ndarray],
    base_rates: dict[str, float],
) -> tuple[numpy.ndarray, numpy.ndarray]:
    def lift(name: str) -> numpy.ndarray:
        base = max(base_rates[name], numpy.finfo(float).tiny)
        return numpy.clip(
            heads[name] / base, 0.0, MAXIMUM_AUXILIARY_LIFT
        )

    long_support = (
        SUPPORT_WEIGHTS["base"]
        + SUPPORT_WEIGHTS["quality_lift"] * lift("long_quality")
        + SUPPORT_WEIGHTS["fast_lift"] * lift("long_fast")
    )
    short_support = (
        SUPPORT_WEIGHTS["base"]
        + SUPPORT_WEIGHTS["quality_lift"] * lift("short_quality")
        + SUPPORT_WEIGHTS["fast_lift"] * lift("short_fast")
    )
    return (
        primary_probabilities[:, LONG_CLASS] * long_support,
        primary_probabilities[:, SHORT_CLASS] * short_support,
    )


def select_threshold(
    model: V4Model,
    dataset: v1.StudentDataset,
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
    for threshold in THRESHOLD_CANDIDATES:
        trades = v2.simulate_predictions(
            subset,
            predictions["long_score"],
            predictions["short_score"],
            threshold,
            funding_series,
            minimum_direction_margin=MINIMUM_DIRECTION_MARGIN,
        )
        metrics = h2_backtest._metrics(
            trades, v1.ROUND_TRIP_COST_PCT
        )
        objective = (
            metrics["compounded_net_return_pct"]
            - metrics["maximum_drawdown_pct"]
        )
        table.append(
            {
                "threshold": threshold,
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
    gate_results = {
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
    zone_labels = v3.anticipatory_zone_labels(
        dataset, oracle, SPLITS["threshold_selection"]
    )
    predicted = v2.prediction_labels(
        predictions["long_score"],
        predictions["short_score"],
        float(selected["threshold"]),
        MINIMUM_DIRECTION_MARGIN,
    )
    paths = v3.path_targets(dataset)
    return (
        float(selected["threshold"]),
        table,
        {
            "results": gate_results,
            "passed": all(gate_results.values()),
            "zone_classification": v2.sparse_classification_metrics(
                zone_labels[rows], predicted
            ),
            "primary": multiclass_diagnostics(
                _zone_classes(zone_labels)[rows],
                predictions["primary"],
            ),
            "auxiliary": v3._head_diagnostics(
                predictions, paths, rows
            ),
        },
    )


def evaluate_audit(
    *,
    name: str,
    model: V4Model,
    dataset: v1.StudentDataset,
    oracle: v2.SparseOracle,
    date_range: tuple[str, str],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    exchange: str,
) -> tuple[dict, list[dict], dict]:
    mask = v1._date_mask(dataset.timestamps, *date_range)
    rows = numpy.flatnonzero(mask)
    subset = dataset.take(mask)
    predictions = model.predict(subset.features)
    trades = v2.simulate_predictions(
        subset,
        predictions["long_score"],
        predictions["short_score"],
        model.threshold,
        funding_series,
        minimum_direction_margin=MINIMUM_DIRECTION_MARGIN,
    )
    for trade in trades:
        trade["exchange"] = exchange
    predicted = v2.prediction_labels(
        predictions["long_score"],
        predictions["short_score"],
        model.threshold,
        MINIMUM_DIRECTION_MARGIN,
    )
    zone_labels = v3.anticipatory_zone_labels(dataset, oracle, date_range)
    metrics = h2_backtest._metrics(trades, v1.ROUND_TRIP_COST_PCT)
    metrics.update(_excursion_metrics(trades))
    return (
        {
            "name": name,
            "evidence_role": "diagnostic_reuse",
            "start": date_range[0],
            "end": date_range[1],
            "oracle_entries": len(oracle.selected_trades),
            "zone_rows": int(numpy.sum(zone_labels[rows] != v1.WAIT)),
            "zone_classification": v2.sparse_classification_metrics(
                zone_labels[rows], predicted
            ),
            "primary": multiclass_diagnostics(
                _zone_classes(zone_labels)[rows],
                predictions["primary"],
            ),
            "auxiliary": v3._head_diagnostics(
                predictions, v3.path_targets(dataset), rows
            ),
            "economic": metrics,
        },
        trades,
        {
            "timestamps": subset.timestamps,
            "zone_observed": zone_labels[rows],
            "predicted": predicted,
            "primary": predictions["primary"],
            "long_score": predictions["long_score"],
            "short_score": predictions["short_score"],
            **{
                name: values
                for name, values in predictions.items()
                if name not in {"primary", "long_score", "short_score"}
            },
        },
    )


def multiclass_diagnostics(
    observed: numpy.ndarray, probabilities: numpy.ndarray
) -> dict:
    clipped = numpy.clip(probabilities, 1e-12, 1.0)
    one_hot = numpy.eye(len(CLASS_NAMES))[observed]
    predicted = numpy.argmax(probabilities, axis=1)
    return {
        "accuracy_pct": float(numpy.mean(predicted == observed) * 100),
        "multiclass_brier_score": float(
            numpy.mean(numpy.sum((probabilities - one_hot) ** 2, axis=1))
        ),
        "log_loss": float(
            -numpy.mean(numpy.log(clipped[numpy.arange(len(observed)), observed]))
        ),
        "observed_rates_pct": {
            name: float(numpy.mean(observed == index) * 100)
            for index, name in enumerate(CLASS_NAMES)
        },
        "mean_probabilities_pct": {
            name: float(numpy.mean(probabilities[:, index]) * 100)
            for index, name in enumerate(CLASS_NAMES)
        },
    }


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
        raise FileNotFoundError("write protocol.json before running V4")
    protocol = frozen_protocol()
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(protocol):
        raise ValueError("persisted V4 protocol differs from frozen code")

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
    binance_funding_series = v1._btc_funding(binance_funding_path)
    kucoin_funding_series = v1._btc_funding(kucoin_funding_path)
    binance_oracles = {
        name: v2.sparse_oracle(binance_dataset, date_range)
        for name, date_range in SPLITS.items()
        if name != "kucoin_reused_audit"
    }
    kucoin_oracle = v2.sparse_oracle(
        kucoin_dataset, SPLITS["kucoin_reused_audit"]
    )

    base_model, fit_report = fit_v4(
        binance_dataset,
        binance_oracles["train"],
        binance_oracles["calibration"],
    )
    threshold, threshold_table, selection_gate = select_threshold(
        base_model,
        binance_dataset,
        binance_oracles["threshold_selection"],
        binance_funding_series,
    )
    model = dataclasses.replace(base_model, threshold=threshold)
    binance_audit, binance_trades, binance_predictions = evaluate_audit(
        name="binance_reused_2025_v4",
        model=model,
        dataset=binance_dataset,
        oracle=binance_oracles["binance_reused_audit"],
        date_range=SPLITS["binance_reused_audit"],
        funding_series=binance_funding_series,
        exchange="binance_usdm",
    )
    kucoin_audit, kucoin_trades, kucoin_predictions = evaluate_audit(
        name="kucoin_reused_2026_v4",
        model=model,
        dataset=kucoin_dataset,
        oracle=kucoin_oracle,
        date_range=SPLITS["kucoin_reused_audit"],
        funding_series=kucoin_funding_series,
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
        "selected_threshold": threshold,
        "threshold_selection": threshold_table,
        "selection_gate": selection_gate,
        "diagnostic_reuse_audits": {
            "binance": binance_audit,
            "kucoin": kucoin_audit,
        },
        "promotion_eligible": False,
        "promotion_blocker": (
            "All post-selection dates were consumed by V1-V3; new forward "
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


def _save_model(model: V4Model, directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "primary": model.primary_model.save(directory / "primary_model.npz"),
        "calibration": model.calibration_model.save(
            directory / "calibration_model.npz"
        ),
    }
    for name, child in model.auxiliary_models.items():
        artifacts[name] = child.save(directory / f"{name}_model.npz")
        calibrator_path = directory / f"{name}_calibrator.json"
        model.auxiliary_calibrators[name].save(calibrator_path)
        artifacts[f"{name}_calibrator"] = v2._artifact(calibrator_path)
    metadata = directory / "model.json"
    metadata.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "feature_names": list(model.primary_model.feature_names),
                "class_names": list(CLASS_NAMES),
                "auxiliary_base_rates": model.auxiliary_base_rates,
                "support_weights": SUPPORT_WEIGHTS,
                "threshold": model.threshold,
                "minimum_direction_margin": MINIMUM_DIRECTION_MARGIN,
                "research_only": True,
                "orders_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts["metadata"] = v2._artifact(metadata)
    return artifacts


def _zone_classes(labels: numpy.ndarray) -> numpy.ndarray:
    result = numpy.zeros(len(labels), dtype=numpy.int8)
    result[labels == v1.LONG] = LONG_CLASS
    result[labels == v1.SHORT] = SHORT_CLASS
    return result


def _excursion_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"average_mfe_pct": 0.0, "average_mae_pct": 0.0}
    return {
        "average_mfe_pct": float(
            numpy.mean(
                [
                    trade["maximum_favorable_excursion_pct"]
                    for trade in trades
                ]
            )
        ),
        "average_mae_pct": float(
            numpy.mean(
                [
                    trade["maximum_adverse_excursion_pct"]
                    for trade in trades
                ]
            )
        ),
    }


def _softmax(logits: numpy.ndarray) -> numpy.ndarray:
    shifted = logits - numpy.max(logits, axis=1, keepdims=True)
    exponentials = numpy.exp(shifted)
    return exponentials / numpy.sum(exponentials, axis=1, keepdims=True)


def _json_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
                "selection_gate": report["selection_gate"],
                "diagnostic_reuse_audits": report[
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
