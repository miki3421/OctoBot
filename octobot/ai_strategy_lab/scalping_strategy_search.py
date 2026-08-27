"""Leakage-resistant evaluation of the frozen BTC Level 5 dataset.

The module is deliberately research-only.  It has no exchange client, order
API, paper broker integration, or automatic promotion path.  The result-free
implementation protocol is persisted and hashed before any economic label is
computed.
"""

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
from octobot.ai_strategy_lab import percentage_probability_engine


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_scalping_micro_momentum_v1_eval1a"
PREREGISTRATION_DATE = "2026-08-27"
PARENT_PROTOCOL_VERSION = "btc_futures_scalping_micro_momentum_v1"
PARENT_PROTOCOL_SHA256 = (
    "8a1e290680bed79e71a97e1012c04c4e5f6ee36bd5107f85a095c2152a9aa065"
)
SNAPSHOT_SHA256 = (
    "96020bbf554b87e6433748fa3586c4d9d07c819cddeeab2e6e90f24475f64bce"
)
SNAPSHOT_MANIFEST_SHA256 = (
    "9900ead58a9f6cad252d12c90c24944df75e4b968c40d858878792f182c4631c"
)
SOURCE_START = "2026-07-23T14:01:49+00:00"
SOURCE_END = "2026-08-26T14:10:57+00:00"
TRAIN_END = "2026-08-13T00:00:00+00:00"
SELECTION_END = "2026-08-20T00:00:00+00:00"
LOCKED_TEST_END = "2026-08-26T14:10:58+00:00"
DECISION_STRIDE_SECONDS = 5
TRAINING_STRIDE_SECONDS = 20
MAXIMUM_FEATURE_LOOKBACK_SECONDS = 300
PRIMARY_LATENCY_MS = 500
STRESS_LATENCY_MS = 1_000
TARGET_BPS = 40
STOP_BPS = 10
HORIZON_SECONDS = 120
FEE_BPS_PER_FILL = 6.0
SLIPPAGE_BPS_PER_FILL = 1.0
COST_STRESS_MULTIPLIER = 2.0
WALK_FORWARD_FOLDS = 5
EMBARGO_SECONDS = HORIZON_SECONDS
CALIBRATION_FRACTION = 0.20
PROBABILITY_QUANTILES = (0.90, 0.95, 0.975, 0.99)
DIRECTION_MARGIN = 0.02
POSITION_FRACTION = 0.10

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
    """Return the complete result-free implementation protocol."""

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
        "parent_protocol": {
            "version": PARENT_PROTOCOL_VERSION,
            "sha256": PARENT_PROTOCOL_SHA256,
        },
        "frozen_source": {
            "snapshot_sha256": SNAPSHOT_SHA256,
            "snapshot_manifest_sha256": SNAPSHOT_MANIFEST_SHA256,
            "start_inclusive": SOURCE_START,
            "end_inclusive": SOURCE_END,
            "exchange": "kucoin_futures",
            "symbol": "XBTUSDTM",
            "known_development_event": (
                "the 2026-07-27 sell-off was inspected previously and lies "
                "inside the development block only"
            ),
        },
        "candidate": {
            "family": "symmetric_directional_micro_momentum",
            "decision_stride_seconds": DECISION_STRIDE_SECONDS,
            "one_trade_at_a_time": True,
            "long_and_short": True,
            "entry": "first recorded top-of-book quote after latency",
            "exit": "executable opposite top-of-book or conservative barrier",
            "primary_latency_ms": PRIMARY_LATENCY_MS,
            "target_bps": TARGET_BPS,
            "stop_bps": STOP_BPS,
            "maximum_hold_seconds": HORIZON_SECONDS,
            "position_fraction_of_equity": POSITION_FRACTION,
            "stop_wins_same_one_second_bucket": True,
            "configuration_reason": (
                "highest net reward-to-risk member of the already frozen "
                "grid and positive gross target after doubled fees/slippage"
            ),
        },
        "features": {
            "maximum_lookback_seconds": (
                MAXIMUM_FEATURE_LOOKBACK_SECONDS
            ),
            "windows_seconds": [5, 15, 30, 60],
            "context_seconds": [60, 300],
            "directional_symmetry": (
                "the same model receives sign-normalized LONG and SHORT rows"
            ),
            "names_by_window": [
                "directional_mid_return_bps",
                "directional_microprice_premium_bps_mean",
                "spread_bps_mean",
                "spread_bps_max",
                "directional_level5_book_imbalance_mean",
                "directional_level5_book_imbalance_slope",
                "directional_aggressor_size_imbalance",
                "directional_aggressor_count_imbalance",
                "book_event_intensity",
                "trade_event_intensity",
                "realized_mid_volatility_bps",
                "high_low_range_bps",
            ],
            "context_names": [
                "directional_one_minute_context_bps",
                "directional_five_minute_context_bps",
                "one_to_five_minute_regime_ratio",
                "utc_hour_sine",
                "utc_hour_cosine",
            ],
            "causality": (
                "every feature uses records received no later than the "
                "decision second close"
            ),
            "candidate_requires_continuous_lookback": True,
            "label_requires_continuous_future": True,
        },
        "labels_and_costs": {
            "target_before_stop_label": True,
            "timeouts_use_executable_deadline_quote": True,
            "fee_bps_per_fill": FEE_BPS_PER_FILL,
            "slippage_bps_per_fill": SLIPPAGE_BPS_PER_FILL,
            "fills_per_trade": 2,
            "primary_cost_multiplier": 1.0,
            "stress_cost_multiplier": COST_STRESS_MULTIPLIER,
            "stress_latency_ms": STRESS_LATENCY_MS,
            "retroactive_fills": False,
            "funding": (
                "excluded because no trade can span the eight-hour funding "
                "interval within the 120-second horizon"
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
            "training_stride_seconds": TRAINING_STRIDE_SECONDS,
            "calibration": "quantile_isotonic_on_latest_training_20pct",
            "calibration_fraction": CALIBRATION_FRACTION,
            "probability_quantiles": list(PROBABILITY_QUANTILES),
            "minimum_long_short_probability_margin": DIRECTION_MARGIN,
            "selection": (
                "lexicographic hard-gates-passed, stressed profit factor, "
                "stressed net return, trade count"
            ),
        },
        "temporal_validation": {
            "development": [SOURCE_START, TRAIN_END],
            "independent_selection": [TRAIN_END, SELECTION_END],
            "locked_final_test": [SELECTION_END, LOCKED_TEST_END],
            "walk_forward_folds_inside_development": WALK_FORWARD_FOLDS,
            "expanding_train": True,
            "embargo_seconds": EMBARGO_SECONDS,
            "locked_test_policy": (
                "do not compute labels, predictions, or metrics unless both "
                "development and independent selection gates pass"
            ),
            "no_mid_test_retuning": True,
        },
        "development_gate": {
            "minimum_oos_trades": 500,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": 4,
            "required_folds": WALK_FORWARD_FOLDS,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "brier_better_than_constant_base_rate": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "selection_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "brier_better_than_constant_base_rate": True,
            "positive_under_doubled_cost_and_latency": True,
        },
        "locked_test_gate": {
            "minimum_trades": 100,
            "minimum_net_profit_factor": 1.20,
            "maximum_drawdown_pct": 5.0,
            "minimum_positive_operating_days_pct": 55.0,
            "long_contribution_non_negative": True,
            "short_contribution_non_negative": True,
            "positive_under_doubled_cost_and_latency": True,
            "paper_shadow_consequence": (
                "passing permits only a separately approved research shadow"
            ),
        },
        "multiple_testing_disclosure": (
            "two model families and four predeclared probability quantiles "
            "are compared only inside development; the independent selection "
            "and locked test protect against choosing the best noise"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Atomically write the protocol once, or verify exact identity."""

    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": _json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted scalping search protocol differs")
        return persisted
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


FEATURE_WINDOWS_SECONDS = (5, 15, 30, 60)
CONTEXT_WINDOWS_SECONDS = (60, 300)
WINDOW_FEATURE_NAMES = (
    "directional_mid_return_bps",
    "directional_microprice_premium_bps_mean",
    "spread_bps_mean",
    "spread_bps_max",
    "directional_level5_book_imbalance_mean",
    "directional_level5_book_imbalance_slope",
    "directional_aggressor_size_imbalance",
    "directional_aggressor_count_imbalance",
    "book_event_intensity",
    "trade_event_intensity",
    "realized_mid_volatility_bps",
    "high_low_range_bps",
)
CONTEXT_FEATURE_NAMES = (
    "directional_one_minute_context_bps",
    "directional_five_minute_context_bps",
    "one_to_five_minute_regime_ratio",
    "utc_hour_sine",
    "utc_hour_cosine",
)
FEATURE_NAMES = tuple(
    f"w{window}_{name}"
    for window in FEATURE_WINDOWS_SECONDS
    for name in WINDOW_FEATURE_NAMES
) + CONTEXT_FEATURE_NAMES
DIRECTIONAL_FEATURE_MASK = numpy.asarray(
    [
        name.startswith("directional_")
        or "_directional_" in name
        or name == "one_to_five_minute_regime_ratio"
        for name in FEATURE_NAMES
    ],
    dtype=bool,
)
_OUTCOME_TARGET = numpy.int8(1)
_OUTCOME_TIMEOUT = numpy.int8(0)
_OUTCOME_STOP = numpy.int8(-1)


def _iso_timestamp(value: str) -> int:
    return int(datetime.datetime.fromisoformat(value).timestamp())


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
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@dataclasses.dataclass
class DenseSource:
    """Dense one-second representation used only by the offline builder."""

    start_second: int
    end_second: int
    values: dict[str, numpy.ndarray]

    @property
    def seconds(self) -> numpy.ndarray:
        return numpy.arange(
            self.start_second, self.end_second + 1, dtype=numpy.int64
        )

    def __len__(self) -> int:
        return self.end_second - self.start_second + 1


@dataclasses.dataclass
class ScalpingResearchDataset:
    """Compact causal features and pre-test economic outcomes."""

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
        row_count = len(self.timestamps)
        if row_count == 0:
            raise ValueError("scalping research dataset is empty")
        if self.features.shape != (row_count, len(FEATURE_NAMES)):
            raise ValueError("scalping feature matrix has an invalid shape")
        if numpy.any(numpy.diff(self.timestamps) <= 0):
            raise ValueError("scalping timestamps are not strictly increasing")
        if int(self.timestamps[-1]) >= _iso_timestamp(SELECTION_END):
            raise ValueError("pre-test dataset leaks into the locked block")
        for field in dataclasses.fields(self):
            name = field.name
            values = getattr(self, name)
            if name in {"timestamps", "features"}:
                continue
            if len(values) != row_count:
                raise ValueError(f"dataset field {name} is misaligned")
        if not numpy.all(numpy.isfinite(self.features)):
            raise ValueError("scalping features contain non-finite values")
        for values in (
            self.primary_long_return,
            self.primary_short_return,
            self.stress_long_return,
            self.stress_short_return,
        ):
            if not numpy.all(numpy.isfinite(values)):
                raise ValueError("scalping returns contain non-finite values")
        for values in (
            self.primary_long_label,
            self.primary_short_label,
        ):
            if not set(numpy.unique(values)).issubset({0, 1}):
                raise ValueError("scalping labels are not binary")

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
                timestamps=self.timestamps,
                features=self.features,
                primary_long_label=self.primary_long_label,
                primary_short_label=self.primary_short_label,
                primary_long_return=self.primary_long_return,
                primary_short_return=self.primary_short_return,
                primary_long_exit=self.primary_long_exit,
                primary_short_exit=self.primary_short_exit,
                stress_long_return=self.stress_long_return,
                stress_short_return=self.stress_short_return,
                stress_long_exit=self.stress_long_exit,
                stress_short_exit=self.stress_short_exit,
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
    ) -> "ScalpingResearchDataset":
        path = pathlib.Path(path_value).resolve()
        if expected_sha256 is not None and _sha256(path) != expected_sha256:
            raise ValueError("scalping dataset hash differs")
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != SCHEMA_VERSION:
                raise ValueError("unsupported scalping dataset schema")
            if str(values["protocol_version"][0]) != PROTOCOL_VERSION:
                raise ValueError("scalping dataset protocol differs")
            if str(values["protocol_sha256"][0]) != _json_hash(
                frozen_protocol()
            ):
                raise ValueError("scalping dataset protocol hash differs")
            if str(values["source_snapshot_sha256"][0]) != SNAPSHOT_SHA256:
                raise ValueError("scalping dataset source snapshot differs")
            if tuple(str(value) for value in values["feature_names"]) != (
                FEATURE_NAMES
            ):
                raise ValueError("scalping dataset feature schema differs")
            if not numpy.array_equal(
                values["directional_feature_mask"],
                DIRECTIONAL_FEATURE_MASK,
            ):
                raise ValueError("scalping directional feature mask differs")
            dataset = cls(
                **{
                    field.name: values[field.name].copy()
                    for field in dataclasses.fields(cls)
                }
            )
        dataset.validate()
        return dataset


def _empty_dense_values(length: int) -> dict[str, numpy.ndarray]:
    integers = {
        "book_event_count": numpy.zeros(length, dtype=numpy.int32),
        "trade_event_count": numpy.zeros(length, dtype=numpy.int32),
        "buy_trade_count": numpy.zeros(length, dtype=numpy.int32),
        "sell_trade_count": numpy.zeros(length, dtype=numpy.int32),
        "raw_book_event_count": numpy.zeros(length, dtype=numpy.int16),
        "entry_ns_0": numpy.zeros(length, dtype=numpy.int64),
        "entry_ns_500": numpy.zeros(length, dtype=numpy.int64),
    }
    zero_floats = {
        "spread_bps_sum",
        "imbalance_5_sum",
        "buy_trade_size",
        "sell_trade_size",
        "microprice_premium_bps_sum",
    }
    nan_floats = {
        "first_mid",
        "high_mid",
        "low_mid",
        "last_mid",
        "last_bid",
        "last_ask",
        "maximum_latency_ms",
        "spread_bps_max",
        "high_bid",
        "low_bid",
        "high_ask",
        "low_ask",
        "entry_bid_0",
        "entry_ask_0",
        "suffix_high_bid_0",
        "suffix_low_bid_0",
        "suffix_high_ask_0",
        "suffix_low_ask_0",
        "entry_bid_500",
        "entry_ask_500",
        "suffix_high_bid_500",
        "suffix_low_bid_500",
        "suffix_high_ask_500",
        "suffix_low_ask_500",
        "prefix_high_bid_500",
        "prefix_low_bid_500",
        "prefix_high_ask_500",
        "prefix_low_ask_500",
        "prefix_last_bid_500",
        "prefix_last_ask_500",
    }
    values: dict[str, numpy.ndarray] = dict(integers)
    values.update(
        {
            name: numpy.zeros(length, dtype=numpy.float64)
            for name in zero_floats
        }
    )
    values.update(
        {
            name: numpy.full(length, numpy.nan, dtype=numpy.float64)
            for name in nan_floats
        }
    )
    return values


def _read_dense_seconds(
    database: pathlib.Path,
    start_second: int,
    end_second: int,
) -> DenseSource:
    if end_second <= start_second:
        raise ValueError("invalid dense source interval")
    source = DenseSource(
        start_second=start_second,
        end_second=end_second,
        values=_empty_dense_values(end_second - start_second + 1),
    )
    connection = sqlite3.connect(
        f"file:{database}?mode=ro&immutable=1", uri=True, timeout=30
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        cursor = connection.execute(
            """
            SELECT
                bucket_ts_s, book_event_count, trade_event_count,
                first_mid, high_mid, low_mid, last_mid,
                spread_bps_sum, imbalance_5_sum,
                buy_trade_size, sell_trade_size,
                buy_trade_count, sell_trade_count,
                last_bid, last_ask, maximum_latency_ms
            FROM second_buckets
            WHERE bucket_ts_s BETWEEN ? AND ?
            ORDER BY bucket_ts_s
            """,
            (start_second, end_second),
        )
        names = (
            "book_event_count",
            "trade_event_count",
            "first_mid",
            "high_mid",
            "low_mid",
            "last_mid",
            "spread_bps_sum",
            "imbalance_5_sum",
            "buy_trade_size",
            "sell_trade_size",
            "buy_trade_count",
            "sell_trade_count",
            "last_bid",
            "last_ask",
            "maximum_latency_ms",
        )
        for row in cursor:
            index = int(row[0]) - start_second
            for name, value in zip(names, row[1:]):
                source.values[name][index] = value
    finally:
        connection.close()
    return source


def _augment_from_raw_books(
    database: pathlib.Path,
    source: DenseSource,
    *,
    progress: typing.Callable[[str], None] | None = None,
) -> None:
    """Stream raw books once and persist only causal one-second summaries."""

    progress = progress or (lambda _message: None)
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
        raise ValueError("frozen source contains no raw books in interval")
    first_id, last_id = int(first_row[0]), int(last_row[0])
    cursor = connection.execute(
        """
        SELECT received_ts_ns, bid_price_1, ask_price_1,
               mid_price, microprice, spread_bps
        FROM book_events
        WHERE id BETWEEN ? AND ?
        ORDER BY id
        """,
        (first_id, last_id),
    )

    current_second: int | None = None
    offsets: list[int] = []
    bids: list[float] = []
    asks: list[float] = []
    mids: list[float] = []
    micros: list[float] = []
    spreads: list[float] = []
    processed = 0
    previous_received_ns = 0
    started = time.monotonic()

    def finalize() -> None:
        if current_second is None:
            return
        index = current_second - source.start_second
        if index < 0 or index >= len(source):
            return
        values = source.values
        count = len(offsets)
        values["raw_book_event_count"][index] = count
        values["microprice_premium_bps_sum"][index] = sum(
            (micro / mid - 1.0) * 10_000.0
            for micro, mid in zip(micros, mids)
        )
        values["spread_bps_max"][index] = max(spreads)
        values["high_bid"][index] = max(bids)
        values["low_bid"][index] = min(bids)
        values["high_ask"][index] = max(asks)
        values["low_ask"][index] = min(asks)

        for offset_ms in (0, 500):
            threshold = offset_ms * 1_000_000
            entry_index = next(
                (
                    position
                    for position, value in enumerate(offsets)
                    if value >= threshold
                ),
                None,
            )
            if entry_index is not None:
                suffix = slice(entry_index, None)
                values[f"entry_ns_{offset_ms}"][index] = (
                    current_second * 1_000_000_000
                    + offsets[entry_index]
                )
                values[f"entry_bid_{offset_ms}"][index] = bids[entry_index]
                values[f"entry_ask_{offset_ms}"][index] = asks[entry_index]
                values[f"suffix_high_bid_{offset_ms}"][index] = max(
                    bids[suffix]
                )
                values[f"suffix_low_bid_{offset_ms}"][index] = min(
                    bids[suffix]
                )
                values[f"suffix_high_ask_{offset_ms}"][index] = max(
                    asks[suffix]
                )
                values[f"suffix_low_ask_{offset_ms}"][index] = min(
                    asks[suffix]
                )
        prefix_indices = [
            position
            for position, value in enumerate(offsets)
            if value <= 500_000_000
        ]
        if prefix_indices:
            end = prefix_indices[-1] + 1
            values["prefix_high_bid_500"][index] = max(bids[:end])
            values["prefix_low_bid_500"][index] = min(bids[:end])
            values["prefix_high_ask_500"][index] = max(asks[:end])
            values["prefix_low_ask_500"][index] = min(asks[:end])
            values["prefix_last_bid_500"][index] = bids[end - 1]
            values["prefix_last_ask_500"][index] = asks[end - 1]

    try:
        for row in cursor:
            received_ns = int(row[0])
            if received_ns < start_ns or received_ns >= end_ns:
                continue
            if previous_received_ns and received_ns < previous_received_ns:
                raise ValueError("raw book receive timestamps are out of order")
            previous_received_ns = received_ns
            second = received_ns // 1_000_000_000
            if current_second is None:
                current_second = second
            elif second != current_second:
                finalize()
                current_second = second
                offsets.clear()
                bids.clear()
                asks.clear()
                mids.clear()
                micros.clear()
                spreads.clear()
            offsets.append(received_ns - second * 1_000_000_000)
            bids.append(float(row[1]))
            asks.append(float(row[2]))
            mids.append(float(row[3]))
            micros.append(float(row[4]))
            spreads.append(float(row[5]))
            processed += 1
            if processed % 2_000_000 == 0:
                progress(
                    f"raw books {processed:,}/{last_id-first_id+1:,} "
                    f"in {time.monotonic()-started:.1f}s"
                )
        finalize()
    finally:
        connection.close()
    progress(f"raw books complete: {processed:,}")


def _rolling_sum(values: numpy.ndarray, window: int) -> numpy.ndarray:
    cleaned = numpy.nan_to_num(values, nan=0.0).astype(numpy.float64)
    cumulative = numpy.concatenate(
        (numpy.asarray([0.0]), numpy.cumsum(cleaned, dtype=numpy.float64))
    )
    output = numpy.full(len(values), numpy.nan, dtype=numpy.float64)
    output[window - 1 :] = cumulative[window:] - cumulative[:-window]
    return output


def _rolling_extreme(
    values: numpy.ndarray, window: int, *, maximum: bool
) -> numpy.ndarray:
    from collections import deque

    output = numpy.full(len(values), numpy.nan, dtype=numpy.float64)
    queue: typing.Deque[int] = deque()
    for index, value in enumerate(values):
        while queue and queue[0] <= index - window:
            queue.popleft()
        if math.isfinite(float(value)):
            if maximum:
                while queue and values[queue[-1]] <= value:
                    queue.pop()
            else:
                while queue and values[queue[-1]] >= value:
                    queue.pop()
            queue.append(index)
        if index >= window - 1 and queue:
            output[index] = values[queue[0]]
    return output


def _rolling_slope(values: numpy.ndarray, window: int) -> numpy.ndarray:
    positions = numpy.arange(len(values), dtype=numpy.float64)
    sum_y = _rolling_sum(values, window)
    sum_xy = _rolling_sum(values * positions, window)
    output = numpy.full(len(values), numpy.nan, dtype=numpy.float64)
    ends = numpy.arange(window - 1, len(values), dtype=numpy.float64)
    starts = ends - window + 1
    sum_x = (starts + ends) * window / 2.0
    sum_x2 = (
        ends * (ends + 1.0) * (2.0 * ends + 1.0)
        - (starts - 1.0)
        * starts
        * (2.0 * starts - 1.0)
    ) / 6.0
    denominator = window * sum_x2 - sum_x * sum_x
    output[window - 1 :] = (
        window * sum_xy[window - 1 :]
        - sum_x * sum_y[window - 1 :]
    ) / denominator
    return output


def _complete_intervals(
    present: numpy.ndarray, starts: numpy.ndarray, lengths: int
) -> numpy.ndarray:
    cumulative = numpy.concatenate(
        (numpy.asarray([0], dtype=numpy.int64), numpy.cumsum(present))
    )
    return (
        cumulative[starts + lengths] - cumulative[starts] == lengths
    )


def _candidate_indices(source: DenseSource) -> numpy.ndarray:
    values = source.values
    present = values["book_event_count"] > 0
    indices = numpy.arange(len(source), dtype=numpy.int64)
    decision_seconds = source.start_second + indices + 1
    eligible = (
        (indices >= MAXIMUM_FEATURE_LOOKBACK_SECONDS - 1)
        & (decision_seconds % DECISION_STRIDE_SECONDS == 0)
        & (
            decision_seconds + HORIZON_SECONDS + 2
            < _iso_timestamp(SELECTION_END)
        )
    )
    candidates = indices[eligible]
    lookback_starts = candidates - MAXIMUM_FEATURE_LOOKBACK_SECONDS + 1
    candidates = candidates[
        _complete_intervals(
            present,
            lookback_starts,
            MAXIMUM_FEATURE_LOOKBACK_SECONDS,
        )
    ]
    primary_starts = candidates + 1
    in_bounds = primary_starts + HORIZON_SECONDS < len(source)
    candidates = candidates[in_bounds]
    primary_starts = candidates + 1
    primary_valid = _complete_intervals(
        present, primary_starts, HORIZON_SECONDS + 1
    )
    stress_starts = candidates + 2
    stress_valid = _complete_intervals(
        present, stress_starts, HORIZON_SECONDS
    )
    quote_valid = (
        numpy.isfinite(values["entry_bid_500"][primary_starts])
        & numpy.isfinite(values["entry_ask_500"][primary_starts])
        & numpy.isfinite(
            values["prefix_last_bid_500"][
                primary_starts + HORIZON_SECONDS
            ]
        )
        & numpy.isfinite(
            values["prefix_last_ask_500"][
                primary_starts + HORIZON_SECONDS
            ]
        )
        & numpy.isfinite(values["entry_bid_0"][stress_starts])
        & numpy.isfinite(values["entry_ask_0"][stress_starts])
    )
    return candidates[primary_valid & stress_valid & quote_valid]


def _build_features(
    source: DenseSource, candidate_indices: numpy.ndarray
) -> tuple[numpy.ndarray, numpy.ndarray]:
    values = source.values
    book_count = values["book_event_count"].astype(numpy.float64)
    trade_count = values["trade_event_count"].astype(numpy.float64)
    mid = values["last_mid"]
    per_second_imbalance = numpy.divide(
        values["imbalance_5_sum"],
        book_count,
        out=numpy.zeros_like(book_count),
        where=book_count > 0,
    )
    log_return_bps = numpy.zeros(len(source), dtype=numpy.float64)
    valid_return = (
        numpy.isfinite(mid[1:])
        & numpy.isfinite(mid[:-1])
        & (mid[1:] > 0)
        & (mid[:-1] > 0)
    )
    log_return_bps[1:][valid_return] = numpy.log(
        mid[1:][valid_return] / mid[:-1][valid_return]
    ) * 10_000.0

    columns: list[numpy.ndarray] = []
    return_by_window: dict[int, numpy.ndarray] = {}
    for window in FEATURE_WINDOWS_SECONDS:
        start = candidate_indices - window + 1
        directional_return = numpy.log(
            mid[candidate_indices] / values["first_mid"][start]
        ) * 10_000.0
        return_by_window[window] = directional_return
        rolling_books = _rolling_sum(book_count, window)[candidate_indices]
        microprice = numpy.divide(
            _rolling_sum(
                values["microprice_premium_bps_sum"], window
            )[candidate_indices],
            rolling_books,
            out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
            where=rolling_books > 0,
        )
        spread_mean = numpy.divide(
            _rolling_sum(values["spread_bps_sum"], window)[candidate_indices],
            rolling_books,
            out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
            where=rolling_books > 0,
        )
        spread_max = _rolling_extreme(
            values["spread_bps_max"], window, maximum=True
        )[candidate_indices]
        book_imbalance = numpy.divide(
            _rolling_sum(values["imbalance_5_sum"], window)[candidate_indices],
            rolling_books,
            out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
            where=rolling_books > 0,
        )
        book_slope = _rolling_slope(
            per_second_imbalance, window
        )[candidate_indices]
        buy_size = _rolling_sum(values["buy_trade_size"], window)[
            candidate_indices
        ]
        sell_size = _rolling_sum(values["sell_trade_size"], window)[
            candidate_indices
        ]
        size_imbalance = numpy.divide(
            buy_size - sell_size,
            buy_size + sell_size,
            out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
            where=(buy_size + sell_size) > 0,
        )
        buy_count = _rolling_sum(
            values["buy_trade_count"].astype(numpy.float64), window
        )[candidate_indices]
        sell_count = _rolling_sum(
            values["sell_trade_count"].astype(numpy.float64), window
        )[candidate_indices]
        count_imbalance = numpy.divide(
            buy_count - sell_count,
            buy_count + sell_count,
            out=numpy.zeros(len(candidate_indices), dtype=numpy.float64),
            where=(buy_count + sell_count) > 0,
        )
        book_intensity = rolling_books / window
        trade_intensity = (
            _rolling_sum(trade_count, window)[candidate_indices] / window
        )
        return_sum = _rolling_sum(log_return_bps, window)[candidate_indices]
        return_square_sum = _rolling_sum(
            log_return_bps * log_return_bps, window
        )[candidate_indices]
        volatility = numpy.sqrt(
            numpy.maximum(
                0.0,
                return_square_sum / window
                - (return_sum / window) ** 2,
            )
        )
        high = _rolling_extreme(
            values["high_mid"], window, maximum=True
        )[candidate_indices]
        low = _rolling_extreme(
            values["low_mid"], window, maximum=False
        )[candidate_indices]
        high_low_range = (high / low - 1.0) * 10_000.0
        columns.extend(
            (
                directional_return,
                microprice,
                spread_mean,
                spread_max,
                book_imbalance,
                book_slope,
                size_imbalance,
                count_imbalance,
                book_intensity,
                trade_intensity,
                volatility,
                high_low_range,
            )
        )

    context_returns = {}
    for window in CONTEXT_WINDOWS_SECONDS:
        start = candidate_indices - window + 1
        context_returns[window] = numpy.log(
            mid[candidate_indices] / values["first_mid"][start]
        ) * 10_000.0
    regime_ratio = numpy.clip(
        context_returns[60] / (numpy.abs(context_returns[300]) + 1.0),
        -10.0,
        10.0,
    )
    decision_seconds = source.start_second + candidate_indices + 1
    hour_angle = (
        (decision_seconds % 86_400) / 86_400.0 * 2.0 * math.pi
    )
    columns.extend(
        (
            context_returns[60],
            context_returns[300],
            regime_ratio,
            numpy.sin(hour_angle),
            numpy.cos(hour_angle),
        )
    )
    features = numpy.column_stack(columns).astype(numpy.float32)
    finite = numpy.all(numpy.isfinite(features), axis=1)
    return features[finite], candidate_indices[finite]


def _direction_outcome(
    source: DenseSource,
    candidate_indices: numpy.ndarray,
    *,
    direction: int,
    latency_ms: int,
    cost_multiplier: float,
) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    values = source.values
    count = len(candidate_indices)
    sentinel = numpy.int16(32_767)
    target_time = numpy.full(count, sentinel, dtype=numpy.int16)
    stop_time = numpy.full(count, sentinel, dtype=numpy.int16)

    if latency_ms == 500:
        starts = candidate_indices + 1
        entry_bid = values["entry_bid_500"][starts]
        entry_ask = values["entry_ask_500"][starts]
        entry_ns = values["entry_ns_500"][starts]
        initial_high_bid = values["suffix_high_bid_500"][starts]
        initial_low_bid = values["suffix_low_bid_500"][starts]
        initial_high_ask = values["suffix_high_ask_500"][starts]
        initial_low_ask = values["suffix_low_ask_500"][starts]
        deadline_indices = starts + HORIZON_SECONDS
        timeout_bid = values["prefix_last_bid_500"][deadline_indices]
        timeout_ask = values["prefix_last_ask_500"][deadline_indices]
        final_extremes = (
            values["prefix_high_bid_500"][deadline_indices],
            values["prefix_low_bid_500"][deadline_indices],
            values["prefix_high_ask_500"][deadline_indices],
            values["prefix_low_ask_500"][deadline_indices],
        )
    elif latency_ms == 1_000:
        starts = candidate_indices + 2
        entry_bid = values["entry_bid_0"][starts]
        entry_ask = values["entry_ask_0"][starts]
        entry_ns = values["entry_ns_0"][starts]
        initial_high_bid = values["suffix_high_bid_0"][starts]
        initial_low_bid = values["suffix_low_bid_0"][starts]
        initial_high_ask = values["suffix_high_ask_0"][starts]
        initial_low_ask = values["suffix_low_ask_0"][starts]
        deadline_indices = starts + HORIZON_SECONDS - 1
        timeout_bid = values["last_bid"][deadline_indices]
        timeout_ask = values["last_ask"][deadline_indices]
        final_extremes = None
    else:
        raise ValueError("unsupported frozen latency")

    entry = entry_ask if direction == 1 else entry_bid
    target_price = entry * (1.0 + direction * TARGET_BPS / 10_000.0)
    stop_price = entry * (1.0 - direction * STOP_BPS / 10_000.0)

    def update(
        high_bid: numpy.ndarray,
        low_bid: numpy.ndarray,
        high_ask: numpy.ndarray,
        low_ask: numpy.ndarray,
        step: int,
    ) -> None:
        if direction == 1:
            target_hit = high_bid >= target_price
            stop_hit = low_bid <= stop_price
        else:
            target_hit = low_ask <= target_price
            stop_hit = high_ask >= stop_price
        target_time[(target_time == sentinel) & target_hit] = step
        stop_time[(stop_time == sentinel) & stop_hit] = step

    update(
        initial_high_bid,
        initial_low_bid,
        initial_high_ask,
        initial_low_ask,
        0,
    )
    for step in range(1, HORIZON_SECONDS):
        indices = starts + step
        update(
            values["high_bid"][indices],
            values["low_bid"][indices],
            values["high_ask"][indices],
            values["low_ask"][indices],
            step,
        )
    if final_extremes is not None:
        update(*final_extremes, HORIZON_SECONDS)

    target = (target_time < stop_time) & (target_time != sentinel)
    stop = (stop_time <= target_time) & (stop_time != sentinel)
    reason = numpy.full(count, _OUTCOME_TIMEOUT, dtype=numpy.int8)
    reason[target] = _OUTCOME_TARGET
    reason[stop] = _OUTCOME_STOP
    timeout_return = (
        timeout_bid / entry_ask - 1.0
        if direction == 1
        else entry_bid / timeout_ask - 1.0
    )
    gross_return = numpy.where(
        target,
        TARGET_BPS / 10_000.0,
        numpy.where(stop, -STOP_BPS / 10_000.0, timeout_return),
    )
    cost = (
        2.0
        * (FEE_BPS_PER_FILL + SLIPPAGE_BPS_PER_FILL)
        * cost_multiplier
        / 10_000.0
    )
    net_return = (gross_return - cost).astype(numpy.float32)
    hit_time = numpy.where(target, target_time, stop_time).astype(numpy.int64)
    entry_second = entry_ns // 1_000_000_000
    exit_second = numpy.where(
        target | stop,
        entry_second + hit_time,
        entry_second + HORIZON_SECONDS,
    ).astype(numpy.int64)
    return (reason == _OUTCOME_TARGET).astype(numpy.uint8), net_return, exit_second


def build_pretest_dataset(
    *,
    database_value: typing.Union[str, pathlib.Path],
    freeze_manifest_value: typing.Union[str, pathlib.Path],
    protocol_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    """Build development/selection rows without opening the locked test."""

    progress = progress or (lambda _message: None)
    database = pathlib.Path(database_value).resolve()
    freeze_manifest_path = pathlib.Path(freeze_manifest_value).resolve()
    protocol_path = pathlib.Path(protocol_value).resolve()
    output = pathlib.Path(output_value).resolve()
    persisted_protocol = write_or_verify_protocol(protocol_path)
    if persisted_protocol["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("wrong scalping implementation protocol")
    freeze = json.loads(freeze_manifest_path.read_text(encoding="utf-8"))
    artifact = freeze.get("artifacts", {}).get("scalping_level5", {})
    if artifact.get("sha256") != SNAPSHOT_SHA256:
        raise ValueError("frozen snapshot hash differs from preregistration")
    if freeze.get("manifest_sha256") != SNAPSHOT_MANIFEST_SHA256:
        raise ValueError("frozen manifest hash differs from preregistration")
    if freeze.get("full_offline_integrity_and_gap_audit") is not True:
        raise ValueError("frozen snapshot did not pass the offline audit")
    if freeze.get("readiness", {}).get("ready") is not True:
        raise ValueError("frozen snapshot is not ready for evaluation")
    if database.stat().st_size != int(artifact.get("bytes", -1)):
        raise ValueError("frozen snapshot byte size differs")

    start_second = _iso_timestamp(SOURCE_START)
    end_second = _iso_timestamp(SELECTION_END) - 1
    progress("loading one-second frozen aggregates")
    source = _read_dense_seconds(database, start_second, end_second)
    progress("streaming raw Level 5 books for execution-aware summaries")
    _augment_from_raw_books(database, source, progress=progress)
    base_candidates = _candidate_indices(source)
    progress(f"causal candidates before finite-feature filter: {len(base_candidates):,}")
    features, candidates = _build_features(source, base_candidates)
    progress(f"causal candidates retained: {len(candidates):,}")

    primary_long = _direction_outcome(
        source,
        candidates,
        direction=1,
        latency_ms=PRIMARY_LATENCY_MS,
        cost_multiplier=1.0,
    )
    primary_short = _direction_outcome(
        source,
        candidates,
        direction=-1,
        latency_ms=PRIMARY_LATENCY_MS,
        cost_multiplier=1.0,
    )
    stress_long = _direction_outcome(
        source,
        candidates,
        direction=1,
        latency_ms=STRESS_LATENCY_MS,
        cost_multiplier=COST_STRESS_MULTIPLIER,
    )
    stress_short = _direction_outcome(
        source,
        candidates,
        direction=-1,
        latency_ms=STRESS_LATENCY_MS,
        cost_multiplier=COST_STRESS_MULTIPLIER,
    )
    dataset = ScalpingResearchDataset(
        timestamps=(source.start_second + candidates + 1).astype(numpy.int64),
        features=features,
        primary_long_label=primary_long[0],
        primary_short_label=primary_short[0],
        primary_long_return=primary_long[1],
        primary_short_return=primary_short[1],
        primary_long_exit=primary_long[2],
        primary_short_exit=primary_short[2],
        stress_long_return=stress_long[1],
        stress_short_return=stress_short[1],
        stress_long_exit=stress_long[2],
        stress_short_exit=stress_short[2],
    )
    artifact_report = dataset.save(output)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": "pretest_scalping_research_dataset",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": persisted_protocol["protocol_sha256"],
        "source_snapshot_sha256": SNAPSHOT_SHA256,
        "locked_test_materialized": False,
        "locked_test_start": SELECTION_END,
        "rows": len(dataset.timestamps),
        "first_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[0]), datetime.timezone.utc
        ).isoformat(),
        "last_decision": datetime.datetime.fromtimestamp(
            int(dataset.timestamps[-1]), datetime.timezone.utc
        ).isoformat(),
        "feature_count": len(FEATURE_NAMES),
        "artifact": artifact_report,
    }
    manifest_path = output.with_suffix(".manifest.json")
    _atomic_json(manifest_path, manifest)
    return {**manifest, "manifest": str(manifest_path)}


def _fit_model(
    name: str,
    features: numpy.ndarray,
    labels: numpy.ndarray,
) -> typing.Union[
    model_module.NumpyLogisticModel,
    model_module.NumpyGradientBoostingModel,
]:
    if name == "numpy_logistic":
        return model_module.NumpyLogisticModel.fit(
            features, labels, FEATURE_NAMES, LOGISTIC_CONFIG
        )
    if name == "numpy_gradient_boosting":
        return model_module.NumpyGradientBoostingModel.fit(
            features, labels, FEATURE_NAMES, BOOSTING_CONFIG
        )
    raise ValueError(f"unknown frozen model family: {name}")


def _stack_directional_rows(
    dataset: ScalpingResearchDataset,
    indices: numpy.ndarray,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    features = numpy.concatenate(
        (
            dataset.directional_features(indices, 1),
            dataset.directional_features(indices, -1),
        )
    )
    labels = numpy.concatenate(
        (
            dataset.primary_long_label[indices],
            dataset.primary_short_label[indices],
        )
    ).astype(numpy.uint8)
    return features, labels


def _predict_directions(
    dataset: ScalpingResearchDataset,
    indices: numpy.ndarray,
    model: typing.Any,
    calibrator: percentage_probability_engine.QuantileIsotonicCalibrator,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    long_probability = calibrator.predict(
        model.predict_proba(dataset.directional_features(indices, 1))
    )
    short_probability = calibrator.predict(
        model.predict_proba(dataset.directional_features(indices, -1))
    )
    return long_probability, short_probability


def _fit_with_calibration(
    dataset: ScalpingResearchDataset,
    available_indices: numpy.ndarray,
    *,
    model_name: str,
) -> tuple[
    typing.Any,
    percentage_probability_engine.QuantileIsotonicCalibrator,
    numpy.ndarray,
    dict,
]:
    if len(available_indices) < 2_000:
        raise ValueError("insufficient rows for frozen fit/calibration split")
    split_position = int(
        len(available_indices) * (1.0 - CALIBRATION_FRACTION)
    )
    calibration_start = int(dataset.timestamps[available_indices[split_position]])
    fit_end = calibration_start - EMBARGO_SECONDS
    fit_indices = available_indices[
        (dataset.timestamps[available_indices] < fit_end)
        & (
            dataset.timestamps[available_indices]
            % TRAINING_STRIDE_SECONDS
            == 0
        )
    ]
    calibration_indices = available_indices[split_position:]
    if len(fit_indices) < 1_000 or len(calibration_indices) < 500:
        raise ValueError("frozen fit/calibration split is too small")
    fit_features, fit_labels = _stack_directional_rows(dataset, fit_indices)
    model = _fit_model(model_name, fit_features, fit_labels)
    calibration_features, calibration_labels = _stack_directional_rows(
        dataset, calibration_indices
    )
    raw_probability = model.predict_proba(calibration_features)
    calibrator = (
        percentage_probability_engine.QuantileIsotonicCalibrator.fit(
            raw_probability,
            calibration_labels,
            maximum_bins=100,
            minimum_rows_per_bin=200,
        )
    )
    calibrated = calibrator.predict(raw_probability)
    diagnostics = {
        "fit_rows": int(len(fit_features)),
        "fit_decisions": int(len(fit_indices)),
        "calibration_rows": int(len(calibration_features)),
        "calibration_decisions": int(len(calibration_indices)),
        "calibration_start": datetime.datetime.fromtimestamp(
            calibration_start, datetime.timezone.utc
        ).isoformat(),
        "fit_base_rate": float(numpy.mean(fit_labels)),
        "calibration_base_rate": float(numpy.mean(calibration_labels)),
        "calibration_brier": float(
            numpy.mean((calibrated - calibration_labels) ** 2)
        ),
        "calibration_constant_brier": float(
            numpy.mean(
                (
                    numpy.mean(calibration_labels)
                    - calibration_labels
                )
                ** 2
            )
        ),
    }
    return model, calibrator, calibration_indices, diagnostics


def _signals(
    long_probability: numpy.ndarray,
    short_probability: numpy.ndarray,
    threshold: float,
) -> numpy.ndarray:
    direction = numpy.zeros(len(long_probability), dtype=numpy.int8)
    margin = numpy.abs(long_probability - short_probability)
    eligible = (
        numpy.maximum(long_probability, short_probability) >= threshold
    ) & (margin >= DIRECTION_MARGIN)
    direction[eligible & (long_probability > short_probability)] = 1
    direction[eligible & (short_probability > long_probability)] = -1
    return direction


def _simulate_trades(
    dataset: ScalpingResearchDataset,
    indices: numpy.ndarray,
    long_probability: numpy.ndarray,
    short_probability: numpy.ndarray,
    threshold: float,
    *,
    stress: bool,
) -> dict[str, numpy.ndarray]:
    directions = _signals(long_probability, short_probability, threshold)
    selected_rows: list[int] = []
    selected_directions: list[int] = []
    selected_returns: list[float] = []
    selected_exits: list[int] = []
    selected_probabilities: list[float] = []
    free_after = -1
    for position, row in enumerate(indices):
        timestamp = int(dataset.timestamps[row])
        direction = int(directions[position])
        if direction == 0 or timestamp <= free_after:
            continue
        prefix = "stress" if stress else "primary"
        side = "long" if direction == 1 else "short"
        trade_return = float(
            getattr(dataset, f"{prefix}_{side}_return")[row]
        )
        exit_timestamp = int(
            getattr(dataset, f"{prefix}_{side}_exit")[row]
        )
        if exit_timestamp <= timestamp:
            raise ValueError("trade exit is not after its decision")
        selected_rows.append(int(row))
        selected_directions.append(direction)
        selected_returns.append(trade_return)
        selected_exits.append(exit_timestamp)
        selected_probabilities.append(
            float(
                long_probability[position]
                if direction == 1
                else short_probability[position]
            )
        )
        free_after = exit_timestamp
    return {
        "rows": numpy.asarray(selected_rows, dtype=numpy.int64),
        "directions": numpy.asarray(selected_directions, dtype=numpy.int8),
        "instrument_returns": numpy.asarray(
            selected_returns, dtype=numpy.float64
        ),
        "exit_timestamps": numpy.asarray(selected_exits, dtype=numpy.int64),
        "probabilities": numpy.asarray(
            selected_probabilities, dtype=numpy.float64
        ),
    }


def _trade_metrics(
    dataset: ScalpingResearchDataset,
    trades: dict[str, numpy.ndarray],
) -> dict:
    instrument_returns = trades["instrument_returns"]
    portfolio_returns = instrument_returns * POSITION_FRACTION
    if not len(portfolio_returns):
        return {
            "trades": 0,
            "wins": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "average_instrument_return_bps": 0.0,
            "positive_operating_days_pct": 0.0,
            "operating_days": 0,
            "positive_days": 0,
            "by_direction": {
                "long": {"trades": 0, "total_return": 0.0},
                "short": {"trades": 0, "total_return": 0.0},
            },
        }
    equity = numpy.cumprod(1.0 + portfolio_returns)
    peaks = numpy.maximum.accumulate(
        numpy.concatenate((numpy.asarray([1.0]), equity))
    )[1:]
    drawdown = 1.0 - equity / peaks
    profits = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    gross_profit = float(numpy.sum(profits))
    gross_loss = float(-numpy.sum(losses))
    day_returns: dict[str, list[float]] = {}
    for row, trade_return in zip(trades["rows"], portfolio_returns):
        day = datetime.datetime.fromtimestamp(
            int(dataset.timestamps[row]), datetime.timezone.utc
        ).date().isoformat()
        day_returns.setdefault(day, []).append(float(trade_return))
    compounded_days = {
        day: float(numpy.prod(1.0 + numpy.asarray(values)) - 1.0)
        for day, values in day_returns.items()
    }
    by_direction = {}
    for direction, name in ((1, "long"), (-1, "short")):
        selected = portfolio_returns[trades["directions"] == direction]
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
                        instrument_returns[
                            trades["directions"] == direction
                        ]
                    )
                    * 10_000.0
                )
                if len(selected)
                else 0.0
            ),
        }
    positive_days = sum(value > 0 for value in compounded_days.values())
    return {
        "trades": int(len(portfolio_returns)),
        "wins": int(numpy.sum(portfolio_returns > 0)),
        "win_rate": float(numpy.mean(portfolio_returns > 0)),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else (float("inf") if gross_profit > 0 else 0.0)
        ),
        "total_return": float(equity[-1] - 1.0),
        "max_drawdown": float(numpy.max(drawdown)),
        "average_instrument_return_bps": float(
            numpy.mean(instrument_returns) * 10_000.0
        ),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "operating_days": len(compounded_days),
        "positive_days": positive_days,
        "positive_operating_days_pct": (
            positive_days / len(compounded_days) * 100.0
        ),
        "daily_returns": compounded_days,
        "by_direction": by_direction,
    }


def _calibration_metrics(
    dataset: ScalpingResearchDataset,
    indices: numpy.ndarray,
    long_probability: numpy.ndarray,
    short_probability: numpy.ndarray,
    constant_probability: float,
) -> dict:
    labels = numpy.concatenate(
        (
            dataset.primary_long_label[indices],
            dataset.primary_short_label[indices],
        )
    ).astype(numpy.float64)
    probabilities = numpy.concatenate(
        (long_probability, short_probability)
    ).astype(numpy.float64)
    return {
        "rows": int(len(labels)),
        "base_rate": float(numpy.mean(labels)),
        "mean_probability": float(numpy.mean(probabilities)),
        "brier": float(numpy.mean((probabilities - labels) ** 2)),
        "constant_brier": float(
            numpy.mean((float(constant_probability) - labels) ** 2)
        ),
        "expected_calibration_error": float(
            model_module.expected_calibration_error(labels, probabilities)
        ),
    }


def _gate_checks(
    primary: dict,
    stress: dict,
    calibration: dict,
    *,
    minimum_trades: int,
    minimum_positive_folds: int | None = None,
    positive_folds: int | None = None,
) -> dict:
    checks = {
        "minimum_trades": primary["trades"] >= minimum_trades,
        "profit_factor": primary["profit_factor"] >= 1.20,
        "maximum_drawdown": primary["max_drawdown"] <= 0.05,
        "positive_operating_days": (
            primary["positive_operating_days_pct"] >= 55.0
        ),
        "long_non_negative": (
            primary["by_direction"]["long"]["trades"] > 0
            and primary["by_direction"]["long"]["total_return"] >= 0
        ),
        "short_non_negative": (
            primary["by_direction"]["short"]["trades"] > 0
            and primary["by_direction"]["short"]["total_return"] >= 0
        ),
        "calibration_better_than_constant": (
            calibration["brier"] < calibration["constant_brier"]
        ),
        "stress_positive": stress["total_return"] > 0,
    }
    if minimum_positive_folds is not None:
        checks["positive_folds"] = (
            positive_folds is not None
            and positive_folds >= minimum_positive_folds
        )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
    }


def _json_safe(value: typing.Any) -> typing.Any:
    if isinstance(value, dict):
        return {key: _json_safe(element) for key, element in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(element) for element in value]
    if isinstance(value, numpy.ndarray):
        return [_json_safe(element) for element in value.tolist()]
    if isinstance(value, numpy.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _combine_trades(parts: list[dict[str, numpy.ndarray]]) -> dict[str, numpy.ndarray]:
    if not parts:
        return {
            "rows": numpy.asarray([], dtype=numpy.int64),
            "directions": numpy.asarray([], dtype=numpy.int8),
            "instrument_returns": numpy.asarray([], dtype=numpy.float64),
            "exit_timestamps": numpy.asarray([], dtype=numpy.int64),
            "probabilities": numpy.asarray([], dtype=numpy.float64),
        }
    return {
        name: numpy.concatenate([part[name] for part in parts])
        for name in parts[0]
    }


def _aggregate_calibration(parts: list[dict]) -> dict:
    total_rows = sum(int(part["rows"]) for part in parts)
    if total_rows == 0:
        raise ValueError("no calibration diagnostics to aggregate")
    return {
        "rows": total_rows,
        "base_rate": sum(
            part["base_rate"] * part["rows"] for part in parts
        )
        / total_rows,
        "mean_probability": sum(
            part["mean_probability"] * part["rows"] for part in parts
        )
        / total_rows,
        "brier": sum(part["brier"] * part["rows"] for part in parts)
        / total_rows,
        "constant_brier": sum(
            part["constant_brier"] * part["rows"] for part in parts
        )
        / total_rows,
        "expected_calibration_error": sum(
            part["expected_calibration_error"] * part["rows"]
            for part in parts
        )
        / total_rows,
    }


def _development_folds(
    dataset: ScalpingResearchDataset,
) -> list[tuple[numpy.ndarray, numpy.ndarray]]:
    development = numpy.flatnonzero(
        dataset.timestamps < _iso_timestamp(TRAIN_END)
    )
    if len(development) < WALK_FORWARD_FOLDS + 1:
        raise ValueError("development block is too small")
    test_size = len(development) // (WALK_FORWARD_FOLDS + 1)
    if test_size < 1:
        raise ValueError("walk-forward test size is empty")
    folds = []
    for fold in range(WALK_FORWARD_FOLDS):
        test_start_position = (fold + 1) * test_size
        test_end_position = (
            len(development)
            if fold == WALK_FORWARD_FOLDS - 1
            else test_start_position + test_size
        )
        test = development[test_start_position:test_end_position]
        test_start = int(dataset.timestamps[test[0]])
        train = development[
            dataset.timestamps[development] < test_start - EMBARGO_SECONDS
        ]
        folds.append((train, test))
    return folds


def _candidate_rank(report: dict) -> tuple:
    stress_profit_factor = report["stress"]["profit_factor"]
    if not math.isfinite(float(stress_profit_factor)):
        stress_profit_factor = 1_000.0
    return (
        int(report["gate"]["passed_checks"]),
        float(stress_profit_factor),
        float(report["stress"]["total_return"]),
        float(report["primary"]["total_return"]),
        int(report["primary"]["trades"]),
        report["model"],
        -float(report["probability_quantile"]),
    )


def _save_model(
    model: typing.Any,
    model_name: str,
    path: pathlib.Path,
) -> dict:
    if model_name not in {"numpy_logistic", "numpy_gradient_boosting"}:
        raise ValueError("unknown model name")
    return model.save(path)


def _load_model(model_name: str, path: pathlib.Path) -> typing.Any:
    if model_name == "numpy_logistic":
        return model_module.NumpyLogisticModel.load(path)
    if model_name == "numpy_gradient_boosting":
        return model_module.NumpyGradientBoostingModel.load(path)
    raise ValueError("unknown model name")


def evaluate_pretest(
    *,
    dataset_value: typing.Union[str, pathlib.Path],
    dataset_manifest_value: typing.Union[str, pathlib.Path],
    protocol_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
    progress: typing.Callable[[str], None] | None = None,
) -> dict:
    """Run development and selection, leaving the final block unopened."""

    progress = progress or (lambda _message: None)
    protocol_path = pathlib.Path(protocol_value).resolve()
    persisted_protocol = write_or_verify_protocol(protocol_path)
    dataset_path = pathlib.Path(dataset_value).resolve()
    dataset_manifest_path = pathlib.Path(dataset_manifest_value).resolve()
    dataset_manifest = json.loads(
        dataset_manifest_path.read_text(encoding="utf-8")
    )
    if dataset_manifest.get("locked_test_materialized") is not False:
        raise ValueError("pre-test dataset unexpectedly materialized locked data")
    if dataset_manifest.get("protocol_sha256") != persisted_protocol.get(
        "protocol_sha256"
    ):
        raise ValueError("dataset and protocol hashes differ")
    dataset = ScalpingResearchDataset.load(
        dataset_path,
        expected_sha256=dataset_manifest.get("artifact", {}).get("sha256"),
    )
    folds = _development_folds(dataset)
    candidate_parts: dict[tuple[str, float], dict] = {
        (model_name, quantile): {
            "primary_trades": [],
            "stress_trades": [],
            "calibration": [],
            "folds": [],
            "thresholds": [],
        }
        for model_name in ("numpy_logistic", "numpy_gradient_boosting")
        for quantile in PROBABILITY_QUANTILES
    }

    for fold_number, (train_indices, test_indices) in enumerate(folds, 1):
        progress(
            f"walk-forward fold {fold_number}/{WALK_FORWARD_FOLDS}: "
            f"train={len(train_indices):,} test={len(test_indices):,}"
        )
        for model_name in ("numpy_logistic", "numpy_gradient_boosting"):
            progress(f"fold {fold_number}: fitting {model_name}")
            model, calibrator, calibration_indices, fit_report = (
                _fit_with_calibration(
                    dataset, train_indices, model_name=model_name
                )
            )
            calibration_long, calibration_short = _predict_directions(
                dataset, calibration_indices, model, calibrator
            )
            test_long, test_short = _predict_directions(
                dataset, test_indices, model, calibrator
            )
            calibration_report = _calibration_metrics(
                dataset,
                test_indices,
                test_long,
                test_short,
                fit_report["calibration_base_rate"],
            )
            calibration_probabilities = numpy.concatenate(
                (calibration_long, calibration_short)
            )
            for quantile in PROBABILITY_QUANTILES:
                threshold = float(
                    numpy.quantile(calibration_probabilities, quantile)
                )
                primary_trades = _simulate_trades(
                    dataset,
                    test_indices,
                    test_long,
                    test_short,
                    threshold,
                    stress=False,
                )
                stress_trades = _simulate_trades(
                    dataset,
                    test_indices,
                    test_long,
                    test_short,
                    threshold,
                    stress=True,
                )
                primary_metrics = _trade_metrics(dataset, primary_trades)
                stress_metrics = _trade_metrics(dataset, stress_trades)
                part = candidate_parts[(model_name, quantile)]
                part["primary_trades"].append(primary_trades)
                part["stress_trades"].append(stress_trades)
                part["calibration"].append(calibration_report)
                part["thresholds"].append(threshold)
                part["folds"].append(
                    {
                        "fold": fold_number,
                        "test_start": datetime.datetime.fromtimestamp(
                            int(dataset.timestamps[test_indices[0]]),
                            datetime.timezone.utc,
                        ).isoformat(),
                        "test_end": datetime.datetime.fromtimestamp(
                            int(dataset.timestamps[test_indices[-1]]),
                            datetime.timezone.utc,
                        ).isoformat(),
                        "threshold": threshold,
                        "fit": fit_report,
                        "calibration": calibration_report,
                        "primary": primary_metrics,
                        "stress": stress_metrics,
                    }
                )

    candidates = []
    for (model_name, quantile), part in candidate_parts.items():
        primary = _trade_metrics(
            dataset, _combine_trades(part["primary_trades"])
        )
        stress = _trade_metrics(
            dataset, _combine_trades(part["stress_trades"])
        )
        calibration = _aggregate_calibration(part["calibration"])
        positive_folds = sum(
            fold["primary"]["total_return"] > 0
            for fold in part["folds"]
        )
        gate = _gate_checks(
            primary,
            stress,
            calibration,
            minimum_trades=500,
            minimum_positive_folds=4,
            positive_folds=positive_folds,
        )
        candidates.append(
            {
                "model": model_name,
                "probability_quantile": quantile,
                "thresholds": {
                    "minimum": min(part["thresholds"]),
                    "maximum": max(part["thresholds"]),
                    "mean": float(numpy.mean(part["thresholds"])),
                },
                "primary": primary,
                "stress": stress,
                "calibration": calibration,
                "positive_folds": positive_folds,
                "folds": part["folds"],
                "gate": gate,
            }
        )
    candidates.sort(key=_candidate_rank, reverse=True)
    chosen = candidates[0]
    progress(
        "development choice: "
        f"{chosen['model']} q={chosen['probability_quantile']} "
        f"gate={chosen['gate']['passed']}"
    )

    development_indices = numpy.flatnonzero(
        dataset.timestamps < _iso_timestamp(TRAIN_END)
    )
    final_model, final_calibrator, final_calibration_indices, fit_report = (
        _fit_with_calibration(
            dataset,
            development_indices,
            model_name=chosen["model"],
        )
    )
    final_calibration_long, final_calibration_short = _predict_directions(
        dataset,
        final_calibration_indices,
        final_model,
        final_calibrator,
    )
    frozen_threshold = float(
        numpy.quantile(
            numpy.concatenate(
                (final_calibration_long, final_calibration_short)
            ),
            chosen["probability_quantile"],
        )
    )
    selection_indices = numpy.flatnonzero(
        (dataset.timestamps >= _iso_timestamp(TRAIN_END))
        & (dataset.timestamps < _iso_timestamp(SELECTION_END))
    )
    selection_long, selection_short = _predict_directions(
        dataset, selection_indices, final_model, final_calibrator
    )
    selection_primary_trades = _simulate_trades(
        dataset,
        selection_indices,
        selection_long,
        selection_short,
        frozen_threshold,
        stress=False,
    )
    selection_stress_trades = _simulate_trades(
        dataset,
        selection_indices,
        selection_long,
        selection_short,
        frozen_threshold,
        stress=True,
    )
    selection_primary = _trade_metrics(dataset, selection_primary_trades)
    selection_stress = _trade_metrics(dataset, selection_stress_trades)
    selection_calibration = _calibration_metrics(
        dataset,
        selection_indices,
        selection_long,
        selection_short,
        fit_report["calibration_base_rate"],
    )
    selection_gate = _gate_checks(
        selection_primary,
        selection_stress,
        selection_calibration,
        minimum_trades=100,
    )
    locked_authorized = bool(
        chosen["gate"]["passed"] and selection_gate["passed"]
    )

    created_at = datetime.datetime.now(datetime.timezone.utc)
    experiment_id = (
        f"{PROTOCOL_VERSION}-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    )
    output_root = pathlib.Path(output_root_value).resolve()
    experiment = output_root / experiment_id
    experiment.mkdir(parents=True, exist_ok=False)
    model_path = experiment / "model.npz"
    model_artifact = _save_model(final_model, chosen["model"], model_path)
    calibrator_path = experiment / "calibrator.json"
    final_calibrator.save(calibrator_path)
    calibrator_artifact = {
        "path": str(calibrator_path),
        "bytes": calibrator_path.stat().st_size,
        "sha256": _sha256(calibrator_path),
    }
    reloaded_model = _load_model(chosen["model"], model_path)
    reloaded_calibrator = (
        percentage_probability_engine.QuantileIsotonicCalibrator.load(
            calibrator_path
        )
    )
    reproduced_long, reproduced_short = _predict_directions(
        dataset,
        selection_indices,
        reloaded_model,
        reloaded_calibrator,
    )
    maximum_reproduction_difference = max(
        float(numpy.max(numpy.abs(reproduced_long - selection_long))),
        float(numpy.max(numpy.abs(reproduced_short - selection_short))),
    )
    if maximum_reproduction_difference > 1e-12:
        raise RuntimeError("saved scalping model does not reproduce predictions")

    trade_path = experiment / "selection_trades.npz"
    with trade_path.open("wb") as stream:
        numpy.savez_compressed(
            stream,
            rows=selection_primary_trades["rows"],
            timestamps=dataset.timestamps[selection_primary_trades["rows"]],
            directions=selection_primary_trades["directions"],
            instrument_returns=selection_primary_trades[
                "instrument_returns"
            ],
            exit_timestamps=selection_primary_trades["exit_timestamps"],
            probabilities=selection_primary_trades["probabilities"],
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
            "sha256": persisted_protocol["protocol_sha256"],
        },
        "dataset": {
            "sha256": dataset_manifest["artifact"]["sha256"],
            "rows": len(dataset.timestamps),
            "locked_test_materialized": False,
        },
        "configuration": {
            "target_bps": TARGET_BPS,
            "stop_bps": STOP_BPS,
            "horizon_seconds": HORIZON_SECONDS,
            "primary_latency_ms": PRIMARY_LATENCY_MS,
            "stress_latency_ms": STRESS_LATENCY_MS,
            "position_fraction": POSITION_FRACTION,
        },
        "development": {
            "chosen_candidate": {
                key: chosen[key]
                for key in (
                    "model",
                    "probability_quantile",
                    "thresholds",
                    "primary",
                    "stress",
                    "calibration",
                    "positive_folds",
                    "gate",
                )
            },
            "all_candidates": candidates,
        },
        "frozen_model": {
            "model": model_artifact,
            "calibrator": calibrator_artifact,
            "fit": fit_report,
            "probability_threshold": frozen_threshold,
            "maximum_reproduction_difference": (
                maximum_reproduction_difference
            ),
        },
        "independent_selection": {
            "start": TRAIN_END,
            "end": SELECTION_END,
            "primary": selection_primary,
            "stress": selection_stress,
            "calibration": selection_calibration,
            "gate": selection_gate,
        },
        "locked_final_test": {
            "start": SELECTION_END,
            "end": LOCKED_TEST_END,
            "status": (
                "authorized_but_not_opened"
                if locked_authorized
                else "sealed_gate_failed"
            ),
            "authorized_to_open": locked_authorized,
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
    _atomic_json(report_path, _json_safe(report))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "created_at": created_at.isoformat(),
        "research_only": True,
        "orders_authorized": False,
        "protocol_sha256": persisted_protocol["protocol_sha256"],
        "dataset_sha256": dataset_manifest["artifact"]["sha256"],
        "model": model_artifact,
        "calibrator": calibrator_artifact,
        "selection_trades": {
            "path": str(trade_path),
            "bytes": trade_path.stat().st_size,
            "sha256": _sha256(trade_path),
        },
        "report": {
            "path": str(report_path),
            "bytes": report_path.stat().st_size,
            "sha256": _sha256(report_path),
        },
        "locked_test_authorized": locked_authorized,
    }
    manifest_path = experiment / "manifest.json"
    _atomic_json(manifest_path, manifest)
    registry_entry = {
        "experiment_id": experiment_id,
        "created_at": created_at.isoformat(),
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "protocol_sha256": persisted_protocol["protocol_sha256"],
        "dataset_sha256": dataset_manifest["artifact"]["sha256"],
        "development_gate_passed": chosen["gate"]["passed"],
        "selection_gate_passed": selection_gate["passed"],
        "locked_test_authorized": locked_authorized,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "experiments.jsonl").open(
        "a", encoding="utf-8"
    ) as registry:
        registry.write(json.dumps(registry_entry, sort_keys=True) + "\n")
    return {
        "experiment_id": experiment_id,
        "experiment_directory": str(experiment),
        "report": str(report_path),
        "development_gate_passed": chosen["gate"]["passed"],
        "selection_gate_passed": selection_gate["passed"],
        "locked_test_authorized": locked_authorized,
    }


def main(arguments: typing.Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    protocol_parser = subparsers.add_parser("write-protocol")
    protocol_parser.add_argument("--output", required=True)
    dataset_parser = subparsers.add_parser("build-pretest-dataset")
    dataset_parser.add_argument("--database", required=True)
    dataset_parser.add_argument("--freeze-manifest", required=True)
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
        payload = write_or_verify_protocol(parsed.output)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if parsed.command == "build-pretest-dataset":
        report = build_pretest_dataset(
            database_value=parsed.database,
            freeze_manifest_value=parsed.freeze_manifest,
            protocol_value=parsed.protocol,
            output_value=parsed.output,
            progress=progress,
        )
        print(json.dumps(_json_safe(report), indent=2, sort_keys=True))
        return 0
    if parsed.command == "evaluate-pretest":
        report = evaluate_pretest(
            dataset_value=parsed.dataset,
            dataset_manifest_value=parsed.dataset_manifest,
            protocol_value=parsed.protocol,
            output_root_value=parsed.output_root,
            progress=progress,
        )
        print(json.dumps(_json_safe(report), indent=2, sort_keys=True))
        return 0
    raise AssertionError("unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
