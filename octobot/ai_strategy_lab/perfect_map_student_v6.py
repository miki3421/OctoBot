"""Pre-registered V6 challenger protocol for future-path forecasting.

The design and implementation manifests are frozen before results are
computed. The module provides offline training and evaluation but contains no
paper-trading runtime and cannot authorize orders. In particular, the frozen
V5 forward journal is an explicitly forbidden development input.
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
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v2 as v2
from octobot.ai_strategy_lab import perfect_map_student_v3 as v3
from octobot.ai_strategy_lab import perfect_map_student_v4 as v4
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_future_path_efficiency_ensemble_v6"
PREREGISTRATION_DATE = "2026-07-26"
ENSEMBLE_SEEDS = (
    20_260_801,
    20_260_802,
    20_260_803,
    20_260_804,
    20_260_805,
)
TIME_NORMALIZED_THRESHOLDS = (0.000, 0.0125, 0.025, 0.0375, 0.050)
RAW_EXPECTED_NET_FLOOR_PCT = 0.075
UNCERTAINTY_STANDARD_DEVIATIONS = 1.0
CALIBRATION_CONFIG = {
    **v5.CALIBRATION_CONFIG,
    "seed": 20_260_806,
}


def protocol_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def frozen_protocol() -> dict:
    """Return the result-free V6 protocol frozen before implementation."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "preregistered_design_only",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent": {
            "protocol_version": v5.PROTOCOL_VERSION,
            "immutable": True,
            "v5_threshold_or_weights_may_change": False,
            "motivation": (
                "reduce long-horizon/maximum-target concentration and account "
                "for forecast uncertainty without retuning V5"
            ),
        },
        "data_policy": {
            "allowed_for_fit_and_selection": {
                "train": list(v1.SPLITS["train"]),
                "calibration": list(v1.SPLITS["calibration"]),
                "threshold_selection": list(
                    v1.SPLITS["threshold_selection"]
                ),
            },
            "diagnostic_reuse_only": {
                "binance": list(v1.SPLITS["locked_test"]),
                "kucoin": list(v1.SPLITS["external_reused_kucoin"]),
            },
            "forbidden_for_fit_calibration_and_selection": [
                "/v5-paper/binance/v5-paper.sqlite",
                "/v5-paper/binance/health.json",
                "all V5 forward decisions, events, positions and outcomes",
            ],
            "first_eligible_new_forward_date": "2026-07-27",
            "future_used_for_labels_only": True,
        },
        "prediction_target": v5.frozen_protocol()["prediction_target"],
        "features": {
            "schema": "perfect_map_student_v1_99_causal_features",
            "feature_count": len(v1.student_feature_names()),
            "new_feature_search": False,
        },
        "forecast": {
            "type": "five_member_block_resampled_grouped_softmax_ensemble",
            "members": len(ENSEMBLE_SEEDS),
            "seeds": list(ENSEMBLE_SEEDS),
            "training_block_hours": 168,
            "base_head_schema": "same_50_stop_timeout_target_heads_as_v5",
            "logical_probability_projection": "same_as_v5",
            "calibration": {
                "type": "per_head_joint_softmax_on_ensemble_mean_logits",
                "split": "calibration_only",
            },
            "uncertainty": (
                "sample standard deviation of expected net across members"
            ),
        },
        "decision": {
            "raw_expected_net_pct": (
                "P(TARGET)*protected_profit_pct "
                "- P(STOP)*initial_stop_pct - round_trip_cost_pct"
            ),
            "conservative_expected_net_pct": (
                "ensemble_mean_expected_net_pct "
                "- 1.0*ensemble_standard_deviation_expected_net_pct"
            ),
            "time_normalized_score": (
                "conservative_expected_net_pct / sqrt(horizon_hours)"
            ),
            "choose": (
                "maximum time_normalized_score configuration and direction "
                "per closed candle"
            ),
            "raw_expected_net_floor_pct": RAW_EXPECTED_NET_FLOOR_PCT,
            "time_normalized_threshold_candidates": list(
                TIME_NORMALIZED_THRESHOLDS
            ),
            "minimum_direction_margin_pct": (
                v5.MINIMUM_DIRECTION_MARGIN_PCT
            ),
            "one_trade_at_a_time": True,
            "threshold_selection_objective": (
                "compounded_net_return_pct minus maximum_drawdown_pct"
            ),
            "selection_gate": {
                "minimum_closed_trades": 20,
                "profit_factor": 1.10,
                "positive_compounded_return": True,
                "positive_objective": True,
                "at_least_one_trade_per_direction": True,
                "at_least_two_distinct_targets": True,
                "at_least_two_distinct_horizons": True,
                "maximum_single_target_share": 0.75,
                "maximum_single_horizon_share": 0.75,
            },
            "tie_break_order": [
                "higher conservative expected net",
                "shorter horizon",
                "smaller protected target",
                "LONG before SHORT for exact numeric equality",
            ],
        },
        "simulation": v5.frozen_protocol()["simulation"],
        "evidence_policy": {
            "development_result_can_promote_v5": False,
            "diagnostic_reuse_can_promote_v6": False,
            "new_forward_required": True,
            "minimum_new_forward_days": 90,
            "minimum_new_forward_closed_trades": 30,
            "paper_activation_requires_manual_approval": True,
            "no_mid_test_retuning": True,
        },
        "implementation_policy": {
            "protocol_must_exist_before_training": True,
            "persist_protocol_hash_with_every_artifact": True,
            "persist_dataset_model_prediction_and_report_hashes": True,
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
            {
                **protocol,
                "protocol_sha256": protocol_sha256(protocol),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def frozen_implementation_manifest() -> dict:
    """Freeze deterministic details not expanded in the design protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256(frozen_protocol()),
        "result_free": True,
        "training": {
            "base_config": {
                name: value
                for name, value in v5.PRIMARY_CONFIG.items()
                if name != "seed"
            },
            "member_seeds": list(ENSEMBLE_SEEDS),
            "training_stride": v5.TRAINING_STRIDE,
            "resampling": {
                "type": "fixed_length_moving_block_bootstrap",
                "block_hours": 168,
                "sample_rows": "same_count_as_strided_training_rows",
                "start_sampling": "uniform_with_replacement",
                "partial_final_block": "truncate_to_sample_rows",
            },
        },
        "calibration": {
            "input": "arithmetic_mean_of_member_logits",
            "config": CALIBRATION_CONFIG,
            "member_uncertainty_probabilities": (
                "common_calibrator_applied_to_each_member_logits"
            ),
            "probability_surface": "V5 coherent projection per member",
        },
        "decision": {
            "ensemble_mean": "arithmetic_mean_across_members",
            "ensemble_uncertainty": "sample_standard_deviation_ddof_1",
            "configuration_tie_break": [
                "higher time_normalized_score",
                "higher conservative_expected_net_pct",
                "shorter horizon",
                "smaller protected target",
            ],
            "direction_tie_break": [
                "higher time_normalized_score",
                "higher conservative_expected_net_pct",
                "LONG",
            ],
            "direction_margin_basis": "conservative_expected_net_pct",
            "threshold_tie_break": [
                "higher selection objective",
                "more closed trades",
                "higher time-normalized threshold",
            ],
        },
        "persistence": {
            "float_arrays": "numpy_native_precision",
            "prediction_replay_tolerance": 0.0,
        },
    }


def write_implementation_manifest(
    output_value: typing.Union[str, pathlib.Path]
) -> pathlib.Path:
    output = pathlib.Path(output_value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = frozen_implementation_manifest()
    path = output / "implementation.json"
    path.write_text(
        json.dumps(
            {
                **manifest,
                "implementation_sha256": protocol_sha256(manifest),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _verify_preregistration(output: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    protocol_path = output / "protocol.json"
    implementation_path = output / "implementation.json"
    if not protocol_path.is_file() or not implementation_path.is_file():
        raise FileNotFoundError(
            "write protocol.json and implementation.json before V6 training"
        )
    persisted_protocol = json.loads(
        protocol_path.read_text(encoding="utf-8")
    )
    expected_protocol = frozen_protocol()
    if persisted_protocol.get("protocol_sha256") != protocol_sha256(
        expected_protocol
    ):
        raise ValueError("persisted V6 protocol differs from frozen code")
    persisted_implementation = json.loads(
        implementation_path.read_text(encoding="utf-8")
    )
    expected_implementation = frozen_implementation_manifest()
    if persisted_implementation.get(
        "implementation_sha256"
    ) != protocol_sha256(expected_implementation):
        raise ValueError(
            "persisted V6 implementation manifest differs from frozen code"
        )
    return protocol_path, implementation_path


@dataclasses.dataclass(frozen=True)
class V6Model:
    members: tuple[v5.NumpyGroupedSoftmaxModel, ...]
    calibrator: v5.NumpyGroupedSoftmaxCalibrator
    time_normalized_threshold: float

    def predict(self, features: numpy.ndarray) -> dict[str, numpy.ndarray]:
        member_probabilities = []
        for member in self.members:
            logits = member.predict_logits(features)
            probabilities = self.calibrator.predict_proba(logits)
            member_probabilities.append(
                v5.coherent_probability_surface(probabilities)
            )
        stacked = numpy.stack(member_probabilities)
        return ensemble_path_decisions(stacked)

    @classmethod
    def load(
        cls, directory_value: typing.Union[str, pathlib.Path]
    ) -> "V6Model":
        directory = pathlib.Path(directory_value).resolve()
        metadata = json.loads(
            (directory / "model.json").read_text(encoding="utf-8")
        )
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported V6 model schema")
        if metadata.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported V6 model protocol")
        member_files = metadata.get("member_files", [])
        if len(member_files) != len(ENSEMBLE_SEEDS):
            raise ValueError("V6 persisted ensemble member count differs")
        members = tuple(
            v5.NumpyGroupedSoftmaxModel.load(directory / name)
            for name in member_files
        )
        calibrator = v5.NumpyGroupedSoftmaxCalibrator.load(
            directory / "calibrator.npz"
        )
        first = members[0]
        if any(
            member.feature_names != first.feature_names
            or member.head_names != first.head_names
            for member in members[1:]
        ):
            raise ValueError("V6 persisted ensemble schemas differ")
        if calibrator.head_names != first.head_names:
            raise ValueError("V6 persisted calibration heads differ")
        return cls(
            members=members,
            calibrator=calibrator,
            time_normalized_threshold=float(
                metadata["time_normalized_threshold"]
            ),
        )


def _expected_net_surface(
    probabilities: numpy.ndarray,
) -> numpy.ndarray:
    reshaped = probabilities.reshape(
        *probabilities.shape[:-2],
        len(v5.DIRECTIONS),
        len(v5.TARGET_PROFITS_PCT),
        len(v5.HORIZON_HOURS),
        len(v5.CLASS_NAMES),
    )
    target_probabilities = reshaped[..., v5.TARGET_CLASS]
    targets = numpy.asarray(v5.TARGET_PROFITS_PCT).reshape(
        (1,) * (target_probabilities.ndim - 2)
        + (len(v5.TARGET_PROFITS_PCT), 1)
    )
    return (
        target_probabilities * targets
        - reshaped[..., v5.STOP_CLASS] * v5.INITIAL_STOP_PCT
        - v5.ROUND_TRIP_COST_PCT
    )


def ensemble_path_decisions(
    member_probabilities: numpy.ndarray,
) -> dict[str, numpy.ndarray]:
    """Aggregate member surfaces and choose the frozen V6 configuration."""

    expected_shape = (
        len(v5.HEAD_SPECS),
        len(v5.CLASS_NAMES),
    )
    if (
        member_probabilities.ndim != 4
        or member_probabilities.shape[0] < 2
        or member_probabilities.shape[2:] != expected_shape
    ):
        raise ValueError("V6 member probability surface shape differs")
    member_expected = _expected_net_surface(member_probabilities)
    mean_expected = numpy.mean(member_expected, axis=0)
    standard_deviation = numpy.std(member_expected, axis=0, ddof=1)
    conservative = (
        mean_expected
        - UNCERTAINTY_STANDARD_DEVIATIONS * standard_deviation
    )
    horizons = numpy.sqrt(
        numpy.asarray(v5.HORIZON_HOURS, dtype=float)
    )[None, None, None, :]
    time_score = conservative / horizons

    maximum_score = numpy.max(time_score, axis=(2, 3), keepdims=True)
    score_ties = time_score == maximum_score
    tied_conservative = numpy.where(score_ties, conservative, -numpy.inf)
    maximum_conservative = numpy.max(
        tied_conservative, axis=(2, 3), keepdims=True
    )
    final_ties = score_ties & (
        conservative == maximum_conservative
    )
    configuration_order = [
        (target_index, horizon_index)
        for horizon_index in range(len(v5.HORIZON_HOURS))
        for target_index in range(len(v5.TARGET_PROFITS_PCT))
    ]
    ordered_ties = numpy.stack(
        [
            final_ties[..., target_index, horizon_index]
            for target_index, horizon_index in configuration_order
        ],
        axis=-1,
    )
    best_ordered = numpy.argmax(ordered_ties, axis=-1)
    target_lookup = numpy.asarray(
        [value[0] for value in configuration_order], dtype=numpy.int8
    )
    horizon_lookup = numpy.asarray(
        [value[1] for value in configuration_order], dtype=numpy.int8
    )
    target_index = target_lookup[best_ordered]
    horizon_index = horizon_lookup[best_ordered]

    rows = numpy.arange(member_probabilities.shape[1])[:, None]
    directions = numpy.arange(len(v5.DIRECTIONS))[None, :]
    mean_probabilities = numpy.mean(member_probabilities, axis=0)
    reshaped_probabilities = mean_probabilities.reshape(
        len(mean_probabilities),
        len(v5.DIRECTIONS),
        len(v5.TARGET_PROFITS_PCT),
        len(v5.HORIZON_HOURS),
        len(v5.CLASS_NAMES),
    )
    selected_probabilities = reshaped_probabilities[
        rows,
        directions,
        target_index,
        horizon_index,
    ]
    selected_mean = mean_expected[
        rows, directions, target_index, horizon_index
    ]
    selected_standard_deviation = standard_deviation[
        rows, directions, target_index, horizon_index
    ]
    selected_conservative = conservative[
        rows, directions, target_index, horizon_index
    ]
    selected_time_score = time_score[
        rows, directions, target_index, horizon_index
    ]
    return {
        "probabilities": mean_probabilities,
        "expected_net_pct": selected_mean,
        "expected_net_standard_deviation_pct": (
            selected_standard_deviation
        ),
        "conservative_expected_net_pct": selected_conservative,
        "time_normalized_score": selected_time_score,
        "target_index": target_index,
        "horizon_index": horizon_index,
        "target_probability": selected_probabilities[
            ..., v5.TARGET_CLASS
        ],
        "stop_probability": selected_probabilities[..., v5.STOP_CLASS],
        "timeout_probability": selected_probabilities[
            ..., v5.TIMEOUT_CLASS
        ],
    }


def decision_labels(
    predictions: dict[str, numpy.ndarray], threshold: float
) -> numpy.ndarray:
    time_scores = predictions["time_normalized_score"]
    conservative = predictions["conservative_expected_net_pct"]
    mean_expected = predictions["expected_net_pct"]
    labels = numpy.zeros(len(time_scores), dtype=numpy.int8)
    margin = numpy.abs(conservative[:, 0] - conservative[:, 1])
    long_preferred = (time_scores[:, 0] > time_scores[:, 1]) | (
        (time_scores[:, 0] == time_scores[:, 1])
        & (conservative[:, 0] >= conservative[:, 1])
    )
    selected_mean_expected = numpy.where(
        long_preferred, mean_expected[:, 0], mean_expected[:, 1]
    )
    selected_time_score = numpy.where(
        long_preferred, time_scores[:, 0], time_scores[:, 1]
    )
    eligible = (
        selected_time_score >= threshold
    ) & (
        selected_mean_expected >= RAW_EXPECTED_NET_FLOOR_PCT
    ) & (margin >= v5.MINIMUM_DIRECTION_MARGIN_PCT)
    labels[eligible & long_preferred] = v1.LONG
    labels[eligible & ~long_preferred] = v1.SHORT
    return labels


def _block_resampled_rows(
    train_rows: numpy.ndarray,
    timestamps: numpy.ndarray,
    seed: int,
    block_hours: int = 168,
) -> tuple[numpy.ndarray, int]:
    if len(train_rows) < 2:
        raise ValueError("V6 training split is too short")
    spacing_seconds = float(
        numpy.median(numpy.diff(timestamps[train_rows]))
    )
    if not math.isfinite(spacing_seconds) or spacing_seconds <= 0:
        raise ValueError("V6 training timestamps are not increasing")
    block_rows = max(
        1, int(round(block_hours * 3600 / spacing_seconds))
    )
    block_rows = min(block_rows, len(train_rows))
    maximum_start = len(train_rows) - block_rows
    block_count = math.ceil(len(train_rows) / block_rows)
    generator = numpy.random.default_rng(seed)
    starts = generator.integers(
        0, maximum_start + 1, size=block_count
    )
    sampled_positions = numpy.concatenate(
        [
            numpy.arange(start, start + block_rows)
            for start in starts
        ]
    )[: len(train_rows)]
    return train_rows[sampled_positions], block_rows


def fit_v6(
    dataset: v1.StudentDataset,
    outcomes: numpy.ndarray,
) -> tuple[V6Model, dict]:
    train_mask = v1._date_mask(dataset.timestamps, *v1.SPLITS["train"])
    train_rows = numpy.flatnonzero(train_mask)[::v5.TRAINING_STRIDE]
    calibration_mask = v1._date_mask(
        dataset.timestamps, *v1.SPLITS["calibration"]
    )
    calibration_rows = numpy.flatnonzero(calibration_mask)
    head_names = tuple(spec.name for spec in v5.HEAD_SPECS)
    members = []
    block_rows = None
    for seed in ENSEMBLE_SEEDS:
        sampled_rows, current_block_rows = _block_resampled_rows(
            train_rows, dataset.timestamps, seed
        )
        block_rows = current_block_rows
        config = {**v5.PRIMARY_CONFIG, "seed": seed}
        members.append(
            v5.NumpyGroupedSoftmaxModel.fit(
                dataset.features[sampled_rows],
                outcomes[sampled_rows],
                v1.student_feature_names(),
                head_names,
                v5.CLASS_NAMES,
                config,
            )
        )
    calibration_logits = numpy.mean(
        numpy.stack(
            [
                member.predict_logits(
                    dataset.features[calibration_rows]
                )
                for member in members
            ]
        ),
        axis=0,
    )
    calibrator = v5.NumpyGroupedSoftmaxCalibrator.fit(
        calibration_logits,
        outcomes[calibration_rows],
        head_names,
        v5.CLASS_NAMES,
        CALIBRATION_CONFIG,
    )
    model = V6Model(
        members=tuple(members),
        calibrator=calibrator,
        time_normalized_threshold=TIME_NORMALIZED_THRESHOLDS[0],
    )
    calibration_predictions = model.predict(
        dataset.features[calibration_rows]
    )
    return (
        model,
        {
            "training_rows_per_member": len(train_rows),
            "training_block_rows": block_rows,
            "training_block_hours": 168,
            "calibration_rows": len(calibration_rows),
            "members": len(members),
            "heads": len(v5.HEAD_SPECS),
            "calibration": v5.surface_diagnostics(
                outcomes[calibration_rows],
                calibration_predictions["probabilities"],
            ),
            "mean_selected_expected_net_standard_deviation_pct": float(
                numpy.mean(
                    calibration_predictions[
                        "expected_net_standard_deviation_pct"
                    ]
                )
            ),
        },
    )


def _trade_concentration(trades: list[dict]) -> dict:
    def summarize(name: str) -> dict:
        values: dict[str, int] = {}
        for trade in trades:
            key = str(trade[name])
            values[key] = values.get(key, 0) + 1
        largest = max(values.values(), default=0)
        return {
            "counts": values,
            "distinct": len(values),
            "largest_share": (
                largest / len(trades) if trades else 0.0
            ),
        }

    return {
        "target_profit_pct": summarize("target_profit_pct"),
        "horizon_hours": summarize("horizon_hours"),
    }


def decision_diagnostics(
    predictions: dict[str, numpy.ndarray],
    labels: numpy.ndarray,
) -> dict:
    selected_rows = numpy.flatnonzero(labels != v1.WAIT)
    if not len(selected_rows):
        return {
            "signals": 0,
            "long_signals": 0,
            "short_signals": 0,
            "target_profit_pct": {},
            "horizon_hours": {},
        }
    direction_indices = numpy.where(
        labels[selected_rows] == v1.LONG, 0, 1
    )
    target_indices = predictions["target_index"][
        selected_rows, direction_indices
    ]
    horizon_indices = predictions["horizon_index"][
        selected_rows, direction_indices
    ]
    return {
        "signals": len(selected_rows),
        "long_signals": int(numpy.sum(labels == v1.LONG)),
        "short_signals": int(numpy.sum(labels == v1.SHORT)),
        "mean_expected_net_pct": float(
            numpy.mean(
                predictions["expected_net_pct"][
                    selected_rows, direction_indices
                ]
            )
        ),
        "mean_expected_net_standard_deviation_pct": float(
            numpy.mean(
                predictions["expected_net_standard_deviation_pct"][
                    selected_rows, direction_indices
                ]
            )
        ),
        "mean_conservative_expected_net_pct": float(
            numpy.mean(
                predictions["conservative_expected_net_pct"][
                    selected_rows, direction_indices
                ]
            )
        ),
        "mean_time_normalized_score": float(
            numpy.mean(
                predictions["time_normalized_score"][
                    selected_rows, direction_indices
                ]
            )
        ),
        "target_profit_pct": {
            str(target): int(numpy.sum(target_indices == index))
            for index, target in enumerate(v5.TARGET_PROFITS_PCT)
        },
        "horizon_hours": {
            str(hours): int(numpy.sum(horizon_indices == index))
            for index, hours in enumerate(v5.HORIZON_HOURS)
        },
    }


def simulate_predictions(
    dataset: v1.StudentDataset,
    predictions: dict[str, numpy.ndarray],
    threshold: float,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> list[dict]:
    labels = decision_labels(predictions, threshold)
    candidates = []
    for row in numpy.flatnonzero(labels != v1.WAIT):
        direction_index = 0 if labels[row] == v1.LONG else 1
        opposite_index = 1 - direction_index
        target_index = int(
            predictions["target_index"][row, direction_index]
        )
        horizon_index = int(
            predictions["horizon_index"][row, direction_index]
        )
        candidates.append(
            {
                "entry_index": int(dataset.candle_indices[row]),
                "direction": v5.DIRECTIONS[direction_index],
                "expected_net_pct": float(
                    predictions["expected_net_pct"][
                        row, direction_index
                    ]
                ),
                "opposite_expected_net_pct": float(
                    predictions["expected_net_pct"][
                        row, opposite_index
                    ]
                ),
                "expected_net_standard_deviation_pct": float(
                    predictions[
                        "expected_net_standard_deviation_pct"
                    ][row, direction_index]
                ),
                "conservative_expected_net_pct": float(
                    predictions["conservative_expected_net_pct"][
                        row, direction_index
                    ]
                ),
                "time_normalized_score": float(
                    predictions["time_normalized_score"][
                        row, direction_index
                    ]
                ),
                "target_probability_pct": float(
                    predictions["target_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "stop_probability_pct": float(
                    predictions["stop_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "timeout_probability_pct": float(
                    predictions["timeout_probability"][
                        row, direction_index
                    ]
                    * 100
                ),
                "target_profit_pct": v5.TARGET_PROFITS_PCT[
                    target_index
                ],
                "horizon_hours": v5.HORIZON_HOURS[horizon_index],
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
                candidate["target_profit_pct"]
                + v5.ACTIVATION_BUFFER_PCT
            ),
            initial_stop_pct=v5.INITIAL_STOP_PCT,
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
            1
            if trade["direction"] == percentage_engine.LONG
            else -1
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


def select_threshold(
    model: V6Model,
    dataset: v1.StudentDataset,
    outcomes: numpy.ndarray,
    oracle: v2.SparseOracle,
    funding_series: tuple[numpy.ndarray, numpy.ndarray],
) -> tuple[float, list[dict], dict]:
    date_range = v1.SPLITS["threshold_selection"]
    mask = v1._date_mask(dataset.timestamps, *date_range)
    rows = numpy.flatnonzero(mask)
    subset = dataset.take(mask)
    predictions = model.predict(subset.features)
    table = []
    for threshold in TIME_NORMALIZED_THRESHOLDS:
        trades = simulate_predictions(
            subset, predictions, threshold, funding_series
        )
        metrics = h2_backtest._metrics(
            trades, v5.ROUND_TRIP_COST_PCT
        )
        objective = (
            metrics["compounded_net_return_pct"]
            - metrics["maximum_drawdown_pct"]
        )
        table.append(
            {
                "time_normalized_threshold": threshold,
                "eligible": metrics["trades"] >= 20,
                "objective": objective,
                "concentration": _trade_concentration(trades),
                "metrics": metrics,
            }
        )
    eligible = [value for value in table if value["eligible"]]
    selected = max(
        eligible or table,
        key=lambda value: (
            value["objective"],
            value["metrics"]["trades"],
            value["time_normalized_threshold"],
        ),
    )
    metrics = selected["metrics"]
    concentration = selected["concentration"]
    target_concentration = concentration["target_profit_pct"]
    horizon_concentration = concentration["horizon_hours"]
    gate = {
        "minimum_closed_trades": metrics["trades"] >= 20,
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
        "at_least_two_distinct_targets": (
            target_concentration["distinct"] >= 2
        ),
        "at_least_two_distinct_horizons": (
            horizon_concentration["distinct"] >= 2
        ),
        "maximum_single_target_share": (
            target_concentration["largest_share"] <= 0.75
        ),
        "maximum_single_horizon_share": (
            horizon_concentration["largest_share"] <= 0.75
        ),
    }
    selected_threshold = float(
        selected["time_normalized_threshold"]
    )
    predicted = decision_labels(predictions, selected_threshold)
    zones = v3.anticipatory_zone_labels(
        dataset, oracle, date_range
    )
    return (
        selected_threshold,
        table,
        {
            "results": gate,
            "passed": all(gate.values()),
            "surface": v5.surface_diagnostics(
                outcomes[rows], predictions["probabilities"]
            ),
            "zone_classification": v2.sparse_classification_metrics(
                zones[rows], predicted
            ),
            "decision_distribution": decision_diagnostics(
                predictions, predicted
            ),
            "trade_concentration": concentration,
        },
    )


def evaluate_audit(
    *,
    name: str,
    model: V6Model,
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
        model.time_normalized_threshold,
        funding_series,
    )
    for trade in trades:
        trade["exchange"] = exchange
    predicted = decision_labels(
        predictions, model.time_normalized_threshold
    )
    zones = v3.anticipatory_zone_labels(dataset, oracle, date_range)
    metrics = h2_backtest._metrics(
        trades, v5.ROUND_TRIP_COST_PCT
    )
    metrics.update(v4._excursion_metrics(trades))
    return (
        {
            "name": name,
            "evidence_role": "diagnostic_reuse",
            "start": date_range[0],
            "end": date_range[1],
            "surface": v5.surface_diagnostics(
                outcomes[rows], predictions["probabilities"]
            ),
            "zone_classification": v2.sparse_classification_metrics(
                zones[rows], predicted
            ),
            "decision_distribution": decision_diagnostics(
                predictions, predicted
            ),
            "trade_concentration": _trade_concentration(trades),
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


def _save_model(model: V6Model, directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    member_files = []
    for index, member in enumerate(model.members):
        name = f"member_{index}.npz"
        member_files.append(name)
        artifacts[f"member_{index}"] = member.save(directory / name)
    artifacts["calibrator"] = model.calibrator.save(
        directory / "calibrator.npz"
    )
    metadata_path = directory / "model.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "protocol_sha256": protocol_sha256(frozen_protocol()),
                "implementation_sha256": protocol_sha256(
                    frozen_implementation_manifest()
                ),
                "research_only": True,
                "orders_authorized": False,
                "paper_orders_authorized": False,
                "feature_names": list(
                    model.members[0].feature_names
                ),
                "head_names": list(model.members[0].head_names),
                "class_names": list(v5.CLASS_NAMES),
                "member_files": member_files,
                "time_normalized_threshold": (
                    model.time_normalized_threshold
                ),
                "raw_expected_net_floor_pct": (
                    RAW_EXPECTED_NET_FLOOR_PCT
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


def _prediction_replay_max_difference(
    original: dict[str, numpy.ndarray],
    replayed: dict[str, numpy.ndarray],
) -> float:
    differences = []
    for name, values in original.items():
        if name not in replayed:
            raise ValueError(f"V6 replay is missing {name}")
        if values.shape != replayed[name].shape:
            raise ValueError(f"V6 replay shape differs for {name}")
        differences.append(
            float(numpy.max(numpy.abs(values - replayed[name])))
            if values.size
            else 0.0
        )
    return max(differences, default=0.0)


def run_study(
    *,
    binance_collector: typing.Union[str, pathlib.Path],
    binance_funding: typing.Union[str, pathlib.Path],
    kucoin_collector: typing.Union[str, pathlib.Path],
    kucoin_funding: typing.Union[str, pathlib.Path],
    output_directory: typing.Union[str, pathlib.Path],
) -> dict:
    output = pathlib.Path(output_directory).resolve()
    protocol_path, implementation_path = _verify_preregistration(output)
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
    binance_outcomes = v5.future_path_outcomes(binance_dataset)
    kucoin_outcomes = v5.future_path_outcomes(kucoin_dataset)
    binance_funding_values = v1._btc_funding(
        binance_funding_path
    )
    kucoin_funding_values = v1._btc_funding(kucoin_funding_path)
    binance_oracles = {
        name: v2.sparse_oracle(
            binance_dataset, v1.SPLITS[name]
        )
        for name in ("threshold_selection", "locked_test")
    }
    kucoin_oracle = v2.sparse_oracle(
        kucoin_dataset, v1.SPLITS["external_reused_kucoin"]
    )
    base_model, fit_report = fit_v6(
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
        base_model, time_normalized_threshold=threshold
    )
    output.mkdir(parents=True, exist_ok=True)
    model_artifacts = _save_model(model, output / "model")
    reloaded_model = V6Model.load(output / "model")

    selection_mask = v1._date_mask(
        binance_dataset.timestamps,
        *v1.SPLITS["threshold_selection"],
    )
    selection_features = binance_dataset.features[selection_mask]
    selection_predictions = model.predict(selection_features)
    replay_difference = _prediction_replay_max_difference(
        selection_predictions,
        reloaded_model.predict(selection_features),
    )
    if replay_difference != 0.0:
        raise RuntimeError(
            "reloaded V6 predictions do not reproduce exactly"
        )

    binance_audit, binance_trades, binance_predictions = evaluate_audit(
        name="binance_reused_2025_v6",
        model=reloaded_model,
        dataset=binance_dataset,
        outcomes=binance_outcomes,
        oracle=binance_oracles["locked_test"],
        date_range=v1.SPLITS["locked_test"],
        funding_series=binance_funding_values,
        exchange="binance_usdm",
    )
    kucoin_audit, kucoin_trades, kucoin_predictions = evaluate_audit(
        name="kucoin_reused_2026_v6",
        model=reloaded_model,
        dataset=kucoin_dataset,
        outcomes=kucoin_outcomes,
        oracle=kucoin_oracle,
        date_range=v1.SPLITS["external_reused_kucoin"],
        funding_series=kucoin_funding_values,
        exchange="kucoin_futures",
    )
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
        "protocol_sha256": protocol_sha256(frozen_protocol()),
        "implementation_sha256": protocol_sha256(
            frozen_implementation_manifest()
        ),
        "created_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "future_used_for_features": False,
        "future_used_for_labels_and_evaluation": True,
        "v5_forward_data_used": False,
        "fit": fit_report,
        "selected_time_normalized_threshold": threshold,
        "raw_expected_net_floor_pct": RAW_EXPECTED_NET_FLOOR_PCT,
        "threshold_selection": threshold_table,
        "selection_gate": selection_gate,
        "prediction_replay_max_abs_difference": replay_difference,
        "diagnostic_reuse_audits": {
            "binance": binance_audit,
            "kucoin": kucoin_audit,
        },
        "promotion_eligible": False,
        "promotion_blocker": (
            "V6 requires at least 90 new forward days and 30 closed "
            "forward trades after preregistration."
        ),
        "artifacts": {
            "protocol": v2._artifact(protocol_path),
            "implementation": v2._artifact(implementation_path),
            "model": model_artifacts,
            "predictions": v2._artifact(predictions_path),
            "inputs": {
                "binance_collector": v2._artifact(binance_path),
                "binance_funding": v2._artifact(
                    binance_funding_path
                ),
                "kucoin_collector": v2._artifact(kucoin_path),
                "kucoin_funding": v2._artifact(
                    kucoin_funding_path
                ),
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


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--binance-collector")
    parser.add_argument("--binance-funding")
    parser.add_argument("--kucoin-collector")
    parser.add_argument("--kucoin-funding")
    parser.add_argument("--write-preregistration-only", action="store_true")
    arguments = parser.parse_args(argv)
    output = pathlib.Path(arguments.output).resolve()
    protocol_path = output / "protocol.json"
    if not protocol_path.is_file():
        write_protocol(output)
    implementation_path = output / "implementation.json"
    if not implementation_path.is_file():
        write_implementation_manifest(output)
    _verify_preregistration(output)
    if arguments.write_preregistration_only:
        print(
            json.dumps(
                {
                    "protocol_path": str(protocol_path),
                    "implementation_path": str(implementation_path),
                },
                indent=2,
            )
        )
        return 0
    required = (
        arguments.binance_collector,
        arguments.binance_funding,
        arguments.kucoin_collector,
        arguments.kucoin_funding,
    )
    if any(value is None for value in required):
        parser.error("all collector and funding paths are required")
    result = run_study(
        binance_collector=arguments.binance_collector,
        binance_funding=arguments.binance_funding,
        kucoin_collector=arguments.kucoin_collector,
        kucoin_funding=arguments.kucoin_funding,
        output_directory=output,
    )
    print(
        json.dumps(
            {
                "report_path": result["report_path"],
                "selected_time_normalized_threshold": result[
                    "selected_time_normalized_threshold"
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
