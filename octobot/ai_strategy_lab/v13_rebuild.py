"""Build a standalone V13 rebuild from the surviving public cache.

This tool is deliberately offline and result-free with respect to paper/live
execution. It creates a new lineage; it never edits the existing V13 account
or the old diversified journal.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import tempfile
import zipfile

import numpy

from octobot.ai_strategy_lab import trend
from octobot.ai_strategy_lab import v13_benchmark


UTC = dt.timezone.utc
CONFIG = next(value for value in trend.TREND_CONFIGS if value.name == "risk_budgeted_bear_regime_v13")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def json_hash(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def build_collector(cache: pathlib.Path, output: pathlib.Path) -> list[str]:
    """Materialize the surviving 1h Binance cache as a read-only SQLite panel."""
    output.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output)
    db.executescript("CREATE TABLE IF NOT EXISTS ohlcv(symbol TEXT, time_frame TEXT, timestamp INTEGER, candle TEXT, PRIMARY KEY(symbol,time_frame,timestamp));")
    symbols = []
    for symbol_dir in sorted((cache / "futures_um" / "klines").iterdir()):
        month_files = sorted((symbol_dir / "1h").glob("*.zip"))
        if not month_files:
            continue
        symbols.append(symbol_dir.name)
        for archive in month_files:
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.namelist():
                    with zipped.open(member) as raw:
                        reader = csv.reader((line.decode("utf-8") for line in raw))
                        next(reader, None)
                        for row in reader:
                            if len(row) < 6:
                                continue
                            # The research dataset stores Unix seconds; the
                            # exchange archive stores Unix milliseconds.
                            timestamp = int(row[0]) // 1000
                            candle = [timestamp, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])]
                            db.execute("INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?)", (symbol_dir.name, "1h", timestamp, json.dumps(candle, separators=(",", ":"))))
    db.commit()
    db.close()
    return symbols


def build_funding(cache: pathlib.Path, symbols: list[str], output: pathlib.Path) -> None:
    rates = {}
    for symbol in symbols:
        points = []
        for archive in sorted((cache / "futures_um" / "fundingRate" / symbol).glob("*.zip")):
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.namelist():
                    with zipped.open(member) as raw:
                        reader = csv.reader((line.decode("utf-8") for line in raw))
                        next(reader, None)
                        for row in reader:
                            if len(row) >= 3:
                                points.append({"timestamp_ms": int(row[0]), "rate": float(row[2])})
        if points:
            rates[symbol] = sorted({p["timestamp_ms"]: p for p in points}.values(), key=lambda p: p["timestamp_ms"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_version": 1, "rates": rates}, sort_keys=True, indent=2) + "\n")


def load_market(collector: pathlib.Path, funding_path: pathlib.Path):
    from octobot.ai_strategy_lab import dataset, funding
    series = dataset.load_collector_series([collector], required_time_frames=("1h",))
    funding_data = funding.load_funding(funding_path)
    symbols = sorted(set(series) & set(funding_data))
    if len(symbols) < 8:
        raise ValueError(f"insufficient symbols with funding: {len(symbols)}")
    def display(symbol: str) -> str:
        return f"{symbol[:-4]}/USDT:USDT" if symbol.endswith("USDT") else symbol
    mapped_series = {display(symbol): series[symbol]["1h"] for symbol in symbols}
    mapped_funding = {display(symbol): funding_data[symbol] for symbol in symbols}
    market = trend._build_daily_market(mapped_series, mapped_funding)
    return market, [display(symbol) for symbol in symbols]


def run(cache: pathlib.Path, output_root: pathlib.Path) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    collector = output_root / "v13-rebuild-1h.sqlite"
    funding_path = output_root / "v13-rebuild-funding.json"
    symbols = build_collector(cache, collector)
    build_funding(cache, symbols, funding_path)
    market, symbols = load_market(collector, funding_path)
    targets = v13_benchmark.build_targets(market, CONFIG)
    start = max(CONFIG.slow_days, CONFIG.volatility_lookback_days)
    scenarios = {}
    for multiplier in (1, 3):
        scenarios[f"cost_{multiplier}x"] = v13_benchmark.simulate(
            market, targets["v13_quantities"], start,
            CONFIG.fee_per_turnover * multiplier,
            CONFIG.slippage_per_turnover * multiplier,
            delay_days=1,
        )
        scenarios[f"cost_{multiplier}x"].pop("trajectory", None)
    protocol = {
        "schema_version": 1,
        "protocol_version": "v13_standalone_rebuild_v1",
        "created_at": dt.datetime.now(UTC).isoformat(),
        "research_only": True,
        "paper_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "configuration": CONFIG.__dict__,
        "symbols": symbols,
        "inputs": {"collector_sha256": sha256(collector), "funding_sha256": sha256(funding_path)},
        "results": None,
    }
    protocol["protocol_sha256"] = json_hash(protocol)
    (output_root / "protocol.json").write_text(json.dumps(protocol, sort_keys=True, indent=2) + "\n")
    report = {"schema_version": 1, "mode": "standalone_v13_rebuild_training", "research_only": True, "orders_authorized": False, "paper_orders_authorized": False, "automatic_promotion": False, "protocol_sha256": protocol["protocol_sha256"], "market_start": str(market["dates"][0]), "market_end": str(market["dates"][-1]), "symbols": symbols, "scenarios": scenarios}
    (output_root / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.cache, args.output_root), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
