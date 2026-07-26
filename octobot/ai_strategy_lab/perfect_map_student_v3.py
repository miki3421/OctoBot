"""Anticipatory-zone, multi-task V3 student of the perfect percentage map.

The primary target is a causal decision zone up to four 15-minute candles
before an oracle entry. Auxiliary heads estimate path quality and whether the
activation is reached within four hours. Future data is used only for labels
and evaluation; this module is offline and cannot authorize orders.
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
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_probability_engine as probability_module
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_perfect_map_zone_multitask_student_v3"
WAIT = v1.WAIT
LONG = v1.LONG
SHORT = v1.SHORT
ZONE_LEAD_BARS = 4
FAST_TARGET_BARS = 16
HARD_NEGATIVES_PER_POSITIVE = 1
BACKGROUND_NEGATIVES_PER_POSITIVE = 1
SAMPLING_SEED = 20_260_726
DECISION_WEIGHTS = {
    "zone": 0.55,
    "quality": 0.30,
    "fast": 0.15,
}
MINIMUM_DIRECTION_MARGIN = 0.02
THRESHOLD_CANDIDATES = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55)
MINIMUM_SELECTION_TRADES = 15
ZONE_MODEL_CONFIG = model_module.BoostingConfig(
    trees=40,
    max_depth=3,
    bins=24,
    learning_rate=0.05,
    l2=3.0,
    minimum_leaf_rows=60,
    minimum_gain=0.001,
    feature_fraction=0.65,
    seed=20_260_726,
)
AUXILIARY_MODEL_CONFIG = model_module.LogisticConfig(
    epochs=18,
    batch_size=8192,
    learning_rate=0.012,
    l2=0.002,
    seed=20_260_726,
)
SPLITS = v2.SPLITS


@dataclasses.dataclass(frozen=True)
class PathTargets:
    long_quality: numpy.ndarray
    short_quality: numpy.ndarray
    long_fast: numpy.ndarray
    short_fast: numpy.ndarray


@dataclasses.dataclass(frozen=True)
class V3Model:
    long_zone_model: model_module.NumpyGradientBoostingModel
    short_zone_model: model_module.NumpyGradientBoostingModel
    long_quality_model: model_module.NumpyLogisticModel
    short_quality_model: model_module.NumpyLogisticModel
    long_fast_model: model_module.NumpyLogisticModel
    short_fast_model: model_module.NumpyLogisticModel
    calibrators: dict[str, probability_module.QuantileIsotonicCalibrator]
    threshold: float

    def predict_heads(self, features: numpy.ndarray) -> dict[str, numpy.ndarray]:
        models = {
            "long_zone": self.long_zone_model,
            "short_zone": self.short_zone_model,
            "long_quality": self.long_quality_model,
            "short_quality": self.short_quality_model,
            "long_fast": self.long_fast_model,
            "short_fast": self.short_fast_model,
        }
        return {
            name: self.calibrators[name].predict(model.predict_proba(features))
            for name, model in models.items()
        }


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "primary_target": {
            "source": "V2 maximum-compound non-overlapping oracle entries",
            "zone_lead_bars": ZONE_LEAD_BARS,
            "zone_lead_minutes": ZONE_LEAD_BARS * 15,
            "includes_oracle_entry": True,
            "truncate_while_previous_oracle_trade_is_open": True,
            "classes": ["LONG_ZONE", "SHORT_ZONE", "WAIT"],
        },
        "auxiliary_targets": {
            "quality": "+1.2% before -1.0% within 24h",
            "fast": (
                "+1.2% before -1.0% within "
                f"{FAST_TARGET_BARS * 15} minutes"
            ),
            "same_candle_policy": "stop_wins",
        },
        "features": {
            "schema": "perfect_map_student_v1_99_causal_features",
            "feature_count": len(v1.student_feature_names()),
            "maximum_candle_lookback": max(v1.WINDOWS),
        },
        "models": {
            "zone": {
                "type": "two_one_vs_rest_numpy_gradient_boosting_models",
                "config": dataclasses.asdict(ZONE_MODEL_CONFIG),
            },
            "quality_and_fast": {
                "type": "four_numpy_logistic_models",
                "config": dataclasses.asdict(AUXILIARY_MODEL_CONFIG),
                "training_stride": v1.TRAINING_STRIDE,
            },
            "calibration": "six_quantile_isotonic_mappers",
        },
        "zone_training_sampling": {
            "all_zone_rows": True,
            "hard_target_capable_per_positive": HARD_NEGATIVES_PER_POSITIVE,
            "background_wait_per_positive": BACKGROUND_NEGATIVES_PER_POSITIVE,
            "seed": SAMPLING_SEED,
        },
        "decision": {
            "score": "weighted sum of calibrated zone, quality and fast heads",
            "weights": DECISION_WEIGHTS,
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
            },
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


def anticipatory_zone_labels(
    dataset: v1.StudentDataset,
    oracle: v2.SparseOracle,
    date_range: tuple[str, str],
) -> numpy.ndarray:
    """Expand each oracle entry backwards without crossing a prior open trade."""

    mask = v1._date_mask(dataset.timestamps, *date_range)
    rows = numpy.flatnonzero(mask)
    labels = numpy.zeros(len(dataset.labels), dtype=numpy.int8)
    row_by_candle = {
        int(dataset.candle_indices[row]): int(row) for row in rows
    }
    previous_exit = -1
    for trade in oracle.selected_trades:
        entry_index = int(trade["entry_index"])
        start_index = max(entry_index - ZONE_LEAD_BARS, previous_exit + 1)
        direction = int(trade["label_direction"])
        for candle_index in range(start_index, entry_index + 1):
            row = row_by_candle.get(candle_index)
            if row is not None:
                labels[row] = direction
        previous_exit = int(trade["exit_index"])
    return labels


def path_targets(dataset: v1.StudentDataset) -> PathTargets:
    long_wins, long_offsets = v1._first_touch(dataset.candles, LONG)
    short_wins, short_offsets = v1._first_touch(dataset.candles, SHORT)
    indices = dataset.candle_indices
    return PathTargets(
        long_quality=long_wins[indices].astype(numpy.int8),
        short_quality=short_wins[indices].astype(numpy.int8),
        long_fast=(
            long_wins[indices] & (long_offsets[indices] <= FAST_TARGET_BARS)
        ).astype(numpy.int8),
        short_fast=(
            short_wins[indices] & (short_offsets[indices] <= FAST_TARGET_BARS)
        ).astype(numpy.int8),
    )


def sample_zone_training_rows(
    zone_labels: numpy.ndarray,
    oracle: v2.SparseOracle,
    range_mask: numpy.ndarray,
    *,
    seed: int = SAMPLING_SEED,
) -> numpy.ndarray:
    positives = numpy.flatnonzero(range_mask & (zone_labels != WAIT))
    if not len(positives):
        raise ValueError("V3 contains no zone-positive training rows")
    hard = numpy.flatnonzero(
        range_mask & oracle.target_capable & (zone_labels == WAIT)
    )
    background = numpy.flatnonzero(
        range_mask & ~oracle.target_capable & (zone_labels == WAIT)
    )
    generator = numpy.random.default_rng(seed)
    hard_count = min(
        len(hard), len(positives) * HARD_NEGATIVES_PER_POSITIVE
    )
    background_count = min(
        len(background),
        len(positives) * BACKGROUND_NEGATIVES_PER_POSITIVE,
    )
    return numpy.sort(
        numpy.concatenate(
            (
                positives,
                generator.choice(hard, size=hard_count, replace=False),
                generator.choice(
                    background, size=background_count, replace=False
                ),
            )
        ).astype(numpy.int64)
    )


def fit_v3(
    dataset: v1.StudentDataset,
    train_oracle: v2.SparseOracle,
    calibration_oracle: v2.SparseOracle,
) -> tuple[V3Model, dict, dict[str, numpy.ndarray]]:
    train_zone = anticipatory_zone_labels(
        dataset, train_oracle, SPLITS["train"]
    )
    calibration_zone = anticipatory_zone_labels(
        dataset, calibration_oracle, SPLITS["calibration"]
    )
    paths = path_targets(dataset)
    train_mask = v1._date_mask(dataset.timestamps, *SPLITS["train"])
    zone_rows = sample_zone_training_rows(
        train_zone, train_oracle, train_mask
    )
    auxiliary_rows = numpy.flatnonzero(train_mask)[::v1.TRAINING_STRIDE]
    feature_names = v1.student_feature_names()
    long_zone_model = model_module.NumpyGradientBoostingModel.fit(
        dataset.features[zone_rows],
        (train_zone[zone_rows] == LONG).astype(numpy.int8),
        feature_names,
        ZONE_MODEL_CONFIG,
    )
    short_zone_model = model_module.NumpyGradientBoostingModel.fit(
        dataset.features[zone_rows],
        (train_zone[zone_rows] == SHORT).astype(numpy.int8),
        feature_names,
        dataclasses.replace(
            ZONE_MODEL_CONFIG, seed=ZONE_MODEL_CONFIG.seed + 1
        ),
    )
    auxiliary_specs = {
        "long_quality": paths.long_quality,
        "short_quality": paths.short_quality,
        "long_fast": paths.long_fast,
        "short_fast": paths.short_fast,
    }
    auxiliary_models = {}
    for offset, (name, labels) in enumerate(auxiliary_specs.items(), start=2):
        auxiliary_models[name] = model_module.NumpyLogisticModel.fit(
            dataset.features[auxiliary_rows],
            labels[auxiliary_rows],
            feature_names,
            dataclasses.replace(
                AUXILIARY_MODEL_CONFIG,
                seed=AUXILIARY_MODEL_CONFIG.seed + offset,
            ),
        )

    calibration_mask = v1._date_mask(
        dataset.timestamps, *SPLITS["calibration"]
    )
    calibration_rows = numpy.flatnonzero(calibration_mask)
    models = {
        "long_zone": long_zone_model,
        "short_zone": short_zone_model,
        **auxiliary_models,
    }
    calibration_labels = {
        "long_zone": (calibration_zone == LONG).astype(numpy.int8),
        "short_zone": (calibration_zone == SHORT).astype(numpy.int8),
        **auxiliary_specs,
    }
    calibrators = {
        name: probability_module.QuantileIsotonicCalibrator.fit(
            model.predict_proba(dataset.features[calibration_rows]),
            calibration_labels[name][calibration_rows],
            minimum_rows_per_bin=100,
        )
        for name, model in models.items()
    }
    model = V3Model(
        long_zone_model=long_zone_model,
        short_zone_model=short_zone_model,
        long_quality_model=auxiliary_models["long_quality"],
        short_quality_model=auxiliary_models["short_quality"],
        long_fast_model=auxiliary_models["long_fast"],
        short_fast_model=auxiliary_models["short_fast"],
        calibrators=calibrators,
        threshold=THRESHOLD_CANDIDATES[0],
    )
    report = {
        "zone_training_rows": len(zone_rows),
        "zone_training_distribution": v1._class_distribution(
            train_zone[zone_rows]
        ),
        "auxiliary_training_rows": len(auxiliary_rows),
        "train_oracle_entries": len(train_oracle.selected_trades),
        "train_zone_rows": int(numpy.sum(train_zone != WAIT)),
        "calibration_oracle_entries": len(
            calibration_oracle.selected_trades
        ),
        "calibration_zone_rows": int(
            numpy.sum(calibration_zone != WAIT)
        ),
        "auxiliary_train_rates_pct": {
            name: float(numpy.mean(labels[auxiliary_rows]) * 100)
            for name, labels in auxiliary_specs.items()
        },
    }
    labels = {
        "train_zone": train_zone,
        "calibration_zone": calibration_zone,
    }
    return model, report, labels


def decision_scores(heads: dict[str, numpy.ndarray]) -> tuple[
    numpy.ndarray, numpy.ndarray
]:
    long_score = (
        DECISION_WEIGHTS["zone"] * heads["long_zone"]
        + DECISION_WEIGHTS["quality"] * heads["long_quality"]
        + DECISION_WEIGHTS["fast"] * heads["long_fast"]
    )
    short_score = (
        DECISION_WEIGHTS["zone"] * heads["short_zone"]
        + DECISION_WEIGHTS["quality"] * heads["short_quality"]
        + DECISION_WEIGHTS["fast"] * heads["short_fast"]
    )
    return long_score, short_score


def select_threshold(
    model: V3Model,
    dataset: v1.StudentDataset,
    oracle: v2.SparseOracle,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> tuple[float, list[dict], dict]:
    mask = v1._date_mask(
        dataset.timestamps, *SPLITS["threshold_selection"]
    )
    rows = numpy.flatnonzero(mask)
    subset = dataset.take(mask)
    heads = model.predict_heads(subset.features)
    long_score, short_score = decision_scores(heads)
    table = []
    for threshold in THRESHOLD_CANDIDATES:
        trades = v2.simulate_predictions(
            subset,
            long_score,
            short_score,
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
    }
    zone_labels = anticipatory_zone_labels(
        dataset, oracle, SPLITS["threshold_selection"]
    )
    predicted = v2.prediction_labels(
        long_score,
        short_score,
        float(selected["threshold"]),
        MINIMUM_DIRECTION_MARGIN,
    )
    return (
        float(selected["threshold"]),
        table,
        {
            "results": gate_results,
            "passed": all(gate_results.values()),
            "zone_classification": v2.sparse_classification_metrics(
                zone_labels[rows], predicted
            ),
            "head_diagnostics": _head_diagnostics(
                heads, path_targets(dataset), rows
            ),
        },
    )


def evaluate_audit(
    *,
    name: str,
    model: V3Model,
    dataset: v1.StudentDataset,
    oracle: v2.SparseOracle,
    date_range: tuple[str, str],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    exchange: str,
) -> tuple[dict, list[dict], dict]:
    mask = v1._date_mask(dataset.timestamps, *date_range)
    rows = numpy.flatnonzero(mask)
    subset = dataset.take(mask)
    heads = model.predict_heads(subset.features)
    long_score, short_score = decision_scores(heads)
    trades = v2.simulate_predictions(
        subset,
        long_score,
        short_score,
        model.threshold,
        funding_series,
        minimum_direction_margin=MINIMUM_DIRECTION_MARGIN,
    )
    for trade in trades:
        trade["exchange"] = exchange
    predicted = v2.prediction_labels(
        long_score,
        short_score,
        model.threshold,
        MINIMUM_DIRECTION_MARGIN,
    )
    zone_labels = anticipatory_zone_labels(dataset, oracle, date_range)
    metrics = h2_backtest._metrics(trades, v1.ROUND_TRIP_COST_PCT)
    metrics["average_mfe_pct"] = (
        float(
            numpy.mean(
                [
                    trade["maximum_favorable_excursion_pct"]
                    for trade in trades
                ]
            )
        )
        if trades
        else 0.0
    )
    metrics["average_mae_pct"] = (
        float(
            numpy.mean(
                [
                    trade["maximum_adverse_excursion_pct"]
                    for trade in trades
                ]
            )
        )
        if trades
        else 0.0
    )
    return (
        {
            "name": name,
            "evidence_role": "diagnostic_reuse",
            "start": date_range[0],
            "end": date_range[1],
            "oracle_entries": len(oracle.selected_trades),
            "zone_rows": int(numpy.sum(zone_labels[rows] != WAIT)),
            "zone_classification": v2.sparse_classification_metrics(
                zone_labels[rows], predicted
            ),
            "head_diagnostics": _head_diagnostics(
                heads, path_targets(dataset), rows
            ),
            "economic": metrics,
        },
        trades,
        {
            "timestamps": subset.timestamps,
            "zone_observed": zone_labels[rows],
            "predicted": predicted,
            "long_score": long_score,
            "short_score": short_score,
            **heads,
        },
    )


def _head_diagnostics(
    heads: dict[str, numpy.ndarray],
    paths: PathTargets,
    rows: numpy.ndarray,
) -> dict:
    observed = {
        "long_quality": paths.long_quality[rows],
        "short_quality": paths.short_quality[rows],
        "long_fast": paths.long_fast[rows],
        "short_fast": paths.short_fast[rows],
    }
    return {
        name: {
            "observed_rate_pct": float(numpy.mean(labels) * 100),
            "mean_probability_pct": float(numpy.mean(heads[name]) * 100),
            "brier_score": float(
                numpy.mean((heads[name] - labels) ** 2)
            ),
        }
        for name, labels in observed.items()
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
        raise FileNotFoundError("write protocol.json before running V3")
    protocol = frozen_protocol()
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(protocol):
        raise ValueError("persisted V3 protocol differs from frozen code")

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

    base_model, fit_report, _ = fit_v3(
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
        name="binance_reused_2025_v3",
        model=model,
        dataset=binance_dataset,
        oracle=binance_oracles["binance_reused_audit"],
        date_range=SPLITS["binance_reused_audit"],
        funding_series=binance_funding_series,
        exchange="binance_usdm",
    )
    kucoin_audit, kucoin_trades, kucoin_predictions = evaluate_audit(
        name="kucoin_reused_2026_v3",
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
        "oracle_counts": {
            name: len(oracle.selected_trades)
            for name, oracle in {
                **binance_oracles,
                "kucoin_reused_audit": kucoin_oracle,
            }.items()
        },
        "selected_threshold": threshold,
        "threshold_selection": threshold_table,
        "selection_gate": selection_gate,
        "diagnostic_reuse_audits": {
            "binance": binance_audit,
            "kucoin": kucoin_audit,
        },
        "promotion_eligible": False,
        "promotion_blocker": (
            "All post-selection periods were consumed by V1/V2; new forward "
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


def _save_model(model: V3Model, directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    models = {
        "long_zone": model.long_zone_model,
        "short_zone": model.short_zone_model,
        "long_quality": model.long_quality_model,
        "short_quality": model.short_quality_model,
        "long_fast": model.long_fast_model,
        "short_fast": model.short_fast_model,
    }
    artifacts = {
        name: child.save(directory / f"{name}_model.npz")
        for name, child in models.items()
    }
    for name, calibrator in model.calibrators.items():
        path = directory / f"{name}_calibrator.json"
        calibrator.save(path)
        artifacts[f"{name}_calibrator"] = v2._artifact(path)
    metadata = directory / "model.json"
    metadata.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "feature_names": list(v1.student_feature_names()),
                "decision_weights": DECISION_WEIGHTS,
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
