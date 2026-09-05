"""One-shot diagnostic for Semantic Trend V2 using existing local evidence.

This module is deliberately not a collector.  It snapshots the already stored
TA matrix inputs, evaluates one frozen rule against the immutable Binance
futures archive, writes a terminal verdict, and exits.  It cannot import an
exchange client or authorize an order.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from tentacles.Evaluator.Strategies.ai_strategies_evaluator.guarded_llm import (
    semantic_trend_v2_decision,
)


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_semantic_trend_pullback_v2"
SOURCE_MODEL = "deterministic-alignment"
SOURCE_PROMPT = "deterministic-alignment-v1"
START_TRIGGERED_AT = 1_776_838_500  # 2026-04-22 14:15 UTC
END_TRIGGERED_AT = 1_782_863_100  # 2026-06-30 23:45 UTC
SYMBOL = "BTC/USDT:USDT"
TIME_FRAME = "15m"
POSITION_FRACTION = 0.10
INITIAL_STOP_FRACTION = 0.01
PROFIT_ACTIVATION_FRACTION = 0.012
LOCKED_PROFIT_FRACTION = 0.01
MAX_HOLD_BARS = 96
STOP_COOLDOWN_BARS = 96
OTHER_COOLDOWN_BARS = 16
BASE_ROUND_TRIP_COST = 0.0016
STRESS_ROUND_TRIP_COST = 0.0032
FUTURES_SHA256 = "cdacae131f194c2b4e0b5a2dce51569de23b6fca9be9f34e68240769c7c53a6d"
FUTURES_BYTES = 73_801_728


class ResearchError(ValueError):
    """Raised when frozen inputs or one-shot invariants differ."""


def canonical_json(value: typing.Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def logical_hash(value: typing.Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path_value: str | pathlib.Path) -> str:
    digest = hashlib.sha256()
    with pathlib.Path(path_value).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_protocol() -> dict:
    """Return the result-free rules fixed before historical execution."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_on": "2026-09-04",
        "status": "historical_diagnostic_due_to_known_and_reused_data",
        "question": (
            "Can the physical trend meaning of DoubleMA and ADX prevent the "
            "legacy contrarian-breakout error while retaining cost-aware entries?"
        ),
        "inputs": {
            "source_journal_slice": {
                "model": SOURCE_MODEL,
                "prompt_version": SOURCE_PROMPT,
                "start_triggered_at": START_TRIGGERED_AT,
                "end_triggered_at": END_TRIGGERED_AT,
                "fields": ["id", "triggered_at", "input_json", "action", "approved"],
                "outcome_fields_read_during_snapshot": False,
            },
            "futures_archive": {
                "sha256": FUTURES_SHA256,
                "bytes": FUTURES_BYTES,
                "symbol": SYMBOL,
                "time_frame": TIME_FRAME,
            },
        },
        "candidate": {
            "name": "semantic_trend_v2",
            "higher_timeframes": ["4h", "1h"],
            "physical_trend_inputs": [
                "DoubleMovingAverageTrendEvaluator",
                "ADXMomentumEvaluator",
            ],
            "physical_note_mapping": "positive=bullish, negative=bearish",
            "minimum_mean_absolute_trend_note": 0.10,
            "timing_timeframe": "15m",
            "mandatory_macd_magnitude": 0.15,
            "timing_confirmation": "MACD plus RSI>=0.20 or BB>=0.10 in the same direction",
            "entry_deduplication": "only HOLD/direction to BUY/SELL transitions",
            "parameter_search": False,
            "post_result_tuning": False,
        },
        "execution": {
            "entry": "next 15m Binance futures open",
            "one_position_at_a_time": True,
            "position_fraction": POSITION_FRACTION,
            "initial_stop_fraction": INITIAL_STOP_FRACTION,
            "profit_activation_fraction": PROFIT_ACTIVATION_FRACTION,
            "locked_profit_fraction": LOCKED_PROFIT_FRACTION,
            "maximum_hold_bars": MAX_HOLD_BARS,
            "stop_cooldown_bars": STOP_COOLDOWN_BARS,
            "other_cooldown_bars": OTHER_COOLDOWN_BARS,
            "intrabar_ordering": "conservative: existing stop before activation; new lock applies next bar",
            "base_round_trip_cost": BASE_ROUND_TRIP_COST,
            "stress_round_trip_cost": STRESS_ROUND_TRIP_COST,
        },
        "gates": {
            "minimum_trades": 12,
            "base_total_return_strictly_positive": True,
            "stress_total_return_strictly_positive": True,
            "base_profit_factor_minimum": 1.10,
            "stress_profit_factor_minimum": 1.00,
            "maximum_drawdown_maximum": 0.03,
            "positive_active_month_fraction_minimum": 0.50,
            "must_outperform_legacy_same_execution": True,
            "approved_side": "at least 6 trades, positive stress return and stress PF>1",
        },
        "interpretation": {
            "historical_pass_can_authorize": "manual paper-only integration after verification",
            "historical_pass_cannot_authorize": ["real orders", "automatic promotion", "income claims"],
            "failure_action": "reject candidate and do not create a collector or service",
        },
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "results": None,
    }


def _write_immutable_json(path: pathlib.Path, payload: dict) -> pathlib.Path:
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise ResearchError(f"immutable artifact differs: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
    return path


def write_protocol(path_value: str | pathlib.Path) -> pathlib.Path:
    payload = frozen_protocol()
    payload["protocol_sha256"] = logical_hash(payload)
    return _write_immutable_json(pathlib.Path(path_value), payload)


def snapshot_inputs(database_value: str | pathlib.Path, output_value: str | pathlib.Path) -> dict:
    """Freeze input matrices without reading prices, orders, or outcomes."""

    uri = f"file:{pathlib.Path(database_value).resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """
            SELECT id, triggered_at, input_json, action, approved
            FROM ai_decisions
            WHERE model = ? AND prompt_version = ?
              AND triggered_at BETWEEN ? AND ?
            ORDER BY triggered_at, id
            """,
            (SOURCE_MODEL, SOURCE_PROMPT, START_TRIGGERED_AT, END_TRIGGERED_AT),
        ).fetchall()
    if len(rows) < 1_000:
        raise ResearchError("insufficient frozen decision inputs")

    payload_rows = []
    previous_triggered_at = None
    for row_id, triggered_at, input_json, action, approved in rows:
        technical_data = json.loads(input_json)
        if not isinstance(technical_data, dict):
            raise ResearchError("invalid technical input payload")
        if previous_triggered_at is not None and triggered_at <= previous_triggered_at:
            raise ResearchError("decision input timestamps are not strictly increasing")
        previous_triggered_at = triggered_at
        payload_rows.append(
            {
                "source_decision_id": int(row_id),
                "triggered_at": int(triggered_at),
                "technical_data": technical_data,
                "legacy_action": str(action),
                "legacy_approved": bool(approved),
            }
        )

    output = pathlib.Path(output_value)
    serialized = "".join(canonical_json(row) + "\n" for row in payload_rows)
    if output.exists() and output.read_text(encoding="utf-8") != serialized:
        raise ResearchError(f"immutable snapshot differs: {output}")
    if not output.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    return {
        "rows": len(payload_rows),
        "first_triggered_at": payload_rows[0]["triggered_at"],
        "last_triggered_at": payload_rows[-1]["triggered_at"],
        "sha256": file_hash(output),
        "bytes": output.stat().st_size,
    }


def write_implementation_lock(
    protocol_value: str | pathlib.Path,
    snapshot_value: str | pathlib.Path,
    futures_value: str | pathlib.Path,
    test_value: str | pathlib.Path,
    output_value: str | pathlib.Path,
) -> pathlib.Path:
    """Bind the exact result-free implementation before price evaluation."""

    protocol_path = pathlib.Path(protocol_value)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("results") is not None:
        raise ResearchError("implementation lock requires a result-free protocol")
    futures_path = pathlib.Path(futures_value)
    if futures_path.stat().st_size != FUTURES_BYTES or file_hash(futures_path) != FUTURES_SHA256:
        raise ResearchError("futures archive differs before implementation lock")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "protocol_sha256": protocol["protocol_sha256"],
        "protocol_file_sha256": file_hash(protocol_path),
        "snapshot_sha256": file_hash(snapshot_value),
        "futures_sha256": FUTURES_SHA256,
        "source_sha256": file_hash(__file__),
        "test_sha256": file_hash(test_value),
        "outcomes_read": False,
        "results": None,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    payload["content_sha256"] = logical_hash(payload)
    return _write_immutable_json(pathlib.Path(output_value), payload)


def _load_snapshot(path_value: str | pathlib.Path) -> list[dict]:
    rows = []
    with pathlib.Path(path_value).open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    if len(rows) < 1_000:
        raise ResearchError("frozen snapshot is incomplete")
    return rows


def candidate_actions(rows: list[dict]) -> list[str]:
    actions = []
    for row in rows:
        decision = semantic_trend_v2_decision(
            row["technical_data"], ("15m", "1h", "4h")
        )
        actions.append(decision.action)
    return actions


def legacy_actions(rows: list[dict]) -> list[str]:
    return [
        row["legacy_action"] if row["legacy_approved"] else "HOLD"
        for row in rows
    ]


def _simulate_trade(candles: numpy.ndarray, entry_index: int, side: str) -> dict:
    entry_price = float(candles[entry_index, 1])
    if side == "long":
        stop_price = entry_price * (1 - INITIAL_STOP_FRACTION)
        activation_price = entry_price * (1 + PROFIT_ACTIVATION_FRACTION)
        locked_price = entry_price * (1 + LOCKED_PROFIT_FRACTION)
    else:
        stop_price = entry_price * (1 + INITIAL_STOP_FRACTION)
        activation_price = entry_price * (1 - PROFIT_ACTIVATION_FRACTION)
        locked_price = entry_price * (1 - LOCKED_PROFIT_FRACTION)

    activated = False
    last_index = min(len(candles) - 1, entry_index + MAX_HOLD_BARS - 1)
    exit_index = last_index
    exit_price = float(candles[last_index, 4])
    exit_reason = "timeout"
    for index in range(entry_index, last_index + 1):
        high = float(candles[index, 2])
        low = float(candles[index, 3])
        active_stop = locked_price if activated else stop_price
        if side == "long" and low <= active_stop:
            exit_index, exit_price = index, active_stop
            exit_reason = "locked_profit" if activated else "stop_loss"
            break
        if side == "short" and high >= active_stop:
            exit_index, exit_price = index, active_stop
            exit_reason = "locked_profit" if activated else "stop_loss"
            break
        if not activated:
            activated = (
                high >= activation_price if side == "long" else low <= activation_price
            )

    gross_return = (
        exit_price / entry_price - 1
        if side == "long"
        else entry_price / exit_price - 1
    )
    return {
        "entry_index": entry_index,
        "exit_index": exit_index,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_return": gross_return,
        "exit_reason": exit_reason,
    }


def simulate(rows: list[dict], actions: list[str], candles: numpy.ndarray) -> list[dict]:
    timestamps = candles[:, 0].astype(numpy.int64)
    trades: list[dict] = []
    previous_action = "HOLD"
    next_available_index = 0
    for row, action in zip(rows, actions, strict=True):
        is_transition = action in {"BUY", "SELL"} and action != previous_action
        previous_action = action
        if not is_transition:
            continue
        entry_index = int(numpy.searchsorted(timestamps, row["triggered_at"] + 900))
        if entry_index >= len(candles) or entry_index < next_available_index:
            continue
        trade = _simulate_trade(
            candles, entry_index, "long" if action == "BUY" else "short"
        )
        trade["source_decision_id"] = row["source_decision_id"]
        trade["signal_timestamp"] = row["triggered_at"]
        trade["entry_timestamp"] = int(timestamps[entry_index])
        trade["exit_timestamp"] = int(timestamps[trade["exit_index"]])
        trade["base_net_return"] = trade["gross_return"] - BASE_ROUND_TRIP_COST
        trade["stress_net_return"] = trade["gross_return"] - STRESS_ROUND_TRIP_COST
        trades.append(trade)
        cooldown = (
            STOP_COOLDOWN_BARS
            if trade["exit_reason"] == "stop_loss"
            else OTHER_COOLDOWN_BARS
        )
        next_available_index = trade["exit_index"] + cooldown
    return trades


def _profit_factor(returns: numpy.ndarray) -> float:
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    if losses == 0:
        return 1_000_000_000.0 if gains > 0 else 0.0
    return gains / losses


def metrics(trades: list[dict], net_field: str) -> dict:
    if not trades:
        return {
            "trades": 0,
            "total_return": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "maximum_drawdown": 0.0,
            "positive_active_month_fraction": 0.0,
            "stops": 0,
            "longs": 0,
            "shorts": 0,
        }
    returns = numpy.asarray([trade[net_field] for trade in trades], dtype=float)
    allocated = POSITION_FRACTION * returns
    equity = numpy.cumprod(1 + allocated)
    running_peak = numpy.maximum.accumulate(numpy.concatenate(([1.0], equity)))
    drawdowns = 1 - numpy.concatenate(([1.0], equity)) / running_peak
    monthly: dict[str, float] = {}
    for trade, value in zip(trades, allocated, strict=True):
        month = datetime.datetime.fromtimestamp(
            trade["exit_timestamp"], datetime.timezone.utc
        ).strftime("%Y-%m")
        monthly[month] = monthly.get(month, 0.0) + float(value)
    return {
        "trades": len(trades),
        "total_return": float(equity[-1] - 1),
        "profit_factor": _profit_factor(returns),
        "win_rate": float(numpy.mean(returns > 0)),
        "maximum_drawdown": float(numpy.max(drawdowns)),
        "positive_active_month_fraction": float(
            sum(value > 0 for value in monthly.values()) / len(monthly)
        ),
        "active_months": monthly,
        "stops": sum(trade["exit_reason"] == "stop_loss" for trade in trades),
        "longs": sum(trade["side"] == "long" for trade in trades),
        "shorts": sum(trade["side"] == "short" for trade in trades),
    }


def side_metrics(trades: list[dict], side: str) -> dict:
    selected = [trade for trade in trades if trade["side"] == side]
    result = metrics(selected, "stress_net_return")
    result["approved"] = (
        result["trades"] >= 6
        and result["total_return"] > 0
        and result["profit_factor"] > 1.0
    )
    return result


def evaluate_gates(candidate: dict, legacy: dict, sides: dict) -> dict:
    checks = {
        "minimum_trades": candidate["base"]["trades"] >= 12,
        "base_total_return_strictly_positive": candidate["base"]["total_return"] > 0,
        "stress_total_return_strictly_positive": candidate["stress"]["total_return"] > 0,
        "base_profit_factor_minimum": candidate["base"]["profit_factor"] >= 1.10,
        "stress_profit_factor_minimum": candidate["stress"]["profit_factor"] >= 1.00,
        "maximum_drawdown_maximum": candidate["stress"]["maximum_drawdown"] <= 0.03,
        "positive_active_month_fraction_minimum": (
            candidate["stress"]["positive_active_month_fraction"] >= 0.50
        ),
        "outperforms_legacy_same_execution": (
            candidate["stress"]["total_return"] > legacy["stress"]["total_return"]
        ),
        "at_least_one_approved_side": any(value["approved"] for value in sides.values()),
    }
    return {"checks": checks, "passed": sum(checks.values()), "total": len(checks), "all_passed": all(checks.values())}


def evaluate(
    protocol_value: str | pathlib.Path,
    snapshot_value: str | pathlib.Path,
    futures_value: str | pathlib.Path,
    output_value: str | pathlib.Path,
    trades_value: str | pathlib.Path,
) -> dict:
    protocol_path = pathlib.Path(protocol_value)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    expected = frozen_protocol()
    expected_hash = logical_hash(expected)
    if protocol.get("protocol_sha256") != expected_hash or protocol.get("results") is not None:
        raise ResearchError("protocol is not the frozen result-free artifact")
    futures_path = pathlib.Path(futures_value)
    if futures_path.stat().st_size != FUTURES_BYTES or file_hash(futures_path) != FUTURES_SHA256:
        raise ResearchError("futures archive differs from frozen input")

    rows = _load_snapshot(snapshot_value)
    series = dataset_module.load_collector_series(
        [futures_path], (TIME_FRAME,)
    )[SYMBOL][TIME_FRAME]
    candles = series.values
    candidate_trades = simulate(rows, candidate_actions(rows), candles)
    legacy_trades = simulate(rows, legacy_actions(rows), candles)
    candidate_summary = {
        "base": metrics(candidate_trades, "base_net_return"),
        "stress": metrics(candidate_trades, "stress_net_return"),
    }
    legacy_summary = {
        "base": metrics(legacy_trades, "base_net_return"),
        "stress": metrics(legacy_trades, "stress_net_return"),
    }
    sides = {
        "long": side_metrics(candidate_trades, "long"),
        "short": side_metrics(candidate_trades, "short"),
    }
    gates = evaluate_gates(candidate_summary, legacy_summary, sides)
    verdict = "PAPER_ELIGIBLE_DIAGNOSTIC" if gates["all_passed"] else "REJECTED_HISTORICAL_DIAGNOSTIC"
    trade_payload = {
        "schema_version": SCHEMA_VERSION,
        "protocol_sha256": expected_hash,
        "candidate": candidate_trades,
        "legacy": legacy_trades,
    }
    trades_path = pathlib.Path(trades_value)
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    trades_path.write_text(
        json.dumps(trade_payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "protocol_sha256": expected_hash,
        "snapshot_sha256": file_hash(snapshot_value),
        "futures_sha256": FUTURES_SHA256,
        "candidate": candidate_summary,
        "legacy": legacy_summary,
        "candidate_sides_stress": sides,
        "gates": gates,
        "verdict": verdict,
        "trades_artifact": {
            "path": str(trades_path),
            "sha256": file_hash(trades_path),
            "bytes": trades_path.stat().st_size,
        },
        "historical_role": "diagnostic_only_due_to_known_and_reused_data",
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
    }
    report["content_sha256"] = logical_hash(report)
    output = pathlib.Path(output_value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    protocol_parser = subparsers.add_parser("protocol")
    protocol_parser.add_argument("--database", required=True)
    protocol_parser.add_argument("--protocol", required=True)
    protocol_parser.add_argument("--snapshot", required=True)
    protocol_parser.add_argument("--futures", required=True)
    protocol_parser.add_argument("--test", required=True)
    protocol_parser.add_argument("--lock", required=True)
    evaluation_parser = subparsers.add_parser("evaluate")
    evaluation_parser.add_argument("--protocol", required=True)
    evaluation_parser.add_argument("--snapshot", required=True)
    evaluation_parser.add_argument("--futures", required=True)
    evaluation_parser.add_argument("--output", required=True)
    evaluation_parser.add_argument("--trades", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "protocol":
        protocol_path = write_protocol(arguments.protocol)
        snapshot = snapshot_inputs(arguments.database, arguments.snapshot)
        lock_path = write_implementation_lock(
            protocol_path,
            arguments.snapshot,
            arguments.futures,
            arguments.test,
            arguments.lock,
        )
        print(canonical_json({"protocol": str(protocol_path), "snapshot": snapshot, "lock": str(lock_path)}))
        return 0
    report = evaluate(
        arguments.protocol,
        arguments.snapshot,
        arguments.futures,
        arguments.output,
        arguments.trades,
    )
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
