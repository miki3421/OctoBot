"""One-shot, offline diagnostic. Does not authorize trading or alter frozen research.

Reuses the September 4 snapshot/exit simulator. This is known historical data,
not a new holdout. Corrects linear-USDT short P/L and applies an actual 3x cost
multiplier to both legs. Funding and intrabar execution remain unmodelled.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sqlite3
from decimal import Decimal

from octobot.ai_strategy_lab import semantic_trend_v2_research as research


def closed_metrics(rows):
    gross = sum((Decimal(str(row["gross_price_pnl"])) for row in rows), Decimal(0))
    fees = sum((Decimal(str(row["known_fees"])) for row in rows), Decimal(0))
    wins = [Decimal(str(row["net_pnl_excluding_funding"])) for row in rows
            if row["net_pnl_excluding_funding"] > 0]
    losses = [-Decimal(str(row["net_pnl_excluding_funding"])) for row in rows
              if row["net_pnl_excluding_funding"] < 0]
    return {
        "trades": len(rows), "wins": len(wins), "losses": len(losses),
        "gross_usdt": float(gross), "fees_usdt": float(fees),
        "net_ex_funding_usdt": float(gross-fees),
        "profit_factor": float(sum(wins)/sum(losses)) if losses else None,
        "same_exit_inverse_ex_funding_usdt": float(-gross-fees),
    }


def recost(trade, multiplier=1.0):
    ratio = trade["exit_price"] / trade["entry_price"]
    gross = (ratio - 1.0) * (1.0 if trade["side"] == "long" else -1.0)
    # Fee 6bps + slippage budget 2bps, paid on entry and exit notional.
    return gross - multiplier * .0008 * (1.0 + ratio)


def audit(database, snapshot, futures):
    if research.file_hash(snapshot) != "dfdb42e6c50ea52a522a20a1cb454cbd21e0b480e38bc1b1e09adefd6337e693":
        raise ValueError("historical decision snapshot differs")
    if research.file_hash(futures) != research.FUTURES_SHA256:
        raise ValueError("historical futures snapshot differs")
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute("SELECT * FROM ai_position_outcomes ORDER BY id")]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("decision journal integrity failed")
    signals = research._load_snapshot(snapshot)
    candles = research.dataset_module.load_collector_series(
        [futures], (research.TIME_FRAME,)
    )[research.SYMBOL][research.TIME_FRAME].values
    original = research.legacy_actions(signals)
    inverted = [{"BUY": "SELL", "SELL": "BUY", "HOLD": "HOLD"}[action] for action in original]
    replay = {}
    for name, actions in (("original", original), ("inverted", inverted)):
        trades = research.simulate(signals, actions, candles)
        for trade in trades:
            trade["linear_base"] = recost(trade)
            trade["linear_stress3"] = recost(trade, 3)
        replay[name] = {"base": research.metrics(trades, "linear_base"),
                        "stress_3x": research.metrics(trades, "linear_stress3")}
    return {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "BTC legacy only; V13 excluded",
        "closed_trade_rows_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        "integrity": integrity, "closed": closed_metrics(rows),
        "by_side": {side: closed_metrics([row for row in rows if row["side"] == side])
                    for side in ("long", "short")},
        "since_2026_09_08": closed_metrics([row for row in rows if row["entry_at"] >= "2026-09-08"]),
        "path_replay": replay,
        "snapshot_sha256": research.file_hash(snapshot),
        "futures_sha256": research.FUTURES_SHA256,
        "exit_simulator_sha256": research.file_hash(research.__file__),
        "diagnostic_source_sha256": research.file_hash(__file__),
        "costs": {"one_way_fee_bps": 6, "one_way_slippage_bps": 2, "stress_multiplier": 3},
        "limitations": ["Known April-June 2026 data, not out-of-sample",
                        "15m bars, next-bar entry; frozen 24h/4h cooldowns differ from native runtime",
                        "OHLC exit approximation; no order-book fills or intrabar path",
                        "Funding excluded; not an estimate of guaranteed executable profits",
                        "All historical closed versions aggregated, not one stationary strategy"],
        "orders_authorized": False, "paper_orders_authorized": False,
        "automatic_promotion": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("database", "snapshot", "futures", "output"):
        parser.add_argument("--"+field, required=True, type=pathlib.Path)
    args = parser.parse_args()
    report = audit(args.database, args.snapshot, args.futures)
    # New diagnostic only: never replace the locked historical reports.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
