"""Result-free protocol for event-level BTC queue-flow research V3."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import time
import typing

import numpy

from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import scalping_strategy_search as v1
from octobot.ai_strategy_lab import scalping_strategy_search_v2 as v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_scalping_queue_flow_v3"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_PROTOCOL_VERSION = v2.PROTOCOL_VERSION
PARENT_PROTOCOL_SHA256 = (
    "22d0872fc679f1b9f01110409251a0a8dd792fa4844670f67c3da703c7744a04"
)
PARENT_REPORT_SHA256 = (
    "c298856cf1b42c331bbc34e06bb12c6cb7b059708152746683297401a26243cb"
)
SNAPSHOT_SHA256 = v1.SNAPSHOT_SHA256
SOURCE_START = v1.SOURCE_START
DEVELOPMENT_END = v2.DEVELOPMENT_END
DIAGNOSTIC_CONFIRMATION_END = v2.DIAGNOSTIC_CONFIRMATION_END
LOCKED_TEST_END = v2.LOCKED_TEST_END
QUEUE_WINDOWS_SECONDS = (2, 5, 15, 60)
QUEUE_WINDOW_FEATURES = (
    "directional_normalized_ofi_mean",
    "directional_depletion_asymmetry_mean",
    "directional_refill_asymmetry_mean",
    "directional_depth1_imbalance_mean",
    "directional_depth5_imbalance_mean",
    "directional_microprice_change_bps",
    "directional_quote_move_imbalance",
    "directional_aggressor_to_depth",
    "directional_ofi_trade_divergence",
    "normalized_ofi_abs_mean",
    "update_intensity",
    "depth1_mean",
    "depth5_mean",
    "top_depth_concentration_mean",
)
QUEUE_FEATURE_NAMES = tuple(
    f"q{window}_{name}"
    for window in QUEUE_WINDOWS_SECONDS
    for name in QUEUE_WINDOW_FEATURES
)
FEATURE_NAMES = v1.FEATURE_NAMES + QUEUE_FEATURE_NAMES
DIRECTIONAL_FEATURE_MASK = numpy.concatenate(
    (
        v1.DIRECTIONAL_FEATURE_MASK,
        numpy.asarray(
            ["directional_" in name for name in QUEUE_FEATURE_NAMES],
            dtype=bool,
        ),
    )
)
REGRESSION_TARGET_CLIP_BPS = 60.0
EXPECTED_RETURN_QUANTILES = (0.90, 0.95)
MINIMUM_DIRECTION_MARGIN_BPS = 2.0
BOOSTING_CONFIG = model_module.BoostingConfig(
    trees=48,
    max_depth=2,
    bins=24,
    learning_rate=0.06,
    l2=100.0,
    minimum_leaf_rows=400,
    minimum_gain=1.0,
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
    """Return the immutable, result-free V3 evaluation protocol."""

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
        "parent_rejection": {
            "protocol_version": PARENT_PROTOCOL_VERSION,
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "report_sha256": PARENT_REPORT_SHA256,
            "lesson_used": (
                "V2 probability calibration was slightly informative but "
                "selected gross expectancy was far below taker costs"
            ),
            "economic_configurations_unchanged": True,
            "costs_unchanged": True,
            "thresholds_not_retuned_from_parent_results": True,
        },
        "frozen_source": {
            "snapshot_sha256": SNAPSHOT_SHA256,
            "start_inclusive": SOURCE_START,
            "pretest_end_exclusive": DIAGNOSTIC_CONFIRMATION_END,
            "locked_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_not_materialized_at_preregistration": True,
        },
        "candidate_family": {
            "name": "event_level_queue_flow_expected_return",
            "decision_stride_seconds": v2.DECISION_STRIDE_SECONDS,
            "training_stride_seconds": v2.TRAINING_STRIDE_SECONDS,
            "one_trade_at_a_time": True,
            "directions": ["LONG", "SHORT"],
            "entry": "first executable top-of-book after 500ms",
            "primary_latency_ms": v2.PRIMARY_LATENCY_MS,
            "stress_latency_ms": v2.STRESS_LATENCY_MS,
            "configurations": list(v2.CONFIGURATIONS),
            "outcomes_reused_without_change": PARENT_PROTOCOL_VERSION,
            "decision_rule": (
                "choose the side with greater predicted net return only when "
                "it exceeds both zero and a calibration quantile and exceeds "
                "the opposite side by at least 2 bps"
            ),
            "expected_return_quantiles": list(EXPECTED_RETURN_QUANTILES),
            "minimum_direction_margin_bps": MINIMUM_DIRECTION_MARGIN_BPS,
            "selection_candidates": (
                len(v2.CONFIGURATIONS) * len(EXPECTED_RETURN_QUANTILES)
            ),
        },
        "features": {
            "schema": list(FEATURE_NAMES),
            "original_aggregate_features": len(v1.FEATURE_NAMES),
            "new_queue_flow_features": len(QUEUE_FEATURE_NAMES),
            "queue_windows_seconds": list(QUEUE_WINDOWS_SECONDS),
            "raw_event_clock": "received_ts_ns",
            "causal_at_decision_close": True,
            "directional_symmetry": True,
            "session_or_gap_reset_seconds": 5,
            "queue_dynamics": {
                "normalized_ofi": (
                    "Cont-style best-quote order-flow imbalance normalized by "
                    "the adjacent mean top-of-book depth"
                ),
                "depletion_and_refill": (
                    "signed best-quote depletion and refill asymmetry"
                ),
                "depth": (
                    "event-weighted level-1 and level-5 depth, imbalance and "
                    "top-level concentration"
                ),
                "price_response": (
                    "microprice changes and quote direction imbalance"
                ),
                "trade_interaction": (
                    "aggressor volume normalized by displayed depth and its "
                    "divergence from queue flow"
                ),
            },
        },
        "costs": {
            "fee_bps_per_fill": v2.FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": v2.SLIPPAGE_BPS_PER_FILL,
            "fills": 2,
            "position_fraction": v2.POSITION_FRACTION,
            "stress_multiplier": v2.COST_STRESS_MULTIPLIER,
            "maker_fill_assumptions": False,
        },
        "model": {
            "name": "numpy_squared_error_gradient_boosting",
            "config": dataclasses.asdict(BOOSTING_CONFIG),
            "target": "realized primary net instrument return in bps",
            "target_clip_bps": REGRESSION_TARGET_CLIP_BPS,
            "model_families": 1,
            "regression_gate": (
                "out-of-sample MSE must beat a training-mean constant"
            ),
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "development_walk_forward_folds": v2.WALK_FORWARD_FOLDS,
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
            "mse_better_than_training_mean_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "confirmation_and_locked_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "mse_better_than_training_mean_constant": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "multiple_testing_disclosure": (
            "one model family, two unchanged economic configurations and two "
            "predeclared expected-return quantiles are compared in development; "
            "the August 20-26 block remains the sole untouched test"
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
            raise ValueError("persisted scalping V3 protocol differs")
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
class ScalpingV3Dataset:
    timestamps: numpy.ndarray
    features: numpy.ndarray
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
        configurations = len(v2.CONFIGURATIONS)
        if not rows or numpy.any(numpy.diff(self.timestamps) <= 0):
            raise ValueError("V3 timestamps are empty or unordered")
        if self.features.shape != (rows, len(FEATURE_NAMES)):
            raise ValueError("V3 feature shape differs")
        if int(self.timestamps[-1]) >= v1._iso_timestamp(
            DIAGNOSTIC_CONFIRMATION_END
        ):
            raise ValueError("V3 pre-test dataset enters the locked block")
        if not numpy.all(numpy.isfinite(self.features)):
            raise ValueError("V3 features contain non-finite values")
        for field in dataclasses.fields(self):
            if field.name in {"timestamps", "features"}:
                continue
            values = getattr(self, field.name)
            if values.shape != (rows, configurations):
                raise ValueError(f"V3 field {field.name} is misaligned")
            if "return" in field.name and not numpy.all(
                numpy.isfinite(values)
            ):
                raise ValueError("V3 returns contain non-finite values")

    def directional_features(
        self, indices: numpy.ndarray, direction: int
    ) -> numpy.ndarray:
        values = self.features[indices].copy()
        if direction == -1:
            values[:, DIRECTIONAL_FEATURE_MASK] *= -1.0
        elif direction != 1:
            raise ValueError("direction must be +1 or -1")
        return values

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
                protocol_sha256=numpy.asarray(
                    [_json_hash(frozen_protocol())]
                ),
                source_snapshot_sha256=numpy.asarray([SNAPSHOT_SHA256]),
                feature_names=numpy.asarray(FEATURE_NAMES),
                directional_feature_mask=DIRECTIONAL_FEATURE_MASK,
                configurations=numpy.asarray(
                    [
                        json.dumps(value, sort_keys=True)
                        for value in v2.CONFIGURATIONS
                    ]
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
    ) -> "ScalpingV3Dataset":
        path = pathlib.Path(path_value).resolve()
        if expected_sha256 is not None and v1._sha256(path) != expected_sha256:
            raise ValueError("V3 dataset hash differs")
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported V3 dataset schema")
            if str(values["protocol_version"][0]) != PROTOCOL_VERSION:
                raise ValueError("V3 dataset protocol differs")
            if str(values["protocol_sha256"][0]) != _json_hash(
                frozen_protocol()
            ):
                raise ValueError("V3 dataset protocol hash differs")
            if str(values["source_snapshot_sha256"][0]) != SNAPSHOT_SHA256:
                raise ValueError("V3 source snapshot differs")
            if tuple(str(value) for value in values["feature_names"]) != (
                FEATURE_NAMES
            ):
                raise ValueError("V3 feature schema differs")
            if not numpy.array_equal(
                values["directional_feature_mask"],
                DIRECTIONAL_FEATURE_MASK,
            ):
                raise ValueError("V3 directional mask differs")
            configurations = tuple(
                json.loads(str(value)) for value in values["configurations"]
            )
            if configurations != v2.CONFIGURATIONS:
                raise ValueError("V3 economic configurations differ")
            dataset = cls(
                **{
                    field.name: values[field.name].copy()
                    for field in dataclasses.fields(cls)
                }
            )
        dataset.validate()
        return dataset


def _empty_queue_values(length: int) -> dict[str, numpy.ndarray]:
    names = (
        "normalized_ofi_sum",
        "normalized_ofi_abs_sum",
        "depletion_asymmetry_sum",
        "refill_asymmetry_sum",
        "depth1_imbalance_sum",
        "depth5_imbalance_sum",
        "microprice_change_bps_sum",
        "depth1_sum",
        "depth5_sum",
        "top_depth_concentration_sum",
    )
    values = {
        name: numpy.zeros(length, dtype=numpy.float64) for name in names
    }
    values.update(
        {
            "event_count": numpy.zeros(length, dtype=numpy.int32),
            "quote_up_count": numpy.zeros(length, dtype=numpy.int32),
            "quote_down_count": numpy.zeros(length, dtype=numpy.int32),
        }
    )
    return values


def _side_flow(
    previous_price: float,
    previous_size: float,
    price: float,
    size: float,
    *,
    bid: bool,
) -> float:
    if price == previous_price:
        return size - previous_size
    improved = price > previous_price if bid else price < previous_price
    return size if improved else -previous_size


def _scan_queue_events(
    database: pathlib.Path,
    source: v1.DenseSource,
    *,
    progress: typing.Callable[[str], None] | None = None,
) -> tuple[dict[str, numpy.ndarray], dict]:
    progress = progress or (lambda _message: None)
    queue = _empty_queue_values(len(source))
    start_ns = source.start_second * 1_000_000_000
    end_ns = (source.end_second + 1) * 1_000_000_000
    connection = sqlite3.connect(
        f"file:{database}?mode=ro&immutable=1", uri=True, timeout=30
    )
    connection.execute("PRAGMA query_only=ON")
    first_row = connection.execute(
        """
        SELECT id FROM book_events
        WHERE received_ts_ns >= ?
        ORDER BY received_ts_ns LIMIT 1
        """,
        (start_ns,),
    ).fetchone()
    last_row = connection.execute(
        """
        SELECT id FROM book_events
        WHERE received_ts_ns < ?
        ORDER BY received_ts_ns DESC LIMIT 1
        """,
        (end_ns,),
    ).fetchone()
    if first_row is None or last_row is None:
        connection.close()
        raise ValueError("frozen source contains no V3 queue events")
    first_id, last_id = int(first_row[0]), int(last_row[0])
    cursor = connection.execute(
        """
        SELECT received_ts_ns, session_id,
               bid_price_1, bid_size_1, bid_size_2, bid_size_3,
               bid_size_4, bid_size_5,
               ask_price_1, ask_size_1, ask_size_2, ask_size_3,
               ask_size_4, ask_size_5, mid_price, microprice
        FROM book_events
        WHERE id BETWEEN ? AND ?
        ORDER BY id
        """,
        (first_id, last_id),
    )
    previous: tuple | None = None
    previous_received_ns = 0
    processed = 0
    transitions = 0
    resets = 0
    started = time.monotonic()
    try:
        for row in cursor:
            received_ns = int(row[0])
            if received_ns < start_ns or received_ns >= end_ns:
                continue
            if previous_received_ns and received_ns < previous_received_ns:
                raise ValueError("raw V3 receive timestamps are out of order")
            previous_received_ns = received_ns
            index = received_ns // 1_000_000_000 - source.start_second
            if index < 0 or index >= len(source):
                continue
            session = str(row[1])
            bid_price = float(row[2])
            bid_sizes = numpy.asarray(row[3:8], dtype=numpy.float64)
            ask_price = float(row[8])
            ask_sizes = numpy.asarray(row[9:14], dtype=numpy.float64)
            mid = float(row[14])
            microprice = float(row[15])
            depth1 = float(bid_sizes[0] + ask_sizes[0])
            bid_depth5 = float(numpy.sum(bid_sizes))
            ask_depth5 = float(numpy.sum(ask_sizes))
            depth5 = bid_depth5 + ask_depth5
            queue["event_count"][index] += 1
            if depth1 > 0:
                queue["depth1_imbalance_sum"][index] += float(
                    (bid_sizes[0] - ask_sizes[0]) / depth1
                )
            if depth5 > 0:
                queue["depth5_imbalance_sum"][index] += float(
                    (bid_depth5 - ask_depth5) / depth5
                )
                queue["top_depth_concentration_sum"][index] += (
                    depth1 / depth5
                )
            queue["depth1_sum"][index] += depth1
            queue["depth5_sum"][index] += depth5

            continuous = (
                previous is not None
                and previous[0] == session
                and received_ns - int(previous[1]) <= 5_000_000_000
            )
            if continuous:
                previous_bid_price = float(previous[2])
                previous_bid_size = float(previous[3])
                previous_ask_price = float(previous[4])
                previous_ask_size = float(previous[5])
                previous_mid = float(previous[6])
                previous_microprice = float(previous[7])
                bid_flow = _side_flow(
                    previous_bid_price,
                    previous_bid_size,
                    bid_price,
                    float(bid_sizes[0]),
                    bid=True,
                )
                ask_flow = _side_flow(
                    previous_ask_price,
                    previous_ask_size,
                    ask_price,
                    float(ask_sizes[0]),
                    bid=False,
                )
                normalization = max(
                    1e-9,
                    0.5
                    * (
                        previous_bid_size
                        + previous_ask_size
                        + float(bid_sizes[0])
                        + float(ask_sizes[0])
                    ),
                )
                normalized_ofi = (bid_flow - ask_flow) / normalization
                depletion = (
                    max(-ask_flow, 0.0) - max(-bid_flow, 0.0)
                ) / normalization
                refill = (
                    max(bid_flow, 0.0) - max(ask_flow, 0.0)
                ) / normalization
                queue["normalized_ofi_sum"][index] += normalized_ofi
                queue["normalized_ofi_abs_sum"][index] += abs(
                    normalized_ofi
                )
                queue["depletion_asymmetry_sum"][index] += depletion
                queue["refill_asymmetry_sum"][index] += refill
                if previous_microprice > 0 and microprice > 0:
                    queue["microprice_change_bps_sum"][index] += (
                        math.log(microprice / previous_microprice) * 10_000.0
                    )
                if mid > previous_mid:
                    queue["quote_up_count"][index] += 1
                elif mid < previous_mid:
                    queue["quote_down_count"][index] += 1
                transitions += 1
            elif previous is not None:
                resets += 1
            previous = (
                session,
                received_ns,
                bid_price,
                float(bid_sizes[0]),
                ask_price,
                float(ask_sizes[0]),
                mid,
                microprice,
            )
            processed += 1
            if processed % 2_000_000 == 0:
                progress(
                    f"V3 queue books {processed:,}/{last_id-first_id+1:,} "
                    f"in {time.monotonic()-started:.1f}s"
                )
    finally:
        connection.close()
    report = {
        "first_id": first_id,
        "last_id": last_id,
        "processed_book_events": processed,
        "continuous_transitions": transitions,
        "session_or_gap_resets": resets,
        "first_received_ts_ns": start_ns,
        "end_received_ts_ns_exclusive": end_ns,
    }
    progress(f"V3 queue books complete: {processed:,}")
    return queue, report


def _build_queue_features(
    source: v1.DenseSource,
    queue: dict[str, numpy.ndarray],
    candidate_indices: numpy.ndarray,
) -> numpy.ndarray:
    columns: list[numpy.ndarray] = []
    for window in QUEUE_WINDOWS_SECONDS:
        events = v1._rolling_sum(queue["event_count"], window)[
            candidate_indices
        ]

        def event_mean(name: str) -> numpy.ndarray:
            totals = v1._rolling_sum(queue[name], window)[candidate_indices]
            return numpy.divide(
                totals,
                events,
                out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
                where=events > 0,
            )

        normalized_ofi = event_mean("normalized_ofi_sum")
        depletion = event_mean("depletion_asymmetry_sum")
        refill = event_mean("refill_asymmetry_sum")
        depth1_imbalance = event_mean("depth1_imbalance_sum")
        depth5_imbalance = event_mean("depth5_imbalance_sum")
        microprice_change = v1._rolling_sum(
            queue["microprice_change_bps_sum"], window
        )[candidate_indices]
        up = v1._rolling_sum(queue["quote_up_count"], window)[
            candidate_indices
        ]
        down = v1._rolling_sum(queue["quote_down_count"], window)[
            candidate_indices
        ]
        quote_move_imbalance = numpy.divide(
            up - down,
            up + down,
            out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
            where=(up + down) > 0,
        )
        depth1_mean = event_mean("depth1_sum")
        depth5_mean = event_mean("depth5_sum")
        concentration = event_mean("top_depth_concentration_sum")
        buy_size = v1._rolling_sum(
            source.values["buy_trade_size"], window
        )[candidate_indices]
        sell_size = v1._rolling_sum(
            source.values["sell_trade_size"], window
        )[candidate_indices]
        aggressor_to_depth = numpy.divide(
            buy_size - sell_size,
            depth1_mean,
            out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
            where=depth1_mean > 0,
        )
        ofi_trade_divergence = normalized_ofi - numpy.tanh(
            aggressor_to_depth
        )
        columns.extend(
            (
                normalized_ofi,
                depletion,
                refill,
                depth1_imbalance,
                depth5_imbalance,
                microprice_change,
                quote_move_imbalance,
                aggressor_to_depth,
                ofi_trade_divergence,
                event_mean("normalized_ofi_abs_sum"),
                events / window,
                numpy.log1p(numpy.maximum(depth1_mean, 0.0)),
                numpy.log1p(numpy.maximum(depth5_mean, 0.0)),
                concentration,
            )
        )
    features = numpy.column_stack(columns).astype(numpy.float32)
    if features.shape != (len(candidate_indices), len(QUEUE_FEATURE_NAMES)):
        raise RuntimeError("V3 queue feature construction differs")
    if not numpy.all(numpy.isfinite(features)):
        raise ValueError("V3 queue features contain non-finite values")
    return features


def build_pretest_dataset(
    *,
    database_value: typing.Union[str, pathlib.Path],
    freeze_manifest_value: typing.Union[str, pathlib.Path],
    source_cache_value: typing.Union[str, pathlib.Path],
    v2_dataset_value: typing.Union[str, pathlib.Path],
    v2_manifest_value: typing.Union[str, pathlib.Path],
    protocol_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    progress = progress or (lambda _message: None)
    protocol = write_or_verify_protocol(protocol_value)
    database = pathlib.Path(database_value).resolve()
    freeze_manifest_path = pathlib.Path(freeze_manifest_value).resolve()
    freeze_manifest = json.loads(
        freeze_manifest_path.read_text(encoding="utf-8")
    )
    frozen_artifact = freeze_manifest.get("artifacts", {}).get(
        "scalping_level5", {}
    )
    if frozen_artifact.get("sha256") != SNAPSHOT_SHA256:
        raise ValueError("V3 freeze manifest snapshot differs")
    if frozen_artifact.get("bytes") != database.stat().st_size:
        raise ValueError("V3 frozen database size differs")
    v2_manifest = json.loads(
        pathlib.Path(v2_manifest_value).read_text(encoding="utf-8")
    )
    if v2_manifest.get("locked_test_materialized") is not False:
        raise ValueError("V3 parent dataset contains locked data")
    parent = v2.ScalpingV2Dataset.load(
        v2_dataset_value,
        expected_sha256=v2_manifest["artifact"]["sha256"],
    )
    source_cache = pathlib.Path(source_cache_value).resolve()
    source = v1._load_dense_cache(source_cache)
    if source.end_second != v1._iso_timestamp(
        DIAGNOSTIC_CONFIRMATION_END
    ) - 1:
        raise ValueError("V3 dense source crosses its pre-test boundary")
    candidate_indices = (
        parent.timestamps - source.start_second - 1
    ).astype(numpy.int64)
    if numpy.any(candidate_indices < 0) or numpy.any(
        candidate_indices >= len(source)
    ):
        raise ValueError("V3 parent decisions do not align to dense source")
    progress("streaming event-level V3 queue dynamics")
    queue, scan_report = _scan_queue_events(
        database, source, progress=progress
    )
    progress("building causal V3 queue windows")
    queue_features = _build_queue_features(
        source, queue, candidate_indices
    )
    dataset = ScalpingV3Dataset(
        timestamps=parent.timestamps.copy(),
        features=numpy.column_stack(
            (parent.features, queue_features)
        ).astype(numpy.float32),
        **{
            name: getattr(parent, name).copy()
            for name in (
                "primary_long_return",
                "primary_short_return",
                "primary_long_exit",
                "primary_short_exit",
                "stress_long_return",
                "stress_short_return",
                "stress_long_exit",
                "stress_short_exit",
            )
        },
    )
    output = pathlib.Path(output_value).resolve()
    artifact = dataset.save(output)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": "pretest_scalping_v3_queue_flow_dataset",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "source_snapshot_sha256": SNAPSHOT_SHA256,
        "source_cache_sha256": v1._sha256(source_cache),
        "parent_v2_dataset_sha256": v2_manifest["artifact"]["sha256"],
        "freeze_manifest_sha256": v1._sha256(freeze_manifest_path),
        "locked_test_materialized": False,
        "rows": len(dataset.timestamps),
        "features": len(FEATURE_NAMES),
        "original_features": len(v1.FEATURE_NAMES),
        "queue_features": len(QUEUE_FEATURE_NAMES),
        "configurations": list(v2.CONFIGURATIONS),
        "first_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[0]), datetime.timezone.utc
        ).isoformat(),
        "last_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[-1]), datetime.timezone.utc
        ).isoformat(),
        "queue_scan": scan_report,
        "artifact": artifact,
    }
    manifest_path = output.with_suffix(".manifest.json")
    v1._atomic_json(manifest_path, manifest)
    return {**manifest, "manifest": str(manifest_path)}


def _build_regression_tree(
    binned: numpy.ndarray,
    thresholds: list[numpy.ndarray],
    gradients: numpy.ndarray,
    indices: numpy.ndarray,
    *,
    depth: int,
    selected_features: numpy.ndarray,
    config: model_module.BoostingConfig,
    nodes: list[dict],
    leaf_assignments: list[tuple[numpy.ndarray, float]],
) -> int:
    gradient_sum = float(numpy.sum(gradients[indices]))
    row_count = len(indices)
    leaf_value = gradient_sum / (row_count + config.l2)
    node_index = len(nodes)
    nodes.append(
        {
            "feature": -1,
            "threshold": 0.0,
            "left": -1,
            "right": -1,
            "value": float(
                numpy.clip(
                    leaf_value,
                    -REGRESSION_TARGET_CLIP_BPS,
                    REGRESSION_TARGET_CLIP_BPS,
                )
            ),
        }
    )
    if depth >= config.max_depth or row_count < 2 * config.minimum_leaf_rows:
        leaf_assignments.append((indices, nodes[node_index]["value"]))
        return node_index
    parent_score = gradient_sum * gradient_sum / (row_count + config.l2)
    best_gain = config.minimum_gain
    best_feature = -1
    best_bin = -1
    for feature in selected_features:
        feature_bins = binned[indices, feature]
        bin_count = len(thresholds[int(feature)]) + 1
        counts = numpy.bincount(feature_bins, minlength=bin_count)
        gradient_bins = numpy.bincount(
            feature_bins,
            weights=gradients[indices],
            minlength=bin_count,
        )
        left_counts = numpy.cumsum(counts)[:-1]
        right_counts = row_count - left_counts
        valid = (
            (left_counts >= config.minimum_leaf_rows)
            & (right_counts >= config.minimum_leaf_rows)
        )
        if not numpy.any(valid):
            continue
        left_gradients = numpy.cumsum(gradient_bins)[:-1]
        right_gradients = gradient_sum - left_gradients
        gains = 0.5 * (
            left_gradients * left_gradients / (left_counts + config.l2)
            + right_gradients * right_gradients
            / (right_counts + config.l2)
            - parent_score
        )
        gains[~valid] = -numpy.inf
        split_bin = int(numpy.argmax(gains))
        gain = float(gains[split_bin])
        if gain > best_gain:
            best_gain = gain
            best_feature = int(feature)
            best_bin = split_bin
    if best_feature < 0:
        leaf_assignments.append((indices, nodes[node_index]["value"]))
        return node_index
    left_mask = binned[indices, best_feature] <= best_bin
    left_indices = indices[left_mask]
    right_indices = indices[~left_mask]
    left_node = _build_regression_tree(
        binned,
        thresholds,
        gradients,
        left_indices,
        depth=depth + 1,
        selected_features=selected_features,
        config=config,
        nodes=nodes,
        leaf_assignments=leaf_assignments,
    )
    right_node = _build_regression_tree(
        binned,
        thresholds,
        gradients,
        right_indices,
        depth=depth + 1,
        selected_features=selected_features,
        config=config,
        nodes=nodes,
        leaf_assignments=leaf_assignments,
    )
    nodes[node_index].update(
        {
            "feature": best_feature,
            "threshold": float(thresholds[best_feature][best_bin]),
            "left": left_node,
            "right": right_node,
        }
    )
    return node_index


@dataclasses.dataclass
class NumpySquaredBoostingRegressor:
    feature_names: tuple[str, ...]
    initial_score: float
    trees: list[list[dict]]
    config: model_module.BoostingConfig

    @classmethod
    def fit(
        cls,
        features: numpy.ndarray,
        targets: numpy.ndarray,
        feature_names: tuple[str, ...] = FEATURE_NAMES,
        config: model_module.BoostingConfig = BOOSTING_CONFIG,
    ) -> "NumpySquaredBoostingRegressor":
        config.validate()
        if len(features) != len(targets) or not len(targets):
            raise ValueError("V3 regression training data is empty or misaligned")
        if features.shape[1] != len(feature_names):
            raise ValueError("V3 regression feature schema differs")
        features = features.astype(numpy.float32, copy=False)
        targets = numpy.clip(
            targets.astype(numpy.float64),
            -REGRESSION_TARGET_CLIP_BPS,
            REGRESSION_TARGET_CLIP_BPS,
        )
        if not numpy.all(numpy.isfinite(features)) or not numpy.all(
            numpy.isfinite(targets)
        ):
            raise ValueError("V3 regression data contain non-finite values")
        quantiles = numpy.linspace(0.0, 1.0, config.bins + 1)[1:-1]
        thresholds = [
            numpy.unique(numpy.quantile(features[:, index], quantiles))
            for index in range(features.shape[1])
        ]
        binned = numpy.empty(features.shape, dtype=numpy.uint8)
        for index, feature_thresholds in enumerate(thresholds):
            binned[:, index] = numpy.searchsorted(
                feature_thresholds,
                features[:, index],
                side="right",
            ).astype(numpy.uint8)
        initial_score = float(numpy.mean(targets))
        predictions = numpy.full(len(targets), initial_score)
        trees: list[list[dict]] = []
        random = numpy.random.RandomState(config.seed)
        feature_count = max(
            1, int(math.ceil(features.shape[1] * config.feature_fraction))
        )
        for _ in range(config.trees):
            gradients = targets - predictions
            selected_features = numpy.sort(
                random.choice(
                    features.shape[1],
                    size=feature_count,
                    replace=False,
                )
            )
            nodes: list[dict] = []
            leaf_assignments: list[tuple[numpy.ndarray, float]] = []
            _build_regression_tree(
                binned,
                thresholds,
                gradients,
                numpy.arange(len(targets), dtype=numpy.int64),
                depth=0,
                selected_features=selected_features,
                config=config,
                nodes=nodes,
                leaf_assignments=leaf_assignments,
            )
            for indices, value in leaf_assignments:
                predictions[indices] += config.learning_rate * value
            trees.append(nodes)
        return cls(
            feature_names=feature_names,
            initial_score=initial_score,
            trees=trees,
            config=config,
        )

    def predict(self, features: numpy.ndarray) -> numpy.ndarray:
        if features.shape[1] != len(self.feature_names):
            raise ValueError("V3 regression feature matrix differs")
        predictions = numpy.full(len(features), self.initial_score)
        for tree in self.trees:
            predictions += self.config.learning_rate * model_module._predict_tree(
                tree, features
            )
        return predictions

    def save(self, path_value: typing.Union[str, pathlib.Path]) -> dict:
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        numpy.savez_compressed(
            path,
            schema_version=numpy.asarray([SCHEMA_VERSION]),
            model_type=numpy.asarray(["numpy_squared_error_gradient_boosting"]),
            feature_names=numpy.asarray(self.feature_names),
            initial_score=numpy.asarray([self.initial_score]),
            trees=numpy.asarray([json.dumps(self.trees, sort_keys=True)]),
            config=numpy.asarray([json.dumps(dataclasses.asdict(self.config))]),
        )
        return {
            "path": str(path),
            "sha256": v1._sha256(path),
            "bytes": path.stat().st_size,
        }

    @classmethod
    def load(
        cls, path_value: typing.Union[str, pathlib.Path]
    ) -> "NumpySquaredBoostingRegressor":
        path = pathlib.Path(path_value).resolve()
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported V3 regression model schema")
            if str(values["model_type"][0]) != (
                "numpy_squared_error_gradient_boosting"
            ):
                raise ValueError("V3 regression model type differs")
            return cls(
                feature_names=tuple(
                    str(value) for value in values["feature_names"]
                ),
                initial_score=float(values["initial_score"][0]),
                trees=json.loads(str(values["trees"][0])),
                config=model_module.BoostingConfig(
                    **json.loads(str(values["config"][0]))
                ),
            )


def _returns(
    dataset: ScalpingV3Dataset,
    configuration_index: int,
    indices: numpy.ndarray,
    direction: int,
    *,
    stress: bool,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    prefix = "stress" if stress else "primary"
    side = "long" if direction == 1 else "short"
    return (
        getattr(dataset, f"{prefix}_{side}_return")[
            indices, configuration_index
        ],
        getattr(dataset, f"{prefix}_{side}_exit")[
            indices, configuration_index
        ],
    )


def _stack_training(
    dataset: ScalpingV3Dataset,
    configuration_index: int,
    indices: numpy.ndarray,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    long_returns, _ = _returns(
        dataset, configuration_index, indices, 1, stress=False
    )
    short_returns, _ = _returns(
        dataset, configuration_index, indices, -1, stress=False
    )
    return (
        numpy.concatenate(
            (
                dataset.directional_features(indices, 1),
                dataset.directional_features(indices, -1),
            )
        ),
        numpy.concatenate((long_returns, short_returns)).astype(
            numpy.float64
        )
        * 10_000.0,
    )


def _fit_with_calibration(
    dataset: ScalpingV3Dataset,
    configuration_index: int,
    available: numpy.ndarray,
) -> tuple[NumpySquaredBoostingRegressor, numpy.ndarray, dict]:
    split = int(len(available) * (1.0 - v2.CALIBRATION_FRACTION))
    calibration_start = int(dataset.timestamps[available[split]])
    fit = available[
        (
            dataset.timestamps[available]
            < calibration_start - max(
                int(value["horizon_seconds"])
                for value in v2.CONFIGURATIONS
            )
        )
        & (dataset.timestamps[available] % v2.TRAINING_STRIDE_SECONDS == 0)
    ]
    calibration = available[split:]
    if len(fit) < 1_000 or len(calibration) < 500:
        raise ValueError("V3 fit/calibration split is too small")
    features, targets = _stack_training(dataset, configuration_index, fit)
    model = NumpySquaredBoostingRegressor.fit(features, targets)
    return model, calibration, {
        "fit_decisions": int(len(fit)),
        "fit_rows": int(len(targets)),
        "fit_target_mean_bps": float(numpy.mean(targets)),
        "fit_target_std_bps": float(numpy.std(targets)),
        "calibration_decisions": int(len(calibration)),
    }


def _predict_sides(
    dataset: ScalpingV3Dataset,
    indices: numpy.ndarray,
    model: NumpySquaredBoostingRegressor,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    return (
        model.predict(dataset.directional_features(indices, 1)),
        model.predict(dataset.directional_features(indices, -1)),
    )


def _regression_metrics(
    dataset: ScalpingV3Dataset,
    configuration_index: int,
    indices: numpy.ndarray,
    long_predictions: numpy.ndarray,
    short_predictions: numpy.ndarray,
    constant_prediction: float,
) -> dict:
    long_returns, _ = _returns(
        dataset, configuration_index, indices, 1, stress=False
    )
    short_returns, _ = _returns(
        dataset, configuration_index, indices, -1, stress=False
    )
    actual = numpy.concatenate((long_returns, short_returns)).astype(
        numpy.float64
    ) * 10_000.0
    predicted = numpy.concatenate((long_predictions, short_predictions))
    squared_error = (predicted - actual) ** 2
    constant_squared_error = (constant_prediction - actual) ** 2
    absolute_error = numpy.abs(predicted - actual)
    constant_absolute_error = numpy.abs(constant_prediction - actual)
    if len(actual) > 1 and numpy.std(predicted) > 0 and numpy.std(actual) > 0:
        correlation = float(numpy.corrcoef(predicted, actual)[0, 1])
    else:
        correlation = 0.0
    return {
        "rows": int(len(actual)),
        "mse": float(numpy.mean(squared_error)),
        "constant_mse": float(numpy.mean(constant_squared_error)),
        "mse_skill": float(
            1.0
            - numpy.mean(squared_error)
            / max(float(numpy.mean(constant_squared_error)), 1e-12)
        ),
        "mae": float(numpy.mean(absolute_error)),
        "constant_mae": float(numpy.mean(constant_absolute_error)),
        "correlation": correlation,
        "mean_prediction_bps": float(numpy.mean(predicted)),
        "mean_actual_bps": float(numpy.mean(actual)),
    }


def _aggregate_regression(reports: list[dict]) -> dict:
    rows = sum(report["rows"] for report in reports)
    if not rows:
        return {
            "rows": 0,
            "mse": math.inf,
            "constant_mse": 0.0,
            "mse_skill": -math.inf,
            "mae": math.inf,
            "constant_mae": 0.0,
            "mean_prediction_bps": 0.0,
            "mean_actual_bps": 0.0,
        }

    def weighted(name: str) -> float:
        return float(
            sum(report[name] * report["rows"] for report in reports) / rows
        )

    mse = weighted("mse")
    constant_mse = weighted("constant_mse")
    return {
        "rows": rows,
        "mse": mse,
        "constant_mse": constant_mse,
        "mse_skill": 1.0 - mse / max(constant_mse, 1e-12),
        "mae": weighted("mae"),
        "constant_mae": weighted("constant_mae"),
        "mean_prediction_bps": weighted("mean_prediction_bps"),
        "mean_actual_bps": weighted("mean_actual_bps"),
    }


def _simulate_scores(
    dataset: ScalpingV3Dataset,
    configuration_index: int,
    indices: numpy.ndarray,
    long_scores: numpy.ndarray,
    short_scores: numpy.ndarray,
    threshold: float,
    *,
    stress: bool,
) -> dict[str, numpy.ndarray]:
    selected_rows: list[int] = []
    selected_directions: list[int] = []
    selected_returns: list[float] = []
    selected_exits: list[int] = []
    selected_scores: list[float] = []
    free_after = -1
    for position, row in enumerate(indices):
        timestamp = int(dataset.timestamps[row])
        if timestamp <= free_after:
            continue
        long_score = float(long_scores[position])
        short_score = float(short_scores[position])
        score = max(long_score, short_score)
        if (
            score < threshold
            or score <= 0.0
            or abs(long_score - short_score) < MINIMUM_DIRECTION_MARGIN_BPS
        ):
            continue
        direction = 1 if long_score > short_score else -1
        trade_return, exit_timestamp = _returns(
            dataset,
            configuration_index,
            numpy.asarray([row], dtype=numpy.int64),
            direction,
            stress=stress,
        )
        exit_value = int(exit_timestamp[0])
        if exit_value <= timestamp:
            raise ValueError("V3 trade exit is not after its decision")
        selected_rows.append(int(row))
        selected_directions.append(direction)
        selected_returns.append(float(trade_return[0]))
        selected_exits.append(exit_value)
        selected_scores.append(score)
        free_after = exit_value
    return {
        "rows": numpy.asarray(selected_rows, dtype=numpy.int64),
        "directions": numpy.asarray(selected_directions, dtype=numpy.int8),
        "instrument_returns": numpy.asarray(
            selected_returns, dtype=numpy.float64
        ),
        "exit_timestamps": numpy.asarray(selected_exits, dtype=numpy.int64),
        "predicted_return_bps": numpy.asarray(
            selected_scores, dtype=numpy.float64
        ),
    }


def _gate(
    primary: dict,
    stress: dict,
    regression: dict,
    *,
    minimum_trades: int,
    positive_folds: int | None = None,
    valid_folds: int | None = None,
) -> dict:
    checks = {
        "minimum_trades": primary["trades"] >= minimum_trades,
        "profit_factor": primary["profit_factor"] >= 1.20,
        "maximum_drawdown": primary["max_drawdown"] <= 0.05,
        "positive_operating_days": (
            primary["positive_operating_days_pct"] >= 55.0
        ),
        "long_non_negative": (
            primary["by_direction"]["long"]["total_return"] >= 0.0
        ),
        "short_non_negative": (
            primary["by_direction"]["short"]["total_return"] >= 0.0
        ),
        "mse_better_than_constant": (
            regression["mse"] < regression["constant_mse"]
        ),
        "stress_positive": stress["total_return"] > 0.0,
    }
    if positive_folds is not None:
        checks["positive_folds"] = positive_folds >= 4
    if valid_folds is not None:
        checks["all_folds_fitted"] = valid_folds == v2.WALK_FORWARD_FOLDS
    return {
        "passed": all(checks.values()),
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "checks": checks,
    }


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
        -report["expected_return_quantile"],
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
        raise ValueError("V3 dataset/protocol mismatch")
    if dataset_manifest.get("locked_test_materialized") is not False:
        raise ValueError("V3 pre-test artifact contains locked data")
    dataset = ScalpingV3Dataset.load(
        dataset_value,
        expected_sha256=dataset_manifest["artifact"]["sha256"],
    )
    states = {
        (configuration_index, quantile): {
            "primary": [],
            "stress": [],
            "regression": [],
            "folds": [],
            "thresholds": [],
            "fit_failures": [],
        }
        for configuration_index in range(len(v2.CONFIGURATIONS))
        for quantile in EXPECTED_RETURN_QUANTILES
    }
    for configuration_index, configuration in enumerate(v2.CONFIGURATIONS):
        folds = v2._development_folds(dataset)
        for fold_number, (train, test) in enumerate(folds, 1):
            progress(
                f"V3 {configuration['name']} fold {fold_number}/5 "
                f"train={len(train):,} test={len(test):,}"
            )
            try:
                model, calibration_rows, fit_report = _fit_with_calibration(
                    dataset, configuration_index, train
                )
            except ValueError as error:
                for quantile in EXPECTED_RETURN_QUANTILES:
                    states[(configuration_index, quantile)][
                        "fit_failures"
                    ].append({"fold": fold_number, "reason": str(error)})
                continue
            calibration_long, calibration_short = _predict_sides(
                dataset, calibration_rows, model
            )
            test_long, test_short = _predict_sides(dataset, test, model)
            regression = _regression_metrics(
                dataset,
                configuration_index,
                test,
                test_long,
                test_short,
                fit_report["fit_target_mean_bps"],
            )
            threshold_source = numpy.maximum(
                calibration_long, calibration_short
            )
            for quantile in EXPECTED_RETURN_QUANTILES:
                threshold = max(
                    0.0, float(numpy.quantile(threshold_source, quantile))
                )
                primary_trades = _simulate_scores(
                    dataset,
                    configuration_index,
                    test,
                    test_long,
                    test_short,
                    threshold,
                    stress=False,
                )
                stress_trades = _simulate_scores(
                    dataset,
                    configuration_index,
                    test,
                    test_long,
                    test_short,
                    threshold,
                    stress=True,
                )
                primary_metric = v1._trade_metrics(dataset, primary_trades)
                stress_metric = v1._trade_metrics(dataset, stress_trades)
                state = states[(configuration_index, quantile)]
                state["primary"].append(primary_trades)
                state["stress"].append(stress_trades)
                state["regression"].append(regression)
                state["thresholds"].append(threshold)
                state["folds"].append(
                    {
                        "fold": fold_number,
                        "fit": fit_report,
                        "threshold_bps": threshold,
                        "primary": primary_metric,
                        "stress": stress_metric,
                        "regression": regression,
                    }
                )
    candidates = []
    for (configuration_index, quantile), state in states.items():
        primary = v1._trade_metrics(
            dataset, v1._combine_trades(state["primary"])
        )
        stress = v1._trade_metrics(
            dataset, v1._combine_trades(state["stress"])
        )
        regression = _aggregate_regression(state["regression"])
        positive_folds = sum(
            fold["primary"]["total_return"] > 0
            for fold in state["folds"]
        )
        gate = _gate(
            primary,
            stress,
            regression,
            minimum_trades=500,
            positive_folds=positive_folds,
            valid_folds=len(state["folds"]),
        )
        candidates.append(
            {
                "configuration": v2.CONFIGURATIONS[configuration_index][
                    "name"
                ],
                "configuration_index": configuration_index,
                "expected_return_quantile": quantile,
                "thresholds_bps": (
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
                "regression": regression,
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
        f"V3 development choice {chosen['configuration']} "
        f"q={chosen['expected_return_quantile']} "
        f"gate={chosen['gate']['passed']}"
    )
    configuration_index = chosen["configuration_index"]
    development = numpy.flatnonzero(
        dataset.timestamps < v1._iso_timestamp(DEVELOPMENT_END)
    )
    final_model, calibration_rows, final_fit = _fit_with_calibration(
        dataset, configuration_index, development
    )
    calibration_long, calibration_short = _predict_sides(
        dataset, calibration_rows, final_model
    )
    threshold = max(
        0.0,
        float(
            numpy.quantile(
                numpy.maximum(calibration_long, calibration_short),
                chosen["expected_return_quantile"],
            )
        ),
    )
    confirmation = numpy.flatnonzero(
        (dataset.timestamps >= v1._iso_timestamp(DEVELOPMENT_END))
        & (
            dataset.timestamps
            < v1._iso_timestamp(DIAGNOSTIC_CONFIRMATION_END)
        )
    )
    confirmation_long, confirmation_short = _predict_sides(
        dataset, confirmation, final_model
    )
    confirmation_primary_trades = _simulate_scores(
        dataset,
        configuration_index,
        confirmation,
        confirmation_long,
        confirmation_short,
        threshold,
        stress=False,
    )
    confirmation_stress_trades = _simulate_scores(
        dataset,
        configuration_index,
        confirmation,
        confirmation_long,
        confirmation_short,
        threshold,
        stress=True,
    )
    confirmation_primary = v1._trade_metrics(
        dataset, confirmation_primary_trades
    )
    confirmation_stress = v1._trade_metrics(
        dataset, confirmation_stress_trades
    )
    confirmation_regression = _regression_metrics(
        dataset,
        configuration_index,
        confirmation,
        confirmation_long,
        confirmation_short,
        final_fit["fit_target_mean_bps"],
    )
    confirmation_gate = _gate(
        confirmation_primary,
        confirmation_stress,
        confirmation_regression,
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
    reloaded = NumpySquaredBoostingRegressor.load(model_path)
    reproduced = _predict_sides(dataset, confirmation, reloaded)
    reproduction_difference = max(
        float(numpy.max(numpy.abs(reproduced[0] - confirmation_long))),
        float(numpy.max(numpy.abs(reproduced[1] - confirmation_short))),
    )
    if reproduction_difference > 1e-12:
        raise RuntimeError("V3 persisted model does not reproduce predictions")
    trades_path = experiment / "confirmation_trades.npz"
    with trades_path.open("wb") as stream:
        numpy.savez_compressed(
            stream,
            rows=confirmation_primary_trades["rows"],
            timestamps=dataset.timestamps[
                confirmation_primary_trades["rows"]
            ],
            directions=confirmation_primary_trades["directions"],
            instrument_returns=confirmation_primary_trades[
                "instrument_returns"
            ],
            exit_timestamps=confirmation_primary_trades["exit_timestamps"],
            predicted_return_bps=confirmation_primary_trades[
                "predicted_return_bps"
            ],
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
            "features": len(FEATURE_NAMES),
            "sha256": dataset_manifest["artifact"]["sha256"],
            "locked_test_materialized": False,
        },
        "development": {
            "chosen_candidate": {
                key: chosen[key]
                for key in (
                    "configuration",
                    "configuration_index",
                    "expected_return_quantile",
                    "thresholds_bps",
                    "primary",
                    "stress",
                    "regression",
                    "positive_folds",
                    "valid_folds",
                    "fit_failures",
                    "gate",
                )
            },
            "all_candidates": candidates,
        },
        "frozen_model": {
            "configuration": v2.CONFIGURATIONS[configuration_index],
            "model": model_artifact,
            "fit": final_fit,
            "expected_return_threshold_bps": threshold,
            "minimum_direction_margin_bps": MINIMUM_DIRECTION_MARGIN_BPS,
            "maximum_reproduction_difference": reproduction_difference,
        },
        "diagnostic_confirmation": {
            "diagnostic_reuse": True,
            "start": DEVELOPMENT_END,
            "end": DIAGNOSTIC_CONFIRMATION_END,
            "primary": confirmation_primary,
            "stress": confirmation_stress,
            "regression": confirmation_regression,
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
        "report": {
            "path": str(report_path),
            "bytes": report_path.stat().st_size,
            "sha256": v1._sha256(report_path),
        },
        "model": model_artifact,
        "confirmation_trades": {
            "path": str(trades_path),
            "bytes": trades_path.stat().st_size,
            "sha256": v1._sha256(trades_path),
        },
        "development_gate_passed": chosen["gate"]["passed"],
        "confirmation_gate_passed": confirmation_gate["passed"],
        "locked_test_authorized": locked_authorized,
        "orders_authorized": False,
        "paper_orders_authorized": False,
    }
    manifest_path = experiment / "manifest.json"
    v1._atomic_json(manifest_path, manifest)
    return {
        "experiment_id": experiment_id,
        "experiment_directory": str(experiment),
        "report": str(report_path),
        "development_gate_passed": chosen["gate"]["passed"],
        "confirmation_gate_passed": confirmation_gate["passed"],
        "locked_test_authorized": locked_authorized,
    }


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Result-free event-level queue-flow research V3."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    protocol_parser = commands.add_parser("write-protocol")
    protocol_parser.add_argument("--output", required=True)
    build_parser = commands.add_parser("build-pretest-dataset")
    build_parser.add_argument("--database", required=True)
    build_parser.add_argument("--freeze-manifest", required=True)
    build_parser.add_argument("--source-cache", required=True)
    build_parser.add_argument("--v2-dataset", required=True)
    build_parser.add_argument("--v2-manifest", required=True)
    build_parser.add_argument("--protocol", required=True)
    build_parser.add_argument("--output", required=True)
    evaluate_parser = commands.add_parser("evaluate-pretest")
    evaluate_parser.add_argument("--dataset", required=True)
    evaluate_parser.add_argument("--dataset-manifest", required=True)
    evaluate_parser.add_argument("--protocol", required=True)
    evaluate_parser.add_argument("--output-root", required=True)
    arguments = parser.parse_args()
    if arguments.command == "write-protocol":
        result = write_or_verify_protocol(arguments.output)
    elif arguments.command == "build-pretest-dataset":
        result = build_pretest_dataset(
            database_value=arguments.database,
            freeze_manifest_value=arguments.freeze_manifest,
            source_cache_value=arguments.source_cache,
            v2_dataset_value=arguments.v2_dataset,
            v2_manifest_value=arguments.v2_manifest,
            protocol_value=arguments.protocol,
            output_value=arguments.output,
            progress=lambda message: print(message, flush=True),
        )
    else:
        result = evaluate_pretest(
            dataset_value=arguments.dataset,
            dataset_manifest_value=arguments.dataset_manifest,
            protocol_value=arguments.protocol,
            output_root_value=arguments.output_root,
            progress=lambda message: print(message, flush=True),
        )
    print(json.dumps(v1._json_safe(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    _main()
