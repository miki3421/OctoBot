"""Offline BTC futures passive-execution feasibility protocol V1.

This module asks whether the collected Level-5 book can reduce the execution
cost of an already independent, slow signal.  It does not predict direction
and it cannot place orders.  A virtual buy and sell are evaluated at each UTC
quarter hour against an immediate-taker benchmark.  Passive fills are declared
only after observed aggressive volume consumes a conservative queue estimate;
cancelled displayed liquidity never helps the virtual order.

Only the pre-test portion of the immutable 26 August freeze is queried.  The
20--26 August locked block is deliberately unreachable from this evaluator.
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

from octobot.ai_strategy_lab import scalping_strategy_search as scalping_v1


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_passive_execution_v1"
PREREGISTRATION_DATE = "2026-08-28"

SOURCE_START = scalping_v1.SOURCE_START
DEVELOPMENT_END = scalping_v1.TRAIN_END
DIAGNOSTIC_CONFIRMATION_END = scalping_v1.SELECTION_END
LOCKED_TEST_END = scalping_v1.LOCKED_TEST_END

FREEZE_MANIFEST_FILE_SHA256 = (
    "7c999831e0d44156c4a5594d9a2c66c7fcae6faa9e3caded5e758a5f5b155114"
)
FREEZE_DATABASE_SHA256 = (
    "96020bbf554b87e6433748fa3586c4d9d07c819cddeeab2e6e90f24475f64bce"
)
FREEZE_DATABASE_BYTES = 10_946_617_344

CONTRACT_MULTIPLIER_BTC = 0.001
TARGET_NOTIONAL_USDT = 1_000.0
MAKER_FEE_BPS = 2.0
TAKER_FEE_BPS = 6.0
PRIMARY_LATENCY_MS = 500
PRIMARY_FALLBACK_LATENCY_MS = 500
PRIMARY_TIMEOUT_SECONDS = 60
PRIMARY_QUEUE_MULTIPLIER = 1.25
PRIMARY_IMBALANCE_SAFETY = 0.20
STRESS_LATENCY_MS = 1_000
STRESS_FALLBACK_LATENCY_MS = 1_000
STRESS_TIMEOUT_SECONDS = 30
STRESS_QUEUE_MULTIPLIER = 2.0
STRESS_FEE_MULTIPLIER = 1.5
DECISION_STRIDE_SECONDS = 15 * 60
BOOK_STALENESS_NS = 2_000_000_000
POST_FILL_HORIZONS_SECONDS = (5, 60)
WALK_FORWARD_FOLDS = 5
BOOTSTRAP_SAMPLES = 20_000
RANDOM_SEED = 20260828

BOOK_COLUMNS = (
    "received_ts_ns",
    "bid_price_1",
    "bid_size_1",
    "bid_price_2",
    "bid_size_2",
    "bid_price_3",
    "bid_size_3",
    "bid_price_4",
    "bid_size_4",
    "bid_price_5",
    "bid_size_5",
    "ask_price_1",
    "ask_size_1",
    "ask_price_2",
    "ask_size_2",
    "ask_price_3",
    "ask_size_3",
    "ask_price_4",
    "ask_size_4",
    "ask_price_5",
    "ask_size_5",
    "mid_price",
    "imbalance_5",
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


def _epoch_ns(value: str) -> int:
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("execution boundary must be timezone-aware")
    return int(parsed.timestamp() * 1_000_000_000)


def frozen_protocol() -> dict:
    """Return the result-free passive-execution protocol."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_execution_diagnostic_protocol",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "hypothesis": {
            "name": "imbalance_guarded_passive_execution",
            "statement": (
                "for a slow independent signal, attempting a conservative "
                "best-quote maker fill only when queue imbalance is favorable "
                "reduces implementation shortfall relative to immediate taker"
            ),
            "directional_alpha_claim": False,
            "primary_candidate_count": 1,
            "post_result_policy_inversion": False,
        },
        "source": {
            "symbol": "XBTUSDTM",
            "exchange": "kucoin",
            "frozen_database_manifest_file_sha256": (
                FREEZE_MANIFEST_FILE_SHA256
            ),
            "frozen_database_sha256": FREEZE_DATABASE_SHA256,
            "frozen_database_bytes": FREEZE_DATABASE_BYTES,
            "database_hash_is_trusted_from_verified_freeze_manifest": True,
            "sqlite_open_mode": "read-only immutable",
            "contract_multiplier_btc": CONTRACT_MULTIPLIER_BTC,
            "minimum_lot_contracts": 1,
            "official_contract_spec": (
                "https://www.kucoin.com/docs-new/rest/futures-trading/"
                "market-data/get-symbol"
            ),
        },
        "virtual_parent_orders": {
            "decision_schedule": "every UTC quarter hour",
            "sides_per_decision": ["buy", "sell"],
            "target_notional_usdt": TARGET_NOTIONAL_USDT,
            "quantity_rule": (
                "ceil(target_notional / (arrival_mid * 0.001)); integer lots"
            ),
            "overlapping_rows_are_execution_diagnostics_not_a_portfolio": True,
        },
        "primary_policy": {
            "arrival_latency_ms": PRIMARY_LATENCY_MS,
            "fallback_latency_ms": PRIMARY_FALLBACK_LATENCY_MS,
            "maker_price": "arrival best bid for buy; best ask for sell",
            "post_only": True,
            "side_adjusted_imbalance_minimum": PRIMARY_IMBALANCE_SAFETY,
            "queue_ahead_multiplier_of_displayed_best_size": (
                PRIMARY_QUEUE_MULTIPLIER
            ),
            "own_size_is_behind_queue": True,
            "cancellations_reduce_queue": False,
            "fill_rule": (
                "observed opposing aggressor volume at or through the limit "
                "must consume queue ahead plus the complete virtual order"
            ),
            "partial_fill_credit": False,
            "timeout_seconds": PRIMARY_TIMEOUT_SECONDS,
            "timeout_action": "taker fallback after fallback latency",
            "maker_fee_bps": MAKER_FEE_BPS,
            "taker_fee_bps": TAKER_FEE_BPS,
        },
        "stress_policy": {
            "arrival_latency_ms": STRESS_LATENCY_MS,
            "fallback_latency_ms": STRESS_FALLBACK_LATENCY_MS,
            "queue_ahead_multiplier_of_displayed_best_size": (
                STRESS_QUEUE_MULTIPLIER
            ),
            "timeout_seconds": STRESS_TIMEOUT_SECONDS,
            "fee_multiplier": STRESS_FEE_MULTIPLIER,
            "same_imbalance_gate": True,
        },
        "measurement": {
            "benchmark": "immediate taker at the same arrival book",
            "reference_price": "last non-stale mid at decision timestamp",
            "implementation_shortfall_lower_is_better": True,
            "saving_bps": "benchmark shortfall minus policy shortfall",
            "post_fill_adverse_selection_seconds": list(
                POST_FILL_HORIZONS_SECONDS
            ),
            "adverse_selection_is_diagnostic_not_directional_pnl": True,
            "book_maximum_staleness_ms": BOOK_STALENESS_NS / 1_000_000,
            "top_five_vwap_for_taker": True,
        },
        "validation": {
            "development": [SOURCE_START, DEVELOPMENT_END],
            "development_walk_forward_folds": WALK_FORWARD_FOLDS,
            "diagnostic_confirmation": [
                DEVELOPMENT_END,
                DIAGNOSTIC_CONFIRMATION_END,
            ],
            "diagnostic_confirmation_is_not_pristine": True,
            "confirmation_read_only_after_complete_development_pass": True,
            "locked_final_test": [
                DIAGNOSTIC_CONFIRMATION_END,
                LOCKED_TEST_END,
            ],
            "locked_rows_queryable_by_this_evaluator": False,
            "locked_test_materialized": False,
        },
        "development_gate": {
            "minimum_completed_rows_per_side": 1_800,
            "minimum_maker_attempts_per_side": 300,
            "minimum_coverage": 0.99,
            "minimum_maker_fill_rate": 0.10,
            "mean_saving_bps_strictly_positive": True,
            "buy_mean_saving_bps_strictly_positive": True,
            "sell_mean_saving_bps_strictly_positive": True,
            "minimum_positive_operating_days_pct": 55.0,
            "minimum_positive_folds": 3,
            "daily_bootstrap_samples": BOOTSTRAP_SAMPLES,
            "daily_bootstrap_one_sided_level": 0.90,
            "bootstrap_lower_mean_saving_bps_strictly_positive": True,
            "stress_mean_saving_bps_strictly_positive": True,
        },
        "diagnostic_confirmation_gate": {
            "minimum_completed_rows_per_side": 600,
            "minimum_maker_attempts_per_side": 100,
            "minimum_coverage": 0.99,
            "minimum_maker_fill_rate": 0.10,
            "mean_saving_bps_strictly_positive": True,
            "buy_mean_saving_bps_strictly_positive": True,
            "sell_mean_saving_bps_strictly_positive": True,
            "minimum_positive_operating_days_pct": 50.0,
            "stress_mean_saving_bps_strictly_positive": True,
        },
        "multiple_testing_disclosure": (
            "one frozen imbalance-guarded maker policy, one immediate-taker "
            "benchmark and one adverse stress; unconditional passive results "
            "are not an eligible alternative"
        ),
        "advancement_consequence": (
            "a complete pre-test pass permits only a separately authorized "
            "offline locked evaluation; it cannot authorize shadow, paper or "
            "real orders"
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
            raise ValueError("persisted passive-execution V1 protocol differs")
        return persisted
    _atomic_json(path, payload)
    return payload


@dataclasses.dataclass(frozen=True)
class Book:
    timestamp_ns: int
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    mid: float
    imbalance: float

    def validate(self) -> None:
        if self.timestamp_ns <= 0 or not math.isfinite(self.mid) or self.mid <= 0:
            raise ValueError("invalid execution book")
        if not -1 <= self.imbalance <= 1:
            raise ValueError("invalid book imbalance")
        if len(self.bids) != 5 or len(self.asks) != 5:
            raise ValueError("five book levels are required")
        for price, size in (*self.bids, *self.asks):
            if not math.isfinite(price) or not math.isfinite(size):
                raise ValueError("non-finite book level")
            if price <= 0 or size < 0:
                raise ValueError("invalid book level")
        if self.bids[0][0] >= self.asks[0][0]:
            raise ValueError("crossed execution book")


@dataclasses.dataclass(frozen=True)
class Trade:
    timestamp_ns: int
    side: str
    price: float
    size: float


@dataclasses.dataclass(frozen=True)
class Window:
    decision_ns: int
    books: tuple[Book, ...]
    trades: tuple[Trade, ...]

    @property
    def book_timestamps(self) -> tuple[int, ...]:
        return tuple(value.timestamp_ns for value in self.books)


@dataclasses.dataclass(frozen=True)
class Policy:
    name: str
    arrival_latency_ms: int
    fallback_latency_ms: int
    timeout_seconds: int
    queue_multiplier: float
    maker_fee_bps: float
    taker_fee_bps: float


PRIMARY_POLICY = Policy(
    name="primary",
    arrival_latency_ms=PRIMARY_LATENCY_MS,
    fallback_latency_ms=PRIMARY_FALLBACK_LATENCY_MS,
    timeout_seconds=PRIMARY_TIMEOUT_SECONDS,
    queue_multiplier=PRIMARY_QUEUE_MULTIPLIER,
    maker_fee_bps=MAKER_FEE_BPS,
    taker_fee_bps=TAKER_FEE_BPS,
)
STRESS_POLICY = Policy(
    name="stress",
    arrival_latency_ms=STRESS_LATENCY_MS,
    fallback_latency_ms=STRESS_FALLBACK_LATENCY_MS,
    timeout_seconds=STRESS_TIMEOUT_SECONDS,
    queue_multiplier=STRESS_QUEUE_MULTIPLIER,
    maker_fee_bps=MAKER_FEE_BPS * STRESS_FEE_MULTIPLIER,
    taker_fee_bps=TAKER_FEE_BPS * STRESS_FEE_MULTIPLIER,
)


def _book_from_row(row: sqlite3.Row) -> Book:
    book = Book(
        timestamp_ns=int(row["received_ts_ns"]),
        bids=tuple(
            (float(row[f"bid_price_{level}"]), float(row[f"bid_size_{level}"]))
            for level in range(1, 6)
        ),
        asks=tuple(
            (float(row[f"ask_price_{level}"]), float(row[f"ask_size_{level}"]))
            for level in range(1, 6)
        ),
        mid=float(row["mid_price"]),
        imbalance=float(row["imbalance_5"]),
    )
    book.validate()
    return book


def _load_window(connection: sqlite3.Connection, decision_ns: int) -> Window:
    maximum_horizon_ns = (
        max(PRIMARY_LATENCY_MS, STRESS_LATENCY_MS) * 1_000_000
        + max(PRIMARY_TIMEOUT_SECONDS, STRESS_TIMEOUT_SECONDS) * 1_000_000_000
        + max(PRIMARY_FALLBACK_LATENCY_MS, STRESS_FALLBACK_LATENCY_MS)
        * 1_000_000
        + max(POST_FILL_HORIZONS_SECONDS) * 1_000_000_000
        + BOOK_STALENESS_NS
    )
    lower_ns = decision_ns - BOOK_STALENESS_NS
    upper_ns = decision_ns + maximum_horizon_ns
    columns = ", ".join(BOOK_COLUMNS)
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
        (decision_ns, upper_ns),
    ).fetchall()
    return Window(
        decision_ns=decision_ns,
        books=tuple(_book_from_row(row) for row in book_rows),
        trades=tuple(
            Trade(
                timestamp_ns=int(row["received_ts_ns"]),
                side=str(row["side"]),
                price=float(row["price"]),
                size=float(row["size"]),
            )
            for row in trade_rows
        ),
    )


def _book_before(window: Window, target_ns: int) -> Book | None:
    timestamps = window.book_timestamps
    index = bisect.bisect_right(timestamps, target_ns) - 1
    if index < 0:
        return None
    book = window.books[index]
    if target_ns - book.timestamp_ns > BOOK_STALENESS_NS:
        return None
    return book


def _book_after(window: Window, target_ns: int) -> Book | None:
    timestamps = window.book_timestamps
    index = bisect.bisect_left(timestamps, target_ns)
    if index >= len(window.books):
        return None
    book = window.books[index]
    if book.timestamp_ns - target_ns > BOOK_STALENESS_NS:
        return None
    return book


def _quantity_contracts(book: Book) -> int:
    quantity = math.ceil(
        TARGET_NOTIONAL_USDT / (book.mid * CONTRACT_MULTIPLIER_BTC)
    )
    return max(1, int(quantity))


def _vwap(book: Book, side: str, quantity: int) -> float | None:
    levels = book.asks if side == "buy" else book.bids
    remaining = float(quantity)
    value = 0.0
    for price, size in levels:
        consumed = min(remaining, size)
        value += consumed * price
        remaining -= consumed
        if remaining <= 1e-12:
            return value / quantity
    return None


def _shortfall_bps(side: str, price: float, reference_mid: float, fee_bps: float) -> float:
    direction = 1.0 if side == "buy" else -1.0
    return direction * (price / reference_mid - 1.0) * 10_000.0 + fee_bps


def _is_safe(book: Book, side: str) -> bool:
    side_adjusted = book.imbalance * (
        1.0 if side == "buy" else -1.0
    )
    return side_adjusted >= PRIMARY_IMBALANCE_SAFETY


def _fill_time(
    window: Window,
    *,
    side: str,
    arrival_book: Book,
    limit_price: float,
    queue_ahead: float,
    own_quantity: int,
    timeout_seconds: int,
) -> int | None:
    required = queue_ahead + own_quantity
    consumed = 0.0
    deadline_ns = arrival_book.timestamp_ns + timeout_seconds * 1_000_000_000
    for trade in window.trades:
        if trade.timestamp_ns < arrival_book.timestamp_ns:
            continue
        if trade.timestamp_ns > deadline_ns:
            break
        eligible = (
            side == "buy"
            and trade.side == "sell"
            and trade.price <= limit_price + 1e-12
        ) or (
            side == "sell"
            and trade.side == "buy"
            and trade.price >= limit_price - 1e-12
        )
        if eligible:
            consumed += trade.size
            if consumed + 1e-12 >= required:
                return trade.timestamp_ns
    return None


def _adverse_markout_bps(window: Window, side: str, fill_ns: int, price: float, seconds: int) -> float | None:
    book = _book_after(window, fill_ns + seconds * 1_000_000_000)
    if book is None:
        return None
    direction = 1.0 if side == "buy" else -1.0
    return direction * (book.mid / price - 1.0) * 10_000.0


def simulate_side(window: Window, side: str, policy: Policy) -> dict:
    if side not in {"buy", "sell"}:
        raise ValueError("execution side must be buy or sell")
    decision_book = _book_before(window, window.decision_ns)
    arrival_target_ns = (
        window.decision_ns + policy.arrival_latency_ms * 1_000_000
    )
    arrival_book = _book_after(window, arrival_target_ns)
    base = {
        "timestamp_ns": window.decision_ns,
        "side": side,
        "policy": policy.name,
        "completed": False,
        "exclusion": None,
        "maker_attempted": False,
        "maker_filled": False,
        "route": None,
        "quantity_contracts": None,
        "baseline_cost_bps": None,
        "policy_cost_bps": None,
        "saving_bps": None,
        "fill_timestamp_ns": None,
        "adverse_5s_bps": None,
        "adverse_60s_bps": None,
    }
    if decision_book is None:
        return {**base, "exclusion": "missing_decision_book"}
    if arrival_book is None:
        return {**base, "exclusion": "missing_arrival_book"}
    quantity = _quantity_contracts(arrival_book)
    benchmark_price = _vwap(arrival_book, side, quantity)
    if benchmark_price is None:
        return {**base, "exclusion": "insufficient_arrival_depth"}
    benchmark_cost = _shortfall_bps(
        side, benchmark_price, decision_book.mid, policy.taker_fee_bps
    )
    common = {
        **base,
        "quantity_contracts": quantity,
        "baseline_cost_bps": benchmark_cost,
    }
    if not _is_safe(arrival_book, side):
        return {
            **common,
            "completed": True,
            "route": "immediate_taker_filter",
            "policy_cost_bps": benchmark_cost,
            "saving_bps": 0.0,
        }
    limit_price, visible_size = (
        arrival_book.bids[0] if side == "buy" else arrival_book.asks[0]
    )
    fill_ns = _fill_time(
        window,
        side=side,
        arrival_book=arrival_book,
        limit_price=limit_price,
        queue_ahead=visible_size * policy.queue_multiplier,
        own_quantity=quantity,
        timeout_seconds=policy.timeout_seconds,
    )
    if fill_ns is not None:
        policy_cost = _shortfall_bps(
            side, limit_price, decision_book.mid, policy.maker_fee_bps
        )
        return {
            **common,
            "completed": True,
            "maker_attempted": True,
            "maker_filled": True,
            "route": "maker_fill",
            "policy_cost_bps": policy_cost,
            "saving_bps": benchmark_cost - policy_cost,
            "fill_timestamp_ns": fill_ns,
            "adverse_5s_bps": _adverse_markout_bps(
                window, side, fill_ns, limit_price, 5
            ),
            "adverse_60s_bps": _adverse_markout_bps(
                window, side, fill_ns, limit_price, 60
            ),
        }
    fallback_target_ns = (
        arrival_book.timestamp_ns
        + policy.timeout_seconds * 1_000_000_000
        + policy.fallback_latency_ms * 1_000_000
    )
    fallback_book = _book_after(window, fallback_target_ns)
    if fallback_book is None:
        return {
            **common,
            "maker_attempted": True,
            "exclusion": "missing_fallback_book",
        }
    fallback_price = _vwap(fallback_book, side, quantity)
    if fallback_price is None:
        return {
            **common,
            "maker_attempted": True,
            "exclusion": "insufficient_fallback_depth",
        }
    policy_cost = _shortfall_bps(
        side, fallback_price, decision_book.mid, policy.taker_fee_bps
    )
    return {
        **common,
        "completed": True,
        "maker_attempted": True,
        "route": "taker_fallback",
        "policy_cost_bps": policy_cost,
        "saving_bps": benchmark_cost - policy_cost,
    }


def _decision_timestamps(start_ns: int, end_ns: int) -> list[int]:
    stride_ns = DECISION_STRIDE_SECONDS * 1_000_000_000
    first = ((start_ns + stride_ns - 1) // stride_ns) * stride_ns
    return list(range(first, end_ns, stride_ns))


def simulate_period(
    connection: sqlite3.Connection,
    start: str,
    end: str,
    policy: Policy,
) -> list[dict]:
    return simulate_period_policies(connection, start, end, (policy,))[
        policy.name
    ]


def simulate_period_policies(
    connection: sqlite3.Connection,
    start: str,
    end: str,
    policies: typing.Sequence[Policy],
) -> dict[str, list[dict]]:
    start_ns = _epoch_ns(start)
    end_ns = _epoch_ns(end)
    if end_ns > _epoch_ns(DIAGNOSTIC_CONFIRMATION_END):
        raise ValueError("passive-execution evaluator cannot query locked rows")
    if not policies or len({value.name for value in policies}) != len(policies):
        raise ValueError("execution policy names must be unique")
    records = {value.name: [] for value in policies}
    for decision_ns in _decision_timestamps(start_ns, end_ns):
        window = _load_window(connection, decision_ns)
        for policy in policies:
            for side in ("buy", "sell"):
                records[policy.name].append(simulate_side(window, side, policy))
    return records


def _mean(values: typing.Iterable[float]) -> float | None:
    array = numpy.asarray(list(values), dtype=numpy.float64)
    if len(array) == 0:
        return None
    return float(numpy.mean(array))


def _side_metrics(records: list[dict], side: str) -> dict:
    expected = [value for value in records if value["side"] == side]
    completed = [value for value in expected if value["completed"]]
    attempts = [value for value in completed if value["maker_attempted"]]
    fills = [value for value in attempts if value["maker_filled"]]
    savings = [float(value["saving_bps"]) for value in completed]
    return {
        "expected_rows": len(expected),
        "completed_rows": len(completed),
        "coverage": len(completed) / len(expected) if expected else 0.0,
        "maker_attempts": len(attempts),
        "maker_fills": len(fills),
        "maker_fill_rate": len(fills) / len(attempts) if attempts else 0.0,
        "mean_baseline_cost_bps": _mean(
            float(value["baseline_cost_bps"]) for value in completed
        ),
        "mean_policy_cost_bps": _mean(
            float(value["policy_cost_bps"]) for value in completed
        ),
        "mean_saving_bps": _mean(savings),
        "median_saving_bps": (
            float(numpy.median(savings)) if savings else None
        ),
        "mean_filled_adverse_5s_bps": _mean(
            float(value["adverse_5s_bps"])
            for value in fills
            if value["adverse_5s_bps"] is not None
        ),
        "mean_filled_adverse_60s_bps": _mean(
            float(value["adverse_60s_bps"])
            for value in fills
            if value["adverse_60s_bps"] is not None
        ),
    }


def _daily_means(records: list[dict]) -> tuple[numpy.ndarray, numpy.ndarray]:
    grouped: dict[int, list[float]] = {}
    for record in records:
        if not record["completed"]:
            continue
        day = int(record["timestamp_ns"]) // (86_400 * 1_000_000_000)
        grouped.setdefault(day, []).append(float(record["saving_bps"]))
    days = numpy.asarray(sorted(grouped), dtype=numpy.int64)
    means = numpy.asarray(
        [numpy.mean(grouped[int(day)]) for day in days], dtype=numpy.float64
    )
    return days, means


def _bootstrap_lower(daily_means: numpy.ndarray) -> float | None:
    if len(daily_means) < 2:
        return None
    generator = numpy.random.default_rng(RANDOM_SEED)
    output = numpy.empty(BOOTSTRAP_SAMPLES, dtype=numpy.float64)
    for index in range(BOOTSTRAP_SAMPLES):
        selected = generator.integers(0, len(daily_means), len(daily_means))
        output[index] = numpy.mean(daily_means[selected])
    return float(numpy.quantile(output, 0.10))


def _fold_metrics(records: list[dict], start: str, end: str) -> list[dict]:
    start_ns = _epoch_ns(start)
    end_ns = _epoch_ns(end)
    boundaries = numpy.linspace(
        start_ns, end_ns, WALK_FORWARD_FOLDS + 1, dtype=numpy.int64
    )
    folds = []
    for index in range(WALK_FORWARD_FOLDS):
        values = [
            float(record["saving_bps"])
            for record in records
            if record["completed"]
            and int(boundaries[index]) <= int(record["timestamp_ns"])
            < int(boundaries[index + 1])
        ]
        folds.append(
            {
                "fold": index + 1,
                "rows": len(values),
                "mean_saving_bps": _mean(values),
                "positive": bool(values and numpy.mean(values) > 0),
            }
        )
    return folds


def execution_metrics(records: list[dict], *, start: str, end: str, folds: bool) -> dict:
    completed = [value for value in records if value["completed"]]
    attempts = [value for value in completed if value["maker_attempted"]]
    fills = [value for value in attempts if value["maker_filled"]]
    exclusions: dict[str, int] = {}
    routes: dict[str, int] = {}
    for record in records:
        if record["exclusion"] is not None:
            exclusions[record["exclusion"]] = exclusions.get(record["exclusion"], 0) + 1
        if record["route"] is not None:
            routes[record["route"]] = routes.get(record["route"], 0) + 1
    days, daily = _daily_means(records)
    fold_values = _fold_metrics(records, start, end) if folds else []
    savings = [float(value["saving_bps"]) for value in completed]
    return {
        "expected_rows": len(records),
        "completed_rows": len(completed),
        "coverage": len(completed) / len(records) if records else 0.0,
        "maker_attempts": len(attempts),
        "maker_fills": len(fills),
        "maker_fill_rate": len(fills) / len(attempts) if attempts else 0.0,
        "mean_saving_bps": _mean(savings),
        "median_saving_bps": float(numpy.median(savings)) if savings else None,
        "positive_row_pct": (
            100.0 * sum(value > 0 for value in savings) / len(savings)
            if savings
            else 0.0
        ),
        "operating_days": len(days),
        "positive_operating_days_pct": (
            100.0 * float(numpy.mean(daily > 0)) if len(daily) else 0.0
        ),
        "daily_bootstrap_lower_mean_saving_bps_90pct": _bootstrap_lower(daily),
        "by_side": {
            side: _side_metrics(records, side) for side in ("buy", "sell")
        },
        "routes": routes,
        "exclusions": exclusions,
        "folds": fold_values,
        "positive_folds": sum(value["positive"] for value in fold_values),
    }


def _development_gate(primary: dict, stress: dict, protocol: dict) -> dict:
    gate = protocol["development_gate"]
    checks = {
        "minimum_completed_rows_per_side": all(
            primary["by_side"][side]["completed_rows"]
            >= gate["minimum_completed_rows_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_maker_attempts_per_side": all(
            primary["by_side"][side]["maker_attempts"]
            >= gate["minimum_maker_attempts_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_coverage": primary["coverage"] >= gate["minimum_coverage"],
        "minimum_maker_fill_rate": (
            primary["maker_fill_rate"] >= gate["minimum_maker_fill_rate"]
        ),
        "mean_saving_bps_strictly_positive": primary["mean_saving_bps"] is not None
        and primary["mean_saving_bps"] > 0,
        "buy_mean_saving_bps_strictly_positive": (
            primary["by_side"]["buy"]["mean_saving_bps"] is not None
            and primary["by_side"]["buy"]["mean_saving_bps"] > 0
        ),
        "sell_mean_saving_bps_strictly_positive": (
            primary["by_side"]["sell"]["mean_saving_bps"] is not None
            and primary["by_side"]["sell"]["mean_saving_bps"] > 0
        ),
        "minimum_positive_operating_days_pct": (
            primary["positive_operating_days_pct"]
            >= gate["minimum_positive_operating_days_pct"]
        ),
        "minimum_positive_folds": (
            primary["positive_folds"] >= gate["minimum_positive_folds"]
        ),
        "bootstrap_lower_mean_saving_bps_strictly_positive": (
            primary["daily_bootstrap_lower_mean_saving_bps_90pct"] is not None
            and primary["daily_bootstrap_lower_mean_saving_bps_90pct"] > 0
        ),
        "stress_mean_saving_bps_strictly_positive": (
            stress["mean_saving_bps"] is not None
            and stress["mean_saving_bps"] > 0
        ),
    }
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _confirmation_gate(primary: dict, stress: dict, protocol: dict) -> dict:
    gate = protocol["diagnostic_confirmation_gate"]
    checks = {
        "minimum_completed_rows_per_side": all(
            primary["by_side"][side]["completed_rows"]
            >= gate["minimum_completed_rows_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_maker_attempts_per_side": all(
            primary["by_side"][side]["maker_attempts"]
            >= gate["minimum_maker_attempts_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_coverage": primary["coverage"] >= gate["minimum_coverage"],
        "minimum_maker_fill_rate": (
            primary["maker_fill_rate"] >= gate["minimum_maker_fill_rate"]
        ),
        "mean_saving_bps_strictly_positive": primary["mean_saving_bps"] is not None
        and primary["mean_saving_bps"] > 0,
        "buy_mean_saving_bps_strictly_positive": (
            primary["by_side"]["buy"]["mean_saving_bps"] is not None
            and primary["by_side"]["buy"]["mean_saving_bps"] > 0
        ),
        "sell_mean_saving_bps_strictly_positive": (
            primary["by_side"]["sell"]["mean_saving_bps"] is not None
            and primary["by_side"]["sell"]["mean_saving_bps"] > 0
        ),
        "minimum_positive_operating_days_pct": (
            primary["positive_operating_days_pct"]
            >= gate["minimum_positive_operating_days_pct"]
        ),
        "stress_mean_saving_bps_strictly_positive": (
            stress["mean_saving_bps"] is not None
            and stress["mean_saving_bps"] > 0
        ),
    }
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _records_arrays(prefix: str, records: list[dict]) -> dict[str, numpy.ndarray]:
    def values(name, dtype, missing):
        return numpy.asarray(
            [missing if row[name] is None else row[name] for row in records],
            dtype=dtype,
        )

    return {
        f"{prefix}_timestamp_ns": values("timestamp_ns", numpy.int64, -1),
        f"{prefix}_side": numpy.asarray(
            [1 if row["side"] == "buy" else -1 for row in records],
            dtype=numpy.int8,
        ),
        f"{prefix}_completed": values("completed", numpy.bool_, False),
        f"{prefix}_maker_attempted": values(
            "maker_attempted", numpy.bool_, False
        ),
        f"{prefix}_maker_filled": values("maker_filled", numpy.bool_, False),
        f"{prefix}_quantity_contracts": values(
            "quantity_contracts", numpy.int32, -1
        ),
        f"{prefix}_baseline_cost_bps": values(
            "baseline_cost_bps", numpy.float64, numpy.nan
        ),
        f"{prefix}_policy_cost_bps": values(
            "policy_cost_bps", numpy.float64, numpy.nan
        ),
        f"{prefix}_saving_bps": values(
            "saving_bps", numpy.float64, numpy.nan
        ),
        f"{prefix}_fill_timestamp_ns": values(
            "fill_timestamp_ns", numpy.int64, -1
        ),
        f"{prefix}_adverse_5s_bps": values(
            "adverse_5s_bps", numpy.float64, numpy.nan
        ),
        f"{prefix}_adverse_60s_bps": values(
            "adverse_60s_bps", numpy.float64, numpy.nan
        ),
    }


def _verify_freeze(database: pathlib.Path, manifest_path: pathlib.Path) -> dict:
    if _sha256(manifest_path) != FREEZE_MANIFEST_FILE_SHA256:
        raise ValueError("passive-execution freeze manifest hash differs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest.get("artifacts", {}).get("scalping_level5", {})
    if artifact.get("sha256") != FREEZE_DATABASE_SHA256:
        raise ValueError("passive-execution database identity differs")
    if int(artifact.get("bytes", -1)) != FREEZE_DATABASE_BYTES:
        raise ValueError("passive-execution database byte declaration differs")
    if database.stat().st_size != FREEZE_DATABASE_BYTES:
        raise ValueError("passive-execution database size differs")
    if manifest.get("collector_confirmed_stopped") is not True:
        raise ValueError("passive-execution source was not frozen offline")
    if manifest.get("orders_authorized") is not False:
        raise ValueError("passive-execution source safety invariant failed")
    return manifest


def _open_database(path: pathlib.Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path}?mode=ro&immutable=1", uri=True
    )
    connection.row_factory = sqlite3.Row
    required = {"book_events", "trade_events", "scalping_sessions"}
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not required.issubset(present):
        connection.close()
        raise ValueError("passive-execution database schema is incomplete")
    return connection


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


def evaluate_prelock(
    protocol_value: typing.Union[str, pathlib.Path],
    database_value: typing.Union[str, pathlib.Path],
    freeze_manifest_value: typing.Union[str, pathlib.Path],
    output_root_value: typing.Union[str, pathlib.Path],
) -> dict:
    protocol_path = pathlib.Path(protocol_value).resolve()
    database_path = pathlib.Path(database_value).resolve()
    freeze_manifest_path = pathlib.Path(freeze_manifest_value).resolve()
    output_root = pathlib.Path(output_root_value).resolve()
    protocol = write_or_verify_protocol(protocol_path)
    _verify_freeze(database_path, freeze_manifest_path)

    connection = _open_database(database_path)
    try:
        development_records = simulate_period_policies(
            connection,
            SOURCE_START,
            DEVELOPMENT_END,
            (PRIMARY_POLICY, STRESS_POLICY),
        )
        development_primary_records = development_records[PRIMARY_POLICY.name]
        development_stress_records = development_records[STRESS_POLICY.name]
        development_primary = execution_metrics(
            development_primary_records,
            start=SOURCE_START,
            end=DEVELOPMENT_END,
            folds=True,
        )
        development_stress = execution_metrics(
            development_stress_records,
            start=SOURCE_START,
            end=DEVELOPMENT_END,
            folds=True,
        )
        development_gate = _development_gate(
            development_primary, development_stress, protocol
        )

        confirmation_primary_records: list[dict] = []
        confirmation_stress_records: list[dict] = []
        confirmation_primary = None
        confirmation_stress = None
        confirmation_gate = {
            "not_evaluated": not development_gate["passed"],
            "reason": (
                "development_gate_failed"
                if not development_gate["passed"]
                else None
            ),
            "passed": False,
        }
        if development_gate["passed"]:
            confirmation_records = simulate_period_policies(
                connection,
                DEVELOPMENT_END,
                DIAGNOSTIC_CONFIRMATION_END,
                (PRIMARY_POLICY, STRESS_POLICY),
            )
            confirmation_primary_records = confirmation_records[
                PRIMARY_POLICY.name
            ]
            confirmation_stress_records = confirmation_records[
                STRESS_POLICY.name
            ]
            confirmation_primary = execution_metrics(
                confirmation_primary_records,
                start=DEVELOPMENT_END,
                end=DIAGNOSTIC_CONFIRMATION_END,
                folds=False,
            )
            confirmation_stress = execution_metrics(
                confirmation_stress_records,
                start=DEVELOPMENT_END,
                end=DIAGNOSTIC_CONFIRMATION_END,
                folds=False,
            )
            confirmation_gate = _confirmation_gate(
                confirmation_primary, confirmation_stress, protocol
            )
    finally:
        connection.close()

    locked_authorized = bool(
        development_gate["passed"] and confirmation_gate["passed"]
    )
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
                "database_sha256_from_freeze": FREEZE_DATABASE_SHA256,
                "database_bytes": database_path.stat().st_size,
                "freeze_manifest": str(freeze_manifest_path),
                "freeze_manifest_file_sha256": _sha256(freeze_manifest_path),
            },
            "development": {
                "primary": development_primary,
                "stress": development_stress,
                "gate": development_gate,
            },
            "diagnostic_confirmation": {
                "materialized": confirmation_primary is not None,
                "primary": confirmation_primary,
                "stress": confirmation_stress,
                "gate": confirmation_gate,
            },
            "locked_test": {
                "interval": [
                    DIAGNOSTIC_CONFIRMATION_END,
                    LOCKED_TEST_END,
                ],
                "authorized_to_open_separately": locked_authorized,
                "materialized": False,
                "rows_queried": False,
                "reason": (
                    "separate_locked_protocol_required"
                    if locked_authorized
                    else "prelock_gate_failed"
                ),
            },
            "verdict": (
                "PRELOCK_PASS_REQUIRES_SEPARATE_LOCKED_EVALUATION"
                if locked_authorized
                else "REJECTED_BEFORE_LOCK"
            ),
        }
    )

    identity = (
        f"passive-execution-v1-{protocol['protocol_sha256'][:12]}-"
        f"{FREEZE_MANIFEST_FILE_SHA256[:12]}"
    )
    experiment = output_root / identity
    if experiment.exists():
        manifest_path = experiment / "manifest.json"
        report_path = experiment / "report.json"
        if not manifest_path.is_file() or not report_path.is_file():
            raise FileExistsError("incomplete passive-execution experiment exists")
        persisted = json.loads(report_path.read_text(encoding="utf-8"))
        if persisted != report:
            raise ValueError("persisted passive-execution report is not reproducible")
        return {
            "experiment": str(experiment),
            "report": persisted,
            "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
        }

    experiment.mkdir(parents=True, exist_ok=False)
    dataset_path = experiment / "decisions.npz"
    arrays = {
        "schema_version": numpy.asarray([SCHEMA_VERSION], dtype=numpy.int64),
        "protocol_sha256": numpy.asarray([protocol["protocol_sha256"]]),
        **_records_arrays("development_primary", development_primary_records),
        **_records_arrays("development_stress", development_stress_records),
        **_records_arrays("confirmation_primary", confirmation_primary_records),
        **_records_arrays("confirmation_stress", confirmation_stress_records),
    }
    _atomic_npz(dataset_path, arrays)
    report_path = experiment / "report.json"
    _atomic_json(report_path, report)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "identity": identity,
        "source_manifest_file_sha256": FREEZE_MANIFEST_FILE_SHA256,
        "source_database_sha256": FREEZE_DATABASE_SHA256,
        "dataset": {
            "file": dataset_path.name,
            "bytes": dataset_path.stat().st_size,
            "sha256": _sha256(dataset_path),
        },
        "report": {
            "file": report_path.name,
            "bytes": report_path.stat().st_size,
            "sha256": _sha256(report_path),
        },
        "locked_test_materialized": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    manifest["content_sha256"] = _json_hash(manifest)
    manifest_path = experiment / "manifest.json"
    _atomic_json(manifest_path, manifest)
    return {
        "experiment": str(experiment),
        "report": report,
        "manifest": manifest,
    }


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
