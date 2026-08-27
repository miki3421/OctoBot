"""Result-free protocol for cost-aware BTC microstructure search V2."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import percentage_probability_engine
from octobot.ai_strategy_lab import scalping_strategy_search as v1


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_scalping_cost_aware_v2"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_PROTOCOL_VERSION = v1.PROTOCOL_VERSION
PARENT_PROTOCOL_SHA256 = (
    "4f97d7acf72482b31d9aae9ddc0b9a01c2a488394ff5b9546e5423fe380d0db7"
)
SNAPSHOT_SHA256 = v1.SNAPSHOT_SHA256
SOURCE_START = v1.SOURCE_START
DEVELOPMENT_END = v1.TRAIN_END
DIAGNOSTIC_CONFIRMATION_END = v1.SELECTION_END
LOCKED_TEST_END = v1.LOCKED_TEST_END
DECISION_STRIDE_SECONDS = 15
TRAINING_STRIDE_SECONDS = 60
FEATURE_LOOKBACK_SECONDS = 300
PRIMARY_LATENCY_MS = 500
STRESS_LATENCY_MS = 1_000
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0
COST_STRESS_MULTIPLIER = 2.0
POSITION_FRACTION = 0.10
WALK_FORWARD_FOLDS = 5
CALIBRATION_FRACTION = 0.20
PROBABILITY_QUANTILES = (0.90, 0.95, 0.975, 0.99)
DIRECTION_MARGIN = 0.02
CONFIGURATIONS = (
    {
        "name": "balanced_5m",
        "target_bps": 40,
        "stop_bps": 20,
        "horizon_seconds": 300,
    },
    {
        "name": "wide_15m",
        "target_bps": 60,
        "stop_bps": 30,
        "horizon_seconds": 900,
    },
)
LOGISTIC_CONFIG = model_module.LogisticConfig(
    epochs=12,
    batch_size=8192,
    learning_rate=0.01,
    l2=0.003,
    seed=20260827,
)
BOOSTING_CONFIG = model_module.BoostingConfig(
    trees=32,
    max_depth=2,
    bins=24,
    learning_rate=0.05,
    l2=3.0,
    minimum_leaf_rows=500,
    minimum_gain=0.001,
    feature_fraction=0.75,
    seed=20260827,
)


def _json_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def frozen_protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_evaluation_protocol",
        "research_only": True,
        "public_data_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_failure": {
            "version": PARENT_PROTOCOL_VERSION,
            "sha256": PARENT_PROTOCOL_SHA256,
            "lesson_used": (
                "40 bps in 120 seconds had no positive fit labels in fold 1"
            ),
            "no_parent_threshold_retuning": True,
        },
        "frozen_source": {
            "snapshot_sha256": SNAPSHOT_SHA256,
            "start_inclusive": SOURCE_START,
            "diagnostic_reuse_end_exclusive": (
                DIAGNOSTIC_CONFIRMATION_END
            ),
            "locked_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_not_materialized_at_preregistration": True,
        },
        "candidate_family": {
            "name": "cost_aware_microstructure_timing",
            "decision_stride_seconds": DECISION_STRIDE_SECONDS,
            "training_stride_seconds": TRAINING_STRIDE_SECONDS,
            "one_trade_at_a_time": True,
            "directions": ["LONG", "SHORT"],
            "entry": "first executable top-of-book after 500ms",
            "primary_latency_ms": PRIMARY_LATENCY_MS,
            "stress_latency_ms": STRESS_LATENCY_MS,
            "configurations": list(CONFIGURATIONS),
            "configuration_reason": (
                "predeclared gross reward/risk of 2:1 with longer horizons "
                "that can amortize a 14 bps primary round trip"
            ),
            "outcome_label": "net instrument return strictly above zero",
            "stop_wins_same_one_second_bucket": True,
            "timeouts_exit_at_executable_quote": True,
        },
        "features": {
            "schema": list(v1.FEATURE_NAMES),
            "lookback_seconds": FEATURE_LOOKBACK_SECONDS,
            "directional_symmetry": True,
            "causal_at_decision_close": True,
            "continuous_lookback_and_future_required": True,
        },
        "costs": {
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "fills": 2,
            "position_fraction": POSITION_FRACTION,
            "stress_multiplier": COST_STRESS_MULTIPLIER,
            "funding_excluded": (
                "the maximum 15-minute hold cannot cross an eight-hour "
                "funding settlement"
            ),
        },
        "models": {
            "candidates": [
                {
                    "name": "numpy_logistic",
                    "config": dataclasses.asdict(LOGISTIC_CONFIG),
                },
                {
                    "name": "numpy_gradient_boosting",
                    "config": dataclasses.asdict(BOOSTING_CONFIG),
                },
            ],
            "calibration": "quantile_isotonic_latest_training_20pct",
            "calibration_fraction": CALIBRATION_FRACTION,
            "probability_quantiles": list(PROBABILITY_QUANTILES),
            "minimum_direction_margin": DIRECTION_MARGIN,
            "selection_candidates": 16,
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "development_walk_forward_folds": WALK_FORWARD_FOLDS,
            "purge_embargo_seconds": 900,
            "diagnostic_confirmation": [
                DEVELOPMENT_END,
                DIAGNOSTIC_CONFIRMATION_END,
            ],
            "diagnostic_confirmation_is_not_pristine": True,
            "locked_final_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_policy": (
                "materialize once only if development and diagnostic "
                "confirmation both pass every gate"
            ),
            "no_mid_test_retuning": True,
        },
        "development_gate": {
            "minimum_oos_trades": 500,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": 4,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "brier_better_than_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "confirmation_and_locked_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "brier_better_than_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "multiple_testing_disclosure": (
            "two economic configurations, two model families and four "
            "probability quantiles are selected only in development; the "
            "20-26 August block is the sole untouched test"
        ),
        "promotion_consequence": (
            "even a full pass permits only a manually approved, orderless "
            "shadow; it never authorizes paper or real orders"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted scalping V2 protocol differs")
        return persisted
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


@dataclasses.dataclass
class ScalpingV2Dataset:
    timestamps: numpy.ndarray
    features: numpy.ndarray
    primary_long_label: numpy.ndarray
    primary_short_label: numpy.ndarray
    primary_long_return: numpy.ndarray
    primary_short_return: numpy.ndarray
    primary_long_exit: numpy.ndarray
    primary_short_exit: numpy.ndarray
    stress_long_return: numpy.ndarray
    stress_short_return: numpy.ndarray
    stress_long_exit: numpy.ndarray
    stress_short_exit: numpy.ndarray

    def validate(self) -> None:
        rows = len(self.timestamps)
        configurations = len(CONFIGURATIONS)
        if not rows or numpy.any(numpy.diff(self.timestamps) <= 0):
            raise ValueError("V2 timestamps are empty or unordered")
        if self.features.shape != (rows, len(v1.FEATURE_NAMES)):
            raise ValueError("V2 feature shape differs")
        if int(self.timestamps[-1]) >= v1._iso_timestamp(
            DIAGNOSTIC_CONFIRMATION_END
        ):
            raise ValueError("V2 pre-test dataset enters the locked block")
        for field in dataclasses.fields(self):
            values = getattr(self, field.name)
            if field.name == "timestamps":
                continue
            if field.name == "features":
                if not numpy.all(numpy.isfinite(values)):
                    raise ValueError("V2 features contain non-finite values")
                continue
            if values.shape != (rows, configurations):
                raise ValueError(f"V2 field {field.name} is misaligned")
            if "return" in field.name and not numpy.all(numpy.isfinite(values)):
                raise ValueError("V2 returns contain non-finite values")
        for values in (self.primary_long_label, self.primary_short_label):
            if not set(numpy.unique(values)).issubset({0, 1}):
                raise ValueError("V2 labels are not binary")

    def view(self, configuration_index: int) -> v1.ScalpingResearchDataset:
        if not 0 <= configuration_index < len(CONFIGURATIONS):
            raise IndexError("V2 configuration index is invalid")
        return v1.ScalpingResearchDataset(
            timestamps=self.timestamps,
            features=self.features,
            primary_long_label=self.primary_long_label[:, configuration_index],
            primary_short_label=self.primary_short_label[:, configuration_index],
            primary_long_return=self.primary_long_return[:, configuration_index],
            primary_short_return=self.primary_short_return[:, configuration_index],
            primary_long_exit=self.primary_long_exit[:, configuration_index],
            primary_short_exit=self.primary_short_exit[:, configuration_index],
            stress_long_return=self.stress_long_return[:, configuration_index],
            stress_short_return=self.stress_short_return[:, configuration_index],
            stress_long_exit=self.stress_long_exit[:, configuration_index],
            stress_short_exit=self.stress_short_exit[:, configuration_index],
        )

    def save(self, path_value: typing.Union[str, pathlib.Path]) -> dict:
        self.validate()
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            numpy.savez_compressed(
                stream,
                schema_version=numpy.asarray([SCHEMA_VERSION]),
                protocol_version=numpy.asarray([PROTOCOL_VERSION]),
                protocol_sha256=numpy.asarray([_json_hash(frozen_protocol())]),
                source_snapshot_sha256=numpy.asarray([SNAPSHOT_SHA256]),
                feature_names=numpy.asarray(v1.FEATURE_NAMES),
                configurations=numpy.asarray(
                    [json.dumps(value, sort_keys=True) for value in CONFIGURATIONS]
                ),
                **{
                    field.name: getattr(self, field.name)
                    for field in dataclasses.fields(self)
                },
            )
            stream.flush()
        temporary.replace(path)
        return {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": v1._sha256(path),
        }

    @classmethod
    def load(
        cls,
        path_value: typing.Union[str, pathlib.Path],
        *,
        expected_sha256: str | None = None,
    ) -> "ScalpingV2Dataset":
        path = pathlib.Path(path_value).resolve()
        if expected_sha256 is not None and v1._sha256(path) != expected_sha256:
            raise ValueError("V2 dataset hash differs")
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported V2 dataset schema")
            if str(values["protocol_version"][0]) != PROTOCOL_VERSION:
                raise ValueError("V2 dataset protocol differs")
            if str(values["protocol_sha256"][0]) != _json_hash(
                frozen_protocol()
            ):
                raise ValueError("V2 dataset protocol hash differs")
            if str(values["source_snapshot_sha256"][0]) != SNAPSHOT_SHA256:
                raise ValueError("V2 source snapshot differs")
            if tuple(str(value) for value in values["feature_names"]) != (
                v1.FEATURE_NAMES
            ):
                raise ValueError("V2 feature schema differs")
            configurations = tuple(
                json.loads(str(value)) for value in values["configurations"]
            )
            if configurations != CONFIGURATIONS:
                raise ValueError("V2 economic configurations differ")
            dataset = cls(
                **{
                    field.name: values[field.name].copy()
                    for field in dataclasses.fields(cls)
                }
            )
        dataset.validate()
        return dataset


def _candidate_indices(source: v1.DenseSource) -> numpy.ndarray:
    maximum_horizon = max(
        int(value["horizon_seconds"]) for value in CONFIGURATIONS
    )
    values = source.values
    present = values["book_event_count"] > 0
    indices = numpy.arange(len(source), dtype=numpy.int64)
    decision_seconds = source.start_second + indices + 1
    eligible = (
        (indices >= FEATURE_LOOKBACK_SECONDS - 1)
        & (decision_seconds % DECISION_STRIDE_SECONDS == 0)
        & (
            decision_seconds + maximum_horizon + 2
            < v1._iso_timestamp(DIAGNOSTIC_CONFIRMATION_END)
        )
    )
    candidates = indices[eligible]
    candidates = candidates[
        v1._complete_intervals(
            present,
            candidates - FEATURE_LOOKBACK_SECONDS + 1,
            FEATURE_LOOKBACK_SECONDS,
        )
    ]
    primary_starts = candidates + 1
    in_bounds = primary_starts + maximum_horizon < len(source)
    candidates = candidates[in_bounds]
    primary_starts = candidates + 1
    stress_starts = candidates + 2
    valid = (
        v1._complete_intervals(
            present, primary_starts, maximum_horizon + 1
        )
        & v1._complete_intervals(
            present, stress_starts, maximum_horizon
        )
        & numpy.isfinite(values["entry_bid_500"][primary_starts])
        & numpy.isfinite(values["entry_ask_500"][primary_starts])
        & numpy.isfinite(
            values["prefix_last_bid_500"][
                primary_starts + maximum_horizon
            ]
        )
        & numpy.isfinite(
            values["prefix_last_ask_500"][
                primary_starts + maximum_horizon
            ]
        )
        & numpy.isfinite(values["entry_bid_0"][stress_starts])
        & numpy.isfinite(values["entry_ask_0"][stress_starts])
    )
    return candidates[valid]


def _direction_outcome(
    source: v1.DenseSource,
    candidate_indices: numpy.ndarray,
    *,
    direction: int,
    latency_ms: int,
    cost_multiplier: float,
    configuration: dict,
) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    values = source.values
    horizon = int(configuration["horizon_seconds"])
    target_bps = float(configuration["target_bps"])
    stop_bps = float(configuration["stop_bps"])
    count = len(candidate_indices)
    sentinel = numpy.int16(32_767)
    target_time = numpy.full(count, sentinel, dtype=numpy.int16)
    stop_time = numpy.full(count, sentinel, dtype=numpy.int16)
    if latency_ms == 500:
        starts = candidate_indices + 1
        entry_bid = values["entry_bid_500"][starts]
        entry_ask = values["entry_ask_500"][starts]
        entry_ns = values["entry_ns_500"][starts]
        initial = tuple(
            values[f"suffix_{extreme}_{side}_500"][starts]
            for extreme, side in (
                ("high", "bid"),
                ("low", "bid"),
                ("high", "ask"),
                ("low", "ask"),
            )
        )
        deadline = starts + horizon
        timeout_bid = values["prefix_last_bid_500"][deadline]
        timeout_ask = values["prefix_last_ask_500"][deadline]
        final_extremes = tuple(
            values[f"prefix_{extreme}_{side}_500"][deadline]
            for extreme, side in (
                ("high", "bid"),
                ("low", "bid"),
                ("high", "ask"),
                ("low", "ask"),
            )
        )
    elif latency_ms == 1_000:
        starts = candidate_indices + 2
        entry_bid = values["entry_bid_0"][starts]
        entry_ask = values["entry_ask_0"][starts]
        entry_ns = values["entry_ns_0"][starts]
        initial = tuple(
            values[f"suffix_{extreme}_{side}_0"][starts]
            for extreme, side in (
                ("high", "bid"),
                ("low", "bid"),
                ("high", "ask"),
                ("low", "ask"),
            )
        )
        deadline = starts + horizon - 1
        timeout_bid = values["last_bid"][deadline]
        timeout_ask = values["last_ask"][deadline]
        final_extremes = None
    else:
        raise ValueError("unsupported V2 latency")

    entry = entry_ask if direction == 1 else entry_bid
    target_price = entry * (1.0 + direction * target_bps / 10_000.0)
    stop_price = entry * (1.0 - direction * stop_bps / 10_000.0)

    def update(extremes: tuple[numpy.ndarray, ...], step: int) -> None:
        high_bid, low_bid, high_ask, low_ask = extremes
        if direction == 1:
            target_hit = high_bid >= target_price
            stop_hit = low_bid <= stop_price
        else:
            target_hit = low_ask <= target_price
            stop_hit = high_ask >= stop_price
        target_time[(target_time == sentinel) & target_hit] = step
        stop_time[(stop_time == sentinel) & stop_hit] = step

    update(initial, 0)
    for step in range(1, horizon):
        indices = starts + step
        update(
            (
                values["high_bid"][indices],
                values["low_bid"][indices],
                values["high_ask"][indices],
                values["low_ask"][indices],
            ),
            step,
        )
    if final_extremes is not None:
        update(final_extremes, horizon)
    target = (target_time < stop_time) & (target_time != sentinel)
    stop = (stop_time <= target_time) & (stop_time != sentinel)
    timeout_return = (
        timeout_bid / entry_ask - 1.0
        if direction == 1
        else entry_bid / timeout_ask - 1.0
    )
    gross_return = numpy.where(
        target,
        target_bps / 10_000.0,
        numpy.where(stop, -stop_bps / 10_000.0, timeout_return),
    )
    cost = (
        2.0
        * (FEE_BPS_PER_FILL + SLIPPAGE_BPS_PER_FILL)
        * cost_multiplier
        / 10_000.0
    )
    net_return = (gross_return - cost).astype(numpy.float32)
    label = (net_return > 0).astype(numpy.uint8)
    hit_time = numpy.where(target, target_time, stop_time).astype(numpy.int64)
    entry_second = entry_ns // 1_000_000_000
    exit_second = numpy.where(
        target | stop,
        entry_second + hit_time,
        entry_second + horizon,
    ).astype(numpy.int64)
    return label, net_return, exit_second


def build_pretest_dataset(
    *,
    source_cache_value: typing.Union[str, pathlib.Path],
    protocol_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    progress = progress or (lambda _message: None)
    protocol = write_or_verify_protocol(protocol_value)
    source_cache = pathlib.Path(source_cache_value).resolve()
    source = v1._load_dense_cache(source_cache)
    if source.end_second != v1._iso_timestamp(
        DIAGNOSTIC_CONFIRMATION_END
    ) - 1:
        raise ValueError("V2 dense cache does not end at the frozen boundary")
    progress("selecting V2 causal decision timestamps")
    candidates = _candidate_indices(source)
    progress(f"V2 candidates before feature filter: {len(candidates):,}")
    features, candidates = v1._build_features(source, candidates)
    progress(f"V2 candidates retained: {len(candidates):,}")
    shape = (len(candidates), len(CONFIGURATIONS))
    arrays = {
        name: numpy.empty(
            shape,
            dtype=(
                numpy.uint8
                if "label" in name
                else numpy.float32
                if "return" in name
                else numpy.int64
            ),
        )
        for name in (
            "primary_long_label",
            "primary_short_label",
            "primary_long_return",
            "primary_short_return",
            "primary_long_exit",
            "primary_short_exit",
            "stress_long_return",
            "stress_short_return",
            "stress_long_exit",
            "stress_short_exit",
        )
    }
    for configuration_index, configuration in enumerate(CONFIGURATIONS):
        progress(f"simulating {configuration['name']} primary and stress")
        for direction, side in ((1, "long"), (-1, "short")):
            primary = _direction_outcome(
                source,
                candidates,
                direction=direction,
                latency_ms=PRIMARY_LATENCY_MS,
                cost_multiplier=1.0,
                configuration=configuration,
            )
            stress = _direction_outcome(
                source,
                candidates,
                direction=direction,
                latency_ms=STRESS_LATENCY_MS,
                cost_multiplier=COST_STRESS_MULTIPLIER,
                configuration=configuration,
            )
            arrays[f"primary_{side}_label"][:, configuration_index] = primary[0]
            arrays[f"primary_{side}_return"][:, configuration_index] = primary[1]
            arrays[f"primary_{side}_exit"][:, configuration_index] = primary[2]
            arrays[f"stress_{side}_return"][:, configuration_index] = stress[1]
            arrays[f"stress_{side}_exit"][:, configuration_index] = stress[2]
    dataset = ScalpingV2Dataset(
        timestamps=(source.start_second + candidates + 1).astype(numpy.int64),
        features=features,
        **arrays,
    )
    output = pathlib.Path(output_value).resolve()
    artifact = dataset.save(output)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": "pretest_scalping_v2_dataset",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_snapshot_sha256": SNAPSHOT_SHA256,
        "source_cache_sha256": v1._sha256(source_cache),
        "locked_test_materialized": False,
        "rows": len(dataset.timestamps),
        "features": len(v1.FEATURE_NAMES),
        "configurations": list(CONFIGURATIONS),
        "first_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[0]), datetime.timezone.utc
        ).isoformat(),
        "last_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[-1]), datetime.timezone.utc
        ).isoformat(),
        "artifact": artifact,
    }
    manifest_path = output.with_suffix(".manifest.json")
    v1._atomic_json(manifest_path, manifest)
    return {**manifest, "manifest": str(manifest_path)}


def _fit_model(name: str, features: numpy.ndarray, labels: numpy.ndarray):
    if name == "numpy_logistic":
        return model_module.NumpyLogisticModel.fit(
            features, labels, v1.FEATURE_NAMES, LOGISTIC_CONFIG
        )
    if name == "numpy_gradient_boosting":
        return model_module.NumpyGradientBoostingModel.fit(
            features, labels, v1.FEATURE_NAMES, BOOSTING_CONFIG
        )
    raise ValueError("unknown V2 model family")


def _stack(
    dataset: v1.ScalpingResearchDataset, indices: numpy.ndarray
) -> tuple[numpy.ndarray, numpy.ndarray]:
    return (
        numpy.concatenate(
            (
                dataset.directional_features(indices, 1),
                dataset.directional_features(indices, -1),
            )
        ),
        numpy.concatenate(
            (
                dataset.primary_long_label[indices],
                dataset.primary_short_label[indices],
            )
        ).astype(numpy.uint8),
    )


def _fit_with_calibration(
    dataset: v1.ScalpingResearchDataset,
    available: numpy.ndarray,
    *,
    model_name: str,
):
    split = int(len(available) * (1.0 - CALIBRATION_FRACTION))
    calibration_start = int(dataset.timestamps[available[split]])
    fit = available[
        (dataset.timestamps[available] < calibration_start - 900)
        & (dataset.timestamps[available] % TRAINING_STRIDE_SECONDS == 0)
    ]
    calibration = available[split:]
    if len(fit) < 1_000 or len(calibration) < 500:
        raise ValueError("V2 fit/calibration split is too small")
    fit_features, fit_labels = _stack(dataset, fit)
    calibration_features, calibration_labels = _stack(dataset, calibration)
    model = _fit_model(model_name, fit_features, fit_labels)
    raw = model.predict_proba(calibration_features)
    calibrator = (
        percentage_probability_engine.QuantileIsotonicCalibrator.fit(
            raw,
            calibration_labels,
            maximum_bins=100,
            minimum_rows_per_bin=200,
        )
    )
    calibrated = calibrator.predict(raw)
    return model, calibrator, calibration, {
        "fit_decisions": int(len(fit)),
        "fit_rows": int(len(fit_labels)),
        "fit_base_rate": float(numpy.mean(fit_labels)),
        "calibration_decisions": int(len(calibration)),
        "calibration_rows": int(len(calibration_labels)),
        "calibration_base_rate": float(numpy.mean(calibration_labels)),
        "calibration_brier": float(
            numpy.mean((calibrated - calibration_labels) ** 2)
        ),
        "calibration_constant_brier": float(
            numpy.mean(
                (numpy.mean(calibration_labels) - calibration_labels) ** 2
            )
        ),
    }


def _development_folds(
    dataset: v1.ScalpingResearchDataset,
) -> list[tuple[numpy.ndarray, numpy.ndarray]]:
    development = numpy.flatnonzero(
        dataset.timestamps < v1._iso_timestamp(DEVELOPMENT_END)
    )
    test_size = len(development) // (WALK_FORWARD_FOLDS + 1)
    if test_size < 1:
        raise ValueError("V2 development block is too small")
    folds = []
    for fold in range(WALK_FORWARD_FOLDS):
        start = (fold + 1) * test_size
        end = len(development) if fold == WALK_FORWARD_FOLDS - 1 else start + test_size
        test = development[start:end]
        test_start = int(dataset.timestamps[test[0]])
        train = development[
            dataset.timestamps[development] < test_start - 900
        ]
        folds.append((train, test))
    return folds


def _predict(
    dataset: v1.ScalpingResearchDataset,
    indices: numpy.ndarray,
    model: typing.Any,
    calibrator: percentage_probability_engine.QuantileIsotonicCalibrator,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    return (
        calibrator.predict(
            model.predict_proba(dataset.directional_features(indices, 1))
        ),
        calibrator.predict(
            model.predict_proba(dataset.directional_features(indices, -1))
        ),
    )


def _gate(
    primary: dict,
    stress: dict,
    calibration: dict,
    *,
    minimum_trades: int,
    positive_folds: int | None = None,
    valid_folds: int | None = None,
) -> dict:
    gate = v1._gate_checks(
        primary,
        stress,
        calibration,
        minimum_trades=minimum_trades,
        minimum_positive_folds=(4 if positive_folds is not None else None),
        positive_folds=positive_folds,
    )
    if valid_folds is not None:
        gate["checks"]["all_folds_fitted"] = (
            valid_folds == WALK_FORWARD_FOLDS
        )
        gate["passed"] = all(gate["checks"].values())
        gate["passed_checks"] = sum(
            bool(value) for value in gate["checks"].values()
        )
        gate["total_checks"] = len(gate["checks"])
    return gate


def _rank(report: dict) -> tuple:
    stress_pf = report["stress"]["profit_factor"]
    if not math.isfinite(float(stress_pf)):
        stress_pf = 1_000.0
    return (
        report["gate"]["passed_checks"],
        float(stress_pf),
        report["stress"]["total_return"],
        report["primary"]["total_return"],
        report["primary"]["trades"],
        report["configuration"],
        report["model"],
        -report["probability_quantile"],
    )


def evaluate_pretest(
    *,
    dataset_value: typing.Union[str, pathlib.Path],
    dataset_manifest_value: typing.Union[str, pathlib.Path],
    protocol_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    progress = progress or (lambda _message: None)
    protocol = write_or_verify_protocol(protocol_value)
    dataset_manifest = json.loads(
        pathlib.Path(dataset_manifest_value).read_text(encoding="utf-8")
    )
    if dataset_manifest.get("protocol_sha256") != protocol["protocol_sha256"]:
        raise ValueError("V2 dataset/protocol mismatch")
    if dataset_manifest.get("locked_test_materialized") is not False:
        raise ValueError("V2 pre-test artifact contains locked data")
    dataset = ScalpingV2Dataset.load(
        dataset_value,
        expected_sha256=dataset_manifest["artifact"]["sha256"],
    )
    states = {
        (configuration_index, model_name, quantile): {
            "primary": [],
            "stress": [],
            "calibration": [],
            "folds": [],
            "thresholds": [],
            "fit_failures": [],
        }
        for configuration_index in range(len(CONFIGURATIONS))
        for model_name in ("numpy_logistic", "numpy_gradient_boosting")
        for quantile in PROBABILITY_QUANTILES
    }
    for configuration_index, configuration in enumerate(CONFIGURATIONS):
        view = dataset.view(configuration_index)
        folds = _development_folds(view)
        for fold_number, (train, test) in enumerate(folds, 1):
            progress(
                f"{configuration['name']} fold {fold_number}/5 "
                f"train={len(train):,} test={len(test):,}"
            )
            for model_name in ("numpy_logistic", "numpy_gradient_boosting"):
                progress(
                    f"{configuration['name']} fold {fold_number}: "
                    f"fitting {model_name}"
                )
                try:
                    model, calibrator, calibration_rows, fit_report = (
                        _fit_with_calibration(
                            view, train, model_name=model_name
                        )
                    )
                except ValueError as error:
                    for quantile in PROBABILITY_QUANTILES:
                        states[(configuration_index, model_name, quantile)][
                            "fit_failures"
                        ].append({"fold": fold_number, "reason": str(error)})
                    continue
                calibration_long, calibration_short = _predict(
                    view, calibration_rows, model, calibrator
                )
                test_long, test_short = _predict(view, test, model, calibrator)
                calibration_metric = v1._calibration_metrics(
                    view,
                    test,
                    test_long,
                    test_short,
                    fit_report["calibration_base_rate"],
                )
                threshold_source = numpy.concatenate(
                    (calibration_long, calibration_short)
                )
                for quantile in PROBABILITY_QUANTILES:
                    threshold = float(numpy.quantile(threshold_source, quantile))
                    primary_trades = v1._simulate_trades(
                        view,
                        test,
                        test_long,
                        test_short,
                        threshold,
                        stress=False,
                    )
                    stress_trades = v1._simulate_trades(
                        view,
                        test,
                        test_long,
                        test_short,
                        threshold,
                        stress=True,
                    )
                    primary_metric = v1._trade_metrics(view, primary_trades)
                    stress_metric = v1._trade_metrics(view, stress_trades)
                    state = states[(configuration_index, model_name, quantile)]
                    state["primary"].append(primary_trades)
                    state["stress"].append(stress_trades)
                    state["calibration"].append(calibration_metric)
                    state["thresholds"].append(threshold)
                    state["folds"].append(
                        {
                            "fold": fold_number,
                            "fit": fit_report,
                            "threshold": threshold,
                            "primary": primary_metric,
                            "stress": stress_metric,
                            "calibration": calibration_metric,
                        }
                    )

    candidates = []
    empty_calibration = {
        "rows": 0,
        "base_rate": 0.0,
        "mean_probability": 0.0,
        "brier": 1.0,
        "constant_brier": 0.0,
        "expected_calibration_error": 1.0,
    }
    for (configuration_index, model_name, quantile), state in states.items():
        view = dataset.view(configuration_index)
        primary = v1._trade_metrics(view, v1._combine_trades(state["primary"]))
        stress = v1._trade_metrics(view, v1._combine_trades(state["stress"]))
        calibration = (
            v1._aggregate_calibration(state["calibration"])
            if state["calibration"]
            else empty_calibration
        )
        positive_folds = sum(
            fold["primary"]["total_return"] > 0 for fold in state["folds"]
        )
        gate = _gate(
            primary,
            stress,
            calibration,
            minimum_trades=500,
            positive_folds=positive_folds,
            valid_folds=len(state["folds"]),
        )
        candidates.append(
            {
                "configuration": CONFIGURATIONS[configuration_index]["name"],
                "configuration_index": configuration_index,
                "model": model_name,
                "probability_quantile": quantile,
                "thresholds": (
                    {
                        "minimum": min(state["thresholds"]),
                        "maximum": max(state["thresholds"]),
                        "mean": float(numpy.mean(state["thresholds"])),
                    }
                    if state["thresholds"]
                    else None
                ),
                "primary": primary,
                "stress": stress,
                "calibration": calibration,
                "positive_folds": positive_folds,
                "valid_folds": len(state["folds"]),
                "fit_failures": state["fit_failures"],
                "folds": state["folds"],
                "gate": gate,
            }
        )
    candidates.sort(key=_rank, reverse=True)
    chosen = candidates[0]
    progress(
        f"V2 development choice {chosen['configuration']} "
        f"{chosen['model']} q={chosen['probability_quantile']} "
        f"gate={chosen['gate']['passed']}"
    )
    chosen_view = dataset.view(chosen["configuration_index"])
    development = numpy.flatnonzero(
        chosen_view.timestamps < v1._iso_timestamp(DEVELOPMENT_END)
    )
    final_model, final_calibrator, calibration_rows, final_fit = (
        _fit_with_calibration(
            chosen_view, development, model_name=chosen["model"]
        )
    )
    calibration_long, calibration_short = _predict(
        chosen_view, calibration_rows, final_model, final_calibrator
    )
    threshold = float(
        numpy.quantile(
            numpy.concatenate((calibration_long, calibration_short)),
            chosen["probability_quantile"],
        )
    )
    confirmation = numpy.flatnonzero(
        (chosen_view.timestamps >= v1._iso_timestamp(DEVELOPMENT_END))
        & (
            chosen_view.timestamps
            < v1._iso_timestamp(DIAGNOSTIC_CONFIRMATION_END)
        )
    )
    confirmation_long, confirmation_short = _predict(
        chosen_view, confirmation, final_model, final_calibrator
    )
    confirmation_primary_trades = v1._simulate_trades(
        chosen_view,
        confirmation,
        confirmation_long,
        confirmation_short,
        threshold,
        stress=False,
    )
    confirmation_stress_trades = v1._simulate_trades(
        chosen_view,
        confirmation,
        confirmation_long,
        confirmation_short,
        threshold,
        stress=True,
    )
    confirmation_primary = v1._trade_metrics(
        chosen_view, confirmation_primary_trades
    )
    confirmation_stress = v1._trade_metrics(
        chosen_view, confirmation_stress_trades
    )
    confirmation_calibration = v1._calibration_metrics(
        chosen_view,
        confirmation,
        confirmation_long,
        confirmation_short,
        final_fit["calibration_base_rate"],
    )
    confirmation_gate = _gate(
        confirmation_primary,
        confirmation_stress,
        confirmation_calibration,
        minimum_trades=100,
    )
    locked_authorized = bool(
        chosen["gate"]["passed"] and confirmation_gate["passed"]
    )

    created_at = datetime.datetime.now(datetime.timezone.utc)
    experiment_id = (
        f"{PROTOCOL_VERSION}-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    )
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / experiment_id
    experiment.mkdir(parents=True, exist_ok=False)
    model_path = experiment / "model.npz"
    model_artifact = final_model.save(model_path)
    calibrator_path = experiment / "calibrator.json"
    final_calibrator.save(calibrator_path)
    reload_model = (
        model_module.NumpyLogisticModel.load(model_path)
        if chosen["model"] == "numpy_logistic"
        else model_module.NumpyGradientBoostingModel.load(model_path)
    )
    reload_calibrator = (
        percentage_probability_engine.QuantileIsotonicCalibrator.load(
            calibrator_path
        )
    )
    reproduced = _predict(
        chosen_view, confirmation, reload_model, reload_calibrator
    )
    reproduction_difference = max(
        float(numpy.max(numpy.abs(reproduced[0] - confirmation_long))),
        float(numpy.max(numpy.abs(reproduced[1] - confirmation_short))),
    )
    if reproduction_difference > 1e-12:
        raise RuntimeError("V2 persisted model does not reproduce predictions")
    trades_path = experiment / "confirmation_trades.npz"
    with trades_path.open("wb") as stream:
        numpy.savez_compressed(
            stream,
            rows=confirmation_primary_trades["rows"],
            timestamps=chosen_view.timestamps[
                confirmation_primary_trades["rows"]
            ],
            directions=confirmation_primary_trades["directions"],
            instrument_returns=confirmation_primary_trades[
                "instrument_returns"
            ],
            exit_timestamps=confirmation_primary_trades["exit_timestamps"],
            probabilities=confirmation_primary_trades["probabilities"],
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
        },
        "dataset": {
            "rows": len(dataset.timestamps),
            "sha256": dataset_manifest["artifact"]["sha256"],
            "locked_test_materialized": False,
        },
        "development": {
            "chosen_candidate": {
                key: chosen[key]
                for key in (
                    "configuration",
                    "configuration_index",
                    "model",
                    "probability_quantile",
                    "thresholds",
                    "primary",
                    "stress",
                    "calibration",
                    "positive_folds",
                    "valid_folds",
                    "fit_failures",
                    "gate",
                )
            },
            "all_candidates": candidates,
        },
        "frozen_model": {
            "configuration": CONFIGURATIONS[chosen["configuration_index"]],
            "model": model_artifact,
            "calibrator": {
                "path": str(calibrator_path),
                "bytes": calibrator_path.stat().st_size,
                "sha256": v1._sha256(calibrator_path),
            },
            "fit": final_fit,
            "probability_threshold": threshold,
            "maximum_reproduction_difference": reproduction_difference,
        },
        "diagnostic_confirmation": {
            "diagnostic_reuse": True,
            "start": DEVELOPMENT_END,
            "end": DIAGNOSTIC_CONFIRMATION_END,
            "primary": confirmation_primary,
            "stress": confirmation_stress,
            "calibration": confirmation_calibration,
            "gate": confirmation_gate,
        },
        "locked_final_test": {
            "start": DIAGNOSTIC_CONFIRMATION_END,
            "end": LOCKED_TEST_END,
            "authorized_to_open": locked_authorized,
            "status": (
                "authorized_but_not_opened"
                if locked_authorized
                else "sealed_pretest_gate_failed"
            ),
            "labels_computed": False,
            "predictions_computed": False,
            "metrics_computed": False,
        },
        "conclusion": (
            "pretest_gates_passed_locked_test_may_be_opened_explicitly"
            if locked_authorized
            else "candidate_rejected_before_locked_test"
        ),
    }
    report_path = experiment / "report.json"
    v1._atomic_json(report_path, v1._json_safe(report))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "created_at": created_at.isoformat(),
        "protocol_sha256": protocol["protocol_sha256"],
        "dataset_sha256": dataset_manifest["artifact"]["sha256"],
        "research_only": True,
        "orders_authorized": False,
        "model": model_artifact,
        "calibrator_sha256": v1._sha256(calibrator_path),
        "trades_sha256": v1._sha256(trades_path),
        "report": str(report_path),
        "report_sha256": v1._sha256(report_path),
        "development_gate_passed": chosen["gate"]["passed"],
        "confirmation_gate_passed": confirmation_gate["passed"],
        "locked_test_authorized": locked_authorized,
    }
    manifest_path = experiment / "manifest.json"
    v1._atomic_json(manifest_path, manifest)
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "experiments.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "experiment_id": experiment_id,
                    "created_at": created_at.isoformat(),
                    "manifest": str(manifest_path),
                    "manifest_sha256": v1._sha256(manifest_path),
                    "development_gate_passed": chosen["gate"]["passed"],
                    "confirmation_gate_passed": confirmation_gate["passed"],
                    "locked_test_authorized": locked_authorized,
                },
                sort_keys=True,
            )
            + "\n"
        )
    return {
        "experiment_id": experiment_id,
        "experiment_directory": str(experiment),
        "report": str(report_path),
        "development_gate_passed": chosen["gate"]["passed"],
        "confirmation_gate_passed": confirmation_gate["passed"],
        "locked_test_authorized": locked_authorized,
    }


def main(arguments: typing.Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    protocol_parser = subparsers.add_parser("write-protocol")
    protocol_parser.add_argument("--output", required=True)
    dataset_parser = subparsers.add_parser("build-pretest-dataset")
    dataset_parser.add_argument("--source-cache", required=True)
    dataset_parser.add_argument("--protocol", required=True)
    dataset_parser.add_argument("--output", required=True)
    evaluation_parser = subparsers.add_parser("evaluate-pretest")
    evaluation_parser.add_argument("--dataset", required=True)
    evaluation_parser.add_argument("--dataset-manifest", required=True)
    evaluation_parser.add_argument("--protocol", required=True)
    evaluation_parser.add_argument("--output-root", required=True)
    parsed = parser.parse_args(arguments)

    def progress(message: str) -> None:
        print(message, flush=True)

    if parsed.command == "write-protocol":
        print(
            json.dumps(
                write_or_verify_protocol(parsed.output),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if parsed.command == "build-pretest-dataset":
        result = build_pretest_dataset(
            source_cache_value=parsed.source_cache,
            protocol_value=parsed.protocol,
            output_value=parsed.output,
            progress=progress,
        )
        print(json.dumps(v1._json_safe(result), indent=2, sort_keys=True))
        return 0
    if parsed.command == "evaluate-pretest":
        result = evaluate_pretest(
            dataset_value=parsed.dataset,
            dataset_manifest_value=parsed.dataset_manifest,
            protocol_value=parsed.protocol,
            output_root_value=parsed.output_root,
            progress=progress,
        )
        print(json.dumps(v1._json_safe(result), indent=2, sort_keys=True))
        return 0
    raise AssertionError("unhandled V2 command")


if __name__ == "__main__":
    raise SystemExit(main())
