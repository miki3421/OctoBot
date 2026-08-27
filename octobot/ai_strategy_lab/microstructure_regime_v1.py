"""BTC Level-5 microstructure value study beyond taker scalping.

This module is deliberately research-only.  It compares a price/volume
baseline, a book/flow model and their combination at closed 15-minute
decisions.  The primary task is fixed before labels are built: estimate the
probability that a directional 1% target is reached before a 1% stop within
four hours.  One- and eight-hour paths are diagnostics only.

The historical source ends before the previously sealed 20--26 August block.
Consequently, the report can at most justify a new forward, orderless study;
it cannot authorize a signal, paper order or real order.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import os
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import indicators
from octobot.ai_strategy_lab import model as model_module
from octobot.ai_strategy_lab import scalping_strategy_search as scalping_v1
from octobot.ai_strategy_lab import scalping_strategy_search_v3 as scalping_v3


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_microstructure_regime_multihorizon_v1"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_V3_PROTOCOL_SHA256 = (
    "192c3dd1b040479d9f9f21cdc7ce9e985bb2fd4fdf2bfdb9dc88753c44ea3924"
)
PARENT_V3_DATASET_SHA256 = (
    "6e7cbd40f26e6f3f8a65629f8e4c1d76de4f04bef5035e812f42f28f525403fe"
)
SOURCE_SNAPSHOT_SHA256 = (
    "96020bbf554b87e6433748fa3586c4d9d07c819cddeeab2e6e90f24475f64bce"
)
PRETEST_END = "2026-08-20T00:00:00+00:00"
LOCKED_BLOCK_END = "2026-08-26T14:10:58+00:00"
OFFICIAL_FORWARD_START = "2026-08-28T00:00:00+00:00"
OFFICIAL_FORWARD_MINIMUM_DAYS = 30

DECISION_STRIDE_SECONDS = 15 * 60
PRICE_WINDOWS_SECONDS = (15 * 60, 60 * 60, 4 * 60 * 60)
INDICATOR_TIME_FRAME_SECONDS = 15 * 60
INDICATOR_WARMUP_CANDLES = 54
PRICE_LOOKBACK_SECONDS = max(
    max(PRICE_WINDOWS_SECONDS),
    INDICATOR_WARMUP_CANDLES * INDICATOR_TIME_FRAME_SECONDS,
)
HORIZONS_SECONDS = (60 * 60, 4 * 60 * 60, 8 * 60 * 60)
PRIMARY_HORIZON_SECONDS = 4 * 60 * 60
TARGET_BPS = 100.0
STOP_BPS = 100.0
ENTRY_LATENCY_MS = 500
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0
ROUND_TRIP_COST_BPS = 2.0 * (
    FEE_BPS_PER_FILL + SLIPPAGE_BPS_PER_FILL
)
STRESS_COST_MULTIPLIER = 2.0
MAXIMUM_MISSING_FRACTION = 0.01
MAXIMUM_GAP_SECONDS = 60

WALK_FORWARD_FOLDS = 4
INITIAL_TRAIN_FRACTION = 0.40
EMBARGO_SECONDS = max(HORIZONS_SECONDS)
PROBABILITY_THRESHOLD = 0.60
MINIMUM_DIRECTION_MARGIN = 0.05
POSITION_FRACTION = 0.10
MINIMUM_TRADES = 25
MINIMUM_TRADES_PER_DIRECTION = 3
MINIMUM_POSITIVE_FOLDS = 3
MINIMUM_BOOK_IMPROVEMENT_FOLDS = 3
MINIMUM_RELATIVE_BRIER_IMPROVEMENT = 0.02
MINIMUM_AUC = 0.55

LOGISTIC_CONFIG = model_module.LogisticConfig(
    epochs=60,
    batch_size=2048,
    learning_rate=0.015,
    l2=0.01,
    seed=20260827,
)

COMMON_FEATURE_NAMES = ("utc_hour_sine", "utc_hour_cosine")
PRICE_CONTEXT_FEATURE_NAMES = tuple(
    f"p{window // 60}m_{name}"
    for window in PRICE_WINDOWS_SECONDS
    for name in (
        "directional_return_bps",
        "realized_volatility_bps",
        "range_bps",
        "directional_close_location",
        "log_trade_size",
        "trade_event_intensity",
    )
)
INDICATOR_FEATURE_NAMES = tuple(
    f"i15m_{name}"
    for name in (
        "return_1",
        "return_4",
        "atr_pct",
        "adx",
        "ema_spread_pct",
        "ema_slope_pct",
        "bb_position",
        "bb_width_pct",
        "rsi_centered",
        "macd_hist_pct",
        "return_volatility",
        "volume_zscore",
    )
)
PRICE_FEATURE_NAMES = PRICE_CONTEXT_FEATURE_NAMES + INDICATOR_FEATURE_NAMES
PRICE_DIRECTIONAL_MASK = numpy.asarray(
    [
        "directional_" in name
        or name
        in {
            "i15m_return_1",
            "i15m_return_4",
            "i15m_ema_spread_pct",
            "i15m_ema_slope_pct",
            "i15m_bb_position",
            "i15m_rsi_centered",
            "i15m_macd_hist_pct",
        }
        for name in PRICE_FEATURE_NAMES
    ],
    dtype=bool,
)


def _is_book_feature(name: str) -> bool:
    excluded = (
        "directional_mid_return_bps",
        "realized_mid_volatility_bps",
        "high_low_range_bps",
        "directional_one_minute_context_bps",
        "directional_five_minute_context_bps",
        "one_to_five_minute_regime_ratio",
        "utc_hour_",
    )
    return not any(value in name for value in excluded)


BOOK_PARENT_INDICES = numpy.asarray(
    [
        index
        for index, name in enumerate(scalping_v3.FEATURE_NAMES)
        if _is_book_feature(name)
    ],
    dtype=numpy.int64,
)
BOOK_FEATURE_NAMES = tuple(
    scalping_v3.FEATURE_NAMES[index] for index in BOOK_PARENT_INDICES
)
BOOK_DIRECTIONAL_MASK = scalping_v3.DIRECTIONAL_FEATURE_MASK[
    BOOK_PARENT_INDICES
].copy()


def _json_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _iso_timestamp(value: str) -> int:
    return int(datetime.datetime.fromisoformat(value).timestamp())


def frozen_protocol() -> dict:
    """Return the immutable, result-free research protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_diagnostic_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "parent": {
            "protocol_version": scalping_v3.PROTOCOL_VERSION,
            "protocol_sha256": PARENT_V3_PROTOCOL_SHA256,
            "dataset_sha256": PARENT_V3_DATASET_SHA256,
            "source_snapshot_sha256": SOURCE_SNAPSHOT_SHA256,
            "lesson_used": (
                "the single-venue taker family did not cover costs; this "
                "study tests whether the same book adds incremental value "
                "to a slower price/volume baseline"
            ),
            "parent_thresholds_retuned": False,
        },
        "hypothesis": {
            "name": "book_adds_multihorizon_regime_information",
            "statement": (
                "causal Level-5 order-flow and queue dynamics improve the "
                "calibrated four-hour barrier probability and net economic "
                "selection relative to price and volume alone"
            ),
            "direction_symmetric": True,
            "primary_candidate": "combined_price_and_book",
            "attribution_baselines": ["price_only", "book_only"],
        },
        "decisions": {
            "frequency_seconds": DECISION_STRIDE_SECONDS,
            "availability": "closed 15-minute boundary only",
            "price_context_windows_seconds": list(PRICE_WINDOWS_SECONDS),
            "price_lookback_seconds": PRICE_LOOKBACK_SECONDS,
            "price_features": list(PRICE_FEATURE_NAMES),
            "technical_indicators": {
                "time_frame_seconds": INDICATOR_TIME_FRAME_SECONDS,
                "warmup_candles": INDICATOR_WARMUP_CANDLES,
                "features": list(INDICATOR_FEATURE_NAMES),
                "parameters": {
                    "atr": 14,
                    "adx": 14,
                    "rsi": 14,
                    "ema_fast_slow": [20, 50],
                    "ema_slope_lag": 3,
                    "macd": [12, 26, 9],
                    "bollinger": [20, 2.0],
                    "return_volatility": 20,
                    "volume_zscore": 20,
                },
                "parameter_search": False,
            },
            "book_features": list(BOOK_FEATURE_NAMES),
            "common_features": list(COMMON_FEATURE_NAMES),
            "maximum_missing_fraction": MAXIMUM_MISSING_FRACTION,
            "maximum_gap_seconds": MAXIMUM_GAP_SECONDS,
        },
        "primary_label": {
            "horizon_seconds": PRIMARY_HORIZON_SECONDS,
            "target_bps": TARGET_BPS,
            "stop_bps": STOP_BPS,
            "positive": "target reached strictly before stop",
            "same_observation_tie": "stop wins",
            "timeout": "negative class with executable timeout return",
        },
        "diagnostics_only": {
            "horizons_seconds": list(HORIZONS_SECONDS),
            "outputs": [
                "barrier label",
                "net executable return",
                "maximum favorable excursion",
                "maximum adverse excursion",
                "time to exit",
            ],
            "cannot_select_primary_horizon": True,
        },
        "execution": {
            "entry_latency_ms": ENTRY_LATENCY_MS,
            "entry": "first executable quote at or after 500ms",
            "long": "buy ask and exit bid",
            "short": "sell bid and exit ask",
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "maker_fill_assumptions": False,
            "one_trade_at_a_time": True,
            "position_fraction": POSITION_FRACTION,
        },
        "model": {
            "type": "numpy_logistic_regression",
            "configuration": dataclasses.asdict(LOGISTIC_CONFIG),
            "feature_groups": ["price_only", "book_only", "combined"],
            "model_search": False,
            "hyperparameter_search": False,
            "probability_threshold": PROBABILITY_THRESHOLD,
            "minimum_direction_margin": MINIMUM_DIRECTION_MARGIN,
            "threshold_tuning": False,
        },
        "validation": {
            "historical_discovery": {
                "end_exclusive": PRETEST_END,
                "status": "diagnostic_reuse_not_pristine_validation",
                "walk_forward_folds": WALK_FORWARD_FOLDS,
                "initial_train_fraction": INITIAL_TRAIN_FRACTION,
                "purge_embargo_seconds": EMBARGO_SECONDS,
            },
            "locked_historical_block": {
                "start_inclusive": PRETEST_END,
                "end_exclusive": LOCKED_BLOCK_END,
                "materialized": False,
                "policy": (
                    "remain sealed; this diagnostic cannot authorize opening"
                ),
            },
            "official_forward": {
                "start_inclusive": OFFICIAL_FORWARD_START,
                "minimum_calendar_days": OFFICIAL_FORWARD_MINIMUM_DAYS,
                "minimum_matured_signals": 50,
                "new_result_free_protocol_required": True,
            },
        },
        "diagnostic_advancement_gate": {
            "all_walk_forward_folds_fitted": True,
            "minimum_combined_auc": MINIMUM_AUC,
            "combined_brier_better_than_constant": True,
            "minimum_relative_brier_improvement_vs_price": (
                MINIMUM_RELATIVE_BRIER_IMPROVEMENT
            ),
            "minimum_book_improvement_folds": (
                MINIMUM_BOOK_IMPROVEMENT_FOLDS
            ),
            "minimum_trades": MINIMUM_TRADES,
            "minimum_trades_per_direction": (
                MINIMUM_TRADES_PER_DIRECTION
            ),
            "minimum_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": MINIMUM_POSITIVE_FOLDS,
            "long_and_short_contribution_non_negative": True,
            "double_cost_total_return_non_negative": True,
        },
        "advancement_consequence": (
            "a full diagnostic pass permits only preregistration and "
            "implementation of an orderless forward observer; it does not "
            "authorize opening the historical lock, shadow weights, paper "
            "orders or real orders"
        ),
        "multiple_testing_disclosure": (
            "one primary horizon, one barrier, one model, one probability "
            "threshold and one direction margin; other horizons and path "
            "statistics are descriptive only"
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
            raise ValueError("persisted microstructure regime protocol differs")
        return persisted
    _atomic_json(path, payload)
    return payload


@dataclasses.dataclass
class RegimeDataset:
    """Compact causal decisions and fixed multi-horizon outcomes."""

    timestamps: numpy.ndarray
    common_features: numpy.ndarray
    price_features: numpy.ndarray
    book_features: numpy.ndarray
    long_label: numpy.ndarray
    short_label: numpy.ndarray
    long_return: numpy.ndarray
    short_return: numpy.ndarray
    long_stress_return: numpy.ndarray
    short_stress_return: numpy.ndarray
    long_exit: numpy.ndarray
    short_exit: numpy.ndarray
    long_mfe_bps: numpy.ndarray
    short_mfe_bps: numpy.ndarray
    long_mae_bps: numpy.ndarray
    short_mae_bps: numpy.ndarray

    def validate(self) -> None:
        rows = len(self.timestamps)
        horizons = len(HORIZONS_SECONDS)
        if not rows or numpy.any(numpy.diff(self.timestamps) <= 0):
            raise ValueError("regime timestamps are empty or unordered")
        if int(self.timestamps[-1]) >= _iso_timestamp(PRETEST_END):
            raise ValueError("regime dataset enters the locked block")
        expected = {
            "common_features": (rows, len(COMMON_FEATURE_NAMES)),
            "price_features": (rows, len(PRICE_FEATURE_NAMES)),
            "book_features": (rows, len(BOOK_FEATURE_NAMES)),
        }
        for name, shape in expected.items():
            values = getattr(self, name)
            if values.shape != shape or not numpy.all(numpy.isfinite(values)):
                raise ValueError(f"regime {name} is invalid")
        for field in dataclasses.fields(self):
            if field.name in {"timestamps", *expected}:
                continue
            values = getattr(self, field.name)
            if values.shape != (rows, horizons):
                raise ValueError(f"regime {field.name} is misaligned")
            if "label" in field.name:
                if not set(numpy.unique(values)).issubset({0, 1}):
                    raise ValueError("regime labels are not binary")
            elif not numpy.all(numpy.isfinite(values)):
                raise ValueError(f"regime {field.name} is non-finite")

    def directional_features(
        self,
        indices: numpy.ndarray,
        direction: int,
        group: str,
    ) -> tuple[numpy.ndarray, tuple[str, ...]]:
        if direction not in {-1, 1}:
            raise ValueError("direction must be +1 or -1")
        common = self.common_features[indices]
        parts = [common]
        names = list(COMMON_FEATURE_NAMES)
        if group in {"price_only", "combined"}:
            price = self.price_features[indices].copy()
            if direction == -1:
                price[:, PRICE_DIRECTIONAL_MASK] *= -1.0
            parts.append(price)
            names.extend(PRICE_FEATURE_NAMES)
        if group in {"book_only", "combined"}:
            book = self.book_features[indices].copy()
            if direction == -1:
                book[:, BOOK_DIRECTIONAL_MASK] *= -1.0
            parts.append(book)
            names.extend(BOOK_FEATURE_NAMES)
        if group not in {"price_only", "book_only", "combined"}:
            raise ValueError("unknown feature group")
        return numpy.column_stack(parts).astype(numpy.float32), tuple(names)

    def save(
        self,
        path_value: typing.Union[str, pathlib.Path],
        protocol_sha256: str,
    ) -> dict:
        self.validate()
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            numpy.savez_compressed(
                stream,
                schema_version=numpy.asarray([SCHEMA_VERSION]),
                protocol_version=numpy.asarray([PROTOCOL_VERSION]),
                protocol_sha256=numpy.asarray([protocol_sha256]),
                source_snapshot_sha256=numpy.asarray(
                    [SOURCE_SNAPSHOT_SHA256]
                ),
                parent_v3_dataset_sha256=numpy.asarray(
                    [PARENT_V3_DATASET_SHA256]
                ),
                horizons_seconds=numpy.asarray(HORIZONS_SECONDS),
                common_feature_names=numpy.asarray(COMMON_FEATURE_NAMES),
                price_feature_names=numpy.asarray(PRICE_FEATURE_NAMES),
                price_directional_mask=PRICE_DIRECTIONAL_MASK,
                book_feature_names=numpy.asarray(BOOK_FEATURE_NAMES),
                book_directional_mask=BOOK_DIRECTIONAL_MASK,
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
            "sha256": _sha256(path),
        }

    @classmethod
    def load(
        cls,
        path_value: typing.Union[str, pathlib.Path],
        *,
        expected_sha256: str | None = None,
        expected_protocol_sha256: str | None = None,
    ) -> "RegimeDataset":
        path = pathlib.Path(path_value).resolve()
        if expected_sha256 and _sha256(path) != expected_sha256:
            raise ValueError("regime dataset hash differs")
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported regime dataset schema")
            if str(values["protocol_version"][0]) != PROTOCOL_VERSION:
                raise ValueError("regime dataset protocol differs")
            if (
                expected_protocol_sha256
                and str(values["protocol_sha256"][0])
                != expected_protocol_sha256
            ):
                raise ValueError("regime dataset protocol hash differs")
            if (
                str(values["source_snapshot_sha256"][0])
                != SOURCE_SNAPSHOT_SHA256
            ):
                raise ValueError("regime source snapshot differs")
            if (
                str(values["parent_v3_dataset_sha256"][0])
                != PARENT_V3_DATASET_SHA256
            ):
                raise ValueError("regime parent dataset differs")
            if not numpy.array_equal(
                values["horizons_seconds"], HORIZONS_SECONDS
            ):
                raise ValueError("regime horizons differ")
            schemas = (
                ("common_feature_names", COMMON_FEATURE_NAMES),
                ("price_feature_names", PRICE_FEATURE_NAMES),
                ("book_feature_names", BOOK_FEATURE_NAMES),
            )
            for key, expected in schemas:
                if tuple(str(item) for item in values[key]) != expected:
                    raise ValueError(f"regime {key} differs")
            if not numpy.array_equal(
                values["price_directional_mask"],
                PRICE_DIRECTIONAL_MASK,
            ):
                raise ValueError("regime price directional mask differs")
            if not numpy.array_equal(
                values["book_directional_mask"],
                BOOK_DIRECTIONAL_MASK,
            ):
                raise ValueError("regime book directional mask differs")
            dataset = cls(
                **{
                    field.name: values[field.name].copy()
                    for field in dataclasses.fields(cls)
                }
            )
        dataset.validate()
        return dataset


def _interval_sum(
    cumulative: numpy.ndarray,
    starts: numpy.ndarray,
    lengths: int,
) -> numpy.ndarray:
    return cumulative[starts + lengths] - cumulative[starts]


def _long_gap_mask(present: numpy.ndarray) -> numpy.ndarray:
    bad = numpy.zeros(len(present), dtype=numpy.int8)
    missing = ~present
    changes = numpy.diff(
        numpy.concatenate(
            (
                numpy.asarray([False]),
                missing,
                numpy.asarray([False]),
            )
        ).astype(numpy.int8)
    )
    starts = numpy.flatnonzero(changes == 1)
    ends = numpy.flatnonzero(changes == -1)
    for start, end in zip(starts, ends):
        if end - start > MAXIMUM_GAP_SECONDS:
            bad[start:end] = 1
    return bad


def _eligible_rows(
    source: scalping_v1.DenseSource,
    parent: scalping_v3.ScalpingV3Dataset,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    parent_rows = numpy.flatnonzero(
        parent.timestamps % DECISION_STRIDE_SECONDS == 0
    )
    candidate_indices = (
        parent.timestamps[parent_rows] - source.start_second - 1
    ).astype(numpy.int64)
    maximum_lookback = PRICE_LOOKBACK_SECONDS
    maximum_horizon = max(HORIZONS_SECONDS)
    starts = candidate_indices - maximum_lookback + 1
    future_starts = candidate_indices + 1
    structurally_valid = (
        (starts >= 0)
        & (future_starts + maximum_horizon < len(source))
        & (
            parent.timestamps[parent_rows] + maximum_horizon
            < _iso_timestamp(PRETEST_END)
        )
    )
    parent_rows = parent_rows[structurally_valid]
    candidate_indices = candidate_indices[structurally_valid]
    starts = starts[structurally_valid]
    future_starts = future_starts[structurally_valid]

    values = source.values
    present = (
        (values["book_event_count"] > 0)
        & numpy.isfinite(values["last_mid"])
    )
    present_cumulative = numpy.concatenate(
        (numpy.asarray([0]), numpy.cumsum(present, dtype=numpy.int64))
    )
    bad_gap = _long_gap_mask(present)
    gap_cumulative = numpy.concatenate(
        (numpy.asarray([0]), numpy.cumsum(bad_gap, dtype=numpy.int64))
    )
    lookback_present = _interval_sum(
        present_cumulative, starts, maximum_lookback
    )
    future_length = maximum_horizon + 1
    future_present = _interval_sum(
        present_cumulative, future_starts, future_length
    )
    coverage_valid = (
        lookback_present
        >= maximum_lookback * (1.0 - MAXIMUM_MISSING_FRACTION)
    ) & (
        future_present
        >= future_length * (1.0 - MAXIMUM_MISSING_FRACTION)
    )
    gap_valid = (
        _interval_sum(gap_cumulative, starts, maximum_lookback) == 0
    ) & (
        _interval_sum(gap_cumulative, future_starts, future_length) == 0
    )
    deadline = future_starts + maximum_horizon
    quote_valid = (
        numpy.isfinite(values["entry_bid_500"][future_starts])
        & numpy.isfinite(values["entry_ask_500"][future_starts])
        & (values["entry_ns_500"][future_starts] > 0)
        & numpy.isfinite(values["prefix_last_bid_500"][deadline])
        & numpy.isfinite(values["prefix_last_ask_500"][deadline])
    )
    for window in PRICE_WINDOWS_SECONDS:
        quote_valid &= numpy.isfinite(
            values["last_mid"][candidate_indices - window + 1]
        )
    for horizon in HORIZONS_SECONDS:
        horizon_deadline = future_starts + horizon
        for name in (
            "prefix_last_bid_500",
            "prefix_last_ask_500",
            "prefix_high_bid_500",
            "prefix_low_bid_500",
            "prefix_high_ask_500",
            "prefix_low_ask_500",
        ):
            quote_valid &= numpy.isfinite(values[name][horizon_deadline])
    valid = coverage_valid & gap_valid & quote_valid
    return parent_rows[valid], candidate_indices[valid]


def _window_sum(
    cumulative: numpy.ndarray,
    ends: numpy.ndarray,
    window: int,
) -> numpy.ndarray:
    starts = ends - window + 1
    return cumulative[ends + 1] - cumulative[starts]


def _build_price_features(
    source: scalping_v1.DenseSource,
    candidate_indices: numpy.ndarray,
) -> numpy.ndarray:
    values = source.values
    mid = values["last_mid"].astype(numpy.float64)
    returns = numpy.zeros(len(source), dtype=numpy.float64)
    valid = (
        numpy.isfinite(mid[1:])
        & numpy.isfinite(mid[:-1])
        & (mid[1:] > 0)
        & (mid[:-1] > 0)
    )
    returns[1:][valid] = numpy.log(
        mid[1:][valid] / mid[:-1][valid]
    ) * 10_000.0
    squared_cumulative = numpy.concatenate(
        (numpy.asarray([0.0]), numpy.cumsum(returns * returns))
    )
    trade_size = numpy.nan_to_num(
        values["buy_trade_size"] + values["sell_trade_size"]
    )
    trade_size_cumulative = numpy.concatenate(
        (numpy.asarray([0.0]), numpy.cumsum(trade_size))
    )
    trade_count_cumulative = numpy.concatenate(
        (
            numpy.asarray([0.0]),
            numpy.cumsum(values["trade_event_count"], dtype=numpy.float64),
        )
    )
    columns: list[numpy.ndarray] = []
    for window in PRICE_WINDOWS_SECONDS:
        starts = candidate_indices - window + 1
        start_mid = mid[starts]
        end_mid = mid[candidate_indices]
        directional_return = numpy.log(end_mid / start_mid) * 10_000.0
        realized = numpy.sqrt(
            _window_sum(
                squared_cumulative,
                candidate_indices,
                window,
            )
        )
        highs = numpy.asarray(
            [
                numpy.nanmax(values["high_mid"][start : end + 1])
                for start, end in zip(starts, candidate_indices)
            ],
            dtype=numpy.float64,
        )
        lows = numpy.asarray(
            [
                numpy.nanmin(values["low_mid"][start : end + 1])
                for start, end in zip(starts, candidate_indices)
            ],
            dtype=numpy.float64,
        )
        range_bps = numpy.log(highs / lows) * 10_000.0
        close_location = numpy.divide(
            2.0 * end_mid - highs - lows,
            highs - lows,
            out=numpy.zeros(len(candidate_indices)),
            where=(highs - lows) > 0,
        )
        total_trade_size = _window_sum(
            trade_size_cumulative, candidate_indices, window
        )
        trade_intensity = _window_sum(
            trade_count_cumulative, candidate_indices, window
        ) / window
        columns.extend(
            (
                directional_return,
                realized,
                range_bps,
                close_location,
                numpy.log1p(numpy.maximum(total_trade_size, 0.0)),
                trade_intensity,
            )
        )
    columns.extend(
        _build_closed_candle_indicator_features(
            source, candidate_indices
        ).T
    )
    features = numpy.column_stack(columns).astype(numpy.float32)
    if features.shape != (
        len(candidate_indices),
        len(PRICE_FEATURE_NAMES),
    ):
        raise RuntimeError("price feature construction differs")
    if not numpy.all(numpy.isfinite(features)):
        raise ValueError("price features contain non-finite values")
    return features


def _first_finite(values: numpy.ndarray) -> float:
    finite = values[numpy.isfinite(values)]
    return float(finite[0]) if len(finite) else math.nan


def _last_finite(values: numpy.ndarray) -> float:
    finite = values[numpy.isfinite(values)]
    return float(finite[-1]) if len(finite) else math.nan


def _finite_extreme(values: numpy.ndarray, *, maximum: bool) -> float:
    finite = values[numpy.isfinite(values)]
    if not len(finite):
        return math.nan
    reducer = numpy.max if maximum else numpy.min
    return float(reducer(finite))


def _build_closed_candle_indicator_features(
    source: scalping_v1.DenseSource,
    candidate_indices: numpy.ndarray,
) -> numpy.ndarray:
    """Build fixed indicators from fully closed, UTC-aligned 15m candles."""

    time_frame = INDICATOR_TIME_FRAME_SECONDS
    first_open = (
        (source.start_second + time_frame - 1) // time_frame
    ) * time_frame
    last_close = ((source.end_second + 1) // time_frame) * time_frame
    candle_count = (last_close - first_open) // time_frame
    if candle_count < INDICATOR_WARMUP_CANDLES:
        raise ValueError("insufficient complete candles for indicators")

    values = source.values
    first_index = first_open - source.start_second
    usable = candle_count * time_frame
    mid = values["last_mid"][first_index : first_index + usable].reshape(
        candle_count, time_frame
    )
    high = values["high_mid"][first_index : first_index + usable].reshape(
        candle_count, time_frame
    )
    low = values["low_mid"][first_index : first_index + usable].reshape(
        candle_count, time_frame
    )
    trade_size = (
        values["buy_trade_size"] + values["sell_trade_size"]
    )[first_index : first_index + usable].reshape(candle_count, time_frame)

    candles = numpy.zeros((candle_count, 6), dtype=numpy.float64)
    candles[:, 0] = first_open + (
        numpy.arange(candle_count, dtype=numpy.int64) + 1
    ) * time_frame
    candles[:, 1] = numpy.asarray(
        [_first_finite(row) for row in mid], dtype=numpy.float64
    )
    candles[:, 2] = numpy.asarray(
        [_finite_extreme(row, maximum=True) for row in high],
        dtype=numpy.float64,
    )
    candles[:, 3] = numpy.asarray(
        [_finite_extreme(row, maximum=False) for row in low],
        dtype=numpy.float64,
    )
    candles[:, 4] = numpy.asarray(
        [_last_finite(row) for row in mid], dtype=numpy.float64
    )
    candles[:, 5] = numpy.nansum(trade_size, axis=1)

    expected = tuple(
        name.removeprefix("i15m_") for name in INDICATOR_FEATURE_NAMES
    )
    decision_timestamps = source.start_second + candidate_indices + 1
    candle_indices = (
        decision_timestamps - first_open
    ) // time_frame - 1
    if numpy.any(candle_indices < INDICATOR_WARMUP_CANDLES - 1) or numpy.any(
        candle_indices >= candle_count
    ):
        raise ValueError("decision lacks complete indicator warmup")
    rows = []
    for candle_index in candle_indices:
        start = int(candle_index) - INDICATOR_WARMUP_CANDLES + 1
        feature_arrays = indicators.compute_feature_arrays(
            candles[start : int(candle_index) + 1]
        )
        if tuple(feature_arrays) != expected:
            raise RuntimeError("indicator feature schema differs")
        rows.append(
            [float(feature_arrays[name][-1]) for name in expected]
        )
    matrix = numpy.asarray(rows, dtype=numpy.float32)
    if not numpy.all(numpy.isfinite(matrix)):
        raise ValueError("indicator features contain non-finite values")
    return matrix


def _update_hit_times(
    *,
    direction: int,
    high_bid: numpy.ndarray,
    low_bid: numpy.ndarray,
    high_ask: numpy.ndarray,
    low_ask: numpy.ndarray,
    target_price: numpy.ndarray,
    stop_price: numpy.ndarray,
    target_time: numpy.ndarray,
    stop_time: numpy.ndarray,
    step: int,
) -> None:
    if direction == 1:
        target_hit = high_bid >= target_price
        stop_hit = low_bid <= stop_price
    else:
        target_hit = low_ask <= target_price
        stop_hit = high_ask >= stop_price
    target_time[(target_time < 0) & target_hit] = step
    stop_time[(stop_time < 0) & stop_hit] = step


def _direction_outcomes(
    source: scalping_v1.DenseSource,
    candidate_indices: numpy.ndarray,
    direction: int,
) -> dict[str, numpy.ndarray]:
    values = source.values
    starts = candidate_indices + 1
    entry_bid = values["entry_bid_500"][starts]
    entry_ask = values["entry_ask_500"][starts]
    entry_ns = values["entry_ns_500"][starts]
    entry = entry_ask if direction == 1 else entry_bid
    target_price = entry * (
        1.0 + direction * TARGET_BPS / 10_000.0
    )
    stop_price = entry * (
        1.0 - direction * STOP_BPS / 10_000.0
    )
    target_time = numpy.full(len(starts), -1, dtype=numpy.int32)
    stop_time = numpy.full(len(starts), -1, dtype=numpy.int32)
    favorable = entry.copy()
    adverse = entry.copy()
    outputs = {
        name: numpy.zeros(
            (len(starts), len(HORIZONS_SECONDS)), dtype=dtype
        )
        for name, dtype in (
            ("label", numpy.uint8),
            ("return", numpy.float32),
            ("stress_return", numpy.float32),
            ("exit", numpy.int64),
            ("mfe_bps", numpy.float32),
            ("mae_bps", numpy.float32),
        )
    }

    def update_extremes(
        high_bid: numpy.ndarray,
        low_bid: numpy.ndarray,
        high_ask: numpy.ndarray,
        low_ask: numpy.ndarray,
    ) -> None:
        nonlocal favorable, adverse
        if direction == 1:
            favorable = numpy.fmax(favorable, high_bid)
            adverse = numpy.fmin(adverse, low_bid)
        else:
            favorable = numpy.fmin(favorable, low_ask)
            adverse = numpy.fmax(adverse, high_ask)

    initial = (
        values["suffix_high_bid_500"][starts],
        values["suffix_low_bid_500"][starts],
        values["suffix_high_ask_500"][starts],
        values["suffix_low_ask_500"][starts],
    )
    _update_hit_times(
        direction=direction,
        high_bid=initial[0],
        low_bid=initial[1],
        high_ask=initial[2],
        low_ask=initial[3],
        target_price=target_price,
        stop_price=stop_price,
        target_time=target_time,
        stop_time=stop_time,
        step=0,
    )
    update_extremes(*initial)
    horizon_lookup = {
        horizon: index for index, horizon in enumerate(HORIZONS_SECONDS)
    }
    maximum_horizon = max(HORIZONS_SECONDS)
    entry_second = entry_ns // 1_000_000_000
    for step in range(1, maximum_horizon + 1):
        indices = starts + step
        if step in horizon_lookup:
            prefix = (
                values["prefix_high_bid_500"][indices],
                values["prefix_low_bid_500"][indices],
                values["prefix_high_ask_500"][indices],
                values["prefix_low_ask_500"][indices],
            )
            _update_hit_times(
                direction=direction,
                high_bid=prefix[0],
                low_bid=prefix[1],
                high_ask=prefix[2],
                low_ask=prefix[3],
                target_price=target_price,
                stop_price=stop_price,
                target_time=target_time,
                stop_time=stop_time,
                step=step,
            )
            update_extremes(*prefix)
            position = horizon_lookup[step]
            target = (
                (target_time >= 0)
                & ((stop_time < 0) | (target_time < stop_time))
                & (target_time <= step)
            )
            stop = (
                (stop_time >= 0)
                & ((target_time < 0) | (stop_time <= target_time))
                & (stop_time <= step)
            )
            timeout_bid = values["prefix_last_bid_500"][indices]
            timeout_ask = values["prefix_last_ask_500"][indices]
            timeout_return = (
                timeout_bid / entry_ask - 1.0
                if direction == 1
                else entry_bid / timeout_ask - 1.0
            )
            gross_return = numpy.where(
                target,
                TARGET_BPS / 10_000.0,
                numpy.where(
                    stop,
                    -STOP_BPS / 10_000.0,
                    timeout_return,
                ),
            )
            outputs["label"][:, position] = target.astype(numpy.uint8)
            outputs["return"][:, position] = (
                gross_return - ROUND_TRIP_COST_BPS / 10_000.0
            ).astype(numpy.float32)
            outputs["stress_return"][:, position] = (
                gross_return
                - ROUND_TRIP_COST_BPS
                * STRESS_COST_MULTIPLIER
                / 10_000.0
            ).astype(numpy.float32)
            hit_time = numpy.where(target, target_time, stop_time)
            outputs["exit"][:, position] = numpy.where(
                target | stop,
                entry_second + hit_time,
                entry_second + step,
            )
            if direction == 1:
                outputs["mfe_bps"][:, position] = (
                    (favorable / entry_ask - 1.0) * 10_000.0
                )
                outputs["mae_bps"][:, position] = (
                    (adverse / entry_ask - 1.0) * 10_000.0
                )
            else:
                outputs["mfe_bps"][:, position] = (
                    (entry_bid / favorable - 1.0) * 10_000.0
                )
                outputs["mae_bps"][:, position] = (
                    (entry_bid / adverse - 1.0) * 10_000.0
                )
        if step < maximum_horizon:
            full = (
                values["high_bid"][indices],
                values["low_bid"][indices],
                values["high_ask"][indices],
                values["low_ask"][indices],
            )
            _update_hit_times(
                direction=direction,
                high_bid=full[0],
                low_bid=full[1],
                high_ask=full[2],
                low_ask=full[3],
                target_price=target_price,
                stop_price=stop_price,
                target_time=target_time,
                stop_time=stop_time,
                step=step,
            )
            update_extremes(*full)
    return outputs


def build_pretest_dataset(
    *,
    protocol_value: typing.Union[str, pathlib.Path],
    parent_v3_dataset_value: typing.Union[str, pathlib.Path],
    parent_v3_manifest_value: typing.Union[str, pathlib.Path],
    source_cache_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    """Build only the already diagnostic pre-test block."""

    progress = progress or (lambda _message: None)
    protocol = write_or_verify_protocol(protocol_value)
    parent_manifest_path = pathlib.Path(parent_v3_manifest_value).resolve()
    parent_manifest = json.loads(
        parent_manifest_path.read_text(encoding="utf-8")
    )
    if parent_manifest.get("locked_test_materialized") is not False:
        raise ValueError("parent V3 dataset opened the locked block")
    if (
        parent_manifest.get("artifact", {}).get("sha256")
        != PARENT_V3_DATASET_SHA256
    ):
        raise ValueError("parent V3 dataset hash is not frozen")
    if (
        parent_manifest.get("source_snapshot_sha256")
        != SOURCE_SNAPSHOT_SHA256
    ):
        raise ValueError("parent V3 source snapshot differs")
    parent = scalping_v3.ScalpingV3Dataset.load(
        parent_v3_dataset_value,
        expected_sha256=PARENT_V3_DATASET_SHA256,
    )
    source_cache = pathlib.Path(source_cache_value).resolve()
    progress("loading verified one-second source cache")
    source = scalping_v1._load_dense_cache(source_cache)
    if source.end_second != _iso_timestamp(PRETEST_END) - 1:
        raise ValueError("source cache crosses the pre-test boundary")
    parent_rows, candidate_indices = _eligible_rows(source, parent)
    if not len(parent_rows):
        raise ValueError("no complete 15-minute regime decisions")
    timestamps = parent.timestamps[parent_rows].copy()
    angle = (timestamps % 86_400) / 86_400.0 * 2.0 * math.pi
    common_features = numpy.column_stack(
        (numpy.sin(angle), numpy.cos(angle))
    ).astype(numpy.float32)
    progress(f"building price context for {len(timestamps):,} decisions")
    price_features = _build_price_features(source, candidate_indices)
    book_features = parent.features[
        numpy.ix_(parent_rows, BOOK_PARENT_INDICES)
    ].astype(numpy.float32)
    progress("building fixed long multi-horizon outcomes")
    long = _direction_outcomes(source, candidate_indices, 1)
    progress("building fixed short multi-horizon outcomes")
    short = _direction_outcomes(source, candidate_indices, -1)
    dataset = RegimeDataset(
        timestamps=timestamps,
        common_features=common_features,
        price_features=price_features,
        book_features=book_features,
        **{
            f"{side}_{name}": values[name]
            for side, values in (("long", long), ("short", short))
            for name in (
                "label",
                "return",
                "stress_return",
                "exit",
                "mfe_bps",
                "mae_bps",
            )
        },
    )
    output = pathlib.Path(output_value).resolve()
    artifact = dataset.save(output, protocol["protocol_sha256"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": "diagnostic_reuse_microstructure_regime_dataset",
        "created_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "parent_v3_dataset_sha256": PARENT_V3_DATASET_SHA256,
        "parent_v3_manifest_sha256": _sha256(parent_manifest_path),
        "source_snapshot_sha256": SOURCE_SNAPSHOT_SHA256,
        "source_cache_sha256": _sha256(source_cache),
        "locked_test_materialized": False,
        "rows": len(dataset.timestamps),
        "common_features": len(COMMON_FEATURE_NAMES),
        "price_features": len(PRICE_FEATURE_NAMES),
        "book_features": len(BOOK_FEATURE_NAMES),
        "horizons_seconds": list(HORIZONS_SECONDS),
        "primary_horizon_seconds": PRIMARY_HORIZON_SECONDS,
        "first_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[0]), datetime.timezone.utc
        ).isoformat(),
        "last_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[-1]), datetime.timezone.utc
        ).isoformat(),
        "artifact": artifact,
    }
    manifest_path = output.with_suffix(".manifest.json")
    _atomic_json(manifest_path, manifest)
    return {**manifest, "manifest": str(manifest_path)}


@dataclasses.dataclass(frozen=True)
class WalkForwardFold:
    train: numpy.ndarray
    test: numpy.ndarray
    test_start: int
    test_end: int


def _walk_forward_folds(dataset: RegimeDataset) -> list[WalkForwardFold]:
    rows = len(dataset.timestamps)
    initial = int(rows * INITIAL_TRAIN_FRACTION)
    if initial < 10 or rows - initial < WALK_FORWARD_FOLDS:
        raise ValueError("insufficient decisions for frozen walk-forward")
    boundaries = numpy.linspace(
        initial, rows, WALK_FORWARD_FOLDS + 1, dtype=numpy.int64
    )
    folds = []
    for fold in range(WALK_FORWARD_FOLDS):
        test = numpy.arange(boundaries[fold], boundaries[fold + 1])
        test_start = int(dataset.timestamps[test[0]])
        train = numpy.flatnonzero(
            dataset.timestamps + EMBARGO_SECONDS < test_start
        )
        if len(train) < 10 or not len(test):
            raise ValueError("empty regime fold after purge and embargo")
        folds.append(
            WalkForwardFold(
                train=train,
                test=test,
                test_start=test_start,
                test_end=int(dataset.timestamps[test[-1]]),
            )
        )
    return folds


def _stack_training(
    dataset: RegimeDataset,
    indices: numpy.ndarray,
    group: str,
) -> tuple[numpy.ndarray, numpy.ndarray, tuple[str, ...]]:
    horizon = HORIZONS_SECONDS.index(PRIMARY_HORIZON_SECONDS)
    long_features, names = dataset.directional_features(
        indices, 1, group
    )
    short_features, short_names = dataset.directional_features(
        indices, -1, group
    )
    if names != short_names:
        raise RuntimeError("directional feature schemas differ")
    return (
        numpy.vstack((long_features, short_features)),
        numpy.concatenate(
            (
                dataset.long_label[indices, horizon],
                dataset.short_label[indices, horizon],
            )
        ),
        names,
    )


def _roc_auc(labels: numpy.ndarray, scores: numpy.ndarray) -> float:
    positives = labels == 1
    positive_count = int(numpy.sum(positives))
    negative_count = len(labels) - positive_count
    if not positive_count or not negative_count:
        return 0.5
    order = numpy.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = numpy.empty(len(scores), dtype=numpy.float64)
    start = 0
    while start < len(scores):
        end = start + 1
        while end < len(scores) and sorted_scores[end] == sorted_scores[start]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0 + 1.0
        start = end
    rank_sum = float(numpy.sum(ranks[positives]))
    return (
        rank_sum - positive_count * (positive_count + 1) / 2.0
    ) / (positive_count * negative_count)


def _probability_metrics(
    labels: numpy.ndarray,
    probabilities: numpy.ndarray,
    constant_probability: typing.Union[float, numpy.ndarray],
) -> dict:
    labels = labels.astype(numpy.float64)
    probabilities = numpy.clip(
        probabilities.astype(numpy.float64), 1e-6, 1.0 - 1e-6
    )
    constant = numpy.clip(
        numpy.asarray(constant_probability, dtype=numpy.float64),
        1e-6,
        1.0 - 1e-6,
    )
    return {
        "rows": int(len(labels)),
        "base_rate": float(numpy.mean(labels)),
        "mean_probability": float(numpy.mean(probabilities)),
        "brier": float(numpy.mean((probabilities - labels) ** 2)),
        "constant_brier": float(
            numpy.mean((constant - labels) ** 2)
        ),
        "log_loss": float(
            -numpy.mean(
                labels * numpy.log(probabilities)
                + (1.0 - labels) * numpy.log(1.0 - probabilities)
            )
        ),
        "constant_log_loss": float(
            -numpy.mean(
                labels * numpy.log(constant)
                + (1.0 - labels) * numpy.log(1.0 - constant)
            )
        ),
        "auc": _roc_auc(labels.astype(numpy.uint8), probabilities),
        "expected_calibration_error": float(
            model_module.expected_calibration_error(labels, probabilities)
        ),
    }


def _probability_distribution(probabilities: numpy.ndarray) -> dict:
    if not len(probabilities):
        return {
            "minimum": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "maximum": None,
        }
    quantiles = numpy.quantile(
        probabilities.astype(numpy.float64),
        (0.0, 0.50, 0.90, 0.95, 0.99, 1.0),
    )
    return dict(
        zip(
            ("minimum", "p50", "p90", "p95", "p99", "maximum"),
            (float(value) for value in quantiles),
        )
    )


def _dataset_diagnostics(dataset: RegimeDataset) -> dict:
    """Describe predeclared horizons without fitting or selecting one."""

    diagnostics = []
    target_net = TARGET_BPS / 10_000.0 - (
        ROUND_TRIP_COST_BPS / 10_000.0
    )
    stop_net = -STOP_BPS / 10_000.0 - (
        ROUND_TRIP_COST_BPS / 10_000.0
    )
    for position, horizon in enumerate(HORIZONS_SECONDS):
        directions = {}
        all_labels = []
        all_returns = []
        all_mfe = []
        all_mae = []
        for side in ("long", "short"):
            labels = getattr(dataset, f"{side}_label")[:, position]
            returns = getattr(dataset, f"{side}_return")[:, position]
            mfe = getattr(dataset, f"{side}_mfe_bps")[:, position]
            mae = getattr(dataset, f"{side}_mae_bps")[:, position]
            target = numpy.isclose(returns, target_net, atol=1e-7)
            stop = numpy.isclose(returns, stop_net, atol=1e-7)
            timeout = ~(target | stop)
            directions[side] = {
                "rows": int(len(labels)),
                "target_count": int(numpy.sum(target)),
                "target_rate": float(numpy.mean(labels)),
                "stop_count": int(numpy.sum(stop)),
                "stop_rate": float(numpy.mean(stop)),
                "timeout_count": int(numpy.sum(timeout)),
                "timeout_rate": float(numpy.mean(timeout)),
                "mean_net_return_bps": float(
                    numpy.mean(returns) * 10_000.0
                ),
            }
            all_labels.append(labels)
            all_returns.append(returns)
            all_mfe.append(mfe)
            all_mae.append(mae)
        labels = numpy.concatenate(all_labels)
        returns = numpy.concatenate(all_returns)
        mfe = numpy.concatenate(all_mfe)
        mae = numpy.concatenate(all_mae)
        diagnostics.append(
            {
                "horizon_seconds": horizon,
                "target_rate": float(numpy.mean(labels)),
                "mean_net_return_bps": float(
                    numpy.mean(returns) * 10_000.0
                ),
                "mfe_bps": {
                    "p50": float(numpy.quantile(mfe, 0.50)),
                    "p75": float(numpy.quantile(mfe, 0.75)),
                    "p90": float(numpy.quantile(mfe, 0.90)),
                    "p95": float(numpy.quantile(mfe, 0.95)),
                },
                "mae_bps": {
                    "p05": float(numpy.quantile(mae, 0.05)),
                    "p10": float(numpy.quantile(mae, 0.10)),
                    "p25": float(numpy.quantile(mae, 0.25)),
                    "p50": float(numpy.quantile(mae, 0.50)),
                },
                "directions": directions,
            }
        )
    return {
        "selection_authorized": False,
        "note": (
            "descriptive only; horizons cannot replace the frozen primary"
        ),
        "horizons": diagnostics,
    }


def _save_predictions(
    path: pathlib.Path,
    dataset: RegimeDataset,
    predictions: dict,
    protocol_sha256: str,
    dataset_sha256: str,
) -> dict:
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": numpy.asarray([SCHEMA_VERSION]),
        "protocol_sha256": numpy.asarray([protocol_sha256]),
        "dataset_sha256": numpy.asarray([dataset_sha256]),
        "timestamps": dataset.timestamps,
    }
    for group in ("price_only", "book_only", "combined"):
        for side in ("long", "short", "constant"):
            payload[f"{group}_{side}_probability"] = predictions[group][side]
    with temporary.open("wb") as stream:
        numpy.savez_compressed(stream, **payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _append_experiment_index(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(
            json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        output.flush()
        os.fsync(output.fileno())


def _simulate_trades(
    dataset: RegimeDataset,
    indices: numpy.ndarray,
    long_probability: numpy.ndarray,
    short_probability: numpy.ndarray,
    *,
    stress: bool,
) -> dict[str, numpy.ndarray]:
    horizon = HORIZONS_SECONDS.index(PRIMARY_HORIZON_SECONDS)
    selected_rows: list[int] = []
    directions: list[int] = []
    returns: list[float] = []
    exits: list[int] = []
    probabilities: list[float] = []
    free_after = -1
    for position, row in enumerate(indices):
        timestamp = int(dataset.timestamps[row])
        if timestamp <= free_after:
            continue
        long_score = float(long_probability[position])
        short_score = float(short_probability[position])
        if (
            max(long_score, short_score) < PROBABILITY_THRESHOLD
            or abs(long_score - short_score) < MINIMUM_DIRECTION_MARGIN
        ):
            continue
        direction = 1 if long_score > short_score else -1
        prefix = "long" if direction == 1 else "short"
        returns_field = (
            getattr(dataset, f"{prefix}_stress_return")
            if stress
            else getattr(dataset, f"{prefix}_return")
        )
        exit_field = getattr(dataset, f"{prefix}_exit")
        exit_timestamp = int(exit_field[row, horizon])
        if exit_timestamp <= timestamp:
            raise ValueError("regime trade exit is not after decision")
        selected_rows.append(int(row))
        directions.append(direction)
        returns.append(float(returns_field[row, horizon]))
        exits.append(exit_timestamp)
        probabilities.append(
            long_score if direction == 1 else short_score
        )
        free_after = exit_timestamp
    return {
        "rows": numpy.asarray(selected_rows, dtype=numpy.int64),
        "directions": numpy.asarray(directions, dtype=numpy.int8),
        "instrument_returns": numpy.asarray(returns, dtype=numpy.float64),
        "exit_timestamps": numpy.asarray(exits, dtype=numpy.int64),
        "probabilities": numpy.asarray(probabilities, dtype=numpy.float64),
    }


def _trade_metrics(
    dataset: RegimeDataset,
    trades: dict[str, numpy.ndarray],
) -> dict:
    instrument = trades["instrument_returns"]
    portfolio = instrument * POSITION_FRACTION
    empty_directions = {
        name: {"trades": 0, "total_return": 0.0}
        for name in ("long", "short")
    }
    if not len(portfolio):
        return {
            "trades": 0,
            "wins": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "positive_operating_days_pct": 0.0,
            "operating_days": 0,
            "positive_days": 0,
            "by_direction": empty_directions,
        }
    equity = numpy.cumprod(1.0 + portfolio)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.asarray([1.0]), equity))
    )[1:]
    profits = portfolio[portfolio > 0]
    losses = portfolio[portfolio < 0]
    gross_profit = float(numpy.sum(profits))
    gross_loss = float(-numpy.sum(losses))
    daily: dict[str, list[float]] = {}
    for row, value in zip(trades["rows"], portfolio):
        day = datetime.datetime.fromtimestamp(
            int(dataset.timestamps[row]), datetime.timezone.utc
        ).date().isoformat()
        daily.setdefault(day, []).append(float(value))
    daily_returns = {
        day: float(numpy.prod(1.0 + numpy.asarray(values)) - 1.0)
        for day, values in daily.items()
    }
    by_direction = {}
    for direction, name in ((1, "long"), (-1, "short")):
        selected = portfolio[trades["directions"] == direction]
        by_direction[name] = {
            "trades": int(len(selected)),
            "total_return": (
                float(numpy.prod(1.0 + selected) - 1.0)
                if len(selected)
                else 0.0
            ),
            "average_instrument_return_bps": (
                float(
                    numpy.mean(
                        instrument[trades["directions"] == direction]
                    )
                    * 10_000.0
                )
                if len(selected)
                else 0.0
            ),
        }
    positive_days = sum(value > 0 for value in daily_returns.values())
    return {
        "trades": int(len(portfolio)),
        "wins": int(numpy.sum(portfolio > 0)),
        "win_rate": float(numpy.mean(portfolio > 0)),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else (math.inf if gross_profit > 0 else 0.0)
        ),
        "total_return": float(equity[-1] - 1.0),
        "max_drawdown": float(numpy.max(1.0 - equity / peaks)),
        "average_instrument_return_bps": float(
            numpy.mean(instrument) * 10_000.0
        ),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "operating_days": len(daily_returns),
        "positive_days": positive_days,
        "positive_operating_days_pct": (
            positive_days / len(daily_returns) * 100.0
        ),
        "daily_returns": daily_returns,
        "by_direction": by_direction,
    }


def _json_safe(value: typing.Any) -> typing.Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, numpy.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, numpy.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _gate(
    *,
    combined: dict,
    price: dict,
    fitted_folds: int,
    improvement_folds: int,
    positive_folds: int,
) -> dict:
    probability = combined["probability"]
    primary = combined["primary"]
    stress = combined["stress"]
    relative_brier = 1.0 - probability["brier"] / max(
        price["probability"]["brier"], 1e-12
    )
    checks = {
        "all_walk_forward_folds_fitted": (
            fitted_folds == WALK_FORWARD_FOLDS
        ),
        "combined_auc": probability["auc"] >= MINIMUM_AUC,
        "combined_brier_better_than_constant": (
            probability["brier"] < probability["constant_brier"]
        ),
        "relative_brier_improvement_vs_price": (
            relative_brier >= MINIMUM_RELATIVE_BRIER_IMPROVEMENT
        ),
        "book_improvement_folds": (
            improvement_folds >= MINIMUM_BOOK_IMPROVEMENT_FOLDS
        ),
        "minimum_trades": primary["trades"] >= MINIMUM_TRADES,
        "minimum_long_trades": (
            primary["by_direction"]["long"]["trades"]
            >= MINIMUM_TRADES_PER_DIRECTION
        ),
        "minimum_short_trades": (
            primary["by_direction"]["short"]["trades"]
            >= MINIMUM_TRADES_PER_DIRECTION
        ),
        "profit_factor": primary["profit_factor"] >= 1.20,
        "maximum_drawdown": primary["max_drawdown"] <= 0.05,
        "positive_operating_days": (
            primary["positive_operating_days_pct"] >= 55.0
        ),
        "positive_folds": positive_folds >= MINIMUM_POSITIVE_FOLDS,
        "long_non_negative": (
            primary["by_direction"]["long"]["total_return"] >= 0.0
        ),
        "short_non_negative": (
            primary["by_direction"]["short"]["total_return"] >= 0.0
        ),
        "double_cost_non_negative": stress["total_return"] >= 0.0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "relative_brier_improvement_vs_price": relative_brier,
        "book_improvement_folds": improvement_folds,
        "positive_folds": positive_folds,
    }


def evaluate_discovery(
    *,
    protocol_value: typing.Union[str, pathlib.Path],
    dataset_value: typing.Union[str, pathlib.Path],
    dataset_manifest_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    """Run fixed walk-forward diagnostics without opening locked data."""

    progress = progress or (lambda _message: None)
    protocol_path = pathlib.Path(protocol_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    manifest_path = pathlib.Path(dataset_manifest_value).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("locked_test_materialized") is not False:
        raise ValueError("regime discovery manifest opened locked data")
    if manifest.get("protocol_sha256") != protocol["protocol_sha256"]:
        raise ValueError("regime discovery protocol differs")
    artifact = manifest.get("artifact", {})
    dataset = RegimeDataset.load(
        dataset_value,
        expected_sha256=artifact.get("sha256"),
        expected_protocol_sha256=protocol["protocol_sha256"],
    )
    folds = _walk_forward_folds(dataset)
    groups = ("price_only", "book_only", "combined")
    predictions = {
        group: {
            "long": numpy.full(len(dataset.timestamps), numpy.nan),
            "short": numpy.full(len(dataset.timestamps), numpy.nan),
            "constant": numpy.full(len(dataset.timestamps), numpy.nan),
            "folds": [],
        }
        for group in groups
    }
    fitted_models: dict[
        str, list[tuple[int, numpy.ndarray, model_module.NumpyLogisticModel]]
    ] = {group: [] for group in groups}
    fitted_folds = 0
    for fold_number, fold in enumerate(folds, start=1):
        progress(
            f"walk-forward fold {fold_number}/{WALK_FORWARD_FOLDS}"
        )
        fold_fitted = True
        for group in groups:
            train_features, labels, names = _stack_training(
                dataset, fold.train, group
            )
            try:
                model = model_module.NumpyLogisticModel.fit(
                    train_features,
                    labels,
                    names,
                    LOGISTIC_CONFIG,
                )
            except ValueError as error:
                predictions[group]["folds"].append(
                    {
                        "fold": fold_number,
                        "fitted": False,
                        "error": str(error),
                    }
                )
                fold_fitted = False
                continue
            long_features, _ = dataset.directional_features(
                fold.test, 1, group
            )
            short_features, _ = dataset.directional_features(
                fold.test, -1, group
            )
            long_probability = model.predict_proba(long_features)
            short_probability = model.predict_proba(short_features)
            fitted_models[group].append(
                (fold_number, fold.test.copy(), model)
            )
            predictions[group]["long"][fold.test] = long_probability
            predictions[group]["short"][fold.test] = short_probability
            horizon = HORIZONS_SECONDS.index(PRIMARY_HORIZON_SECONDS)
            test_labels = numpy.concatenate(
                (
                    dataset.long_label[fold.test, horizon],
                    dataset.short_label[fold.test, horizon],
                )
            )
            test_probability = numpy.concatenate(
                (long_probability, short_probability)
            )
            constant = float(numpy.mean(labels))
            predictions[group]["constant"][fold.test] = constant
            probability = _probability_metrics(
                test_labels, test_probability, constant
            )
            trades = _simulate_trades(
                dataset,
                fold.test,
                long_probability,
                short_probability,
                stress=False,
            )
            predictions[group]["folds"].append(
                {
                    "fold": fold_number,
                    "fitted": True,
                    "train_decisions": int(len(fold.train)),
                    "test_decisions": int(len(fold.test)),
                    "test_start": datetime.datetime.fromtimestamp(
                        fold.test_start, datetime.timezone.utc
                    ).isoformat(),
                    "test_end": datetime.datetime.fromtimestamp(
                        fold.test_end, datetime.timezone.utc
                    ).isoformat(),
                    "probability": probability,
                    "primary": _trade_metrics(dataset, trades),
                }
            )
        if fold_fitted:
            fitted_folds += 1

    results = {}
    horizon = HORIZONS_SECONDS.index(PRIMARY_HORIZON_SECONDS)
    for group in groups:
        valid = numpy.flatnonzero(
            numpy.isfinite(predictions[group]["long"])
            & numpy.isfinite(predictions[group]["short"])
        )
        if not len(valid):
            results[group] = {
                "probability": {
                    "rows": 0,
                    "brier": math.inf,
                    "constant_brier": 0.0,
                    "auc": 0.5,
                },
                "primary": _trade_metrics(
                    dataset,
                    _simulate_trades(
                        dataset,
                        valid,
                        numpy.asarray([]),
                        numpy.asarray([]),
                        stress=False,
                    ),
                ),
                "stress": _trade_metrics(
                    dataset,
                    _simulate_trades(
                        dataset,
                        valid,
                        numpy.asarray([]),
                        numpy.asarray([]),
                        stress=True,
                    ),
                ),
                "folds": predictions[group]["folds"],
            }
            continue
        labels = numpy.concatenate(
            (
                dataset.long_label[valid, horizon],
                dataset.short_label[valid, horizon],
            )
        )
        probabilities = numpy.concatenate(
            (
                predictions[group]["long"][valid],
                predictions[group]["short"][valid],
            )
        )
        probability = _probability_metrics(
            labels,
            probabilities,
            numpy.concatenate(
                (
                    predictions[group]["constant"][valid],
                    predictions[group]["constant"][valid],
                )
            ),
        )
        primary_trades = _simulate_trades(
            dataset,
            valid,
            predictions[group]["long"][valid],
            predictions[group]["short"][valid],
            stress=False,
        )
        stress_trades = _simulate_trades(
            dataset,
            valid,
            predictions[group]["long"][valid],
            predictions[group]["short"][valid],
            stress=True,
        )
        results[group] = {
            "probability": probability,
            "probability_distribution": {
                "long": _probability_distribution(
                    predictions[group]["long"][valid]
                ),
                "short": _probability_distribution(
                    predictions[group]["short"][valid]
                ),
                "both_directions": _probability_distribution(
                    probabilities
                ),
            },
            "primary": _trade_metrics(dataset, primary_trades),
            "stress": _trade_metrics(dataset, stress_trades),
            "folds": predictions[group]["folds"],
        }

    improvement_folds = 0
    positive_folds = 0
    for fold_index in range(WALK_FORWARD_FOLDS):
        price_fold = results["price_only"]["folds"][fold_index]
        combined_fold = results["combined"]["folds"][fold_index]
        if price_fold.get("fitted") and combined_fold.get("fitted"):
            if (
                combined_fold["probability"]["brier"]
                < price_fold["probability"]["brier"]
            ):
                improvement_folds += 1
            if combined_fold["primary"]["total_return"] > 0:
                positive_folds += 1
    gate = _gate(
        combined=results["combined"],
        price=results["price_only"],
        fitted_folds=fitted_folds,
        improvement_folds=improvement_folds,
        positive_folds=positive_folds,
    )
    created_at = datetime.datetime.now(datetime.timezone.utc)
    experiment_id = (
        f"{PROTOCOL_VERSION}-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    )
    output = pathlib.Path(output_root_value).resolve() / experiment_id
    if output.exists():
        raise ValueError("regime experiment directory already exists")
    output.mkdir(parents=True)
    prediction_artifact = _save_predictions(
        output / "predictions.npz",
        dataset,
        predictions,
        protocol["protocol_sha256"],
        str(artifact.get("sha256")),
    )
    model_artifacts = []
    for group in groups:
        for fold_number, test_indices, model in fitted_models[group]:
            model_path = (
                output / "models" / f"{group}-fold-{fold_number}.npz"
            )
            model_artifact = model.save(model_path)
            reloaded = model_module.NumpyLogisticModel.load(model_path)
            for direction, side in ((1, "long"), (-1, "short")):
                features, _ = dataset.directional_features(
                    test_indices, direction, group
                )
                expected = predictions[group][side][test_indices]
                actual = reloaded.predict_proba(features)
                if not numpy.allclose(actual, expected, rtol=0.0, atol=1e-12):
                    raise ValueError("reloaded regime model differs")
            model_artifacts.append(
                {
                    "group": group,
                    "fold": fold_number,
                    **model_artifact,
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
        "dataset": {
            "sha256": artifact.get("sha256"),
            "manifest_sha256": _sha256(manifest_path),
            "rows": len(dataset.timestamps),
            "status": "diagnostic_reuse_not_pristine_validation",
            "locked_test_materialized": False,
        },
        "primary_task": {
            "horizon_seconds": PRIMARY_HORIZON_SECONDS,
            "target_bps": TARGET_BPS,
            "stop_bps": STOP_BPS,
            "probability_threshold": PROBABILITY_THRESHOLD,
            "minimum_direction_margin": MINIMUM_DIRECTION_MARGIN,
        },
        "diagnostics_only": _dataset_diagnostics(dataset),
        "models": results,
        "diagnostic_advancement_gate": gate,
        "conclusion": (
            "incremental_book_value_detected_diagnostic_only"
            if gate["passed"]
            else "incremental_book_value_not_demonstrated"
        ),
        "locked_historical_block": {
            "start": PRETEST_END,
            "end": LOCKED_BLOCK_END,
            "materialized": False,
            "authorized_to_open": False,
        },
        "consequence": (
            "no signal or order change; a pass permits only a new result-free "
            "forward observer protocol"
        ),
        "artifacts": {
            "predictions": prediction_artifact,
            "fold_models": model_artifacts,
        },
        "implementation": {
            "source": str(pathlib.Path(__file__).resolve()),
            "source_sha256": _sha256(pathlib.Path(__file__).resolve()),
        },
    }
    report_path = output / "report.json"
    _atomic_json(report_path, report)
    experiment_manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "protocol_sha256": protocol["protocol_sha256"],
        "dataset_sha256": artifact.get("sha256"),
        "report": {
            "path": str(report_path),
            "sha256": _sha256(report_path),
            "bytes": report_path.stat().st_size,
        },
        "predictions": prediction_artifact,
        "fold_models": model_artifacts,
        "implementation_sha256": report["implementation"]["source_sha256"],
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    _atomic_json(output / "manifest.json", experiment_manifest)
    _append_experiment_index(
        pathlib.Path(output_root_value).resolve() / "experiments.jsonl",
        {
            "experiment_id": experiment_id,
            "created_at": created_at.isoformat(),
            "protocol_sha256": protocol["protocol_sha256"],
            "dataset_sha256": artifact.get("sha256"),
            "report_sha256": experiment_manifest["report"]["sha256"],
            "conclusion": report["conclusion"],
            "orders_authorized": False,
        },
    )
    return {**report, "report_path": str(report_path)}


def main(arguments: typing.Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BTC microstructure multi-horizon research V1"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    protocol_parser = subparsers.add_parser("write-protocol")
    protocol_parser.add_argument("--output", required=True)
    dataset_parser = subparsers.add_parser("build-dataset")
    dataset_parser.add_argument("--protocol", required=True)
    dataset_parser.add_argument("--parent-v3-dataset", required=True)
    dataset_parser.add_argument("--parent-v3-manifest", required=True)
    dataset_parser.add_argument("--source-cache", required=True)
    dataset_parser.add_argument("--output", required=True)
    evaluator_parser = subparsers.add_parser("evaluate-discovery")
    evaluator_parser.add_argument("--protocol", required=True)
    evaluator_parser.add_argument("--dataset", required=True)
    evaluator_parser.add_argument("--dataset-manifest", required=True)
    evaluator_parser.add_argument("--output-root", required=True)
    args = parser.parse_args(arguments)
    if args.command == "write-protocol":
        result: typing.Any = write_or_verify_protocol(args.output)
    elif args.command == "build-dataset":
        result = build_pretest_dataset(
            protocol_value=args.protocol,
            parent_v3_dataset_value=args.parent_v3_dataset,
            parent_v3_manifest_value=args.parent_v3_manifest,
            source_cache_value=args.source_cache,
            output_value=args.output,
            progress=print,
        )
    else:
        result = evaluate_discovery(
            protocol_value=args.protocol,
            dataset_value=args.dataset,
            dataset_manifest_value=args.dataset_manifest,
            output_root_value=args.output_root,
            progress=print,
        )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
