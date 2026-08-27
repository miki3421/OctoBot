"""Two-stage BTC microstructure diagnostic research V2.

V1 showed that the price/volume baseline contained information while adding
all 92 Level-5 features directly made calibration worse.  V2 therefore keeps
the frozen four-hour barrier task but decomposes it causally:

* stage A estimates whether either +/-1% barrier will be touched;
* stage B estimates which barrier will be touched first, conditional on a
  non-ambiguous historical barrier event;
* price drives the directional estimate;
* a small, fixed book subset may only adjust activity/liquidity and, in a
  diagnostic challenger, add a shrunken directional residual.

The reused pre-20-August dataset is already diagnostic, not pristine.  This
module never reads the sealed 20--26 August block and can never authorize
paper or real orders.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import math
import os
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import microstructure_regime_v1 as v1
from octobot.ai_strategy_lab import model as model_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_microstructure_regime_two_stage_v2"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_V1_PROTOCOL_SHA256 = (
    "67b026c6ee12bf4a70a08ae585d4412fb0cffb29ddf437315090e7f790bc9f93"
)
PARENT_V1_DATASET_SHA256 = (
    "90046faf85978d88636130871d0a8cbb3b62e34af641ea6abe4c5ae9291162d9"
)
PARENT_V1_REPORT_SHA256 = (
    "542ab45c7cf4db923bba5871d140f2324fa5be698e687c441bd6ed92d291c78e"
)

PRIMARY_HORIZON_SECONDS = v1.PRIMARY_HORIZON_SECONDS
TARGET_BPS = v1.TARGET_BPS
STOP_BPS = v1.STOP_BPS
ROUND_TRIP_COST_BPS = v1.ROUND_TRIP_COST_BPS
STRESS_COST_MULTIPLIER = v1.STRESS_COST_MULTIPLIER
POSITION_FRACTION = v1.POSITION_FRACTION
WALK_FORWARD_FOLDS = v1.WALK_FORWARD_FOLDS
INITIAL_TRAIN_FRACTION = v1.INITIAL_TRAIN_FRACTION
EMBARGO_SECONDS = v1.EMBARGO_SECONDS

# A book model is allowed to change a price logit by only one quarter of its
# own centered logit.  This coefficient is frozen and never fitted or searched.
BOOK_RESIDUAL_WEIGHT = 0.25
MINIMUM_EXPECTED_NET_BPS = 0.0

MINIMUM_AUC = 0.55
MINIMUM_RELATIVE_ACTIVITY_BRIER_IMPROVEMENT = 0.02
MINIMUM_BOOK_IMPROVEMENT_FOLDS = 3
MINIMUM_TRADES = v1.MINIMUM_TRADES
MINIMUM_TRADES_PER_DIRECTION = v1.MINIMUM_TRADES_PER_DIRECTION
MINIMUM_POSITIVE_FOLDS = v1.MINIMUM_POSITIVE_FOLDS

LOGISTIC_CONFIG = v1.LOGISTIC_CONFIG

# Fast / medium / slow representatives are chosen a priori.  The redundant
# 30-second and 5-second queue variants are deliberately omitted.
ACTIVITY_BOOK_FEATURE_NAMES = tuple(
    [
        f"w{window}_{suffix}"
        for window in (5, 15, 60)
        for suffix in (
            "directional_level5_book_imbalance_slope",
            "directional_aggressor_size_imbalance",
            "spread_bps_mean",
            "trade_event_intensity",
        )
    ]
    + [
        f"q{window}_{suffix}"
        for window in (2, 15, 60)
        for suffix in (
            "normalized_ofi_abs_mean",
            "update_intensity",
            "depth5_mean",
            "directional_depletion_asymmetry_mean",
        )
    ]
)

DIRECTION_BOOK_FEATURE_NAMES = tuple(
    [
        f"w{window}_{suffix}"
        for window in (5, 15, 60)
        for suffix in (
            "directional_microprice_premium_bps_mean",
            "directional_level5_book_imbalance_mean",
            "directional_aggressor_size_imbalance",
        )
    ]
    + [
        f"q{window}_{suffix}"
        for window in (2, 15, 60)
        for suffix in (
            "directional_normalized_ofi_mean",
            "directional_depletion_asymmetry_mean",
            "directional_quote_move_imbalance",
        )
    ]
)


def _indices(names: tuple[str, ...]) -> numpy.ndarray:
    missing = sorted(set(names) - set(v1.BOOK_FEATURE_NAMES))
    if missing:
        raise RuntimeError(f"unknown frozen V2 book features: {missing}")
    return numpy.asarray(
        [v1.BOOK_FEATURE_NAMES.index(name) for name in names],
        dtype=numpy.int64,
    )


ACTIVITY_BOOK_INDICES = _indices(ACTIVITY_BOOK_FEATURE_NAMES)
DIRECTION_BOOK_INDICES = _indices(DIRECTION_BOOK_FEATURE_NAMES)
ACTIVITY_BOOK_DIRECTIONAL_MASK = v1.BOOK_DIRECTIONAL_MASK[
    ACTIVITY_BOOK_INDICES
]

ACTIVITY_PRICE_FEATURE_NAMES = v1.COMMON_FEATURE_NAMES + tuple(
    f"abs_{name}" if directional else name
    for name, directional in zip(
        v1.PRICE_FEATURE_NAMES, v1.PRICE_DIRECTIONAL_MASK
    )
)
ACTIVITY_BOOK_MODEL_FEATURE_NAMES = tuple(
    f"abs_{name}" if directional else name
    for name, directional in zip(
        ACTIVITY_BOOK_FEATURE_NAMES, ACTIVITY_BOOK_DIRECTIONAL_MASK
    )
)
DIRECTION_PRICE_FEATURE_NAMES = (
    v1.COMMON_FEATURE_NAMES + v1.PRICE_FEATURE_NAMES
)


def frozen_protocol() -> dict:
    """Return the result-free V2 protocol."""

    target_net_bps = TARGET_BPS - ROUND_TRIP_COST_BPS
    stop_net_bps = -STOP_BPS - ROUND_TRIP_COST_BPS
    stress_cost_bps = ROUND_TRIP_COST_BPS * STRESS_COST_MULTIPLIER
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_diagnostic_reuse_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_v1": {
            "protocol_version": v1.PROTOCOL_VERSION,
            "protocol_sha256": PARENT_V1_PROTOCOL_SHA256,
            "dataset_sha256": PARENT_V1_DATASET_SHA256,
            "report_sha256": PARENT_V1_REPORT_SHA256,
            "known_aggregate_lesson": (
                "price baseline informative; indiscriminate 92-feature book "
                "addition worsened calibration"
            ),
            "row_level_outcomes_reused": True,
            "reuse_status": "diagnostic_reuse_not_pristine_validation",
        },
        "hypothesis": {
            "name": "book_filters_activity_before_price_direction",
            "statement": (
                "a reduced Level-5 volatility/liquidity model improves the "
                "probability of a four-hour barrier event while price and "
                "volume retain responsibility for direction"
            ),
            "primary_candidate": "book_filter",
            "baseline": "price_two_stage",
            "diagnostic_challenger": "book_filter_residual",
            "direction_symmetric": True,
        },
        "architecture": {
            "stage_a": {
                "task": "either +/-1% barrier touched within four hours",
                "price_features": list(ACTIVITY_PRICE_FEATURE_NAMES),
                "book_features": list(ACTIVITY_BOOK_MODEL_FEATURE_NAMES),
                "book_role": "centered shrunken activity-logit correction",
            },
            "stage_b": {
                "task": (
                    "up-first versus down-first conditional on a historical "
                    "non-ambiguous barrier event"
                ),
                "price_features": list(DIRECTION_PRICE_FEATURE_NAMES),
                "book_residual_features": list(
                    DIRECTION_BOOK_FEATURE_NAMES
                ),
                "primary_direction_source": "price_only",
                "book_direction_role": "diagnostic_challenger_only",
            },
            "book_residual_weight": BOOK_RESIDUAL_WEIGHT,
            "book_residual_weight_search": False,
            "raw_book_feature_count": len(v1.BOOK_FEATURE_NAMES),
            "activity_book_feature_count": len(
                ACTIVITY_BOOK_FEATURE_NAMES
            ),
            "direction_book_feature_count": len(
                DIRECTION_BOOK_FEATURE_NAMES
            ),
        },
        "label": {
            "horizon_seconds": PRIMARY_HORIZON_SECONDS,
            "target_bps": TARGET_BPS,
            "stop_bps": STOP_BPS,
            "same_observation_tie": (
                "event=yes, direction=ambiguous and excluded from stage B"
            ),
            "eight_hour_horizon": (
                "descriptive parent result only; not promoted after V1"
            ),
        },
        "economic_selection": {
            "target_net_bps": target_net_bps,
            "stop_net_bps": stop_net_bps,
            "timeout_assumed_gross_bps": 0.0,
            "timeout_net_bps": -ROUND_TRIP_COST_BPS,
            "minimum_expected_net_bps": MINIMUM_EXPECTED_NET_BPS,
            "threshold_search": False,
            "direction": "larger expected net value; exact ties skipped",
            "one_trade_at_a_time": True,
            "position_fraction": POSITION_FRACTION,
            "stress": {
                "target_net_bps": TARGET_BPS - stress_cost_bps,
                "stop_net_bps": -STOP_BPS - stress_cost_bps,
                "timeout_net_bps": -stress_cost_bps,
                "selection_is_unchanged_from_primary": True,
            },
        },
        "model": {
            "type": "four independent numpy logistic regressions per fold",
            "configuration": dataclasses.asdict(LOGISTIC_CONFIG),
            "models": [
                "price_activity",
                "book_activity",
                "price_direction",
                "book_direction_residual",
            ],
            "model_search": False,
            "hyperparameter_search": False,
            "feature_search": False,
        },
        "validation": {
            "status": "diagnostic_reuse_not_pristine_validation",
            "walk_forward_folds": WALK_FORWARD_FOLDS,
            "initial_train_fraction": INITIAL_TRAIN_FRACTION,
            "purge_embargo_seconds": EMBARGO_SECONDS,
            "historical_end_exclusive": v1.PRETEST_END,
            "locked_historical_block": {
                "start_inclusive": v1.PRETEST_END,
                "end_exclusive": v1.LOCKED_BLOCK_END,
                "materialized": False,
                "authorized_to_open": False,
            },
        },
        "diagnostic_advancement_gate": {
            "all_walk_forward_folds_fitted": True,
            "minimum_filtered_activity_auc": MINIMUM_AUC,
            "filtered_activity_brier_better_than_constant": True,
            "minimum_relative_activity_brier_improvement_vs_price": (
                MINIMUM_RELATIVE_ACTIVITY_BRIER_IMPROVEMENT
            ),
            "minimum_book_improvement_folds": (
                MINIMUM_BOOK_IMPROVEMENT_FOLDS
            ),
            "minimum_price_direction_auc": MINIMUM_AUC,
            "price_direction_brier_better_than_constant": True,
            "target_brier_better_than_price_two_stage": True,
            "minimum_trades": MINIMUM_TRADES,
            "minimum_trades_per_direction": MINIMUM_TRADES_PER_DIRECTION,
            "minimum_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": MINIMUM_POSITIVE_FOLDS,
            "long_and_short_contribution_non_negative": True,
            "double_cost_total_return_non_negative": True,
        },
        "multiple_testing_disclosure": (
            "the four-hour horizon, barriers, costs, logistic configuration "
            "and walk-forward are inherited; one reduced feature list and "
            "one fixed residual weight are tested without search"
        ),
        "advancement_consequence": (
            "even a full pass permits only a newly preregistered orderless "
            "forward observer on dates not used here; no historical lock, "
            "paper trading, real orders or automatic promotion"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": v1._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted microstructure V2 protocol differs")
        return persisted
    v1._atomic_json(path, payload)
    return payload


def _activity_price_features(
    dataset: v1.RegimeDataset, indices: numpy.ndarray
) -> tuple[numpy.ndarray, tuple[str, ...]]:
    price = dataset.price_features[indices].copy()
    price[:, v1.PRICE_DIRECTIONAL_MASK] = numpy.abs(
        price[:, v1.PRICE_DIRECTIONAL_MASK]
    )
    return (
        numpy.column_stack((dataset.common_features[indices], price)).astype(
            numpy.float32
        ),
        ACTIVITY_PRICE_FEATURE_NAMES,
    )


def _activity_book_features(
    dataset: v1.RegimeDataset, indices: numpy.ndarray
) -> tuple[numpy.ndarray, tuple[str, ...]]:
    book = dataset.book_features[
        numpy.ix_(indices, ACTIVITY_BOOK_INDICES)
    ].copy()
    book[:, ACTIVITY_BOOK_DIRECTIONAL_MASK] = numpy.abs(
        book[:, ACTIVITY_BOOK_DIRECTIONAL_MASK]
    )
    return book.astype(numpy.float32), ACTIVITY_BOOK_MODEL_FEATURE_NAMES


def _direction_price_features(
    dataset: v1.RegimeDataset, indices: numpy.ndarray
) -> tuple[numpy.ndarray, tuple[str, ...]]:
    return (
        numpy.column_stack(
            (dataset.common_features[indices], dataset.price_features[indices])
        ).astype(numpy.float32),
        DIRECTION_PRICE_FEATURE_NAMES,
    )


def _direction_book_features(
    dataset: v1.RegimeDataset, indices: numpy.ndarray
) -> tuple[numpy.ndarray, tuple[str, ...]]:
    return (
        dataset.book_features[
            numpy.ix_(indices, DIRECTION_BOOK_INDICES)
        ].astype(numpy.float32),
        DIRECTION_BOOK_FEATURE_NAMES,
    )


def _event_direction_labels(
    dataset: v1.RegimeDataset,
) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    horizon = v1.HORIZONS_SECONDS.index(PRIMARY_HORIZON_SECONDS)
    long_target = dataset.long_label[:, horizon].astype(bool)
    short_target = dataset.short_label[:, horizon].astype(bool)
    target_net = (TARGET_BPS - ROUND_TRIP_COST_BPS) / 10_000.0
    stop_net = (-STOP_BPS - ROUND_TRIP_COST_BPS) / 10_000.0
    barrier = numpy.zeros(len(dataset.timestamps), dtype=bool)
    for side in ("long", "short"):
        returns = getattr(dataset, f"{side}_return")[:, horizon]
        barrier |= numpy.isclose(returns, target_net, atol=1e-7)
        barrier |= numpy.isclose(returns, stop_net, atol=1e-7)
    direction_known = numpy.logical_xor(long_target, short_target)
    if numpy.any(direction_known & ~barrier):
        raise ValueError("directional target exists without a barrier event")
    return (
        barrier.astype(numpy.uint8),
        direction_known,
        long_target.astype(numpy.uint8),
    )


def _logit(probability: typing.Union[float, numpy.ndarray]) -> numpy.ndarray:
    clipped = numpy.clip(
        numpy.asarray(probability, dtype=numpy.float64), 1e-6, 1.0 - 1e-6
    )
    return numpy.log(clipped / (1.0 - clipped))


def _sigmoid(values: numpy.ndarray) -> numpy.ndarray:
    values = numpy.asarray(values, dtype=numpy.float64)
    result = numpy.empty_like(values)
    positive = values >= 0
    result[positive] = 1.0 / (1.0 + numpy.exp(-values[positive]))
    exponential = numpy.exp(values[~positive])
    result[~positive] = exponential / (1.0 + exponential)
    return result


def _residual_probability(
    price_probability: numpy.ndarray,
    book_probability: numpy.ndarray,
    book_train_base_rate: float,
) -> numpy.ndarray:
    correction = _logit(book_probability) - _logit(book_train_base_rate)
    return _sigmoid(
        _logit(price_probability) + BOOK_RESIDUAL_WEIGHT * correction
    )


def _expected_values(
    event_probability: numpy.ndarray,
    up_probability: numpy.ndarray,
) -> dict[str, numpy.ndarray]:
    event_probability = numpy.clip(event_probability, 0.0, 1.0)
    up_probability = numpy.clip(up_probability, 0.0, 1.0)
    timeout_probability = 1.0 - event_probability
    long_target = event_probability * up_probability
    short_target = event_probability * (1.0 - up_probability)
    long_stop = short_target
    short_stop = long_target
    target_return = (TARGET_BPS - ROUND_TRIP_COST_BPS) / 10_000.0
    stop_return = (-STOP_BPS - ROUND_TRIP_COST_BPS) / 10_000.0
    timeout_return = -ROUND_TRIP_COST_BPS / 10_000.0
    return {
        "long_target_probability": long_target,
        "short_target_probability": short_target,
        "timeout_probability": timeout_probability,
        "long_expected_return": (
            long_target * target_return
            + long_stop * stop_return
            + timeout_probability * timeout_return
        ),
        "short_expected_return": (
            short_target * target_return
            + short_stop * stop_return
            + timeout_probability * timeout_return
        ),
    }


def _safe_probability_metrics(
    labels: numpy.ndarray,
    probabilities: numpy.ndarray,
    constant: typing.Union[float, numpy.ndarray],
) -> dict:
    if not len(labels):
        return {
            "rows": 0,
            "base_rate": None,
            "mean_probability": None,
            "brier": math.inf,
            "constant_brier": math.inf,
            "log_loss": math.inf,
            "constant_log_loss": math.inf,
            "auc": 0.5,
            "expected_calibration_error": None,
        }
    return v1._probability_metrics(labels, probabilities, constant)


def _simulate_trades(
    dataset: v1.RegimeDataset,
    indices: numpy.ndarray,
    long_expected_return: numpy.ndarray,
    short_expected_return: numpy.ndarray,
    *,
    stress: bool,
) -> dict[str, numpy.ndarray]:
    horizon = v1.HORIZONS_SECONDS.index(PRIMARY_HORIZON_SECONDS)
    selected_rows: list[int] = []
    directions: list[int] = []
    returns: list[float] = []
    exits: list[int] = []
    expected: list[float] = []
    free_after = -1
    minimum = MINIMUM_EXPECTED_NET_BPS / 10_000.0
    for position, row in enumerate(indices):
        timestamp = int(dataset.timestamps[row])
        if timestamp <= free_after:
            continue
        long_ev = float(long_expected_return[position])
        short_ev = float(short_expected_return[position])
        if max(long_ev, short_ev) <= minimum:
            continue
        if math.isclose(long_ev, short_ev, rel_tol=0.0, abs_tol=1e-12):
            continue
        direction = 1 if long_ev > short_ev else -1
        side = "long" if direction == 1 else "short"
        field = f"{side}_{'stress_' if stress else ''}return"
        exit_timestamp = int(getattr(dataset, f"{side}_exit")[row, horizon])
        if exit_timestamp <= timestamp:
            raise ValueError("V2 trade exit is not after decision")
        selected_rows.append(int(row))
        directions.append(direction)
        returns.append(float(getattr(dataset, field)[row, horizon]))
        exits.append(exit_timestamp)
        expected.append(long_ev if direction == 1 else short_ev)
        free_after = exit_timestamp
    return {
        "rows": numpy.asarray(selected_rows, dtype=numpy.int64),
        "directions": numpy.asarray(directions, dtype=numpy.int8),
        "instrument_returns": numpy.asarray(returns, dtype=numpy.float64),
        "exit_timestamps": numpy.asarray(exits, dtype=numpy.int64),
        "expected_returns": numpy.asarray(expected, dtype=numpy.float64),
    }


def _arm_metrics(
    dataset: v1.RegimeDataset,
    indices: numpy.ndarray,
    arm: dict[str, numpy.ndarray],
    constant_long: numpy.ndarray,
    constant_short: numpy.ndarray,
) -> dict:
    horizon = v1.HORIZONS_SECONDS.index(PRIMARY_HORIZON_SECONDS)
    labels = numpy.concatenate(
        (
            dataset.long_label[indices, horizon],
            dataset.short_label[indices, horizon],
        )
    )
    probabilities = numpy.concatenate(
        (
            arm["long_target_probability"][indices],
            arm["short_target_probability"][indices],
        )
    )
    primary = _simulate_trades(
        dataset,
        indices,
        arm["long_expected_return"][indices],
        arm["short_expected_return"][indices],
        stress=False,
    )
    stress = _simulate_trades(
        dataset,
        indices,
        arm["long_expected_return"][indices],
        arm["short_expected_return"][indices],
        stress=True,
    )
    return {
        "target_probability": _safe_probability_metrics(
            labels,
            probabilities,
            numpy.concatenate(
                (constant_long[indices], constant_short[indices])
            ),
        ),
        "target_probability_distribution": {
            "long": v1._probability_distribution(
                arm["long_target_probability"][indices]
            ),
            "short": v1._probability_distribution(
                arm["short_target_probability"][indices]
            ),
        },
        "expected_net_bps_distribution": {
            "long": v1._probability_distribution(
                arm["long_expected_return"][indices] * 10_000.0
            ),
            "short": v1._probability_distribution(
                arm["short_expected_return"][indices] * 10_000.0
            ),
        },
        "primary": v1._trade_metrics(dataset, primary),
        "stress": v1._trade_metrics(dataset, stress),
    }


def _save_predictions(
    path: pathlib.Path,
    dataset: v1.RegimeDataset,
    stages: dict[str, numpy.ndarray],
    arms: dict[str, dict[str, numpy.ndarray]],
    fold_number: numpy.ndarray,
    protocol_sha256: str,
) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload: dict[str, numpy.ndarray] = {
        "schema_version": numpy.asarray([SCHEMA_VERSION]),
        "protocol_sha256": numpy.asarray([protocol_sha256]),
        "parent_dataset_sha256": numpy.asarray(
            [PARENT_V1_DATASET_SHA256]
        ),
        "timestamps": dataset.timestamps,
        "fold_number": fold_number,
    }
    payload.update(stages)
    for arm_name, values in arms.items():
        for key, value in values.items():
            payload[f"{arm_name}_{key}"] = value
    with temporary.open("wb") as stream:
        numpy.savez_compressed(stream, **payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return {
        "path": str(path),
        "sha256": v1._sha256(path),
        "bytes": path.stat().st_size,
    }


def _gate(
    *,
    stages: dict,
    arms: dict,
    fitted_folds: int,
    activity_improvement_folds: int,
    positive_folds: int,
) -> dict:
    price_activity = stages["price_activity"]
    filtered_activity = stages["filtered_activity"]
    price_direction = stages["price_direction"]
    primary = arms["book_filter"]
    baseline = arms["price_two_stage"]
    relative_activity_brier = 1.0 - filtered_activity["brier"] / max(
        price_activity["brier"], 1e-12
    )
    checks = {
        "all_walk_forward_folds_fitted": (
            fitted_folds == WALK_FORWARD_FOLDS
        ),
        "filtered_activity_auc": filtered_activity["auc"] >= MINIMUM_AUC,
        "filtered_activity_brier_better_than_constant": (
            filtered_activity["brier"] < filtered_activity["constant_brier"]
        ),
        "relative_activity_brier_improvement_vs_price": (
            relative_activity_brier
            >= MINIMUM_RELATIVE_ACTIVITY_BRIER_IMPROVEMENT
        ),
        "book_improvement_folds": (
            activity_improvement_folds >= MINIMUM_BOOK_IMPROVEMENT_FOLDS
        ),
        "price_direction_auc": price_direction["auc"] >= MINIMUM_AUC,
        "price_direction_brier_better_than_constant": (
            price_direction["brier"] < price_direction["constant_brier"]
        ),
        "target_brier_better_than_price_two_stage": (
            primary["target_probability"]["brier"]
            < baseline["target_probability"]["brier"]
        ),
        "minimum_trades": primary["primary"]["trades"] >= MINIMUM_TRADES,
        "minimum_long_trades": (
            primary["primary"]["by_direction"]["long"]["trades"]
            >= MINIMUM_TRADES_PER_DIRECTION
        ),
        "minimum_short_trades": (
            primary["primary"]["by_direction"]["short"]["trades"]
            >= MINIMUM_TRADES_PER_DIRECTION
        ),
        "profit_factor": primary["primary"]["profit_factor"] >= 1.20,
        "maximum_drawdown": primary["primary"]["max_drawdown"] <= 0.05,
        "positive_operating_days": (
            primary["primary"]["positive_operating_days_pct"] >= 55.0
        ),
        "positive_folds": positive_folds >= MINIMUM_POSITIVE_FOLDS,
        "long_non_negative": (
            primary["primary"]["by_direction"]["long"]["total_return"]
            >= 0.0
        ),
        "short_non_negative": (
            primary["primary"]["by_direction"]["short"]["total_return"]
            >= 0.0
        ),
        "double_cost_non_negative": (
            primary["stress"]["total_return"] >= 0.0
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "relative_activity_brier_improvement_vs_price": (
            relative_activity_brier
        ),
        "activity_improvement_folds": activity_improvement_folds,
        "positive_folds": positive_folds,
    }


def evaluate_discovery(
    *,
    protocol_value: typing.Union[str, pathlib.Path],
    parent_protocol_value: typing.Union[str, pathlib.Path],
    dataset_value: typing.Union[str, pathlib.Path],
    dataset_manifest_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    """Evaluate the frozen V2 without reading the historical lock."""

    progress = progress or (lambda _message: None)
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    parent_protocol_path = pathlib.Path(parent_protocol_value).resolve()
    if not parent_protocol_path.is_file():
        raise ValueError("parent V1 protocol is missing")
    parent_protocol = json.loads(parent_protocol_path.read_text(encoding="utf-8"))
    if parent_protocol.get("protocol_sha256") != PARENT_V1_PROTOCOL_SHA256:
        raise ValueError("parent V1 protocol hash differs")
    if parent_protocol.get("results") is not None:
        raise ValueError("parent V1 protocol is not result-free")
    for value in (protocol, parent_protocol):
        if value.get("orders_authorized") is not False:
            raise ValueError("microstructure protocol authorizes orders")
        if value.get("paper_orders_authorized") is not False:
            raise ValueError("microstructure protocol authorizes paper orders")

    manifest_path = pathlib.Path(dataset_manifest_value).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("locked_test_materialized") is not False:
        raise ValueError("V2 parent manifest opened locked data")
    artifact = manifest.get("artifact", {})
    if artifact.get("sha256") != PARENT_V1_DATASET_SHA256:
        raise ValueError("V2 parent dataset hash differs")
    if manifest.get("protocol_sha256") != PARENT_V1_PROTOCOL_SHA256:
        raise ValueError("V2 dataset parent protocol differs")
    dataset = v1.RegimeDataset.load(
        dataset_value,
        expected_sha256=PARENT_V1_DATASET_SHA256,
        expected_protocol_sha256=PARENT_V1_PROTOCOL_SHA256,
    )
    event_label, direction_known, up_label = _event_direction_labels(dataset)
    folds = v1._walk_forward_folds(dataset)
    rows = len(dataset.timestamps)
    stage_names = (
        "price_activity",
        "book_activity",
        "filtered_activity",
        "price_direction",
        "book_direction",
        "residual_direction",
        "constant_event",
        "constant_direction",
        "constant_long_target",
        "constant_short_target",
    )
    stage_predictions = {
        name: numpy.full(rows, numpy.nan, dtype=numpy.float64)
        for name in stage_names
    }
    arm_names = (
        "price_two_stage",
        "book_filter",
        "book_filter_residual",
    )
    arm_predictions = {
        name: {
            key: numpy.full(rows, numpy.nan, dtype=numpy.float64)
            for key in (
                "long_target_probability",
                "short_target_probability",
                "timeout_probability",
                "long_expected_return",
                "short_expected_return",
            )
        }
        for name in arm_names
    }
    fold_number_values = numpy.full(rows, -1, dtype=numpy.int8)
    fold_reports = []
    fitted_models: list[dict] = []
    fitted_folds = 0

    feature_builders = {
        "price_activity": _activity_price_features,
        "book_activity": _activity_book_features,
        "price_direction": _direction_price_features,
        "book_direction": _direction_book_features,
    }
    for fold_number, fold in enumerate(folds, start=1):
        progress(f"V2 walk-forward fold {fold_number}/{WALK_FORWARD_FOLDS}")
        train_direction = fold.train[direction_known[fold.train]]
        if len(train_direction) < 10:
            raise ValueError("insufficient conditional direction rows")
        train_event_base = float(numpy.mean(event_label[fold.train]))
        train_direction_base = float(numpy.mean(up_label[train_direction]))
        models = {}
        for stage_name in feature_builders:
            train_indices = (
                train_direction
                if stage_name.endswith("direction")
                else fold.train
            )
            labels = (
                up_label[train_indices]
                if stage_name.endswith("direction")
                else event_label[train_indices]
            )
            features, names = feature_builders[stage_name](
                dataset, train_indices
            )
            model = model_module.NumpyLogisticModel.fit(
                features, labels, names, LOGISTIC_CONFIG
            )
            test_features, test_names = feature_builders[stage_name](
                dataset, fold.test
            )
            if test_names != names:
                raise RuntimeError("V2 train/test feature schema differs")
            stage_predictions[stage_name][fold.test] = model.predict_proba(
                test_features
            )
            models[stage_name] = model
            fitted_models.append(
                {
                    "stage": stage_name,
                    "fold": fold_number,
                    "test": fold.test.copy(),
                    "model": model,
                }
            )

        stage_predictions["filtered_activity"][fold.test] = (
            _residual_probability(
                stage_predictions["price_activity"][fold.test],
                stage_predictions["book_activity"][fold.test],
                train_event_base,
            )
        )
        stage_predictions["residual_direction"][fold.test] = (
            _residual_probability(
                stage_predictions["price_direction"][fold.test],
                stage_predictions["book_direction"][fold.test],
                train_direction_base,
            )
        )
        stage_predictions["constant_event"][fold.test] = train_event_base
        stage_predictions["constant_direction"][fold.test] = (
            train_direction_base
        )
        stage_predictions["constant_long_target"][fold.test] = (
            train_event_base * train_direction_base
        )
        stage_predictions["constant_short_target"][fold.test] = (
            train_event_base * (1.0 - train_direction_base)
        )
        combinations = {
            "price_two_stage": (
                stage_predictions["price_activity"][fold.test],
                stage_predictions["price_direction"][fold.test],
            ),
            "book_filter": (
                stage_predictions["filtered_activity"][fold.test],
                stage_predictions["price_direction"][fold.test],
            ),
            "book_filter_residual": (
                stage_predictions["filtered_activity"][fold.test],
                stage_predictions["residual_direction"][fold.test],
            ),
        }
        for arm_name, (event_probability, direction_probability) in (
            combinations.items()
        ):
            values = _expected_values(
                event_probability, direction_probability
            )
            for key, value in values.items():
                arm_predictions[arm_name][key][fold.test] = value
        fold_number_values[fold.test] = fold_number
        fitted_folds += 1

        known_test = fold.test[direction_known[fold.test]]
        stage_fold = {
            "price_activity": _safe_probability_metrics(
                event_label[fold.test],
                stage_predictions["price_activity"][fold.test],
                train_event_base,
            ),
            "filtered_activity": _safe_probability_metrics(
                event_label[fold.test],
                stage_predictions["filtered_activity"][fold.test],
                train_event_base,
            ),
            "price_direction": _safe_probability_metrics(
                up_label[known_test],
                stage_predictions["price_direction"][known_test],
                train_direction_base,
            ),
        }
        arm_fold = {
            arm_name: _arm_metrics(
                dataset,
                fold.test,
                values,
                stage_predictions["constant_long_target"],
                stage_predictions["constant_short_target"],
            )
            for arm_name, values in arm_predictions.items()
        }
        fold_reports.append(
            {
                "fold": fold_number,
                "fitted": True,
                "train_decisions": int(len(fold.train)),
                "train_direction_events": int(len(train_direction)),
                "test_decisions": int(len(fold.test)),
                "test_direction_events": int(len(known_test)),
                "test_start": datetime.datetime.fromtimestamp(
                    fold.test_start, datetime.timezone.utc
                ).isoformat(),
                "test_end": datetime.datetime.fromtimestamp(
                    fold.test_end, datetime.timezone.utc
                ).isoformat(),
                "stages": stage_fold,
                "arms": arm_fold,
            }
        )

    valid = numpy.flatnonzero(fold_number_values > 0)
    known_valid = valid[direction_known[valid]]
    stage_results = {
        "price_activity": _safe_probability_metrics(
            event_label[valid],
            stage_predictions["price_activity"][valid],
            stage_predictions["constant_event"][valid],
        ),
        "book_activity": _safe_probability_metrics(
            event_label[valid],
            stage_predictions["book_activity"][valid],
            stage_predictions["constant_event"][valid],
        ),
        "filtered_activity": _safe_probability_metrics(
            event_label[valid],
            stage_predictions["filtered_activity"][valid],
            stage_predictions["constant_event"][valid],
        ),
        "price_direction": _safe_probability_metrics(
            up_label[known_valid],
            stage_predictions["price_direction"][known_valid],
            stage_predictions["constant_direction"][known_valid],
        ),
        "book_direction": _safe_probability_metrics(
            up_label[known_valid],
            stage_predictions["book_direction"][known_valid],
            stage_predictions["constant_direction"][known_valid],
        ),
        "residual_direction": _safe_probability_metrics(
            up_label[known_valid],
            stage_predictions["residual_direction"][known_valid],
            stage_predictions["constant_direction"][known_valid],
        ),
    }
    arm_results = {
        name: _arm_metrics(
            dataset,
            valid,
            values,
            stage_predictions["constant_long_target"],
            stage_predictions["constant_short_target"],
        )
        for name, values in arm_predictions.items()
    }
    activity_improvement_folds = sum(
        fold["stages"]["filtered_activity"]["brier"]
        < fold["stages"]["price_activity"]["brier"]
        for fold in fold_reports
    )
    positive_folds = sum(
        fold["arms"]["book_filter"]["primary"]["total_return"] > 0.0
        for fold in fold_reports
    )
    gate = _gate(
        stages=stage_results,
        arms=arm_results,
        fitted_folds=fitted_folds,
        activity_improvement_folds=activity_improvement_folds,
        positive_folds=positive_folds,
    )

    created_at = datetime.datetime.now(datetime.timezone.utc)
    experiment_id = (
        f"{PROTOCOL_VERSION}-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    )
    output = pathlib.Path(output_root_value).resolve() / experiment_id
    if output.exists():
        raise ValueError("microstructure V2 experiment directory exists")
    output.mkdir(parents=True)
    prediction_artifact = _save_predictions(
        output / "predictions.npz",
        dataset,
        stage_predictions,
        arm_predictions,
        fold_number_values,
        protocol["protocol_sha256"],
    )
    model_artifacts = []
    for record in fitted_models:
        stage_name = record["stage"]
        fold_number = record["fold"]
        test_indices = record["test"]
        model = record["model"]
        model_path = output / "models" / f"{stage_name}-fold-{fold_number}.npz"
        artifact_value = model.save(model_path)
        reloaded = model_module.NumpyLogisticModel.load(model_path)
        features, _ = feature_builders[stage_name](dataset, test_indices)
        expected = stage_predictions[stage_name][test_indices]
        actual = reloaded.predict_proba(features)
        if not numpy.allclose(actual, expected, rtol=0.0, atol=1e-12):
            raise ValueError("reloaded V2 model differs")
        model_artifacts.append(
            {
                "stage": stage_name,
                "fold": fold_number,
                **artifact_value,
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "created_at": created_at.isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol": {
            "version": PROTOCOL_VERSION,
            "sha256": protocol["protocol_sha256"],
            "path": str(protocol_path),
        },
        "parent_v1": {
            "protocol_sha256": PARENT_V1_PROTOCOL_SHA256,
            "dataset_sha256": PARENT_V1_DATASET_SHA256,
            "report_sha256": PARENT_V1_REPORT_SHA256,
        },
        "dataset": {
            "sha256": PARENT_V1_DATASET_SHA256,
            "manifest_sha256": v1._sha256(manifest_path),
            "rows": rows,
            "oos_rows": int(len(valid)),
            "status": "diagnostic_reuse_not_pristine_validation",
            "locked_test_materialized": False,
            "barrier_events": int(numpy.sum(event_label)),
            "known_direction_events": int(numpy.sum(direction_known)),
            "ambiguous_barrier_events": int(
                numpy.sum((event_label == 1) & ~direction_known)
            ),
        },
        "primary_task": {
            "horizon_seconds": PRIMARY_HORIZON_SECONDS,
            "target_bps": TARGET_BPS,
            "stop_bps": STOP_BPS,
            "minimum_expected_net_bps": MINIMUM_EXPECTED_NET_BPS,
            "book_residual_weight": BOOK_RESIDUAL_WEIGHT,
        },
        "stages": stage_results,
        "arms": arm_results,
        "folds": fold_reports,
        "diagnostic_advancement_gate": gate,
        "conclusion": (
            "two_stage_book_filter_detected_diagnostic_only"
            if gate["passed"]
            else "two_stage_book_filter_not_demonstrated"
        ),
        "locked_historical_block": {
            "start": v1.PRETEST_END,
            "end": v1.LOCKED_BLOCK_END,
            "materialized": False,
            "authorized_to_open": False,
        },
        "consequence": (
            "no signal or order change; a pass permits only a fresh "
            "result-free forward observer protocol"
        ),
        "artifacts": {
            "predictions": prediction_artifact,
            "fold_models": model_artifacts,
        },
        "implementation": {
            "source": str(pathlib.Path(__file__).resolve()),
            "source_sha256": v1._sha256(pathlib.Path(__file__).resolve()),
        },
    }
    report_path = output / "report.json"
    v1._atomic_json(report_path, report)
    experiment_manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "protocol_sha256": protocol["protocol_sha256"],
        "parent_dataset_sha256": PARENT_V1_DATASET_SHA256,
        "report": {
            "path": str(report_path),
            "sha256": v1._sha256(report_path),
            "bytes": report_path.stat().st_size,
        },
        "predictions": prediction_artifact,
        "fold_models": model_artifacts,
        "implementation_sha256": report["implementation"]["source_sha256"],
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    v1._atomic_json(output / "manifest.json", experiment_manifest)
    v1._append_experiment_index(
        pathlib.Path(output_root_value).resolve() / "experiments.jsonl",
        {
            "experiment_id": experiment_id,
            "created_at": created_at.isoformat(),
            "protocol_sha256": protocol["protocol_sha256"],
            "parent_dataset_sha256": PARENT_V1_DATASET_SHA256,
            "report_sha256": experiment_manifest["report"]["sha256"],
            "conclusion": report["conclusion"],
            "orders_authorized": False,
        },
    )
    return {**report, "report_path": str(report_path)}


def main(arguments: typing.Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BTC microstructure two-stage diagnostic research V2"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    protocol_parser = subparsers.add_parser("write-protocol")
    protocol_parser.add_argument("--output", required=True)
    evaluator = subparsers.add_parser("evaluate-discovery")
    evaluator.add_argument("--protocol", required=True)
    evaluator.add_argument("--parent-protocol", required=True)
    evaluator.add_argument("--dataset", required=True)
    evaluator.add_argument("--dataset-manifest", required=True)
    evaluator.add_argument("--output-root", required=True)
    args = parser.parse_args(arguments)
    if args.command == "write-protocol":
        result: typing.Any = write_or_verify_protocol(args.output)
    else:
        result = evaluate_discovery(
            protocol_value=args.protocol,
            parent_protocol_value=args.parent_protocol,
            dataset_value=args.dataset,
            dataset_manifest_value=args.dataset_manifest,
            output_root_value=args.output_root,
            progress=print,
        )
    print(json.dumps(v1._json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
