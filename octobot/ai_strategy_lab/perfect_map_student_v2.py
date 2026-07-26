"""Sparse-oracle V2 student of the hindsight percentage map.

V2 learns only the entries retained by the map's maximum-compound,
non-overlapping sequence. Other target-capable candles become hard WAIT
controls. All features remain causal and the experiment cannot place orders.
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
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import percentage_probability_engine as probability_module
from octobot.ai_strategy_lab import perfect_map_student as v1


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_perfect_map_sparse_student_v2"
WAIT = v1.WAIT
LONG = v1.LONG
SHORT = v1.SHORT
BACKGROUND_NEGATIVES_PER_POSITIVE = 3
HARD_NEGATIVES_PER_POSITIVE = 3
MINIMUM_DIRECTION_MARGIN = 0.005
THRESHOLD_CANDIDATES = (0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15)
MINIMUM_SELECTION_TRADES = 15
SAMPLING_SEED = 20_260_725
MODEL_CONFIG = model_module.BoostingConfig(
    trees=48,
    max_depth=3,
    bins=24,
    learning_rate=0.05,
    l2=3.0,
    minimum_leaf_rows=50,
    minimum_gain=0.001,
    feature_fraction=0.65,
    seed=20_260_725,
)
SPLITS = {
    "train": v1.SPLITS["train"],
    "calibration": v1.SPLITS["calibration"],
    "threshold_selection": v1.SPLITS["threshold_selection"],
    "binance_reused_audit": v1.SPLITS["locked_test"],
    "kucoin_reused_audit": v1.SPLITS["external_reused_kucoin"],
}


@dataclasses.dataclass(frozen=True)
class SparseOracle:
    labels: numpy.ndarray
    selected_trades: tuple[dict, ...]
    target_capable: numpy.ndarray


@dataclasses.dataclass(frozen=True)
class V2Model:
    long_model: model_module.NumpyGradientBoostingModel
    short_model: model_module.NumpyGradientBoostingModel
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
        "teacher": {
            "source": "hindsight_percentage_research_only",
            "positive_labels": (
                "entries retained by maximum-compound non-overlapping "
                "dynamic programming"
            ),
            "minimum_gross_profit_pct": 1.0,
            "activation_pct": v1.ACTIVATION_PCT,
            "initial_stop_pct": v1.INITIAL_STOP_PCT,
            "protected_stop_pct": v1.PROTECTED_STOP_PCT,
            "horizon_bars_15m": v1.HORIZON_BARS,
            "same_candle_policy": "stop_wins",
            "future_used_for_labels_only": True,
        },
        "features": {
            "schema": "perfect_map_student_v1_99_causal_features",
            "maximum_candle_lookback": max(v1.WINDOWS),
            "feature_count": len(v1.student_feature_names()),
        },
        "training": {
            "model": "two_one_vs_rest_numpy_gradient_boosting_models",
            "model_config": dataclasses.asdict(MODEL_CONFIG),
            "negative_sampling": {
                "hard_target_capable_per_positive": (
                    HARD_NEGATIVES_PER_POSITIVE
                ),
                "background_wait_per_positive": (
                    BACKGROUND_NEGATIVES_PER_POSITIVE
                ),
                "seed": SAMPLING_SEED,
            },
            "calibration": "quantile_isotonic_on_full_calibration_block",
        },
        "decision": {
            "threshold_candidates": list(THRESHOLD_CANDIDATES),
            "minimum_direction_margin": MINIMUM_DIRECTION_MARGIN,
            "one_trade_at_a_time": True,
            "directions_must_alternate": False,
            "minimum_selection_trades": MINIMUM_SELECTION_TRADES,
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
            "entry": "decision candle close",
            "exit": "same conservative stop/activation/profit-lock map rules",
        },
        "splits": SPLITS,
        "evidence_policy": {
            "all_audits_after_threshold_selection": (
                "diagnostic_reuse_because_v1_already_read_them"
            ),
            "promotion_possible": False,
            "next_promotion_evidence": "new_forward_dates_only",
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


def sparse_oracle(
    dataset: v1.StudentDataset,
    date_range: tuple[str, str],
) -> SparseOracle:
    """Select the exact hindsight sequence and map it to dataset rows."""

    range_mask = v1._date_mask(dataset.timestamps, *date_range)
    rows = numpy.flatnonzero(range_mask)
    labels = numpy.zeros(len(dataset.labels), dtype=numpy.int8)
    target_capable = numpy.zeros(len(dataset.labels), dtype=bool)
    if not len(rows):
        return SparseOracle(labels, (), target_capable)

    long_wins, _ = v1._first_touch(dataset.candles, LONG)
    short_wins, _ = v1._first_touch(dataset.candles, SHORT)
    close_times = (
        dataset.candles[:, 0].astype(numpy.int64) + v1.CANDLE_SECONDS
    ).tolist()
    trade_config = percentage_engine.PercentageEngineConfig(
        minimum_profit_pct=v1.PROTECTED_STOP_PCT,
        activation_pct=v1.ACTIVATION_PCT,
        initial_stop_pct=v1.INITIAL_STOP_PCT,
        horizon_candles=v1.HORIZON_BARS,
        directions=(percentage_engine.LONG, percentage_engine.SHORT),
        exclude_last_candle=False,
    )
    candidates = []
    row_by_candle = {
        int(dataset.candle_indices[row]): int(row) for row in rows
    }
    for direction, direction_value, wins in (
        (percentage_engine.LONG, LONG, long_wins),
        (percentage_engine.SHORT, SHORT, short_wins),
    ):
        for candle_index, row in row_by_candle.items():
            if not wins[candle_index]:
                continue
            target_capable[row] = True
            trade = percentage_engine.simulate_trade(
                close_times,
                dataset.candles[:, 2],
                dataset.candles[:, 3],
                dataset.candles[:, 4],
                candle_index,
                direction,
                len(dataset.candles) - 1,
                trade_config,
            )
            if (
                trade["target_reached"]
                and trade["gross_return_pct"]
                >= v1.PROTECTED_STOP_PCT - 1e-12
            ):
                trade["label_direction"] = direction_value
                candidates.append(trade)

    selected = percentage_engine._select_non_overlapping_maximum_compound(
        candidates
    )
    for trade in selected:
        row = row_by_candle[int(trade["entry_index"])]
        labels[row] = int(trade["label_direction"])
    return SparseOracle(labels, tuple(selected), target_capable)


def sample_training_rows(
    oracle: SparseOracle,
    range_mask: numpy.ndarray,
    *,
    seed: int = SAMPLING_SEED,
) -> numpy.ndarray:
    positives = numpy.flatnonzero(range_mask & (oracle.labels != WAIT))
    if not len(positives):
        raise ValueError("sparse oracle contains no positive training rows")
    positive_mask = oracle.labels != WAIT
    hard = numpy.flatnonzero(
        range_mask & oracle.target_capable & ~positive_mask
    )
    background = numpy.flatnonzero(
        range_mask & ~oracle.target_capable & ~positive_mask
    )
    generator = numpy.random.default_rng(seed)
    hard_count = min(
        len(hard), len(positives) * HARD_NEGATIVES_PER_POSITIVE
    )
    background_count = min(
        len(background),
        len(positives) * BACKGROUND_NEGATIVES_PER_POSITIVE,
    )
    selected_hard = generator.choice(hard, size=hard_count, replace=False)
    selected_background = generator.choice(
        background, size=background_count, replace=False
    )
    return numpy.sort(
        numpy.concatenate(
            (positives, selected_hard, selected_background)
        ).astype(numpy.int64)
    )


def fit_v2(
    dataset: v1.StudentDataset,
    train_oracle: SparseOracle,
    calibration_oracle: SparseOracle,
) -> tuple[V2Model, dict]:
    train_mask = v1._date_mask(dataset.timestamps, *SPLITS["train"])
    train_rows = sample_training_rows(train_oracle, train_mask)
    long_model = model_module.NumpyGradientBoostingModel.fit(
        dataset.features[train_rows],
        (train_oracle.labels[train_rows] == LONG).astype(numpy.int8),
        v1.student_feature_names(),
        MODEL_CONFIG,
    )
    short_model = model_module.NumpyGradientBoostingModel.fit(
        dataset.features[train_rows],
        (train_oracle.labels[train_rows] == SHORT).astype(numpy.int8),
        v1.student_feature_names(),
        dataclasses.replace(MODEL_CONFIG, seed=MODEL_CONFIG.seed + 1),
    )
    calibration_mask = v1._date_mask(
        dataset.timestamps, *SPLITS["calibration"]
    )
    calibration_rows = numpy.flatnonzero(calibration_mask)
    long_calibrator = probability_module.QuantileIsotonicCalibrator.fit(
        long_model.predict_proba(dataset.features[calibration_rows]),
        (calibration_oracle.labels[calibration_rows] == LONG).astype(
            numpy.int8
        ),
        minimum_rows_per_bin=100,
    )
    short_calibrator = probability_module.QuantileIsotonicCalibrator.fit(
        short_model.predict_proba(dataset.features[calibration_rows]),
        (calibration_oracle.labels[calibration_rows] == SHORT).astype(
            numpy.int8
        ),
        minimum_rows_per_bin=100,
    )
    model = V2Model(
        long_model,
        short_model,
        long_calibrator,
        short_calibrator,
        threshold=THRESHOLD_CANDIDATES[0],
    )
    return model, {
        "sampled_training_rows": len(train_rows),
        "sampled_training_distribution": v1._class_distribution(
            train_oracle.labels[train_rows]
        ),
        "train_oracle_entries": int(
            numpy.sum(train_mask & (train_oracle.labels != WAIT))
        ),
        "train_target_capable_rows": int(
            numpy.sum(train_mask & train_oracle.target_capable)
        ),
        "calibration_oracle_entries": int(
            numpy.sum(calibration_mask & (calibration_oracle.labels != WAIT))
        ),
    }


def prediction_labels(
    long_probabilities: numpy.ndarray,
    short_probabilities: numpy.ndarray,
    threshold: float,
    minimum_direction_margin: float = MINIMUM_DIRECTION_MARGIN,
) -> numpy.ndarray:
    labels = numpy.zeros(len(long_probabilities), dtype=numpy.int8)
    margin = numpy.abs(long_probabilities - short_probabilities)
    eligible = (
        numpy.maximum(long_probabilities, short_probabilities) >= threshold
    ) & (margin >= minimum_direction_margin)
    labels[eligible & (long_probabilities > short_probabilities)] = LONG
    labels[eligible & (short_probabilities > long_probabilities)] = SHORT
    return labels


def simulate_predictions(
    dataset: v1.StudentDataset,
    long_probabilities: numpy.ndarray,
    short_probabilities: numpy.ndarray,
    threshold: float,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    minimum_direction_margin: float = MINIMUM_DIRECTION_MARGIN,
) -> list[dict]:
    labels = prediction_labels(
        long_probabilities,
        short_probabilities,
        threshold,
        minimum_direction_margin,
    )
    candidates = []
    for row in numpy.flatnonzero(labels != WAIT):
        direction = (
            percentage_engine.LONG
            if labels[row] == LONG
            else percentage_engine.SHORT
        )
        candidates.append(
            {
                "entry_index": int(dataset.candle_indices[row]),
                "direction": direction,
                "probability_pct": float(
                    max(long_probabilities[row], short_probabilities[row])
                    * 100
                ),
                "opposite_probability_pct": float(
                    min(long_probabilities[row], short_probabilities[row])
                    * 100
                ),
            }
        )
    trade_config = percentage_engine.PercentageEngineConfig(
        minimum_profit_pct=v1.PROTECTED_STOP_PCT,
        activation_pct=v1.ACTIVATION_PCT,
        initial_stop_pct=v1.INITIAL_STOP_PCT,
        horizon_candles=v1.HORIZON_BARS,
        directions=(percentage_engine.LONG, percentage_engine.SHORT),
        exclude_last_candle=False,
    )
    close_times = (
        dataset.candles[:, 0].astype(numpy.int64) + v1.CANDLE_SECONDS
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
                "entry_time_utc": v1._timestamp_iso(entry_timestamp),
                "entry_timestamp": entry_timestamp,
                "exit_time_utc": v1._timestamp_iso(exit_timestamp),
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


def select_threshold(
    model: V2Model,
    dataset: v1.StudentDataset,
    oracle: SparseOracle,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> tuple[float, list[dict], dict]:
    mask = v1._date_mask(
        dataset.timestamps, *SPLITS["threshold_selection"]
    )
    subset = dataset.take(mask)
    long_values, short_values = model.predict(subset.features)
    table = []
    for threshold in THRESHOLD_CANDIDATES:
        trades = simulate_predictions(
            subset, long_values, short_values, threshold, funding_series
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
    selected_metrics = selected["metrics"]
    gate = {
        "minimum_trades": (
            selected_metrics["trades"] >= MINIMUM_SELECTION_TRADES
        ),
        "profit_factor": (
            selected_metrics["profit_factor"] is not None
            and selected_metrics["profit_factor"] >= 1.10
        ),
        "positive_compounded_return": (
            selected_metrics["compounded_net_return_pct"] > 0
        ),
        "positive_objective": selected["objective"] > 0,
    }
    selection_rows = numpy.flatnonzero(mask)
    predicted = prediction_labels(
        long_values, short_values, float(selected["threshold"])
    )
    classification = sparse_classification_metrics(
        oracle.labels[selection_rows], predicted
    )
    return (
        float(selected["threshold"]),
        table,
        {
            "results": gate,
            "passed": all(gate.values()),
            "classification": classification,
        },
    )


def sparse_classification_metrics(
    observed: numpy.ndarray, predicted: numpy.ndarray
) -> dict:
    predicted_positive = predicted != WAIT
    observed_positive = observed != WAIT
    exact = predicted_positive & (predicted == observed)
    return {
        "examples": len(observed),
        "oracle_entries": int(numpy.sum(observed_positive)),
        "predicted_entries": int(numpy.sum(predicted_positive)),
        "exact_entry_precision_pct": (
            float(numpy.sum(exact) * 100 / numpy.sum(predicted_positive))
            if numpy.any(predicted_positive)
            else 0.0
        ),
        "exact_entry_recall_pct": (
            float(numpy.sum(exact) * 100 / numpy.sum(observed_positive))
            if numpy.any(observed_positive)
            else 0.0
        ),
        "direction_accuracy_on_matched_timestamp_pct": (
            float(
                numpy.sum(exact)
                * 100
                / numpy.sum(predicted_positive & observed_positive)
            )
            if numpy.any(predicted_positive & observed_positive)
            else 0.0
        ),
    }


def evaluate_audit(
    *,
    name: str,
    model: V2Model,
    dataset: v1.StudentDataset,
    oracle: SparseOracle,
    date_range: tuple[str, str],
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
    exchange: str,
) -> tuple[dict, list[dict], dict]:
    mask = v1._date_mask(dataset.timestamps, *date_range)
    subset = dataset.take(mask)
    rows = numpy.flatnonzero(mask)
    long_values, short_values = model.predict(subset.features)
    trades = simulate_predictions(
        subset,
        long_values,
        short_values,
        model.threshold,
        funding_series,
    )
    for trade in trades:
        trade["exchange"] = exchange
    predicted = prediction_labels(
        long_values, short_values, model.threshold
    )
    return (
        {
            "name": name,
            "evidence_role": "diagnostic_reuse",
            "start": date_range[0],
            "end": date_range[1],
            "oracle_entries": int(numpy.sum(oracle.labels[rows] != WAIT)),
            "classification": sparse_classification_metrics(
                oracle.labels[rows], predicted
            ),
            "economic": h2_backtest._metrics(
                trades, v1.ROUND_TRIP_COST_PCT
            ),
        },
        trades,
        {
            "timestamps": subset.timestamps,
            "observed": oracle.labels[rows],
            "predicted": predicted,
            "long_probabilities": long_values,
            "short_probabilities": short_values,
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
        raise FileNotFoundError("write protocol.json before running V2")
    protocol = frozen_protocol()
    persisted = json.loads(protocol_path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(protocol):
        raise ValueError("persisted V2 protocol differs from frozen code")

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
        name: sparse_oracle(binance_dataset, date_range)
        for name, date_range in SPLITS.items()
        if name != "kucoin_reused_audit"
    }
    kucoin_oracle = sparse_oracle(
        kucoin_dataset, SPLITS["kucoin_reused_audit"]
    )
    base_model, fit_report = fit_v2(
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
        name="binance_reused_2025_v2",
        model=model,
        dataset=binance_dataset,
        oracle=binance_oracles["binance_reused_audit"],
        date_range=SPLITS["binance_reused_audit"],
        funding_series=binance_funding_series,
        exchange="binance_usdm",
    )
    kucoin_audit, kucoin_trades, kucoin_predictions = evaluate_audit(
        name="kucoin_reused_2026_v2",
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
        binance_timestamps=binance_predictions["timestamps"],
        binance_observed=binance_predictions["observed"],
        binance_predicted=binance_predictions["predicted"],
        binance_long_probabilities=binance_predictions[
            "long_probabilities"
        ],
        binance_short_probabilities=binance_predictions[
            "short_probabilities"
        ],
        kucoin_timestamps=kucoin_predictions["timestamps"],
        kucoin_observed=kucoin_predictions["observed"],
        kucoin_predicted=kucoin_predictions["predicted"],
        kucoin_long_probabilities=kucoin_predictions["long_probabilities"],
        kucoin_short_probabilities=kucoin_predictions[
            "short_probabilities"
        ],
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
            name: {
                "selected_entries": len(oracle.selected_trades),
                "target_capable_rows": int(numpy.sum(oracle.target_capable)),
            }
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
            "V1 already consumed all post-selection periods; only new forward "
            "dates can provide promotion evidence."
        ),
        "artifacts": {
            "protocol": _artifact(protocol_path),
            "model": model_artifacts,
            "predictions": _artifact(predictions_path),
            "inputs": {
                "binance_collector": _artifact(binance_path),
                "binance_funding": _artifact(binance_funding_path),
                "kucoin_collector": _artifact(kucoin_path),
                "kucoin_funding": _artifact(kucoin_funding_path),
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


def _save_model(model: V2Model, directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    long = model.long_model.save(directory / "long_model.npz")
    short = model.short_model.save(directory / "short_model.npz")
    long_calibrator = directory / "long_calibrator.json"
    short_calibrator = directory / "short_calibrator.json"
    model.long_calibrator.save(long_calibrator)
    model.short_calibrator.save(short_calibrator)
    metadata = directory / "model.json"
    metadata.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "feature_names": list(v1.student_feature_names()),
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
    return {
        "long_model": long,
        "short_model": short,
        "long_calibrator": _artifact(long_calibrator),
        "short_calibrator": _artifact(short_calibrator),
        "metadata": _artifact(metadata),
    }


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
