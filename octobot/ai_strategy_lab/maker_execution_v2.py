"""Learned two-stage BTC futures passive-execution protocol V2.

V1 showed that a fixed imbalance gate rarely fills and loses through fallback
timing.  V2 uses the same conservative queue and cost assumptions but learns,
from development rows only, (1) fill probability and (2) saving conditional on
no fill.  The resulting expected-saving policy is evaluated in expanding
purged folds.  Confirmation is queried only after every development gate
passes; the 20--26 August lock is unreachable from this module.

This is offline public-data research.  There is no exchange client or order
path in this file.
"""

from __future__ import annotations

import argparse
import bisect
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import typing

import numpy

from octobot.ai_strategy_lab import maker_execution_v1 as v1
from octobot.ai_strategy_lab import model as model_module


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_learned_passive_execution_v2"
PREREGISTRATION_DATE = "2026-08-28"
PARENT_PROTOCOL_SHA256 = (
    "079e58fa244f8266bfe99a22f1f87880b9e3aa86cce7faace88887319c45e646"
)
PARENT_REPORT_SHA256 = (
    "b5f8e00f32788316fa921c9a4f19671d30267f8a17749914e29e86013a1923d1"
)
PARENT_DATASET_SHA256 = (
    "14ed68e27c4f6d61e50c4ea5a30ea7ee6bc4ae1f7cb3ff5b6f18bac3ed24c015"
)

SOURCE_START = v1.SOURCE_START
DEVELOPMENT_END = v1.DEVELOPMENT_END
DIAGNOSTIC_CONFIRMATION_END = v1.DIAGNOSTIC_CONFIRMATION_END
LOCKED_TEST_END = v1.LOCKED_TEST_END

FOLD_WINDOWS = (
    ("2026-07-29T00:00:00+00:00", "2026-08-01T00:00:00+00:00"),
    ("2026-08-01T00:00:00+00:00", "2026-08-04T00:00:00+00:00"),
    ("2026-08-04T00:00:00+00:00", "2026-08-07T00:00:00+00:00"),
    ("2026-08-07T00:00:00+00:00", "2026-08-10T00:00:00+00:00"),
    ("2026-08-10T00:00:00+00:00", "2026-08-13T00:00:00+00:00"),
)
PURGE_SECONDS = 180
FEATURE_LOOKBACK_SECONDS = 30
EXPECTED_SAVING_THRESHOLD_BPS = 0.25
MINIMUM_PREDICTED_FILL_PROBABILITY = 0.10
RIDGE_ALPHA = 25.0
TARGET_CLIP_BPS = 50.0
FEATURE_WINSOR_LOWER = 0.01
FEATURE_WINSOR_UPPER = 0.99
BOOTSTRAP_SAMPLES = 20_000
RANDOM_SEED = 20260828

LOGISTIC_CONFIG = model_module.LogisticConfig(
    epochs=64,
    batch_size=512,
    learning_rate=0.01,
    l2=0.01,
    seed=RANDOM_SEED,
)

FEATURE_NAMES = (
    "side_code",
    "side_adjusted_imbalance_5",
    "side_adjusted_microprice_premium_bps",
    "spread_bps",
    "log1p_queue_ahead_contracts",
    "order_to_queue_ratio",
    "maker_saving_if_fill_bps",
    "side_adjusted_mid_return_5s_bps",
    "side_adjusted_mid_return_30s_bps",
    "mid_range_30s_bps",
    "side_adjusted_trade_imbalance_5s",
    "side_adjusted_trade_imbalance_30s",
    "log1p_trade_volume_30s",
    "log1p_book_updates_5s",
    "arrival_latency_ms",
    "utc_hour_sine",
    "utc_hour_cosine",
)
MAKER_SAVING_FEATURE_INDEX = FEATURE_NAMES.index("maker_saving_if_fill_bps")

RICH_BOOK_COLUMNS = (
    *v1.BOOK_COLUMNS,
    "microprice",
    "spread_bps",
    "latency_ms",
)


def _json_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_npz(path: pathlib.Path, arrays: dict[str, numpy.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        numpy.savez_compressed(stream, **arrays)
    temporary.replace(path)


def frozen_protocol() -> dict:
    """Return the result-free learned-execution V2 protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_learned_execution_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent_v1": {
            "protocol_sha256": PARENT_PROTOCOL_SHA256,
            "report_sha256": PARENT_REPORT_SHA256,
            "dataset_sha256": PARENT_DATASET_SHA256,
            "aggregate_result_inspected": True,
            "unfiltered_row_outcomes_inspected_before_v2_freeze": False,
            "known_lesson": (
                "fixed imbalance gating filled 6.98% and lost 0.133 bps per "
                "scheduled side through fallback timing"
            ),
        },
        "hypothesis": {
            "name": "two_stage_fill_and_fallback_execution",
            "statement": (
                "causal Level-5 state can identify passive attempts whose "
                "fill-probability-weighted maker saving plus expected fallback "
                "saving is positive after conservative queue and fees"
            ),
            "directional_trading_signal": False,
            "primary_candidate_count": 1,
            "post_result_inversion": False,
        },
        "source": {
            "freeze_manifest_file_sha256": v1.FREEZE_MANIFEST_FILE_SHA256,
            "freeze_database_sha256": v1.FREEZE_DATABASE_SHA256,
            "freeze_database_bytes": v1.FREEZE_DATABASE_BYTES,
            "sqlite_open_mode": "read-only immutable",
            "locked_rows_queryable_by_this_evaluator": False,
        },
        "execution": {
            "inherited_primary": v1.frozen_protocol()["primary_policy"],
            "inherited_stress": v1.frozen_protocol()["stress_policy"],
            "target_notional_usdt": v1.TARGET_NOTIONAL_USDT,
            "contract_multiplier_btc": v1.CONTRACT_MULTIPLIER_BTC,
            "unconditional_development_labels": True,
            "cancellations_reduce_queue": False,
            "partial_fill_credit": False,
        },
        "features": {
            "names": list(FEATURE_NAMES),
            "count": len(FEATURE_NAMES),
            "availability": "at or before virtual order arrival only",
            "lookback_seconds": FEATURE_LOOKBACK_SECONDS,
            "selection": False,
            "winsor_quantiles_training_only": [
                FEATURE_WINSOR_LOWER,
                FEATURE_WINSOR_UPPER,
            ],
            "scaling": "training-only median and IQR; zero IQR becomes one",
        },
        "model": {
            "stage_one": {
                "target": "full maker fill before timeout",
                "type": "numpy logistic regression",
                "config": dataclasses.asdict(LOGISTIC_CONFIG),
            },
            "stage_two": {
                "target": "realized saving on non-filled taker fallbacks",
                "type": "ridge regression",
                "alpha": RIDGE_ALPHA,
                "target_clip_bps": [-TARGET_CLIP_BPS, TARGET_CLIP_BPS],
            },
            "expected_saving_identity": (
                "P(fill) * deterministic maker saving + "
                "(1-P(fill)) * predicted fallback saving"
            ),
            "attempt_gate": {
                "minimum_predicted_fill_probability": (
                    MINIMUM_PREDICTED_FILL_PROBABILITY
                ),
                "minimum_expected_saving_bps_strict": (
                    EXPECTED_SAVING_THRESHOLD_BPS
                ),
            },
            "hyperparameter_search": False,
            "threshold_search": False,
            "random_seed": RANDOM_SEED,
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "expanding_purged_folds": [
                {
                    "train_start": SOURCE_START,
                    "train_end_exclusive": start,
                    "test_start": start,
                    "test_end_exclusive": end,
                }
                for start, end in FOLD_WINDOWS
            ],
            "purge_seconds": PURGE_SECONDS,
            "diagnostic_confirmation": [
                DEVELOPMENT_END,
                DIAGNOSTIC_CONFIRMATION_END,
            ],
            "confirmation_read_only_after_complete_development_pass": True,
            "locked_final_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_test_materialized": False,
        },
        "development_gate": {
            "minimum_selected_attempts": 150,
            "minimum_selected_attempts_per_side": 50,
            "minimum_source_coverage": 0.99,
            "minimum_selected_fill_rate": 0.10,
            "minimum_fill_auc": 0.55,
            "fill_brier_better_than_fold_constant": True,
            "selected_mean_saving_bps_strictly_positive": True,
            "buy_selected_mean_saving_bps_strictly_positive": True,
            "sell_selected_mean_saving_bps_strictly_positive": True,
            "minimum_positive_folds": 4,
            "minimum_positive_operating_days_pct": 55.0,
            "daily_bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_lower_mean_saving_bps_strictly_positive": True,
            "stress_selected_mean_saving_bps_strictly_positive": True,
        },
        "diagnostic_confirmation_gate": {
            "minimum_selected_attempts": 50,
            "minimum_selected_attempts_per_side": 15,
            "minimum_source_coverage": 0.99,
            "minimum_selected_fill_rate": 0.10,
            "minimum_fill_auc": 0.52,
            "selected_mean_saving_bps_strictly_positive": True,
            "buy_selected_mean_saving_bps_strictly_positive": True,
            "sell_selected_mean_saving_bps_strictly_positive": True,
            "minimum_positive_operating_days_pct": 50.0,
            "stress_selected_mean_saving_bps_strictly_positive": True,
        },
        "advancement_consequence": (
            "even a full confirmation pass permits only a separate offline "
            "locked protocol; it cannot authorize shadow, paper or real orders"
        ),
        "results": None,
    }


def write_or_verify_protocol(path_value: typing.Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted learned-execution V2 protocol differs")
        return persisted
    _atomic_json(path, payload)
    return payload


@dataclasses.dataclass(frozen=True)
class RichWindow:
    base: v1.Window
    microprices: numpy.ndarray
    spreads_bps: numpy.ndarray
    latencies_ms: numpy.ndarray

    def validate(self) -> None:
        rows = len(self.base.books)
        if any(len(value) != rows for value in (
            self.microprices, self.spreads_bps, self.latencies_ms
        )):
            raise ValueError("rich execution window is misaligned")
        if rows and (
            not numpy.all(numpy.isfinite(self.microprices))
            or not numpy.all(numpy.isfinite(self.spreads_bps))
            or not numpy.all(numpy.isfinite(self.latencies_ms))
        ):
            raise ValueError("rich execution window is non-finite")


@dataclasses.dataclass
class ExecutionModel:
    lower: numpy.ndarray
    upper: numpy.ndarray
    median: numpy.ndarray
    iqr: numpy.ndarray
    logistic: model_module.NumpyLogisticModel
    ridge_intercept: float
    ridge_weights: numpy.ndarray
    training_fill_rate: float

    def transform(self, features: numpy.ndarray) -> numpy.ndarray:
        clipped = numpy.clip(features, self.lower, self.upper)
        return (clipped - self.median) / self.iqr

    def predict(self, features: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
        transformed = self.transform(features)
        fill_probability = self.logistic.predict_proba(transformed)
        fallback = transformed @ self.ridge_weights + self.ridge_intercept
        maker = features[:, MAKER_SAVING_FEATURE_INDEX]
        expected = fill_probability * maker + (1.0 - fill_probability) * fallback
        return fill_probability, fallback, expected


def _load_window(connection: sqlite3.Connection, decision_ns: int) -> RichWindow:
    maximum_horizon_ns = (
        max(v1.PRIMARY_LATENCY_MS, v1.STRESS_LATENCY_MS) * 1_000_000
        + max(v1.PRIMARY_TIMEOUT_SECONDS, v1.STRESS_TIMEOUT_SECONDS)
        * 1_000_000_000
        + max(v1.PRIMARY_FALLBACK_LATENCY_MS, v1.STRESS_FALLBACK_LATENCY_MS)
        * 1_000_000
        + max(v1.POST_FILL_HORIZONS_SECONDS) * 1_000_000_000
        + v1.BOOK_STALENESS_NS
    )
    lower_ns = decision_ns - FEATURE_LOOKBACK_SECONDS * 1_000_000_000 - v1.BOOK_STALENESS_NS
    upper_ns = decision_ns + maximum_horizon_ns
    columns = ", ".join(RICH_BOOK_COLUMNS)
    book_rows = connection.execute(
        f"""
        SELECT {columns}
        FROM book_events
        WHERE received_ts_ns BETWEEN ? AND ?
        ORDER BY received_ts_ns
        """,
        (lower_ns, upper_ns),
    ).fetchall()
    trade_rows = connection.execute(
        """
        SELECT received_ts_ns, side, price, size
        FROM trade_events
        WHERE received_ts_ns BETWEEN ? AND ?
        ORDER BY received_ts_ns
        """,
        (lower_ns, upper_ns),
    ).fetchall()
    books = tuple(v1._book_from_row(row) for row in book_rows)
    window = RichWindow(
        base=v1.Window(
            decision_ns=decision_ns,
            books=books,
            trades=tuple(
                v1.Trade(
                    timestamp_ns=int(row["received_ts_ns"]),
                    side=str(row["side"]),
                    price=float(row["price"]),
                    size=float(row["size"]),
                )
                for row in trade_rows
            ),
        ),
        microprices=numpy.asarray(
            [float(row["microprice"]) for row in book_rows],
            dtype=numpy.float64,
        ),
        spreads_bps=numpy.asarray(
            [float(row["spread_bps"]) for row in book_rows],
            dtype=numpy.float64,
        ),
        latencies_ms=numpy.asarray(
            [float(row["latency_ms"]) for row in book_rows],
            dtype=numpy.float64,
        ),
    )
    window.validate()
    return window


def _book_index_after(window: RichWindow, target_ns: int) -> int | None:
    timestamps = window.base.book_timestamps
    index = bisect.bisect_left(timestamps, target_ns)
    if index >= len(timestamps) or timestamps[index] - target_ns > v1.BOOK_STALENESS_NS:
        return None
    return index


def _book_index_before(window: RichWindow, target_ns: int) -> int | None:
    timestamps = window.base.book_timestamps
    index = bisect.bisect_right(timestamps, target_ns) - 1
    if index < 0 or target_ns - timestamps[index] > v1.BOOK_STALENESS_NS:
        return None
    return index


def _flow(window: RichWindow, arrival_ns: int, seconds: int, side_sign: float) -> tuple[float, float]:
    lower_ns = arrival_ns - seconds * 1_000_000_000
    buy = 0.0
    sell = 0.0
    for trade in window.base.trades:
        if trade.timestamp_ns < lower_ns:
            continue
        if trade.timestamp_ns > arrival_ns:
            break
        if trade.side == "buy":
            buy += trade.size
        else:
            sell += trade.size
    total = buy + sell
    imbalance = (buy - sell) / total if total > 0 else 0.0
    return side_sign * imbalance, total


def _features(window: RichWindow, side: str) -> numpy.ndarray | None:
    side_sign = 1.0 if side == "buy" else -1.0
    decision_book = v1._book_before(window.base, window.base.decision_ns)
    arrival_target = window.base.decision_ns + v1.PRIMARY_LATENCY_MS * 1_000_000
    arrival_index = _book_index_after(window, arrival_target)
    if decision_book is None or arrival_index is None:
        return None
    arrival = window.base.books[arrival_index]
    quantity = v1._quantity_contracts(arrival)
    baseline_price = v1._vwap(arrival, side, quantity)
    if baseline_price is None:
        return None
    maker_price, visible_size = (
        arrival.bids[0] if side == "buy" else arrival.asks[0]
    )
    queue = visible_size * v1.PRIMARY_QUEUE_MULTIPLIER
    if queue <= 0:
        return None
    baseline_cost = v1._shortfall_bps(
        side, baseline_price, decision_book.mid, v1.TAKER_FEE_BPS
    )
    maker_cost = v1._shortfall_bps(
        side, maker_price, decision_book.mid, v1.MAKER_FEE_BPS
    )
    past5_index = _book_index_before(
        window, arrival.timestamp_ns - 5 * 1_000_000_000
    )
    past30_index = _book_index_before(
        window, arrival.timestamp_ns - 30 * 1_000_000_000
    )
    if past5_index is None or past30_index is None:
        return None
    past5 = window.base.books[past5_index]
    past30 = window.base.books[past30_index]
    lower30 = arrival.timestamp_ns - 30 * 1_000_000_000
    lower5 = arrival.timestamp_ns - 5 * 1_000_000_000
    recent_mids = [
        book.mid
        for book in window.base.books
        if lower30 <= book.timestamp_ns <= arrival.timestamp_ns
    ]
    updates5 = sum(
        lower5 <= book.timestamp_ns <= arrival.timestamp_ns
        for book in window.base.books
    )
    if not recent_mids or updates5 == 0:
        return None
    flow5, _ = _flow(window, arrival.timestamp_ns, 5, side_sign)
    flow30, volume30 = _flow(window, arrival.timestamp_ns, 30, side_sign)
    moment = datetime.datetime.fromtimestamp(
        window.base.decision_ns / 1_000_000_000,
        tz=datetime.timezone.utc,
    )
    hour = moment.hour + moment.minute / 60.0
    angle = 2.0 * math.pi * hour / 24.0
    values = numpy.asarray(
        [
            side_sign,
            side_sign * arrival.imbalance,
            side_sign
            * (window.microprices[arrival_index] / arrival.mid - 1.0)
            * 10_000.0,
            window.spreads_bps[arrival_index],
            math.log1p(queue),
            quantity / queue,
            baseline_cost - maker_cost,
            side_sign * (arrival.mid / past5.mid - 1.0) * 10_000.0,
            side_sign * (arrival.mid / past30.mid - 1.0) * 10_000.0,
            (max(recent_mids) / min(recent_mids) - 1.0) * 10_000.0,
            flow5,
            flow30,
            math.log1p(volume30),
            math.log1p(updates5),
            window.latencies_ms[arrival_index],
            math.sin(angle),
            math.cos(angle),
        ],
        dtype=numpy.float64,
    )
    if values.shape != (len(FEATURE_NAMES),) or not numpy.all(numpy.isfinite(values)):
        return None
    return values


def _unconditional_outcome(window: RichWindow, side: str, policy: v1.Policy) -> dict:
    decision_book = v1._book_before(window.base, window.base.decision_ns)
    arrival_target = window.base.decision_ns + policy.arrival_latency_ms * 1_000_000
    arrival = v1._book_after(window.base, arrival_target)
    base = {
        "completed": False,
        "saving_bps": None,
        "filled": False,
        "baseline_cost_bps": None,
        "policy_cost_bps": None,
        "adverse_5s_bps": None,
        "adverse_60s_bps": None,
        "exclusion": None,
    }
    if decision_book is None:
        return {**base, "exclusion": "missing_decision_book"}
    if arrival is None:
        return {**base, "exclusion": "missing_arrival_book"}
    quantity = v1._quantity_contracts(arrival)
    benchmark_price = v1._vwap(arrival, side, quantity)
    if benchmark_price is None:
        return {**base, "exclusion": "insufficient_arrival_depth"}
    benchmark_cost = v1._shortfall_bps(
        side, benchmark_price, decision_book.mid, policy.taker_fee_bps
    )
    limit_price, visible_size = (
        arrival.bids[0] if side == "buy" else arrival.asks[0]
    )
    fill_ns = v1._fill_time(
        window.base,
        side=side,
        arrival_book=arrival,
        limit_price=limit_price,
        queue_ahead=visible_size * policy.queue_multiplier,
        own_quantity=quantity,
        timeout_seconds=policy.timeout_seconds,
    )
    if fill_ns is not None:
        policy_cost = v1._shortfall_bps(
            side, limit_price, decision_book.mid, policy.maker_fee_bps
        )
        return {
            **base,
            "completed": True,
            "saving_bps": benchmark_cost - policy_cost,
            "filled": True,
            "baseline_cost_bps": benchmark_cost,
            "policy_cost_bps": policy_cost,
            "adverse_5s_bps": v1._adverse_markout_bps(
                window.base, side, fill_ns, limit_price, 5
            ),
            "adverse_60s_bps": v1._adverse_markout_bps(
                window.base, side, fill_ns, limit_price, 60
            ),
        }
    fallback_target = (
        arrival.timestamp_ns
        + policy.timeout_seconds * 1_000_000_000
        + policy.fallback_latency_ms * 1_000_000
    )
    fallback = v1._book_after(window.base, fallback_target)
    if fallback is None:
        return {**base, "exclusion": "missing_fallback_book"}
    fallback_price = v1._vwap(fallback, side, quantity)
    if fallback_price is None:
        return {**base, "exclusion": "insufficient_fallback_depth"}
    policy_cost = v1._shortfall_bps(
        side, fallback_price, decision_book.mid, policy.taker_fee_bps
    )
    return {
        **base,
        "completed": True,
        "saving_bps": benchmark_cost - policy_cost,
        "filled": False,
        "baseline_cost_bps": benchmark_cost,
        "policy_cost_bps": policy_cost,
    }


def build_rows(
    connection: sqlite3.Connection,
    start: str,
    end: str,
) -> tuple[list[dict], dict]:
    start_ns = v1._epoch_ns(start)
    end_ns = v1._epoch_ns(end)
    if end_ns > v1._epoch_ns(DIAGNOSTIC_CONFIRMATION_END):
        raise ValueError("learned-execution evaluator cannot query locked rows")
    rows = []
    exclusions: dict[str, int] = {}
    decisions = v1._decision_timestamps(start_ns, end_ns)
    for decision_ns in decisions:
        window = _load_window(connection, decision_ns)
        for side in ("buy", "sell"):
            features = _features(window, side)
            primary = _unconditional_outcome(window, side, v1.PRIMARY_POLICY)
            stress = _unconditional_outcome(window, side, v1.STRESS_POLICY)
            reason = None
            if features is None:
                reason = "missing_causal_features"
            elif not primary["completed"]:
                reason = f"primary_{primary['exclusion']}"
            elif not stress["completed"]:
                reason = f"stress_{stress['exclusion']}"
            if reason is not None:
                exclusions[reason] = exclusions.get(reason, 0) + 1
                continue
            rows.append(
                {
                    "timestamp_ns": decision_ns,
                    "side": side,
                    "features": features,
                    "primary": primary,
                    "stress": stress,
                }
            )
    expected = len(decisions) * 2
    return rows, {
        "expected_rows": expected,
        "usable_rows": len(rows),
        "coverage": len(rows) / expected if expected else 0.0,
        "exclusions": exclusions,
    }


def _fit_model(features: numpy.ndarray, filled: numpy.ndarray, savings: numpy.ndarray) -> ExecutionModel:
    if features.ndim != 2 or features.shape[1] != len(FEATURE_NAMES):
        raise ValueError("learned-execution feature schema differs")
    if len(features) != len(filled) or len(features) != len(savings):
        raise ValueError("learned-execution training arrays are misaligned")
    if len(features) < 200 or len(numpy.unique(filled)) < 2:
        raise ValueError("learned-execution training sample is insufficient")
    lower = numpy.quantile(features, FEATURE_WINSOR_LOWER, axis=0)
    upper = numpy.quantile(features, FEATURE_WINSOR_UPPER, axis=0)
    clipped = numpy.clip(features, lower, upper)
    median = numpy.median(clipped, axis=0)
    q25 = numpy.quantile(clipped, 0.25, axis=0)
    q75 = numpy.quantile(clipped, 0.75, axis=0)
    iqr = q75 - q25
    iqr[iqr < 1e-9] = 1.0
    transformed = (clipped - median) / iqr
    logistic = model_module.NumpyLogisticModel.fit(
        transformed,
        filled.astype(numpy.uint8),
        FEATURE_NAMES,
        LOGISTIC_CONFIG,
    )
    fallback = ~filled
    if numpy.sum(fallback) < 100:
        raise ValueError("learned-execution fallback sample is insufficient")
    design = transformed[fallback]
    target = numpy.clip(savings[fallback], -TARGET_CLIP_BPS, TARGET_CLIP_BPS)
    augmented = numpy.column_stack((numpy.ones(len(design)), design))
    penalty = numpy.eye(augmented.shape[1], dtype=numpy.float64) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    coefficients = numpy.linalg.solve(
        augmented.T @ augmented + penalty,
        augmented.T @ target,
    )
    return ExecutionModel(
        lower=lower,
        upper=upper,
        median=median,
        iqr=iqr,
        logistic=logistic,
        ridge_intercept=float(coefficients[0]),
        ridge_weights=coefficients[1:],
        training_fill_rate=float(numpy.mean(filled)),
    )


def _row_arrays(rows: list[dict]) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    return (
        numpy.vstack([row["features"] for row in rows]),
        numpy.asarray([row["primary"]["filled"] for row in rows], dtype=numpy.bool_),
        numpy.asarray([row["primary"]["saving_bps"] for row in rows], dtype=numpy.float64),
        numpy.asarray([row["stress"]["saving_bps"] for row in rows], dtype=numpy.float64),
    )


def _selection(probability: numpy.ndarray, expected: numpy.ndarray) -> numpy.ndarray:
    return (probability >= MINIMUM_PREDICTED_FILL_PROBABILITY) & (
        expected > EXPECTED_SAVING_THRESHOLD_BPS
    )


def _roc_auc(labels: numpy.ndarray, scores: numpy.ndarray) -> float | None:
    positives = int(numpy.sum(labels))
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    order = numpy.argsort(scores, kind="mergesort")
    ranks = numpy.empty(len(scores), dtype=numpy.float64)
    start = 0
    while start < len(scores):
        end = start + 1
        while end < len(scores) and scores[order[end]] == scores[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    positive_rank_sum = float(numpy.sum(ranks[labels]))
    return (positive_rank_sum - positives * (positives + 1) / 2) / (
        positives * negatives
    )


def _bootstrap_lower(values_by_day: numpy.ndarray) -> float | None:
    if len(values_by_day) < 2:
        return None
    generator = numpy.random.default_rng(RANDOM_SEED)
    samples = numpy.empty(BOOTSTRAP_SAMPLES, dtype=numpy.float64)
    for index in range(BOOTSTRAP_SAMPLES):
        chosen = generator.integers(0, len(values_by_day), len(values_by_day))
        samples[index] = numpy.mean(values_by_day[chosen])
    return float(numpy.quantile(samples, 0.10))


def _economic_metrics(
    rows: list[dict],
    selected: numpy.ndarray,
    *,
    outcome: str,
    fold_ids: numpy.ndarray | None = None,
) -> dict:
    savings = numpy.asarray(
        [row[outcome]["saving_bps"] for row in rows], dtype=numpy.float64
    )
    filled = numpy.asarray(
        [row[outcome]["filled"] for row in rows], dtype=numpy.bool_
    )
    policy_savings = numpy.where(selected, savings, 0.0)
    sides = numpy.asarray([row["side"] for row in rows])
    selected_savings = savings[selected]
    day_map: dict[int, list[float]] = {}
    for row, saving in zip(rows, policy_savings):
        day = int(row["timestamp_ns"]) // (86_400 * 1_000_000_000)
        day_map.setdefault(day, []).append(float(saving))
    daily = numpy.asarray(
        [numpy.mean(day_map[day]) for day in sorted(day_map)], dtype=numpy.float64
    )
    by_side = {}
    for side in ("buy", "sell"):
        mask = selected & (sides == side)
        values = savings[mask]
        by_side[side] = {
            "selected_attempts": int(numpy.sum(mask)),
            "maker_fills": int(numpy.sum(filled[mask])),
            "fill_rate": float(numpy.mean(filled[mask])) if numpy.any(mask) else 0.0,
            "mean_selected_saving_bps": float(numpy.mean(values)) if len(values) else None,
            "total_saving_bps": float(numpy.sum(values)) if len(values) else 0.0,
        }
    fold_reports = []
    if fold_ids is not None:
        for fold in sorted(set(int(value) for value in fold_ids)):
            mask = selected & (fold_ids == fold)
            values = savings[mask]
            fold_reports.append(
                {
                    "fold": fold,
                    "selected_attempts": int(numpy.sum(mask)),
                    "mean_selected_saving_bps": (
                        float(numpy.mean(values)) if len(values) else None
                    ),
                    "positive": bool(len(values) and numpy.mean(values) > 0),
                }
            )
    return {
        "rows": len(rows),
        "selected_attempts": int(numpy.sum(selected)),
        "selected_pct": 100.0 * float(numpy.mean(selected)) if len(rows) else 0.0,
        "maker_fills": int(numpy.sum(filled[selected])),
        "selected_fill_rate": (
            float(numpy.mean(filled[selected])) if numpy.any(selected) else 0.0
        ),
        "mean_selected_saving_bps": (
            float(numpy.mean(selected_savings)) if len(selected_savings) else None
        ),
        "total_saving_bps": float(numpy.sum(selected_savings)),
        "mean_saving_per_scheduled_side_bps": (
            float(numpy.mean(policy_savings)) if len(policy_savings) else None
        ),
        "positive_operating_days_pct": (
            100.0 * float(numpy.mean(daily > 0)) if len(daily) else 0.0
        ),
        "daily_bootstrap_lower_policy_saving_bps_90pct": _bootstrap_lower(daily),
        "by_side": by_side,
        "folds": fold_reports,
        "positive_folds": sum(value["positive"] for value in fold_reports),
    }


def _calibration(labels: numpy.ndarray, probabilities: numpy.ndarray, constants: numpy.ndarray) -> dict:
    auc = _roc_auc(labels, probabilities)
    return {
        "rows": len(labels),
        "base_rate": float(numpy.mean(labels)),
        "auc": auc,
        "brier": float(numpy.mean((probabilities - labels) ** 2)),
        "constant_brier": float(numpy.mean((constants - labels) ** 2)),
    }


def evaluate_development(rows: list[dict], source: dict) -> tuple[dict, dict, list[ExecutionModel]]:
    all_features, all_filled, all_savings, _ = _row_arrays(rows)
    timestamps = numpy.asarray([row["timestamp_ns"] for row in rows], dtype=numpy.int64)
    oos_rows = []
    oos_probabilities = []
    oos_expected = []
    oos_constants = []
    oos_folds = []
    models = []
    fold_details = []
    for fold, (test_start, test_end) in enumerate(FOLD_WINDOWS, start=1):
        start_ns = v1._epoch_ns(test_start)
        end_ns = v1._epoch_ns(test_end)
        train = timestamps < start_ns - PURGE_SECONDS * 1_000_000_000
        test = (timestamps >= start_ns) & (timestamps < end_ns)
        model = _fit_model(
            all_features[train], all_filled[train], all_savings[train]
        )
        probability, fallback, expected = model.predict(all_features[test])
        indices = numpy.flatnonzero(test)
        oos_rows.extend(rows[index] for index in indices)
        oos_probabilities.extend(probability.tolist())
        oos_expected.extend(expected.tolist())
        oos_constants.extend([model.training_fill_rate] * len(indices))
        oos_folds.extend([fold] * len(indices))
        models.append(model)
        fold_details.append(
            {
                "fold": fold,
                "train_rows": int(numpy.sum(train)),
                "test_rows": int(numpy.sum(test)),
                "training_fill_rate": model.training_fill_rate,
                "mean_predicted_fill_probability": float(numpy.mean(probability)),
                "mean_predicted_fallback_saving_bps": float(numpy.mean(fallback)),
                "mean_expected_saving_bps": float(numpy.mean(expected)),
            }
        )
    probability = numpy.asarray(oos_probabilities, dtype=numpy.float64)
    expected = numpy.asarray(oos_expected, dtype=numpy.float64)
    constants = numpy.asarray(oos_constants, dtype=numpy.float64)
    fold_ids = numpy.asarray(oos_folds, dtype=numpy.int16)
    labels = numpy.asarray(
        [row["primary"]["filled"] for row in oos_rows], dtype=numpy.bool_
    )
    selected = _selection(probability, expected)
    primary = _economic_metrics(
        oos_rows, selected, outcome="primary", fold_ids=fold_ids
    )
    stress = _economic_metrics(
        oos_rows, selected, outcome="stress", fold_ids=fold_ids
    )
    report = {
        "source": source,
        "oos_rows": len(oos_rows),
        "fold_details": fold_details,
        "fill_calibration": _calibration(labels, probability, constants),
        "primary": primary,
        "stress": stress,
    }
    predictions = {
        "timestamps_ns": numpy.asarray(
            [row["timestamp_ns"] for row in oos_rows], dtype=numpy.int64
        ),
        "side": numpy.asarray(
            [1 if row["side"] == "buy" else -1 for row in oos_rows],
            dtype=numpy.int8,
        ),
        "fill_probability": probability,
        "expected_saving_bps": expected,
        "selected": selected,
        "fold": fold_ids,
        "realized_primary_saving_bps": numpy.asarray(
            [row["primary"]["saving_bps"] for row in oos_rows],
            dtype=numpy.float64,
        ),
        "realized_stress_saving_bps": numpy.asarray(
            [row["stress"]["saving_bps"] for row in oos_rows],
            dtype=numpy.float64,
        ),
        "filled": labels,
    }
    return report, predictions, models


def _development_gate(report: dict, protocol: dict) -> dict:
    gate = protocol["development_gate"]
    primary = report["primary"]
    stress = report["stress"]
    calibration = report["fill_calibration"]
    checks = {
        "minimum_selected_attempts": primary["selected_attempts"] >= gate["minimum_selected_attempts"],
        "minimum_selected_attempts_per_side": all(
            primary["by_side"][side]["selected_attempts"]
            >= gate["minimum_selected_attempts_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_source_coverage": report["source"]["coverage"] >= gate["minimum_source_coverage"],
        "minimum_selected_fill_rate": primary["selected_fill_rate"] >= gate["minimum_selected_fill_rate"],
        "minimum_fill_auc": calibration["auc"] is not None and calibration["auc"] >= gate["minimum_fill_auc"],
        "fill_brier_better_than_fold_constant": calibration["brier"] < calibration["constant_brier"],
        "selected_mean_saving_bps_strictly_positive": primary["mean_selected_saving_bps"] is not None and primary["mean_selected_saving_bps"] > 0,
        "buy_selected_mean_saving_bps_strictly_positive": primary["by_side"]["buy"]["mean_selected_saving_bps"] is not None and primary["by_side"]["buy"]["mean_selected_saving_bps"] > 0,
        "sell_selected_mean_saving_bps_strictly_positive": primary["by_side"]["sell"]["mean_selected_saving_bps"] is not None and primary["by_side"]["sell"]["mean_selected_saving_bps"] > 0,
        "minimum_positive_folds": primary["positive_folds"] >= gate["minimum_positive_folds"],
        "minimum_positive_operating_days_pct": primary["positive_operating_days_pct"] >= gate["minimum_positive_operating_days_pct"],
        "bootstrap_lower_mean_saving_bps_strictly_positive": primary["daily_bootstrap_lower_policy_saving_bps_90pct"] is not None and primary["daily_bootstrap_lower_policy_saving_bps_90pct"] > 0,
        "stress_selected_mean_saving_bps_strictly_positive": stress["mean_selected_saving_bps"] is not None and stress["mean_selected_saving_bps"] > 0,
    }
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _confirmation_gate(report: dict, protocol: dict) -> dict:
    gate = protocol["diagnostic_confirmation_gate"]
    primary = report["primary"]
    stress = report["stress"]
    calibration = report["fill_calibration"]
    checks = {
        "minimum_selected_attempts": primary["selected_attempts"] >= gate["minimum_selected_attempts"],
        "minimum_selected_attempts_per_side": all(
            primary["by_side"][side]["selected_attempts"] >= gate["minimum_selected_attempts_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_source_coverage": report["source"]["coverage"] >= gate["minimum_source_coverage"],
        "minimum_selected_fill_rate": primary["selected_fill_rate"] >= gate["minimum_selected_fill_rate"],
        "minimum_fill_auc": calibration["auc"] is not None and calibration["auc"] >= gate["minimum_fill_auc"],
        "selected_mean_saving_bps_strictly_positive": primary["mean_selected_saving_bps"] is not None and primary["mean_selected_saving_bps"] > 0,
        "buy_selected_mean_saving_bps_strictly_positive": primary["by_side"]["buy"]["mean_selected_saving_bps"] is not None and primary["by_side"]["buy"]["mean_selected_saving_bps"] > 0,
        "sell_selected_mean_saving_bps_strictly_positive": primary["by_side"]["sell"]["mean_selected_saving_bps"] is not None and primary["by_side"]["sell"]["mean_selected_saving_bps"] > 0,
        "minimum_positive_operating_days_pct": primary["positive_operating_days_pct"] >= gate["minimum_positive_operating_days_pct"],
        "stress_selected_mean_saving_bps_strictly_positive": stress["mean_selected_saving_bps"] is not None and stress["mean_selected_saving_bps"] > 0,
    }
    return {"checks": checks, "passed_checks": sum(checks.values()), "total_checks": len(checks), "passed": all(checks.values())}


def _save_model(path: pathlib.Path, model: ExecutionModel) -> dict:
    arrays = {
        "schema_version": numpy.asarray([SCHEMA_VERSION], dtype=numpy.int64),
        "feature_names": numpy.asarray(FEATURE_NAMES),
        "lower": model.lower,
        "upper": model.upper,
        "median": model.median,
        "iqr": model.iqr,
        "logistic_mean": model.logistic.mean,
        "logistic_scale": model.logistic.scale,
        "logistic_weights": model.logistic.weights,
        "logistic_intercept": numpy.asarray([model.logistic.intercept]),
        "ridge_intercept": numpy.asarray([model.ridge_intercept]),
        "ridge_weights": model.ridge_weights,
        "training_fill_rate": numpy.asarray([model.training_fill_rate]),
    }
    _atomic_npz(path, arrays)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _load_model(path: pathlib.Path) -> ExecutionModel:
    with numpy.load(path, allow_pickle=False) as values:
        if int(values["schema_version"][0]) != SCHEMA_VERSION:
            raise ValueError("learned-execution model schema differs")
        if tuple(str(value) for value in values["feature_names"]) != FEATURE_NAMES:
            raise ValueError("learned-execution model feature names differ")
        logistic = model_module.NumpyLogisticModel(
            feature_names=FEATURE_NAMES,
            mean=values["logistic_mean"],
            scale=values["logistic_scale"],
            weights=values["logistic_weights"],
            intercept=float(values["logistic_intercept"][0]),
            config=LOGISTIC_CONFIG,
        )
        return ExecutionModel(
            lower=values["lower"],
            upper=values["upper"],
            median=values["median"],
            iqr=values["iqr"],
            logistic=logistic,
            ridge_intercept=float(values["ridge_intercept"][0]),
            ridge_weights=values["ridge_weights"],
            training_fill_rate=float(values["training_fill_rate"][0]),
        )


def _confirmation_report(rows: list[dict], source: dict, model: ExecutionModel) -> tuple[dict, dict]:
    features, filled, _, _ = _row_arrays(rows)
    probability, _, expected = model.predict(features)
    selected = _selection(probability, expected)
    constants = numpy.full(len(rows), model.training_fill_rate, dtype=numpy.float64)
    report = {
        "source": source,
        "fill_calibration": _calibration(filled, probability, constants),
        "primary": _economic_metrics(rows, selected, outcome="primary"),
        "stress": _economic_metrics(rows, selected, outcome="stress"),
    }
    predictions = {
        "timestamps_ns": numpy.asarray([row["timestamp_ns"] for row in rows], dtype=numpy.int64),
        "side": numpy.asarray([1 if row["side"] == "buy" else -1 for row in rows], dtype=numpy.int8),
        "fill_probability": probability,
        "expected_saving_bps": expected,
        "selected": selected,
        "realized_primary_saving_bps": numpy.asarray([row["primary"]["saving_bps"] for row in rows]),
        "realized_stress_saving_bps": numpy.asarray([row["stress"]["saving_bps"] for row in rows]),
        "filled": filled,
    }
    return report, predictions


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (numpy.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (numpy.integer,)):
        return int(value)
    if isinstance(value, (numpy.bool_,)):
        return bool(value)
    return value


def evaluate_prelock(protocol_value, database_value, freeze_manifest_value, output_root_value):
    protocol_path = pathlib.Path(protocol_value).resolve()
    database_path = pathlib.Path(database_value).resolve()
    freeze_manifest_path = pathlib.Path(freeze_manifest_value).resolve()
    output_root = pathlib.Path(output_root_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    v1._verify_freeze(database_path, freeze_manifest_path)
    connection = v1._open_database(database_path)
    try:
        development_rows, development_source = build_rows(
            connection, SOURCE_START, DEVELOPMENT_END
        )
        development, predictions, fold_models = evaluate_development(
            development_rows, development_source
        )
        development_gate = _development_gate(development, protocol)
        final_model = None
        confirmation = None
        confirmation_predictions = {}
        confirmation_gate = {
            "not_evaluated": not development_gate["passed"],
            "reason": "development_gate_failed" if not development_gate["passed"] else None,
            "passed": False,
        }
        if development_gate["passed"]:
            features, filled, savings, _ = _row_arrays(development_rows)
            final_model = _fit_model(features, filled, savings)
            confirmation_rows, confirmation_source = build_rows(
                connection, DEVELOPMENT_END, DIAGNOSTIC_CONFIRMATION_END
            )
            confirmation, confirmation_predictions = _confirmation_report(
                confirmation_rows, confirmation_source, final_model
            )
            confirmation_gate = _confirmation_gate(confirmation, protocol)
    finally:
        connection.close()

    locked_authorized = bool(development_gate["passed"] and confirmation_gate["passed"])
    report = _json_safe(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "research_only": True,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "source": {
                "database": str(database_path),
                "database_sha256_from_freeze": v1.FREEZE_DATABASE_SHA256,
                "freeze_manifest_file_sha256": _sha256(freeze_manifest_path),
            },
            "development": {**development, "gate": development_gate},
            "diagnostic_confirmation": {
                "materialized": confirmation is not None,
                "report": confirmation,
                "gate": confirmation_gate,
            },
            "locked_test": {
                "interval": [DIAGNOSTIC_CONFIRMATION_END, LOCKED_TEST_END],
                "authorized_to_open_separately": locked_authorized,
                "materialized": False,
                "rows_queried": False,
                "reason": "separate_locked_protocol_required" if locked_authorized else "prelock_gate_failed",
            },
            "verdict": "PRELOCK_PASS_REQUIRES_SEPARATE_LOCKED_EVALUATION" if locked_authorized else "REJECTED_BEFORE_LOCK",
        }
    )
    identity = (
        f"learned-passive-execution-v2-{protocol['protocol_sha256'][:12]}-"
        f"{v1.FREEZE_MANIFEST_FILE_SHA256[:12]}"
    )
    experiment = output_root / identity
    if experiment.exists():
        report_path = experiment / "report.json"
        manifest_path = experiment / "manifest.json"
        if not report_path.is_file() or not manifest_path.is_file():
            raise FileExistsError("incomplete learned-execution experiment exists")
        persisted = json.loads(report_path.read_text(encoding="utf-8"))
        if persisted != report:
            raise ValueError("persisted learned-execution report is not reproducible")
        return {"experiment": str(experiment), "report": persisted, "manifest": json.loads(manifest_path.read_text(encoding="utf-8"))}
    experiment.mkdir(parents=True, exist_ok=False)
    prediction_path = experiment / "development-predictions.npz"
    _atomic_npz(prediction_path, predictions)
    model_artifacts = []
    for index, fold_model in enumerate(fold_models, start=1):
        path = experiment / f"fold-{index}-model.npz"
        artifact = _save_model(path, fold_model)
        loaded = _load_model(path)
        train_features = numpy.vstack([row["features"] for row in development_rows])
        original = fold_model.predict(train_features)[2]
        reloaded = loaded.predict(train_features)[2]
        if not numpy.allclose(original, reloaded, rtol=0, atol=1e-12):
            raise ValueError("learned-execution reloaded fold model differs")
        model_artifacts.append(artifact)
    final_model_artifact = None
    if final_model is not None:
        path = experiment / "development-final-model.npz"
        final_model_artifact = _save_model(path, final_model)
    confirmation_path = None
    if confirmation_predictions:
        confirmation_path = experiment / "confirmation-predictions.npz"
        _atomic_npz(confirmation_path, confirmation_predictions)
    report_path = experiment / "report.json"
    _atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "identity": identity,
        "source_database_sha256": v1.FREEZE_DATABASE_SHA256,
        "development_predictions": {"file": prediction_path.name, "bytes": prediction_path.stat().st_size, "sha256": _sha256(prediction_path)},
        "fold_models": model_artifacts,
        "final_model": final_model_artifact,
        "confirmation_predictions": (
            {"file": confirmation_path.name, "bytes": confirmation_path.stat().st_size, "sha256": _sha256(confirmation_path)}
            if confirmation_path is not None else None
        ),
        "report": {"file": report_path.name, "bytes": report_path.stat().st_size, "sha256": _sha256(report_path)},
        "locked_test_materialized": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = _json_hash(manifest)
    manifest_path = experiment / "manifest.json"
    _atomic_json(manifest_path, manifest)
    return {"experiment": str(experiment), "report": report, "manifest": manifest}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    evaluate = subparsers.add_parser("evaluate-prelock")
    evaluate.add_argument("--protocol", required=True)
    evaluate.add_argument("--database", required=True)
    evaluate.add_argument("--freeze-manifest", required=True)
    evaluate.add_argument("--output-root", required=True)
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        result = write_or_verify_protocol(arguments.output)
    else:
        result = evaluate_prelock(
            arguments.protocol,
            arguments.database,
            arguments.freeze_manifest,
            arguments.output_root,
        )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
