"""Offline V13 V2 ledger replay and frozen passive counterfactual comparison.

Never opens an account or writes to its source. A SQLite backup can be captured
in a newly allocated audit directory; reports refuse to overwrite any file.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import pathlib
import sqlite3
import tempfile

from octobot.ai_strategy_lab import v13_market as market
from octobot.ai_strategy_lab import v13_paper_v2 as paper


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def write_new_json(path, value):
    encoded = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with pathlib.Path(path).open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def capture_snapshot(source, root):
    """SQLite backup includes committed WAL data without modifying the source."""
    source = pathlib.Path(source).resolve()
    directory = pathlib.Path(tempfile.mkdtemp(
        prefix="audit-v13-benchmark-20260913-", dir=pathlib.Path(root).resolve(),
    ))
    destination = directory / "v13-v2.sqlite"
    started = dt.datetime.now(paper.UTC).isoformat()
    original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    backup = sqlite3.connect(destination)
    try:
        original.backup(backup)
        if backup.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("snapshot SQLite integrity failure")
        cutoff = backup.execute("SELECT max(observed_at) FROM market_events").fetchone()[0]
    finally:
        backup.close()
        original.close()
    write_new_json(directory / "capture.json", {
        "source_database": str(source), "snapshot_database": str(destination),
        "capture_started_at_utc": started,
        "capture_finished_at_utc": dt.datetime.now(paper.UTC).isoformat(),
        "cutoff_utc": cutoff, "snapshot_sha256": sha256(destination),
        "method": "SQLite backup API from mode=ro source; committed WAL included",
    })
    return destination


def close(actual, expected, label):
    if not math.isfinite(actual) or not math.isfinite(expected) or not math.isclose(
        actual, expected, rel_tol=1e-11, abs_tol=1e-8,
    ):
        raise ValueError(f"{label} reconciliation failed: {actual} != {expected}")


def fresh_state(saved, *, pending=None):
    return dict(mode=paper.MODE, initial_equity=saved["initial_equity"],
                activation_at=saved["activation_at"], positions={}, order_count=0,
                last_bar=None, last_market_hash=None, pending=pending)


def gross(state):
    return math.fsum(abs(p["quantity"] * p["current_price"])
                     for p in state["positions"].values())


def metrics(state, curve, fills, initial_gross, budget):
    total = paper.totals(state)
    peak = curve[0]["equity"]
    drawdown = 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, 1 - point["equity"] / peak)
    attribution = {}
    for symbol, position in sorted(state["positions"].items()):
        unrealized = position["quantity"] * (position["current_price"] - position["entry_price"])
        price_pnl = position["realized_pnl"] + unrealized
        attribution[symbol] = dict(quantity=position["quantity"],
            entry_price=position["entry_price"], final_mark=position["current_price"],
            realized_pnl_usdt=position["realized_pnl"], unrealized_pnl_usdt=unrealized,
            price_pnl_usdt=price_pnl, funding_pnl_usdt=position["funding"],
            fees_usdt=position["fees"],
            net_pnl_usdt=price_pnl + position["funding"] - position["fees"])
    close(sum(p["net_pnl_usdt"] for p in attribution.values()), total["pnl"], "asset attribution")
    return dict(total, total_return=total["pnl"] / state["initial_equity"],
        price_pnl=total["realized_pnl"] + total["unrealized_pnl"],
        price_pnl_note="Includes observed entry spread/depth and adverse 2bps; fees are separate.",
        max_drawdown=drawdown, annualized_return=None, realized_annual_volatility=None,
        annualization_note="Intraday diagnostic; no annualized return, volatility or Sharpe inferred.",
        initial_target_gross_usdt=budget, initial_actual_gross_usdt=initial_gross,
        initial_actual_gross_fraction_of_initial_equity=initial_gross / state["initial_equity"],
        rounding_unallocated_budget_usdt=budget - initial_gross,
        final_actual_gross_usdt=gross(state),
        final_actual_gross_fraction_of_equity=gross(state) / total["equity"],
        final_net_exposure_usdt=sum(p["quantity"] * p["current_price"] for p in state["positions"].values()),
        turnover_usdt=sum(abs(f["notional"]) for f in fills),
        fill_count=len(fills), fills=fills, asset_attribution=attribution, equity_curve=curve)


def replay(database, *, expected_universe_size=19):
    """Reconcile every saved tick and construct controls without changing inputs."""
    database = pathlib.Path(database).resolve()
    before_hash = sha256(database)
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        if [tuple(row) for row in connection.execute("PRAGMA integrity_check")] != [("ok",)]:
            raise ValueError("SQLite integrity failure")
        if [tuple(row) for row in connection.execute("SELECT mode FROM account_version")] != [(paper.MODE,)]:
            raise ValueError("not a V13 V2 account")
        saved = json.loads(connection.execute("SELECT payload FROM state WHERE id=1").fetchone()[0])
        orders = [dict(row) for row in connection.execute("SELECT * FROM orders ORDER BY id")]
        events = [dict(row) for row in connection.execute("SELECT * FROM market_events ORDER BY observed_at")]
        intents = {row["decision_hash"]: dict(row) for row in connection.execute("SELECT * FROM intents")}
        history = {row["bar"]: dict(row) for row in connection.execute("SELECT * FROM equity_history")}
        stored_marks = {(r["bar"], r["symbol"]): r["price"] for r in connection.execute("SELECT * FROM marks")}
        stored_funding = {(r["symbol"], r["timestamp_ms"]): dict(r) for r in connection.execute("SELECT * FROM funding_events")}
    finally:
        connection.close()
    if sha256(database) != before_hash:
        raise ValueError("source changed during read; use a frozen SQLite backup")
    if saved["mode"] != paper.MODE or saved["initial_equity"] != paper.INITIAL_EQUITY:
        raise ValueError("unexpected account identity or initial capital")
    if not orders or not events:
        raise ValueError("no executed initial portfolio")
    first_hash = events[0]["record_hash"]
    if orders[0]["market_hash"] != first_hash:
        raise ValueError("initial fill is not on the first archived market record")
    first_intent = intents[orders[0]["decision_hash"]]
    weights = paper.targets({"research_targets": {"trend_component_weights": json.loads(first_intent["targets"])}})
    budget = saved["initial_equity"] * sum(abs(w) for w in weights.values())
    initial_record = json.loads(events[0]["payload"])
    universe = sorted(market.normalize_symbol(o["futures_symbol"]) for o in initial_record["symbols"].values())
    if len(set(universe)) != expected_universe_size or len(universe) != expected_universe_size:
        raise ValueError("unexpected benchmark universe")
    ew_pending = dict(targets={s: budget / saved["initial_equity"] / len(universe) for s in universe},
                      noticed_at=first_intent["noticed_at"], decision_hash="counterfactual_initial_equal_weight")
    states = {"actual_v13_v2": fresh_state(saved),
              "hold_actual_initial_v13_quantities": fresh_state(saved),
              "buy_hold_all_19_equal_weight_initial_v13_target_gross": fresh_state(saved, pending=ew_pending)}
    curves = {name: [dict(at=saved["activation_at"], equity=saved["initial_equity"])] for name in states}
    fills_by_account = {name: [] for name in states}
    initial_gross = {}
    grouped = {}
    for fill in orders:
        grouped.setdefault(fill["market_hash"], []).append(fill)
    if set(grouped) - {event["record_hash"] for event in events}:
        raise ValueError("order references an absent market")
    close(history[saved["activation_at"]]["equity"], saved["initial_equity"], "activation equity")
    close(history[saved["activation_at"]]["pnl"], 0, "activation pnl")
    funding_seen, marks_seen = set(), set()
    previous = paper.timestamp(saved["activation_at"])
    max_error = 0.0
    first_fill_batch = grouped[first_hash]
    initial_symbols = sorted({f["symbol"] for f in first_fill_batch})
    for event in events:
        record = json.loads(event["payload"])
        if record["record_hash"] != event["record_hash"] or record["observed_at_end"] != event["observed_at"]:
            raise ValueError("stored market identity mismatch")
        now = paper.timestamp(event["observed_at"])
        processed = paper.timestamp(event["processed_at"])
        if now <= previous or processed < now or paper.timestamp(record["observed_at_start"]) <= paper.timestamp(saved["activation_at"]):
            raise ValueError("noncausal or nonincreasing market timestamps")
        previous = now
        symbols = sorted(market.normalize_symbol(o["futures_symbol"]) for o in record["symbols"].values())
        if symbols != universe:
            raise ValueError("benchmark universe changed")
        quotes = market.market_quotes(record, universe)
        batch = grouped.get(event["record_hash"], [])
        actual_symbols = sorted(s for at, s in stored_marks if at == quotes[s]["timestamp"])
        required_actual = {s for s, p in states["actual_v13_v2"]["positions"].items() if p["quantity"]} | {f["symbol"] for f in batch}
        if not required_actual.issubset(actual_symbols):
            raise ValueError("missing persisted mark for held/traded symbol")
        for name, state in states.items():
            requested = universe if name.startswith("buy_hold_all") else (actual_symbols if name == "actual_v13_v2" else initial_symbols)
            state, generated, funding, marks = paper.process_market(
                state, record, {s: quotes[s] for s in requested}, processed,
            )
            if state.get("risk", {}).get("rejected_intent"):
                raise ValueError("counterfactual exposure preflight rejected: " + state["risk"]["reason"])
            applied = batch if name == "actual_v13_v2" else (first_fill_batch if name.startswith("hold_actual") and event["record_hash"] == first_hash else [])
            for fill in applied:
                quote = quotes[fill["symbol"]]
                intent = intents[fill["decision_hash"]]
                if intent["status"] != "executed" or paper.timestamp(fill["bar"]) <= paper.timestamp(intent["noticed_at"]) or fill["bar"] != quote["timestamp"]:
                    raise ValueError("noncausal or unexecuted fill intent")
                if fill["status"] != "filled" or fill["action"] != ("BUY" if fill["quantity"] > 0 else "SELL"):
                    raise ValueError("invalid fill status or side")
                close(abs(fill["quantity"]) / quote["step"], round(abs(fill["quantity"]) / quote["step"]), "one-contract quantity")
                close(fill["price"], paper.v13_exposure.execution_price(quote, fill["quantity"], market.fill_price), "depth VWAP fill")
                close(fill["notional"], fill["quantity"] * fill["price"], "fill notional")
                close(fill["fee"], abs(fill["notional"]) * quote["fee_rate"], "fill fee")
                position = state["positions"][fill["symbol"]]
                old_realized = position["realized_pnl"]
                paper.apply_fill(position, fill["quantity"], fill["price"], fill["fee"])
                close(position["realized_pnl"] - old_realized, fill["realized_pnl"], "fill realized pnl")
            fills_by_account[name].extend(applied or generated)
            states[name] = state
            if name not in initial_gross:
                initial_gross[name] = gross(state)
            total = paper.totals(state)
            curves[name].append(dict(at=event["observed_at"], equity=total["equity"]))
            if name != "actual_v13_v2":
                continue
            for at, symbol, price in marks:
                key = (at, symbol)
                close(price, stored_marks[key], "stored mark")
                marks_seen.add(key)
            for symbol, at, rate, quantity, mark, amount in funding:
                key = (symbol, at)
                if key not in stored_funding or key in funding_seen:
                    raise ValueError("funding event missing or duplicated")
                funding_seen.add(key)
                for field, value in (("rate", rate), ("quantity", quantity), ("reference_mark", mark), ("amount", amount)):
                    close(value, stored_funding[key][field], "funding " + field)
            observed = history[event["observed_at"]]
            for field in ("equity", "pnl"):
                close(total[field], observed[field], "tick " + field)
                max_error = max(max_error, abs(total[field] - observed[field]))
    if len(history) != len(events) + 1 or marks_seen != set(stored_marks) or funding_seen != set(stored_funding):
        raise ValueError("orphan equity, mark or funding ledger rows")
    actual = states["actual_v13_v2"]
    if saved["last_market_hash"] != events[-1]["record_hash"] or saved["order_count"] != len(orders):
        raise ValueError("terminal state counters differ")
    if set(actual["positions"]) != set(saved["positions"]):
        raise ValueError("terminal position universe differs")
    for symbol, position in actual["positions"].items():
        for field in ("quantity", "entry_price", "current_price", "realized_pnl", "fees", "funding"):
            close(position[field], saved["positions"][symbol][field], "terminal " + symbol + " " + field)
        if position["last_mark_at"] != saved["positions"][symbol]["last_mark_at"]:
            raise ValueError("terminal mark time differs")
    accounts = {name: metrics(state, curves[name], fills_by_account[name], initial_gross[name], budget)
                for name, state in states.items()}
    actual_metrics = accounts["actual_v13_v2"]
    differences = {name: dict(net_pnl_difference_usdt=actual_metrics["pnl"] - result["pnl"],
        initial_gross_difference_usdt=actual_metrics["initial_actual_gross_usdt"] - result["initial_actual_gross_usdt"])
        for name, result in accounts.items() if name != "actual_v13_v2"}
    return dict(snapshot_sha256=before_hash, initial_equity=saved["initial_equity"],
        activation_at_utc=saved["activation_at"], first_market_at_utc=events[0]["observed_at"],
        cutoff_utc=events[-1]["observed_at"],
        duration_hours=(previous - paper.timestamp(saved["activation_at"])).total_seconds() / 3600,
        market_event_count=len(events), equity_point_count=len(history),
        funding_event_count=len(stored_funding), actual_intent_count=len(intents),
        actual_rebalance_fill_batches=max(0, len(grouped) - 1),
        market_record_hashes=[event["record_hash"] for event in events], universe=universe,
        first_intent=first_intent, maximum_ledger_reconciliation_error_usdt=max_error,
        accounts=accounts, actual_minus_controls=differences)


def run_comparison(database, method):
    method = pathlib.Path(method).resolve()
    protocol = json.loads(method.read_text())
    paper_method = protocol.get("paper")
    if (
        protocol.get("id") != "v13_benchmark_comparison_v1"
        or protocol.get("orders_authorized") is not False
        or protocol.get("paper_orders_authorized") is not False
        or protocol.get("automatic_promotion") is not False
        or "results" not in protocol or protocol["results"] is not None
        or not isinstance(paper_method, dict)
        or paper_method.get("initial_equity") != paper.INITIAL_EQUITY
        or isinstance(paper_method.get("cost_multiplier"), bool)
        or paper_method.get("cost_multiplier") != 1
    ):
        raise ValueError("unexpected benchmark method")
    database = pathlib.Path(database).resolve()
    capture = json.loads((database.parent / "capture.json").read_text())
    if capture["snapshot_sha256"] != sha256(database):
        raise ValueError("snapshot no longer matches capture manifest")
    method_at = dt.datetime.strptime(protocol["recorded_at_utc"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=paper.UTC)
    if paper.timestamp(capture["capture_started_at_utc"]) <= method_at:
        raise ValueError("snapshot predates method freeze")
    result = replay(database)
    if result["cutoff_utc"] != capture["cutoff_utc"]:
        raise ValueError("snapshot cutoff differs from capture")
    return dict(schema_version=1, mode="retrospective_paper_benchmark_diagnostic",
        research_only=True, orders_authorized=False, paper_orders_authorized=False,
        automatic_promotion=False, parameters_tuned=False, new_out_of_sample_evidence=False,
        new_account_created=False, original_account_only="trend_v13_paper_v2",
        methodology={"path": str(method), "sha256": sha256(method)},
        source_capture=capture,
        dependencies={path.name: sha256(path) for path in (
            pathlib.Path(__file__), pathlib.Path(paper.__file__), pathlib.Path(market.__file__))},
        limitations=[
            "Counterfactual constructed after method freeze on September 13; only V13 V2 was actually active from September 12.",
            "Initial V13 holdings are a negative accounting control, not an independent strategy; no rebalance means no allocation timing contrast.",
            "Equal initial target gross and cost model do not guarantee equal rounded exposure, realized volatility or beta.",
            "Full payload hashes and every persisted tick are verified; skipped collector records prevent proving the full upstream journal chain from this database alone.",
            paper.FUNDING_NOTE,
            "One-contract simulation does not certify all exchange minimums; no terminal liquidation.",
            "Short, already-observed sample; descriptive differences are not proven alpha.",
        ], comparison=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", type=pathlib.Path)
    source.add_argument("--capture-source", type=pathlib.Path)
    parser.add_argument("--snapshot-root", type=pathlib.Path)
    parser.add_argument("--method", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("output already exists; refusing overwrite")
    if args.capture_source and not args.snapshot_root:
        parser.error("--capture-source requires --snapshot-root")
    database = args.database or capture_snapshot(args.capture_source, args.snapshot_root)
    result = run_comparison(database, args.method)
    if args.output:
        write_new_json(args.output, result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
