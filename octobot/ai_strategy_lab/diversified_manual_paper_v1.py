"""Manual paper mirror for the frozen diversified forward portfolio.

This service consumes the existing hash-chained, orderless forward journal. It
never contacts an exchange and cannot create real orders.  A user-authorized
paper account is armed at the latest record that exists on first start, so no
already-observed return is credited.  The first later daily decision opens the
simulated target portfolio.  Subsequent equity changes are computed from
replayable market closes and funding data in the local daily snapshots.
"""

from __future__ import annotations

import argparse
import gzip
import datetime
import fcntl
import hashlib
import json
import math
import os
import pathlib
import sqlite3
import tempfile
import time
import typing


SCHEMA_VERSION = 1
MODE = "diversified_trend_cointegration_manual_paper_v1"
UPSTREAM_PROTOCOL_VERSION = (
    "crypto_diversified_trend_cointegration_forward_v1"
)
INITIAL_EQUITY = 10_000.0
BASE_COST_PER_TURNOVER = 0.0008
MAXIMUM_GROSS_WEIGHT = 1.0
MANUAL_AUTHORIZATION = "explicit_user_request_2026-09-04"
UTC = datetime.timezone.utc


class PaperMirrorError(ValueError):
    """Raised when paper or upstream fail-closed invariants differ."""


class PaperMarketDataError(PaperMirrorError):
    """Raised when market data required for mark-to-market is unavailable."""


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def _canonical_bytes(value: typing.Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_hash(value: typing.Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _normalize_symbol(symbol: typing.Any) -> str:
    if not isinstance(symbol, str):
        raise PaperMirrorError("upstream research symbol is not text")
    stripped = symbol
    if "/" in symbol and ":" in symbol:
        left, right = symbol.split(":", 1)
        if "/" in left:
            base, quote = left.split("/", 1)
            if right == quote:
                return f"{base}{quote}"
    return symbol.replace("/", "").replace(":", "")


def _daily_snapshot_path(journal_root: pathlib.Path, bar_date: str) -> pathlib.Path:
    return journal_root / "daily" / f"{bar_date}.json.gz"


def _load_daily_snapshot(
    journal_root: pathlib.Path,
    bar_date: str,
    cache: dict[str, dict[str, typing.Any]],
) -> dict[str, dict[str, float]]:
    if bar_date in cache:
        return cache[bar_date]
    path = _daily_snapshot_path(journal_root, bar_date)
    if not path.exists():
        raise PaperMarketDataError(f"daily market snapshot missing: {bar_date}")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    symbols_payload = payload.get("symbols")
    if not isinstance(symbols_payload, dict):
        raise PaperMarketDataError(f"invalid daily snapshot for {bar_date}")

    normalized: dict[str, dict[str, float]] = {}
    for raw_symbol, content in symbols_payload.items():
        if not isinstance(content, dict):
            continue
        close = content.get("close")
        funding_sum = content.get("funding_rate_sum", 0.0)
        if not isinstance(close, (float, int)):
            raise PaperMarketDataError(f"invalid close for {raw_symbol} on {bar_date}")
        if not isinstance(funding_sum, (float, int)):
            raise PaperMarketDataError(
                f"invalid funding for {raw_symbol} on {bar_date}"
            )
        normalized[_normalize_symbol(raw_symbol)] = {
            "close": float(close),
            "funding_rate_sum": float(funding_sum),
        }
    if not normalized:
        raise PaperMarketDataError(f"daily snapshot empty: {bar_date}")
    cache[bar_date] = normalized
    return normalized


def _mark_to_market_pnl(
    positions: dict[str, float],
    journal_root: pathlib.Path,
    previous_bar: str,
    current_bar: str,
    cache: dict[str, dict[str, typing.Any]],
) -> tuple[float, float, float]:
    if not positions:
        return 0.0, 0.0, 0.0

    previous_snapshot = _load_daily_snapshot(journal_root, previous_bar, cache)
    current_snapshot = _load_daily_snapshot(journal_root, current_bar, cache)

    price_return = 0.0
    funding_return = 0.0
    for key, weight in positions.items():
        _, symbol = key.split("|", 1)
        previous_symbol = previous_snapshot.get(symbol)
        current_symbol = current_snapshot.get(symbol)
        if previous_symbol is None or current_symbol is None:
            raise PaperMarketDataError(
                f"missing market data for {symbol} on period {previous_bar}->{current_bar}"
            )
        previous_close = previous_symbol["close"]
        current_close = current_symbol["close"]
        if previous_close <= 0.0 or current_close <= 0.0:
            raise PaperMarketDataError(
                f"invalid close for {symbol} on {previous_bar} or {current_bar}"
            )
        price_return += weight * (current_close / previous_close - 1.0)
        funding_return += -weight * current_symbol["funding_rate_sum"]

    return price_return, funding_return, price_return + funding_return


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_upstream(
    journal_path: pathlib.Path,
    protocol_path: pathlib.Path,
    implementation_lock_path: pathlib.Path,
) -> tuple[list[dict], dict, dict]:
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    implementation_lock = json.loads(
        implementation_lock_path.read_text(encoding="utf-8")
    )
    for label, value in (
        ("protocol", protocol),
        ("implementation lock", implementation_lock),
    ):
        for field in (
            "orders_authorized",
            "paper_orders_authorized",
            "automatic_promotion",
        ):
            if value.get(field) is not False:
                raise PaperMirrorError(
                    f"upstream {label} safety invariant differs: {field}"
                )
    if (
        protocol.get("protocol_version") != UPSTREAM_PROTOCOL_VERSION
        or protocol.get("results") is not None
        or implementation_lock.get("observer_type")
        != "diversified_trend_cointegration_forward_observer_v1"
        or implementation_lock.get("protocol_sha256")
        != protocol.get("protocol_sha256")
    ):
        raise PaperMirrorError("upstream protocol or lock lineage differs")

    records: list[dict] = []
    previous_hash = None
    previous_date = None
    with journal_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise PaperMirrorError(
                    f"blank upstream journal line {line_number}"
                )
            record = json.loads(line)
            payload = record.get("decision_payload")
            if not isinstance(payload, dict):
                raise PaperMirrorError("upstream decision payload is missing")
            unsigned_payload = {
                key: value
                for key, value in payload.items()
                if key != "decision_payload_sha256"
            }
            if payload.get("decision_payload_sha256") != _json_hash(
                unsigned_payload
            ):
                raise PaperMirrorError("upstream decision payload hash differs")
            unsigned_record = {
                key: value
                for key, value in record.items()
                if key != "journal_record_hash"
            }
            if record.get("journal_record_hash") != _json_hash(unsigned_record):
                raise PaperMirrorError("upstream journal record hash differs")
            if record.get("previous_journal_hash") != previous_hash:
                raise PaperMirrorError("upstream journal chain differs")
            current_date = datetime.date.fromisoformat(payload["bar_date"])
            if (
                previous_date is not None
                and current_date != previous_date + datetime.timedelta(days=1)
            ):
                raise PaperMirrorError("upstream journal calendar differs")
            for field in (
                "orders_authorized",
                "paper_orders_authorized",
                "automatic_promotion",
                "credentials_used",
            ):
                if payload.get(field) is not False:
                    raise PaperMirrorError(
                        f"upstream decision safety invariant differs: {field}"
                    )
            lineage = payload.get("lineage", {})
            if (
                payload.get("mode") != "forward_research_target_only"
                or payload.get("research_only") is not True
                or lineage.get("forward_protocol_sha256")
                != protocol.get("protocol_sha256")
                or lineage.get("implementation_lock_sha256")
                != implementation_lock.get("implementation_lock_sha256")
            ):
                raise PaperMirrorError("upstream decision lineage differs")
            records.append(record)
            previous_hash = record["journal_record_hash"]
            previous_date = current_date
    if not records:
        raise PaperMirrorError("upstream journal has no decision")
    return records, protocol, implementation_lock


def _target_positions(payload: dict) -> dict[str, float]:
    targets = payload.get("research_targets")
    if not isinstance(targets, dict):
        raise PaperMirrorError("upstream research targets are missing")
    if targets.get("cross_sleeve_netting_applied") is not False:
        raise PaperMirrorError("upstream cross-sleeve accounting differs")
    positions: dict[str, float] = {}
    for sleeve, field in (
        ("trend", "trend_effective_portfolio_weights"),
        ("cointegration", "cointegration_effective_portfolio_weights"),
    ):
        weights = targets.get(field)
        if not isinstance(weights, dict):
            raise PaperMirrorError(f"upstream {sleeve} weights are invalid")
        for symbol, raw_weight in weights.items():
            weight = float(raw_weight)
            if not math.isfinite(weight):
                raise PaperMirrorError("upstream target weight is not finite")
            if abs(weight) > 1e-12:
                positions[f"{sleeve}|{_normalize_symbol(symbol)}"] = weight
    gross = sum(abs(value) for value in positions.values())
    if gross > MAXIMUM_GROSS_WEIGHT + 1e-9:
        raise PaperMirrorError("upstream gross target exceeds paper limit")
    return positions


class PaperStore:
    """Transactional SQLite journal for paper decisions and rebalance fills."""

    def __init__(self, path: pathlib.Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=15)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=15000")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS state (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upstream_journal_hash TEXT NOT NULL UNIQUE,
                bar_date TEXT NOT NULL,
                target_bar TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                upstream_equity REAL NOT NULL,
                paper_equity REAL NOT NULL,
                paper_daily_return REAL NOT NULL,
                paper_pnl REAL NOT NULL,
                turnover REAL NOT NULL,
                estimated_cost REAL NOT NULL,
                order_count INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                sleeve TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                delta_weight REAL NOT NULL,
                target_weight REAL NOT NULL,
                notional REAL NOT NULL,
                estimated_cost REAL NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY(decision_id) REFERENCES decisions(id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        self.connection.commit()
        self.integrity = str(
            self.connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        if self.integrity != "ok":
            raise PaperMirrorError(
                f"diversified paper database integrity={self.integrity}"
            )

    def close(self) -> None:
        self.connection.close()

    def load_state(self) -> dict | None:
        row = self.connection.execute(
            "SELECT payload_json FROM state WHERE id = 1"
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def initialize(self, record: dict) -> dict:
        now = _utc_now().isoformat()
        payload = record["decision_payload"]
        state = {
            "schema_version": SCHEMA_VERSION,
            "mode": MODE,
            "manual_authorization": MANUAL_AUTHORIZATION,
            "phase": "armed_waiting_next_decision",
            "activated_at": now,
            "activation_boundary_journal_hash": record["journal_record_hash"],
            "activation_boundary_bar": payload["bar_date"],
            "last_journal_hash": record["journal_record_hash"],
            "last_bar_date": payload["bar_date"],
            "upstream_equity": float(payload["base"]["portfolio_equity"]),
            "initial_equity": INITIAL_EQUITY,
            "paper_equity": INITIAL_EQUITY,
            "positions": {},
            "processed_decisions": 0,
            "order_events": 0,
            "market_data_available": True,
            "market_data_warning": None,
        }
        with self.connection:
            self.connection.execute(
                "INSERT INTO state(id, payload_json, updated_at) VALUES(1, ?, ?)",
                (_canonical_bytes(state).decode(), now),
            )
            self.connection.execute(
                "INSERT INTO events(created_at, event_type, payload_json) VALUES(?, ?, ?)",
                (
                    now,
                    "manual_paper_armed",
                    _canonical_bytes(
                        {
                            "authorization": MANUAL_AUTHORIZATION,
                            "boundary_hash": record["journal_record_hash"],
                            "boundary_bar": payload["bar_date"],
                            "prior_forward_return_credited": False,
                        }
                    ).decode(),
                ),
            )
        return state

    def process(
        self,
        state: dict,
        record: dict,
        journal_root: pathlib.Path,
        market_cache: dict[str, dict[str, typing.Any]],
    ) -> dict:
        payload = record["decision_payload"]
        upstream_equity = float(payload["base"]["portfolio_equity"])
        if not math.isfinite(upstream_equity) or upstream_equity <= 0:
            raise PaperMirrorError("upstream base equity is invalid")
        previous_upstream_equity = float(state["upstream_equity"])
        previous_paper_equity = float(state["paper_equity"])
        previous_bar = state["last_bar_date"]
        positions = _target_positions(payload)
        previous_positions = {
            str(key): float(value)
            for key, value in state.get("positions", {}).items()
        }

        upstream_multiplier = upstream_equity / previous_upstream_equity
        if not math.isfinite(upstream_multiplier) or not 0.5 < upstream_multiplier < 1.5:
            raise PaperMirrorError("upstream daily equity multiplier is invalid")

        market_data_available = True
        market_data_warning = None
        if state["phase"] == "active":
            try:
                price_return, funding_return, total_return = _mark_to_market_pnl(
                    previous_positions,
                    journal_root,
                    previous_bar,
                    payload["bar_date"],
                    market_cache,
                )
                paper_equity = previous_paper_equity * (1.0 + total_return)
            except PaperMarketDataError as error:
                market_data_available = False
                market_data_warning = str(error)
                price_return = 0.0
                funding_return = 0.0
                paper_equity = previous_paper_equity
        else:
            price_return = 0.0
            funding_return = 0.0
            paper_equity = previous_paper_equity

        deltas = {
            key: positions.get(key, 0.0) - previous_positions.get(key, 0.0)
            for key in sorted(set(positions) | set(previous_positions))
        }
        deltas = {
            key: value for key, value in deltas.items() if abs(value) > 1e-12
        }
        turnover = sum(abs(value) for value in deltas.values())
        estimated_cost = paper_equity * turnover * BASE_COST_PER_TURNOVER
        paper_equity -= estimated_cost
        paper_pnl = paper_equity - previous_paper_equity
        paper_daily_return = paper_equity / previous_paper_equity - 1.0
        now = _utc_now().isoformat()
        if not market_data_available:
            self.connection.execute(
                """
                INSERT INTO events(created_at, event_type, payload_json)
                VALUES(?, ?, ?)
                """,
                (
                    now,
                    "mark_to_market_skipped",
                    _canonical_bytes(
                        {
                            "upstream_journal_hash": record["journal_record_hash"],
                            "previous_bar": previous_bar,
                            "current_bar": payload["bar_date"],
                            "reason": market_data_warning,
                        }
                    ).decode(),
                ),
            )
        decision_payload = {
            "upstream_journal_hash": record["journal_record_hash"],
            "upstream_decision_payload_sha256": payload[
                "decision_payload_sha256"
            ],
            "bar_date": payload["bar_date"],
            "target_bar": payload["target_return_bearing_bar"],
            "paper_daily_return": paper_daily_return,
            "paper_pnl": paper_pnl,
            "paper_price_return": price_return,
            "paper_funding_return": funding_return,
            "upstream_multiplier_validated": upstream_multiplier,
            "turnover": turnover,
            "estimated_cost": estimated_cost,
            "mark_to_market_applied": market_data_available,
            "mark_to_market_warning": market_data_warning,
            "cost_is_already_in_upstream_return": False,
            "orders_authorized": False,
            "paper_orders_authorized": True,
            "credentials_used": False,
        }
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO decisions(
                    upstream_journal_hash, bar_date, target_bar, processed_at,
                    upstream_equity, paper_equity, paper_daily_return,
                    paper_pnl, turnover, estimated_cost, order_count,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["journal_record_hash"],
                    payload["bar_date"],
                    payload["target_return_bearing_bar"],
                    now,
                    upstream_equity,
                    paper_equity,
                    paper_daily_return,
                    paper_pnl,
                    turnover,
                    estimated_cost,
                    len(deltas),
                    _canonical_bytes(decision_payload).decode(),
                ),
            )
            decision_id = int(cursor.lastrowid)
            for key, delta in deltas.items():
                sleeve, symbol = key.split("|", 1)
                self.connection.execute(
                    """
                    INSERT INTO orders(
                        decision_id, created_at, sleeve, symbol, action,
                        delta_weight, target_weight, notional,
                        estimated_cost, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'filled')
                    """,
                    (
                        decision_id,
                        now,
                        sleeve,
                        symbol,
                        "BUY" if delta > 0 else "SELL",
                        delta,
                        positions.get(key, 0.0),
                        previous_paper_equity * delta,
                        abs(previous_paper_equity * delta) * BASE_COST_PER_TURNOVER,
                    ),
                )
            updated = {
                **state,
                "phase": "active",
                "last_journal_hash": record["journal_record_hash"],
                "last_bar_date": payload["bar_date"],
                "upstream_equity": upstream_equity,
                "paper_equity": paper_equity,
                "positions": positions,
                "processed_decisions": int(state["processed_decisions"]) + 1,
                "order_events": int(state["order_events"]) + len(deltas),
                "market_data_available": market_data_available,
                "market_data_warning": market_data_warning,
            }
            self.connection.execute(
                "UPDATE state SET payload_json = ?, updated_at = ? WHERE id = 1",
                (_canonical_bytes(updated).decode(), now),
            )
        return updated

    def counts(self) -> tuple[int, int]:
        return (
            int(self.connection.execute("SELECT count(*) FROM decisions").fetchone()[0]),
            int(self.connection.execute("SELECT count(*) FROM orders").fetchone()[0]),
        )


def _health(state: dict, store: PaperStore, latest_record: dict) -> dict:
    positions = state.get("positions", {})
    equity = float(state["paper_equity"])
    initial = float(state["initial_equity"])
    decision_count, order_count = store.counts()
    latest_payload = latest_record["decision_payload"]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "status": "healthy",
        "phase": state["phase"],
        "manual_authorization": MANUAL_AUTHORIZATION,
        "paper_only": True,
        "public_data_only": True,
        "network_required": False,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": True,
        "automatic_promotion": False,
        "real_income_authorized": False,
        "upstream_observer_remains_orderless": True,
        "prior_forward_return_credited": False,
        "market_data_available": state.get("market_data_available", True),
        "market_data_warning": state.get("market_data_warning"),
        "initial_equity": initial,
        "paper_equity": equity,
        "paper_return_pct": 100.0 * (equity / initial - 1.0),
        "paper_pnl": equity - initial,
        "gross_weight_pct": 100.0 * sum(abs(float(value)) for value in positions.values()),
        "net_weight_pct": 100.0 * sum(float(value) for value in positions.values()),
        "position_count": len(positions),
        "decision_count": decision_count,
        "order_event_count": order_count,
        "activation_boundary_bar": state["activation_boundary_bar"],
        "last_processed_bar": state["last_bar_date"],
        "latest_upstream_bar": latest_payload["bar_date"],
        "next_rebalance_requires_new_upstream_decision": True,
        "database_integrity": store.integrity,
        "positions": [
            {
                "sleeve": key.split("|", 1)[0],
                "symbol": key.split("|", 1)[1],
                "weight_pct": 100.0 * float(value),
                "notional": equity * float(value),
            }
            for key, value in sorted(positions.items())
        ],
        "last_success_at": _utc_now().isoformat(),
    }


def run_once(
    journal_path: pathlib.Path,
    protocol_path: pathlib.Path,
    implementation_lock_path: pathlib.Path,
    database_path: pathlib.Path,
    health_path: pathlib.Path,
) -> dict:
    records, _, _ = _load_upstream(
        journal_path, protocol_path, implementation_lock_path
    )
    store = PaperStore(database_path)
    try:
        state = store.load_state()
        if state is None:
            state = store.initialize(records[-1])
        journal_root = journal_path.parent
        market_cache: dict[str, dict[str, typing.Any]] = {}
        hashes = [record["journal_record_hash"] for record in records]
        try:
            index = hashes.index(state["last_journal_hash"])
        except ValueError as error:
            raise PaperMirrorError(
                "paper state boundary is absent from upstream journal"
            ) from error
        for record in records[index + 1 :]:
            state = store.process(
                state,
                record,
                journal_root,
                market_cache,
            )
        health = _health(state, store, records[-1])
        _atomic_json(health_path, health)
        return health
    finally:
        store.close()


def _error_health(path: pathlib.Path, error: Exception) -> None:
    _atomic_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "mode": MODE,
            "status": "error",
            "phase": "failed_closed",
            "error": f"{type(error).__name__}: {error}",
            "manual_authorization": MANUAL_AUTHORIZATION,
            "paper_only": True,
            "network_required": False,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": True,
            "automatic_promotion": False,
            "last_success_at": _utc_now().isoformat(),
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, type=pathlib.Path)
    parser.add_argument("--protocol", required=True, type=pathlib.Path)
    parser.add_argument("--implementation-lock", required=True, type=pathlib.Path)
    parser.add_argument("--database", required=True, type=pathlib.Path)
    parser.add_argument("--health", required=True, type=pathlib.Path)
    parser.add_argument("--runner-lock", required=True, type=pathlib.Path)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--run-once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not math.isfinite(arguments.poll_seconds) or arguments.poll_seconds <= 0:
        raise PaperMirrorError("poll seconds must be positive")
    arguments.runner_lock.parent.mkdir(parents=True, exist_ok=True)
    with arguments.runner_lock.open("a+", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                health = run_once(
                    arguments.journal,
                    arguments.protocol,
                    arguments.implementation_lock,
                    arguments.database,
                    arguments.health,
                )
                if arguments.run_once:
                    print(json.dumps(health, sort_keys=True))
                    return 0
            except Exception as error:
                _error_health(arguments.health, error)
                if arguments.run_once:
                    raise
            time.sleep(arguments.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
