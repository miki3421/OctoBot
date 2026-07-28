"""Candidate-conditioned event-probability meta-model for BTC.

The research model consumes evaluator values that were actually available in
recorded deterministic decisions and estimates whether +1.2% activation will
occur before a -1% stop within 24 hours. It is an offline diagnostic and cannot
create or modify orders.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import typing

import numpy

from octobot.ai_strategy_lab import deterministic_v5_veto as veto_v1
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_probability_engine as probability
from octobot.ai_strategy_lab import perfect_map_student as student
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_deterministic_event_meta_v3"
PREREGISTRATION_DATE = "2026-07-28"
SYMBOL = veto_v1.SYMBOL
CANDLE_SECONDS = 900
ACTIVATION_PCT = 1.2
INITIAL_STOP_PCT = 1.0
PROTECTED_STOP_PCT = 1.0
HORIZON_BARS = 96
ROUND_TRIP_COST_PCT = 0.16
STRESS_ROUND_TRIP_COST_PCT = 0.24
PROBABILITY_THRESHOLD = 0.58
TRAINING_SEED = 20_260_728
MODEL_CONFIG = model_module.LogisticConfig(
    epochs=40,
    batch_size=1024,
    learning_rate=0.012,
    l2=0.003,
    seed=TRAINING_SEED,
)
TIME_FRAMES = ("15m", "1h", "4h")
EVALUATORS = (
    "ADXMomentumEvaluator",
    "BBMomentumEvaluator",
    "DoubleMovingAverageTrendEvaluator",
    "EMADivergenceTrendEvaluator",
    "MACDMomentumEvaluator",
    "RSIMomentumEvaluator",
)
SPLITS = {
    "train": ("2026-04-22", "2026-05-31"),
    "train_embargo": ("2026-06-01", "2026-06-01"),
    "calibration": ("2026-06-02", "2026-06-15"),
    "calibration_embargo": ("2026-06-16", "2026-06-16"),
    "diagnostic_audit": ("2026-06-17", "2026-07-20"),
    "initial_forward": ("2026-07-21", None),
}
CRASH_CASE_DECISION_TIMESTAMP = veto_v1.CRASH_CASE_DECISION_TIMESTAMP


@dataclasses.dataclass(frozen=True)
class MetaDataset:
    features: numpy.ndarray
    labels: numpy.ndarray
    decision_ids: numpy.ndarray
    timestamps: numpy.ndarray
    candle_indices: numpy.ndarray
    directions: numpy.ndarray
    actions: numpy.ndarray
    outcomes: tuple[typing.Optional[dict], ...]
    feature_names: tuple[str, ...]

    def take(self, mask: numpy.ndarray) -> "MetaDataset":
        indices = numpy.flatnonzero(mask)
        return MetaDataset(
            features=self.features[indices],
            labels=self.labels[indices],
            decision_ids=self.decision_ids[indices],
            timestamps=self.timestamps[indices],
            candle_indices=self.candle_indices[indices],
            directions=self.directions[indices],
            actions=self.actions[indices],
            outcomes=tuple(self.outcomes[index] for index in indices),
            feature_names=self.feature_names,
        )


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _json_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def feature_names() -> tuple[str, ...]:
    names = [
        f"aligned_{time_frame}_{evaluator}"
        for time_frame in TIME_FRAMES
        for evaluator in EVALUATORS
    ]
    names.extend(
        (
            "decision_confidence",
            "decision_signal_strength",
            "direction_is_short",
            "v5_selected_expected_net_pct",
            "v5_opposite_expected_net_pct",
            "v5_direction_margin_pct",
            "v5_target_probability",
            "v5_stop_probability",
            "v5_timeout_probability",
            "v5_target_profit_pct",
            "v5_horizon_hours",
            "hour_sin",
            "hour_cos",
            "weekday_sin",
            "weekday_cos",
        )
    )
    return tuple(names)


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "preregistered_design_only",
        "research_only": True,
        "diagnostic_reuse": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "candidate_source": {
            "journal_table": "ai_decisions",
            "symbol": SYMBOL,
            "model": "deterministic-alignment",
            "approved_actions": ["BUY", "SELL"],
            "journal_used_for_training": True,
            "journal_can_create_orders": False,
        },
        "event_label": {
            "positive": "+1.2% activation before -1% initial stop",
            "horizon_hours": 24,
            "same_candle_policy": "initial_stop_wins",
            "profit_lock_pct": PROTECTED_STOP_PCT,
            "profit_lock_active_from_next_candle": True,
            "future_used_for_features": False,
            "future_used_for_label_and_evaluation": True,
        },
        "features": {
            "causal_at_recorded_decision_close": True,
            "names": list(feature_names()),
            "count": len(feature_names()),
            "evaluator_values": {
                "time_frames": list(TIME_FRAMES),
                "evaluators": list(EVALUATORS),
                "alignment": (
                    "LONG multiplies eval_note by -1; SHORT by +1"
                ),
            },
            "decision_fields": [
                "confidence",
                "signal_strength",
                "direction_is_short",
            ],
            "frozen_v5_summary": [
                "selected_and_opposite_expected_net",
                "direction_margin",
                "target_stop_timeout_probabilities",
                "chosen_target_and_horizon",
            ],
            "utc_cyclicity": True,
            "missing_or_non_finite": "exclude_and_count",
        },
        "model": {
            "type": "numpy_logistic_binary_classifier",
            "config": dataclasses.asdict(MODEL_CONFIG),
            "calibration": "quantile_isotonic_on_calibration_only",
            "probability_threshold": PROBABILITY_THRESHOLD,
            "threshold_source": (
                "conservative break-even approximation for +0.84/-1.16"
            ),
            "threshold_tuned_on_pnl": False,
        },
        "splits": SPLITS,
        "embargo_hours": 24,
        "economic_evaluation": {
            "one_trade_at_a_time": True,
            "entry": "decision candle close",
            "activation_pct": ACTIVATION_PCT,
            "initial_stop_pct": INITIAL_STOP_PCT,
            "protected_stop_pct": PROTECTED_STOP_PCT,
            "horizon_hours": 24,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "stress_round_trip_cost_pct": (
                STRESS_ROUND_TRIP_COST_PCT
            ),
            "funding_included": True,
        },
        "diagnostic_gate": {
            "minimum_filtered_trades": 10,
            "both_directions_required": True,
            "minimum_profit_factor": 1.20,
            "positive_compounded_return": True,
            "maximum_drawdown_pct": 10.0,
            "brier_below_calibration_base_rate_constant": True,
            "stress_compounded_return_non_negative": True,
        },
        "evidence_policy": {
            "no_current_result_can_promote": True,
            "new_forward_start_after": "2026-07-28",
            "minimum_new_forward_days": 30,
            "minimum_new_forward_closed_trades": 30,
            "no_mid_test_retuning": True,
        },
        "implementation": {
            "protocol_file_required_before_fit": True,
            "snapshot_max_decision_id": True,
            "persist_input_model_predictions_trades_report": True,
            "reloaded_predictions_must_match_exactly": True,
            "results_in_this_protocol": False,
        },
    }


def write_protocol(
    output_value: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = frozen_protocol()
    path = output / "protocol.json"
    path.write_text(
        json.dumps(
            {
                **protocol,
                "protocol_sha256": _json_hash(protocol),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _verify_protocol(output: pathlib.Path) -> dict:
    path = output / "protocol.json"
    if not path.is_file():
        raise FileNotFoundError(
            "write protocol.json before fitting event meta V3"
        )
    expected = frozen_protocol()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(expected):
        raise ValueError("persisted event-meta protocol hash differs")
    without_hash = {
        key: value
        for key, value in persisted.items()
        if key != "protocol_sha256"
    }
    if _json_hash(without_hash) != _json_hash(expected):
        raise ValueError("persisted event-meta protocol content differs")
    return persisted


def load_journal_candidates(
    path_value: typing.Union[str, pathlib.Path],
) -> tuple[list[dict], dict]:
    path = pathlib.Path(path_value).resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("AI decision journal failed integrity check")
        maximum_id = int(
            connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM ai_decisions"
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT
                id, triggered_at, action, confidence, signal_strength,
                input_json
            FROM ai_decisions
            WHERE id <= ?
              AND symbol = ?
              AND model = 'deterministic-alignment'
              AND approved = 1
              AND action IN ('BUY', 'SELL')
              AND triggered_at IS NOT NULL
            ORDER BY triggered_at, id
            """,
            (maximum_id, SYMBOL),
        ).fetchall()
    finally:
        connection.close()
    by_timestamp: dict[int, list[tuple]] = {}
    for row in rows:
        by_timestamp.setdefault(int(row[1]), []).append(row)
    candidates = []
    ambiguous = 0
    duplicates = 0
    invalid_json = 0
    for timestamp, values in sorted(by_timestamp.items()):
        if len({str(row[2]) for row in values}) != 1:
            ambiguous += 1
            continue
        duplicates += len(values) - 1
        selected = values[-1]
        try:
            payload = json.loads(str(selected[5]))
        except (TypeError, ValueError):
            invalid_json += 1
            continue
        candidates.append(
            {
                "decision_id": int(selected[0]),
                "decision_timestamp": timestamp,
                "action": str(selected[2]),
                "confidence": float(selected[3]),
                "signal_strength": float(selected[4]),
                "input": payload,
            }
        )
    return candidates, {
        "journal": _artifact(path),
        "integrity_check": "ok",
        "maximum_decision_id": maximum_id,
        "eligible_rows": len(rows),
        "deduplicated_candidates": len(candidates),
        "duplicates_removed": duplicates,
        "ambiguous_timestamps_rejected": ambiguous,
        "invalid_json_rejected": invalid_json,
    }


def _evaluator_features(payload: dict, direction: str) -> list[float]:
    multiplier = -1.0 if direction == v5.DIRECTIONS[0] else 1.0
    values = []
    for time_frame in TIME_FRAMES:
        rows = payload.get(time_frame)
        if not isinstance(rows, list):
            raise ValueError(f"missing evaluator rows for {time_frame}")
        by_name = {
            str(row.get("evaluator")): row
            for row in rows
            if isinstance(row, dict)
        }
        for evaluator in EVALUATORS:
            row = by_name.get(evaluator)
            if row is None:
                raise ValueError(
                    f"missing {time_frame} {evaluator}"
                )
            values.append(float(row["eval_note"]) * multiplier)
    return values


def simulate_lock_trade(
    *,
    candles: numpy.ndarray,
    entry_index: int,
    direction: str,
    round_trip_cost_pct: float,
    funding_timestamps: numpy.ndarray,
    funding_rates: numpy.ndarray,
) -> typing.Optional[dict]:
    """Return an economically mature protected-profit trade, else None."""

    if entry_index + 1 >= len(candles):
        return None
    entry_price = float(candles[entry_index, 4])
    sign = 1.0 if direction == v5.DIRECTIONS[0] else -1.0
    initial_stop = entry_price * (
        1 - sign * INITIAL_STOP_PCT / 100
    )
    activation = entry_price * (1 + sign * ACTIVATION_PCT / 100)
    protected_stop = entry_price * (
        1 + sign * PROTECTED_STOP_PCT / 100
    )
    required_end = entry_index + HORIZON_BARS
    horizon_complete = required_end < len(candles)
    available_end = min(required_end, len(candles) - 1)
    activation_index = None
    exit_index = None
    exit_price = None
    outcome = None
    for candle_index in range(entry_index + 1, available_end + 1):
        high = float(candles[candle_index, 2])
        low = float(candles[candle_index, 3])
        if activation_index is None:
            stopped = (
                low <= initial_stop
                if direction == v5.DIRECTIONS[0]
                else high >= initial_stop
            )
            activated = (
                high >= activation
                if direction == v5.DIRECTIONS[0]
                else low <= activation
            )
            if stopped:
                exit_index = candle_index
                exit_price = initial_stop
                outcome = "STOP"
                break
            if activated:
                activation_index = candle_index
                continue
        else:
            locked = (
                low <= protected_stop
                if direction == v5.DIRECTIONS[0]
                else high >= protected_stop
            )
            if locked:
                exit_index = candle_index
                exit_price = protected_stop
                outcome = "PROFIT_LOCK"
                break
    label_mature = (
        outcome == "STOP"
        or activation_index is not None
        or horizon_complete
    )
    if not label_mature:
        return None
    if exit_index is None:
        if not horizon_complete:
            return {
                "label": 1,
                "target_reached": True,
                "economic_mature": False,
                "entry_index": entry_index,
                "entry_timestamp": int(candles[entry_index, 0])
                + CANDLE_SECONDS,
                "direction": direction,
            }
        exit_index = required_end
        exit_price = float(candles[exit_index, 4])
        outcome = (
            "HORIZON_AFTER_LOCK"
            if activation_index is not None
            else "TIMEOUT"
        )
    gross_return_pct = (
        (float(exit_price) / entry_price - 1) * 100 * sign
    )
    entry_timestamp = int(candles[entry_index, 0]) + CANDLE_SECONDS
    exit_timestamp = int(candles[exit_index, 0]) + CANDLE_SECONDS
    funding_return_pct = veto_v1._funding_return_pct(
        direction=direction,
        entry_timestamp=entry_timestamp,
        exit_timestamp=exit_timestamp,
        funding_timestamps=funding_timestamps,
        funding_rates=funding_rates,
    )
    return {
        "label": int(activation_index is not None),
        "target_reached": activation_index is not None,
        "economic_mature": True,
        "entry_index": entry_index,
        "exit_index": exit_index,
        "entry_timestamp": entry_timestamp,
        "exit_timestamp": exit_timestamp,
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "direction": direction,
        "outcome": outcome,
        "activation_index": activation_index,
        "gross_return_pct": gross_return_pct,
        "funding_return_pct": funding_return_pct,
        "round_trip_cost_pct": round_trip_cost_pct,
        "net_return_pct": (
            gross_return_pct
            + funding_return_pct
            - round_trip_cost_pct
        ),
        "duration_bars": exit_index - entry_index,
    }


def build_dataset(
    *,
    candles: numpy.ndarray,
    journal_candidates: list[dict],
    v5_model: v5.V5Model,
    funding_timestamps: numpy.ndarray,
    funding_rates: numpy.ndarray,
) -> tuple[MetaDataset, dict, dict]:
    base_features, names = student.sequence_features(candles)
    if names != student.student_feature_names():
        raise ValueError("unexpected V5 feature schema")
    v5_predictions = v5_model.predict(base_features)
    close_to_index = {
        int(open_time) + CANDLE_SECONDS: index
        for index, open_time in enumerate(candles[:, 0])
    }
    features = []
    labels = []
    decision_ids = []
    timestamps = []
    candle_indices = []
    directions = []
    actions = []
    outcomes: list[typing.Optional[dict]] = []
    missing_timestamp = 0
    invalid_input = 0
    provisional = 0
    for candidate in journal_candidates:
        timestamp = int(candidate["decision_timestamp"])
        candle_index = close_to_index.get(timestamp)
        if candle_index is None:
            missing_timestamp += 1
            continue
        if not numpy.all(numpy.isfinite(base_features[candle_index])):
            invalid_input += 1
            continue
        action = str(candidate["action"])
        direction = (
            v5.DIRECTIONS[0] if action == "BUY" else v5.DIRECTIONS[1]
        )
        direction_index = 0 if direction == v5.DIRECTIONS[0] else 1
        opposite_index = 1 - direction_index
        try:
            values = _evaluator_features(
                candidate["input"], direction
            )
        except (KeyError, TypeError, ValueError):
            invalid_input += 1
            continue
        selected_ev = float(
            v5_predictions["expected_net_pct"][
                candle_index, direction_index
            ]
        )
        opposite_ev = float(
            v5_predictions["expected_net_pct"][
                candle_index, opposite_index
            ]
        )
        target_index = int(
            v5_predictions["target_index"][
                candle_index, direction_index
            ]
        )
        horizon_index = int(
            v5_predictions["horizon_index"][
                candle_index, direction_index
            ]
        )
        close_datetime = datetime.datetime.fromtimestamp(
            timestamp, datetime.timezone.utc
        )
        hour_angle = 2 * math.pi * (
            close_datetime.hour + close_datetime.minute / 60
        ) / 24
        weekday_angle = (
            2 * math.pi * close_datetime.weekday() / 7
        )
        values.extend(
            (
                float(candidate["confidence"]),
                float(candidate["signal_strength"]),
                float(direction == v5.DIRECTIONS[1]),
                selected_ev,
                opposite_ev,
                selected_ev - opposite_ev,
                float(
                    v5_predictions["target_probability"][
                        candle_index, direction_index
                    ]
                ),
                float(
                    v5_predictions["stop_probability"][
                        candle_index, direction_index
                    ]
                ),
                float(
                    v5_predictions["timeout_probability"][
                        candle_index, direction_index
                    ]
                ),
                float(v5.TARGET_PROFITS_PCT[target_index]),
                float(v5.HORIZON_HOURS[horizon_index]),
                math.sin(hour_angle),
                math.cos(hour_angle),
                math.sin(weekday_angle),
                math.cos(weekday_angle),
            )
        )
        if not numpy.all(numpy.isfinite(values)):
            invalid_input += 1
            continue
        outcome = simulate_lock_trade(
            candles=candles,
            entry_index=candle_index,
            direction=direction,
            round_trip_cost_pct=ROUND_TRIP_COST_PCT,
            funding_timestamps=funding_timestamps,
            funding_rates=funding_rates,
        )
        label = -1 if outcome is None else int(outcome["label"])
        if outcome is None:
            provisional += 1
        features.append(values)
        labels.append(label)
        decision_ids.append(int(candidate["decision_id"]))
        timestamps.append(timestamp)
        candle_indices.append(candle_index)
        directions.append(direction)
        actions.append(action)
        outcomes.append(outcome)
    matrix = numpy.asarray(features, dtype=numpy.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(feature_names()):
        raise ValueError("event-meta feature matrix is misaligned")
    dataset = MetaDataset(
        features=matrix,
        labels=numpy.asarray(labels, dtype=numpy.int8),
        decision_ids=numpy.asarray(decision_ids, dtype=numpy.int64),
        timestamps=numpy.asarray(timestamps, dtype=numpy.int64),
        candle_indices=numpy.asarray(candle_indices, dtype=numpy.int64),
        directions=numpy.asarray(directions),
        actions=numpy.asarray(actions),
        outcomes=tuple(outcomes),
        feature_names=feature_names(),
    )
    return dataset, {
        "journal_candidates": len(journal_candidates),
        "dataset_rows": len(dataset.labels),
        "mature_labels": int(numpy.sum(dataset.labels >= 0)),
        "positive_labels": int(numpy.sum(dataset.labels == 1)),
        "negative_labels": int(numpy.sum(dataset.labels == 0)),
        "provisional_labels": provisional,
        "missing_timestamp_rejected": missing_timestamp,
        "invalid_input_rejected": invalid_input,
    }, v5_predictions


def _timestamp(date_value: str, inclusive_end: bool = False) -> int:
    date = datetime.date.fromisoformat(date_value)
    moment = datetime.datetime.combine(
        date,
        datetime.time.max if inclusive_end else datetime.time.min,
        datetime.timezone.utc,
    )
    return int(moment.timestamp())


def _split_mask(
    timestamps: numpy.ndarray,
    start: str,
    end: typing.Optional[str],
) -> numpy.ndarray:
    mask = timestamps >= _timestamp(start)
    if end is not None:
        mask &= timestamps <= _timestamp(end, inclusive_end=True)
    return mask


def _roc_auc(labels: numpy.ndarray, scores: numpy.ndarray) -> float:
    positives = labels == 1
    negatives = labels == 0
    positive_count = int(numpy.sum(positives))
    negative_count = int(numpy.sum(negatives))
    if not positive_count or not negative_count:
        return float("nan")
    order = numpy.argsort(scores, kind="mergesort")
    ranks = numpy.empty(len(scores), dtype=float)
    index = 0
    while index < len(scores):
        end = index + 1
        while end < len(scores) and scores[order[end]] == scores[order[index]]:
            end += 1
        ranks[order[index:end]] = (index + 1 + end) / 2
        index = end
    rank_sum = float(numpy.sum(ranks[positives]))
    return (
        rank_sum - positive_count * (positive_count + 1) / 2
    ) / (positive_count * negative_count)


def classification_metrics(
    labels: numpy.ndarray,
    probabilities: numpy.ndarray,
    constant_probability: float,
) -> dict:
    if not len(labels):
        return {
            "examples": 0,
            "base_rate_pct": None,
            "mean_probability_pct": None,
            "brier": None,
            "constant_brier": None,
            "roc_auc": None,
            "ece_pct": None,
        }
    brier = float(numpy.mean((probabilities - labels) ** 2))
    constant_brier = float(
        numpy.mean((constant_probability - labels) ** 2)
    )
    calibration_error = 0.0
    for lower in numpy.linspace(0, 0.9, 10):
        upper = lower + 0.1
        selected = (probabilities >= lower) & (
            probabilities < upper
            if upper < 1
            else probabilities <= upper
        )
        if numpy.any(selected):
            calibration_error += (
                float(numpy.sum(selected))
                / len(labels)
                * abs(
                    float(numpy.mean(probabilities[selected]))
                    - float(numpy.mean(labels[selected]))
                )
            )
    return {
        "examples": len(labels),
        "base_rate_pct": float(numpy.mean(labels) * 100),
        "mean_probability_pct": float(
            numpy.mean(probabilities) * 100
        ),
        "brier": brier,
        "constant_brier": constant_brier,
        "brier_skill_vs_constant_pct": (
            (constant_brier - brier) / constant_brier * 100
            if constant_brier
            else None
        ),
        "roc_auc": _roc_auc(labels, probabilities),
        "ece_pct": calibration_error * 100,
    }


def simulate_policy(
    *,
    dataset: MetaDataset,
    probabilities: numpy.ndarray,
    mask: numpy.ndarray,
    threshold: typing.Optional[float],
    round_trip_cost_pct: float,
) -> tuple[list[dict], dict]:
    next_available = 0
    trades = []
    skipped_open = 0
    provisional = 0
    for row in numpy.flatnonzero(mask):
        if threshold is not None and probabilities[row] < threshold:
            continue
        outcome = dataset.outcomes[row]
        if outcome is None or not outcome.get("economic_mature", False):
            provisional += 1
            continue
        entry_index = int(dataset.candle_indices[row])
        if entry_index < next_available:
            skipped_open += 1
            continue
        trade = dict(outcome)
        trade["round_trip_cost_pct"] = round_trip_cost_pct
        trade["net_return_pct"] = (
            float(trade["gross_return_pct"])
            + float(trade["funding_return_pct"])
            - round_trip_cost_pct
        )
        trade.update(
            {
                "decision_id": int(dataset.decision_ids[row]),
                "probability": float(probabilities[row]),
                "probability_threshold": threshold,
            }
        )
        trades.append(trade)
        next_available = int(trade["exit_index"]) + 1
    return trades, {
        "skipped_while_position_open": skipped_open,
        "provisional_candidates": provisional,
    }


def _json_safe(value: typing.Any) -> typing.Any:
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, numpy.ndarray):
        return value.tolist()
    if isinstance(value, numpy.generic):
        return value.item()
    return value


def run_study(
    *,
    decision_db: typing.Union[str, pathlib.Path],
    collector: typing.Union[str, pathlib.Path],
    funding_path: typing.Union[str, pathlib.Path],
    v5_model_directory: typing.Union[str, pathlib.Path],
    output_directory: typing.Union[str, pathlib.Path],
) -> dict:
    output = pathlib.Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = _verify_protocol(output)
    journal_candidates, journal_snapshot = load_journal_candidates(
        decision_db
    )
    collector_path = pathlib.Path(collector).resolve()
    funding_file = pathlib.Path(funding_path).resolve()
    model_directory = pathlib.Path(v5_model_directory).resolve()
    candles = veto_v1.load_btc_candles(collector_path)
    funding_timestamps, funding_rates = veto_v1.load_btc_funding(
        funding_file
    )
    frozen_v5 = v5.V5Model.load(model_directory)
    dataset, dataset_diagnostics, _v5_predictions = build_dataset(
        candles=candles,
        journal_candidates=journal_candidates,
        v5_model=frozen_v5,
        funding_timestamps=funding_timestamps,
        funding_rates=funding_rates,
    )
    mature = dataset.labels >= 0
    masks = {
        name: _split_mask(dataset.timestamps, *date_range) & mature
        for name, date_range in (
            ("train", SPLITS["train"]),
            ("calibration", SPLITS["calibration"]),
            ("diagnostic_audit", SPLITS["diagnostic_audit"]),
            ("initial_forward", SPLITS["initial_forward"]),
        )
    }
    if (
        numpy.sum(masks["train"]) < 500
        or numpy.sum(masks["calibration"]) < 150
        or numpy.sum(masks["diagnostic_audit"]) < 200
    ):
        raise ValueError("insufficient event-meta examples in frozen splits")
    base_model = model_module.NumpyLogisticModel.fit(
        dataset.features[masks["train"]],
        dataset.labels[masks["train"]],
        dataset.feature_names,
        MODEL_CONFIG,
    )
    calibration_raw = base_model.predict_proba(
        dataset.features[masks["calibration"]]
    )
    calibrator = probability.QuantileIsotonicCalibrator.fit(
        calibration_raw,
        dataset.labels[masks["calibration"]],
    )
    raw_probabilities = base_model.predict_proba(dataset.features)
    calibrated_probabilities = calibrator.predict(raw_probabilities)
    calibration_constant = float(
        numpy.mean(dataset.labels[masks["calibration"]])
    )
    classifications = {
        split: {
            "raw": classification_metrics(
                dataset.labels[mask],
                raw_probabilities[mask],
                calibration_constant,
            ),
            "calibrated": classification_metrics(
                dataset.labels[mask],
                calibrated_probabilities[mask],
                calibration_constant,
            ),
        }
        for split, mask in masks.items()
    }
    economic = {}
    flows = {}
    stored_trades = {}
    for split in ("diagnostic_audit", "initial_forward"):
        mask = masks[split]
        baseline, baseline_flow = simulate_policy(
            dataset=dataset,
            probabilities=calibrated_probabilities,
            mask=mask,
            threshold=None,
            round_trip_cost_pct=ROUND_TRIP_COST_PCT,
        )
        filtered, filtered_flow = simulate_policy(
            dataset=dataset,
            probabilities=calibrated_probabilities,
            mask=mask,
            threshold=PROBABILITY_THRESHOLD,
            round_trip_cost_pct=ROUND_TRIP_COST_PCT,
        )
        stress, stress_flow = simulate_policy(
            dataset=dataset,
            probabilities=calibrated_probabilities,
            mask=mask,
            threshold=PROBABILITY_THRESHOLD,
            round_trip_cost_pct=STRESS_ROUND_TRIP_COST_PCT,
        )
        economic[split] = {
            "unfiltered": veto_v1.trade_metrics(baseline),
            "filtered": veto_v1.trade_metrics(filtered),
            "filtered_stress": veto_v1.trade_metrics(stress),
        }
        flows[split] = {
            "unfiltered": baseline_flow,
            "filtered": filtered_flow,
            "filtered_stress": stress_flow,
        }
        stored_trades[split] = {
            "unfiltered": baseline,
            "filtered": filtered,
            "filtered_stress": stress,
        }
    audit_classification = classifications["diagnostic_audit"][
        "calibrated"
    ]
    audit_economic = economic["diagnostic_audit"]
    filtered_metrics = audit_economic["filtered"]
    filtered_stress = audit_economic["filtered_stress"]
    gate_results = {
        "minimum_filtered_trades": filtered_metrics["trades"] >= 10,
        "both_directions": all(
            filtered_metrics["by_direction"][direction]["trades"] > 0
            for direction in v5.DIRECTIONS
        ),
        "profit_factor_at_least_1_20": (
            filtered_metrics["profit_factor"] is not None
            and filtered_metrics["profit_factor"] >= 1.20
        ),
        "positive_compounded_return": (
            filtered_metrics["compounded_net_return_pct"] > 0
        ),
        "maximum_drawdown_at_most_10": (
            filtered_metrics["maximum_drawdown_pct"] <= 10
        ),
        "brier_below_constant": (
            audit_classification["brier"]
            < audit_classification["constant_brier"]
        ),
        "stress_compounded_return_non_negative": (
            filtered_stress["compounded_net_return_pct"] >= 0
        ),
    }
    gate = {
        "results": gate_results,
        "passed": all(gate_results.values()),
        "orders_authorized": False,
        "automatic_promotion": False,
    }
    model_root = output / "model"
    model_root.mkdir(parents=True, exist_ok=True)
    model_path = model_root / "base_model.npz"
    calibrator_path = model_root / "calibrator.json"
    base_model.save(model_path)
    calibrator.save(calibrator_path)
    restored_model = model_module.NumpyLogisticModel.load(model_path)
    restored_calibrator = probability.QuantileIsotonicCalibrator.load(
        calibrator_path
    )
    replay = restored_calibrator.predict(
        restored_model.predict_proba(dataset.features)
    )
    if not numpy.array_equal(
        calibrated_probabilities, replay, equal_nan=True
    ):
        raise ValueError("reloaded event-meta predictions differ")

    crash_rows = numpy.flatnonzero(
        dataset.timestamps == CRASH_CASE_DECISION_TIMESTAMP
    )
    crash_case = {
        "decision_timestamp": CRASH_CASE_DECISION_TIMESTAMP,
        "found": len(crash_rows) == 1,
        "used_for_fit_calibration_or_threshold": False,
    }
    if len(crash_rows) == 1:
        row = int(crash_rows[0])
        crash_case.update(
            {
                "decision_id": int(dataset.decision_ids[row]),
                "direction": str(dataset.directions[row]),
                "predicted_success_probability_pct": float(
                    calibrated_probabilities[row] * 100
                ),
                "threshold_pct": PROBABILITY_THRESHOLD * 100,
                "accepted": bool(
                    calibrated_probabilities[row]
                    >= PROBABILITY_THRESHOLD
                ),
                "observed": dataset.outcomes[row],
            }
        )

    predictions_path = output / "predictions.npz"
    numpy.savez_compressed(
        predictions_path,
        decision_ids=dataset.decision_ids,
        timestamps=dataset.timestamps,
        labels=dataset.labels,
        raw_probabilities=raw_probabilities,
        calibrated_probabilities=calibrated_probabilities,
    )
    trades_path = output / "trades.json"
    trades_path.write_text(
        json.dumps(_json_safe(stored_trades), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "research_only": True,
        "diagnostic_reuse": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol": {
            "path": str((output / "protocol.json").resolve()),
            "sha256": protocol["protocol_sha256"],
        },
        "inputs": {
            "journal_snapshot": journal_snapshot,
            "collector": _artifact(collector_path),
            "funding": _artifact(funding_file),
            "v5_model": {
                str(path.relative_to(model_directory)): _artifact(path)
                for path in sorted(model_directory.rglob("*"))
                if path.is_file()
            },
        },
        "dataset": dataset_diagnostics,
        "split_rows": {
            name: int(numpy.sum(mask))
            for name, mask in masks.items()
        },
        "classification": classifications,
        "economic": economic,
        "flows": flows,
        "gate": gate,
        "crash_case": crash_case,
        "model": {
            "base_model": _artifact(model_path),
            "calibrator": _artifact(calibrator_path),
            "reloaded_prediction_max_absolute_difference": float(
                numpy.max(
                    numpy.abs(calibrated_probabilities - replay)
                )
            ),
        },
        "warning": (
            "All audit dates are reused or too short for promotion. "
            "This model cannot create paper or real orders."
        ),
    }
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {
        **report,
        "artifacts": {
            "predictions": _artifact(predictions_path),
            "trades": _artifact(trades_path),
            "report": _artifact(report_path),
        },
        "report_path": str(report_path),
    }


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-db")
    parser.add_argument("--collector")
    parser.add_argument("--funding")
    parser.add_argument("--v5-model")
    parser.add_argument("--output", required=True)
    parser.add_argument("--write-protocol", action="store_true")
    args = parser.parse_args(argv)
    if args.write_protocol:
        path = write_protocol(args.output)
        print(json.dumps({"protocol": str(path)}, indent=2))
        return 0
    required = {
        "--decision-db": args.decision_db,
        "--collector": args.collector,
        "--funding": args.funding,
        "--v5-model": args.v5_model,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")
    result = run_study(
        decision_db=args.decision_db,
        collector=args.collector,
        funding_path=args.funding,
        v5_model_directory=args.v5_model,
        output_directory=args.output,
    )
    print(
        json.dumps(
            {
                "report": result["report_path"],
                "gate": result["gate"],
                "classification": result["classification"],
                "economic": result["economic"],
                "crash_case": result["crash_case"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
