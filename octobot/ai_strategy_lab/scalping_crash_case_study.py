"""Causal, research-only study of BTC microstructure around a known sell-off.

This module intentionally does not expose a trading decision or order API.  It
extracts complete 15-minute buckets from the public KuCoin Futures scalping
observer, measures a previously observed crash case, and freezes one
post-event hypothesis for genuinely forward evaluation.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import statistics
import typing


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_scalping_crash_case_v1"
PREREGISTRATION_DATE = "2026-07-28"
SYMBOL = "XBTUSDTM"
BUCKET_SECONDS = 900
MINIMUM_COMPLETE_SECONDS = 800
MINIMUM_HISTORY_BUCKETS = 96
REFERENCE_WINDOW_DAYS = 7
FLOW_PERCENTILE = 0.05
BOOK_PERCENTILE = 0.10
LONG_VETO_SECONDS = 2 * 60 * 60
EVENT_ONSET_TS = 1_785_191_400  # 2026-07-27 22:30:00 UTC
EVENT_TIMELINE_START_TS = 1_785_182_400  # 2026-07-27 20:00:00 UTC
EVENT_TIMELINE_END_TS = 1_785_194_100  # 2026-07-27 23:15:00 UTC
FORWARD_START_TS = 1_785_225_600  # 2026-07-28 08:00:00 UTC
FORWARD_MINIMUM_DAYS = 30


@dataclasses.dataclass
class Bucket:
    """One causally closed 15-minute microstructure bucket."""

    timestamp: int
    observed_seconds: int
    book_events: int
    trade_events: int
    open_price: float
    close_price: float
    mean_spread_bps: float
    mean_book_imbalance: float
    buy_trade_size: float
    sell_trade_size: float
    buy_trade_count: int
    sell_trade_count: int
    return_pct: float = math.nan
    trade_flow_imbalance: float = math.nan
    trade_flow_imbalance_2: float = math.nan
    book_imbalance_2: float = math.nan
    future_returns_pct: dict[int, float] = dataclasses.field(
        default_factory=dict
    )


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
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _iso(timestamp: int) -> str:
    return datetime.datetime.fromtimestamp(
        timestamp, datetime.timezone.utc
    ).isoformat()


def frozen_protocol() -> dict:
    """Return the result-free protocol and future hypothesis."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "post_event_hypothesis_frozen_before_forward_test",
        "research_only": True,
        "public_data_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "source": {
            "observer": "KuCoin Futures public Level 5 and executions",
            "symbol": SYMBOL,
            "aggregation_seconds": BUCKET_SECONDS,
            "minimum_observed_seconds": MINIMUM_COMPLETE_SECONDS,
            "credentials_used": False,
        },
        "diagnostic_case": {
            "known_after_the_fact": True,
            "event_onset": _iso(EVENT_ONSET_TS),
            "purpose": (
                "measure whether causal microstructure contained an earlier "
                "warning; never count this case as validation"
            ),
        },
        "features_available_at_bucket_close": [
            "aggressor_trade_flow_imbalance",
            "two_bucket_mean_aggressor_trade_flow_imbalance",
            "five_level_book_imbalance",
            "two_bucket_mean_five_level_book_imbalance",
            "mean_spread_bps",
            "trade_count",
            "bucket_return_pct",
        ],
        "post_event_candidate_hypothesis": {
            "role": "long_entry_veto_only",
            "not_a_short_entry": True,
            "history": {
                "minimum_complete_buckets": MINIMUM_HISTORY_BUCKETS,
                "rolling_days": REFERENCE_WINDOW_DAYS,
                "current_bucket_excluded": True,
            },
            "trigger": {
                "two_bucket_trade_flow_at_or_below_percentile": (
                    FLOW_PERCENTILE
                ),
                "two_bucket_book_imbalance_at_or_below_percentile": (
                    BOOK_PERCENTILE
                ),
            },
            "active_from": "trigger_bucket_close",
            "duration_seconds": LONG_VETO_SECONDS,
            "thresholds_tuned_on_profit": False,
            "warning": (
                "chosen after inspecting the diagnostic sell-off; historical "
                "counts are descriptive and cannot validate the rule"
            ),
        },
        "forward_gate": {
            "start_inclusive": _iso(FORWARD_START_TS),
            "minimum_calendar_days": FORWARD_MINIMUM_DAYS,
            "minimum_independent_triggers": 20,
            "minimum_coverage_pct": 95.0,
            "no_mid_test_retuning": True,
            "no_automatic_strategy_integration": True,
            "future_primary_measure": (
                "stop-losses avoided minus profitable longs incorrectly vetoed"
            ),
        },
        "implementation": {
            "protocol_file_required_before_case_evaluation": True,
            "snapshot_max_second_bucket": True,
            "persist_extracted_15m_input": True,
            "live_database_hash_not_used": True,
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
            "write protocol.json before evaluating the crash case"
        )
    expected = frozen_protocol()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    if persisted.get("protocol_sha256") != _json_hash(expected):
        raise ValueError("persisted crash-case protocol hash differs")
    content = {
        key: value
        for key, value in persisted.items()
        if key != "protocol_sha256"
    }
    if _json_hash(content) != _json_hash(expected):
        raise ValueError("persisted crash-case protocol content differs")
    return persisted


def _finite(value: typing.Optional[float]) -> bool:
    return value is not None and math.isfinite(float(value))


def load_complete_buckets(
    database_value: typing.Union[str, pathlib.Path],
) -> tuple[list[Bucket], dict]:
    """Read one stable SQLite snapshot and aggregate complete 15m buckets."""

    database = pathlib.Path(database_value).resolve()
    connection = sqlite3.connect(
        f"file:{database}?mode=ro", uri=True, timeout=30
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        snapshot_max_second = int(
            connection.execute(
                "SELECT COALESCE(MAX(bucket_ts_s), 0) FROM second_buckets"
            ).fetchone()[0]
        )
        snapshot_max_book_id = int(
            connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM book_events"
            ).fetchone()[0]
        )
        snapshot_max_trade_id = int(
            connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM trade_events"
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            WITH aggregated AS (
                SELECT
                    (bucket_ts_s / ?) * ? AS timestamp,
                    COUNT(*) AS observed_seconds,
                    SUM(book_event_count) AS book_events,
                    SUM(trade_event_count) AS trade_events,
                    MIN(
                        CASE WHEN first_mid IS NOT NULL
                        THEN bucket_ts_s END
                    ) AS first_book_second,
                    MAX(
                        CASE WHEN last_mid IS NOT NULL
                        THEN bucket_ts_s END
                    ) AS last_book_second,
                    SUM(spread_bps_sum)
                        / NULLIF(SUM(book_event_count), 0)
                        AS mean_spread_bps,
                    SUM(imbalance_5_sum)
                        / NULLIF(SUM(book_event_count), 0)
                        AS mean_book_imbalance,
                    SUM(buy_trade_size) AS buy_trade_size,
                    SUM(sell_trade_size) AS sell_trade_size,
                    SUM(buy_trade_count) AS buy_trade_count,
                    SUM(sell_trade_count) AS sell_trade_count
                FROM second_buckets
                WHERE bucket_ts_s <= ?
                GROUP BY timestamp
            )
            SELECT
                aggregated.*,
                first_bucket.first_mid AS open_price,
                last_bucket.last_mid AS close_price
            FROM aggregated
            LEFT JOIN second_buckets AS first_bucket
              ON first_bucket.bucket_ts_s = aggregated.first_book_second
            LEFT JOIN second_buckets AS last_bucket
              ON last_bucket.bucket_ts_s = aggregated.last_book_second
            ORDER BY aggregated.timestamp
            """,
            (BUCKET_SECONDS, BUCKET_SECONDS, snapshot_max_second),
        ).fetchall()
        connection.rollback()
    finally:
        connection.close()

    buckets = []
    incomplete = 0
    invalid = 0
    for row in rows:
        if int(row["observed_seconds"]) < MINIMUM_COMPLETE_SECONDS:
            incomplete += 1
            continue
        if not all(
            _finite(row[name])
            for name in (
                "open_price",
                "close_price",
                "mean_spread_bps",
                "mean_book_imbalance",
            )
        ):
            invalid += 1
            continue
        buy_size = float(row["buy_trade_size"])
        sell_size = float(row["sell_trade_size"])
        trade_size = buy_size + sell_size
        buckets.append(
            Bucket(
                timestamp=int(row["timestamp"]),
                observed_seconds=int(row["observed_seconds"]),
                book_events=int(row["book_events"]),
                trade_events=int(row["trade_events"]),
                open_price=float(row["open_price"]),
                close_price=float(row["close_price"]),
                mean_spread_bps=float(row["mean_spread_bps"]),
                mean_book_imbalance=float(
                    row["mean_book_imbalance"]
                ),
                buy_trade_size=buy_size,
                sell_trade_size=sell_size,
                buy_trade_count=int(row["buy_trade_count"]),
                sell_trade_count=int(row["sell_trade_count"]),
                return_pct=(
                    float(row["close_price"])
                    / float(row["open_price"])
                    - 1
                )
                * 100,
                trade_flow_imbalance=(
                    (buy_size - sell_size) / trade_size
                    if trade_size
                    else math.nan
                ),
            )
        )
    _derive_features(buckets)
    return buckets, {
        "path": str(database),
        "bytes_at_read": database.stat().st_size,
        "snapshot_max_second": snapshot_max_second,
        "snapshot_max_second_at": _iso(snapshot_max_second),
        "snapshot_max_book_id": snapshot_max_book_id,
        "snapshot_max_trade_id": snapshot_max_trade_id,
        "raw_15m_buckets": len(rows),
        "complete_15m_buckets": len(buckets),
        "incomplete_15m_buckets_excluded": incomplete,
        "invalid_15m_buckets_excluded": invalid,
    }


def _derive_features(buckets: list[Bucket]) -> None:
    by_timestamp = {bucket.timestamp: bucket for bucket in buckets}
    for bucket in buckets:
        previous = by_timestamp.get(bucket.timestamp - BUCKET_SECONDS)
        if (
            previous is not None
            and _finite(previous.trade_flow_imbalance)
            and _finite(bucket.trade_flow_imbalance)
        ):
            bucket.trade_flow_imbalance_2 = statistics.fmean(
                (
                    previous.trade_flow_imbalance,
                    bucket.trade_flow_imbalance,
                )
            )
            bucket.book_imbalance_2 = statistics.fmean(
                (
                    previous.mean_book_imbalance,
                    bucket.mean_book_imbalance,
                )
            )
        for horizon in (1, 2, 4, 8):
            future = by_timestamp.get(
                bucket.timestamp + horizon * BUCKET_SECONDS
            )
            bucket.future_returns_pct[horizon] = (
                (future.close_price / bucket.close_price - 1) * 100
                if future is not None
                else math.nan
            )


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index + 1
        while (
            end < len(order)
            and values[order[end]] == values[order[index]]
        ):
            end += 1
        rank = (index + end - 1) / 2
        for position in order[index:end]:
            ranks[position] = rank
        index = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) < 3 or len(left) != len(right):
        return math.nan
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    numerator = sum(
        (left_value - mean_left) * (right_value - mean_right)
        for left_value, right_value in zip(left, right)
    )
    denominator = math.sqrt(
        sum((value - mean_left) ** 2 for value in left)
        * sum((value - mean_right) ** 2 for value in right)
    )
    return numerator / denominator if denominator else math.nan


def _spearman(left: list[float], right: list[float]) -> float:
    return _pearson(_average_ranks(left), _average_ranks(right))


def _percentile_rank(value: float, history: list[float]) -> float:
    if not history:
        return math.nan
    return sum(item <= value for item in history) / len(history) * 100


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


def _history_before(
    buckets: list[Bucket], index: int
) -> list[Bucket]:
    current = buckets[index]
    lower = current.timestamp - REFERENCE_WINDOW_DAYS * 86_400
    return [
        bucket
        for bucket in buckets[:index]
        if bucket.timestamp >= lower
        and _finite(bucket.trade_flow_imbalance_2)
        and _finite(bucket.book_imbalance_2)
    ]


def _candidate_events(
    buckets: list[Bucket], maximum_timestamp: int
) -> list[dict]:
    events = []
    for index, bucket in enumerate(buckets):
        if (
            bucket.timestamp >= maximum_timestamp
            or not _finite(bucket.trade_flow_imbalance_2)
        ):
            continue
        history = _history_before(buckets, index)
        if len(history) < MINIMUM_HISTORY_BUCKETS:
            continue
        flow_threshold = _quantile(
            [
                item.trade_flow_imbalance_2
                for item in history
            ],
            FLOW_PERCENTILE,
        )
        book_threshold = _quantile(
            [item.book_imbalance_2 for item in history],
            BOOK_PERCENTILE,
        )
        if (
            bucket.trade_flow_imbalance_2 <= flow_threshold
            and bucket.book_imbalance_2 <= book_threshold
        ):
            events.append(
                {
                    "bucket_open_at": _iso(bucket.timestamp),
                    "available_at": _iso(
                        bucket.timestamp + BUCKET_SECONDS
                    ),
                    "trade_flow_imbalance_2": (
                        bucket.trade_flow_imbalance_2
                    ),
                    "flow_threshold": flow_threshold,
                    "book_imbalance_2": bucket.book_imbalance_2,
                    "book_threshold": book_threshold,
                    "future_returns_pct": {
                        f"{horizon * 15}m": (
                            bucket.future_returns_pct[horizon]
                        )
                        for horizon in (1, 2, 4, 8)
                    },
                }
            )
    return events


def _correlations(buckets: list[Bucket]) -> dict:
    features = {
        "trade_flow_imbalance": lambda row: (
            row.trade_flow_imbalance
        ),
        "trade_flow_imbalance_2": lambda row: (
            row.trade_flow_imbalance_2
        ),
        "book_imbalance": lambda row: row.mean_book_imbalance,
        "book_imbalance_2": lambda row: row.book_imbalance_2,
        "spread_bps": lambda row: row.mean_spread_bps,
        "trade_count": lambda row: float(row.trade_events),
        "current_return_pct": lambda row: row.return_pct,
    }
    result = {}
    for name, getter in features.items():
        horizons = {}
        for horizon in (1, 2, 4, 8):
            pairs = [
                (getter(bucket), bucket.future_returns_pct[horizon])
                for bucket in buckets
                if _finite(getter(bucket))
                and _finite(bucket.future_returns_pct[horizon])
            ]
            horizons[f"{horizon * 15}m"] = {
                "observations": len(pairs),
                "spearman": (
                    _spearman(
                        [pair[0] for pair in pairs],
                        [pair[1] for pair in pairs],
                    )
                    if pairs
                    else math.nan
                ),
            }
        result[name] = horizons
    return result


def _timeline(buckets: list[Bucket]) -> list[dict]:
    rows = []
    for index, bucket in enumerate(buckets):
        if not (
            EVENT_TIMELINE_START_TS
            <= bucket.timestamp
            <= EVENT_TIMELINE_END_TS
        ):
            continue
        history = _history_before(buckets, index)
        flow_values = [
            item.trade_flow_imbalance_2 for item in history
        ]
        book_values = [item.book_imbalance_2 for item in history]
        rows.append(
            {
                "bucket_open_at": _iso(bucket.timestamp),
                "available_at": _iso(
                    bucket.timestamp + BUCKET_SECONDS
                ),
                "open_price": bucket.open_price,
                "close_price": bucket.close_price,
                "return_pct": bucket.return_pct,
                "trade_flow_imbalance": (
                    bucket.trade_flow_imbalance
                ),
                "trade_flow_imbalance_2": (
                    bucket.trade_flow_imbalance_2
                ),
                "trade_flow_2_percentile": (
                    _percentile_rank(
                        bucket.trade_flow_imbalance_2,
                        flow_values,
                    )
                    if _finite(bucket.trade_flow_imbalance_2)
                    else math.nan
                ),
                "book_imbalance": bucket.mean_book_imbalance,
                "book_imbalance_2": bucket.book_imbalance_2,
                "book_2_percentile": (
                    _percentile_rank(
                        bucket.book_imbalance_2, book_values
                    )
                    if _finite(bucket.book_imbalance_2)
                    else math.nan
                ),
                "mean_spread_bps": bucket.mean_spread_bps,
                "trade_count": bucket.trade_events,
                "future_return_120m_pct": (
                    bucket.future_returns_pct[8]
                ),
            }
        )
    return rows


def _descriptive_fast_drop_recall(
    buckets: list[Bucket], candidate_events: list[dict]
) -> dict:
    """Describe recall on known fast drops without treating it as validation."""

    triggers = [
        int(
            datetime.datetime.fromisoformat(
                event["available_at"]
            ).timestamp()
        )
        for event in candidate_events
    ]
    events = []
    for bucket in buckets:
        if (
            bucket.timestamp > EVENT_ONSET_TS
            or bucket.return_pct > -0.5
        ):
            continue
        matching = [
            trigger
            for trigger in triggers
            if (
                bucket.timestamp - LONG_VETO_SECONDS
                <= trigger
                <= bucket.timestamp
            )
        ]
        events.append(
            {
                "bucket_open_at": _iso(bucket.timestamp),
                "return_pct": bucket.return_pct,
                "prior_candidate_trigger": bool(matching),
                "matching_trigger_at": (
                    _iso(max(matching)) if matching else None
                ),
            }
        )
    caught = sum(event["prior_candidate_trigger"] for event in events)
    return {
        "definition_chosen_after_case": (
            "15m return at or below -0.5%; descriptive only"
        ),
        "fast_down_buckets_through_known_onset": len(events),
        "preceded_by_candidate_within_two_hours": caught,
        "descriptive_recall_pct": (
            caught / len(events) * 100 if events else math.nan
        ),
        "events": events,
    }


def _write_input(output: pathlib.Path, buckets: list[Bucket]) -> pathlib.Path:
    path = output / "input_15m.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for bucket in buckets:
            stream.write(
                json.dumps(
                    dataclasses.asdict(bucket),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=True,
                )
                + "\n"
            )
    return path


def _write_timeline(output: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    path = output / "case_timeline.csv"
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def evaluate(
    database_value: typing.Union[str, pathlib.Path],
    output_value: typing.Union[str, pathlib.Path],
) -> pathlib.Path:
    """Evaluate the known case without authorizing any operational action."""

    output = pathlib.Path(output_value).resolve()
    protocol = _verify_protocol(output)
    buckets, source = load_complete_buckets(database_value)
    if not buckets:
        raise ValueError("no complete scalping buckets available")
    input_path = _write_input(output, buckets)
    timeline = _timeline(buckets)
    timeline_path = _write_timeline(output, timeline)
    development = [
        bucket
        for bucket in buckets
        if bucket.timestamp < EVENT_ONSET_TS
    ]
    candidate_events = _candidate_events(
        buckets, maximum_timestamp=EVENT_ONSET_TS
    )
    crash_event = next(
        (
            event
            for event in candidate_events
            if event["bucket_open_at"].startswith(
                "2026-07-27T21:00:00"
            )
        ),
        None,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "status": "diagnostic_only_not_validated",
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol": {
            "path": str((output / "protocol.json").resolve()),
            "sha256": _sha256(output / "protocol.json"),
            "protocol_sha256": protocol["protocol_sha256"],
        },
        "source_snapshot": source,
        "input_15m": _artifact(input_path),
        "case_timeline": _artifact(timeline_path),
        "development_sample": {
            "complete_buckets_before_known_onset": len(development),
            "first_bucket_at": _iso(development[0].timestamp),
            "last_bucket_at": _iso(development[-1].timestamp),
            "future_return_correlations": _correlations(development),
        },
        "post_event_candidate_rule": {
            "comparable_triggers_before_known_onset": len(
                candidate_events
            ),
            "events": candidate_events,
            "diagnostic_crash_trigger": crash_event,
            "diagnostic_conclusion": (
                "The joint sell-pressure pulse was available before the "
                "fast sell-off, but the development sample contains too few "
                "comparable independent events and includes a false "
                "two-hour warning. It may be tested only as a future long "
                "veto, not used as a short-entry signal."
            ),
            "post_event_descriptive_fast_drop_recall": (
                _descriptive_fast_drop_recall(
                    buckets, candidate_events
                )
            ),
        },
        "forward_gate": protocol["forward_gate"],
        "result": {
            "validated_predictor": False,
            "strategy_change_authorized": False,
            "paper_change_authorized": False,
        },
    }
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=True)
        + "\n",
        encoding="utf-8",
    )
    return report_path


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Research-only BTC scalping crash case study"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    protocol_parser = subparsers.add_parser("write-protocol")
    protocol_parser.add_argument("--output", required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--database", required=True)
    evaluate_parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "write-protocol":
        path = write_protocol(arguments.output)
    else:
        path = evaluate(arguments.database, arguments.output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
