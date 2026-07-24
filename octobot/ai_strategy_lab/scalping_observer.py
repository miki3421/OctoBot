"""Public, no-order KuCoin Futures microstructure stream for scalping research."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import time
import typing
import urllib.parse
import uuid


SCHEMA_VERSION = 1
PUBLIC_TOKEN_URL = (
    "https://api-futures.kucoin.com/api/v1/bullet-public"
)
DEFAULT_SYMBOL = "XBTUSDTM"
BOOK_TOPIC_TEMPLATE = "/contractMarket/level2Depth5:{symbol}"
TRADE_TOPIC_TEMPLATE = "/contractMarket/execution:{symbol}"
BOOK_PUSH_INTERVAL_MS = 100
AGGREGATION_INTERVAL_MS = 1_000
DEPTH_LEVELS = 5
INTEGRITY_CHECK_INTERVAL_SECONDS = 3_600


@dataclasses.dataclass(frozen=True)
class ScalpingObserverConfig:
    database_path: pathlib.Path
    health_path: pathlib.Path
    symbol: str = DEFAULT_SYMBOL
    health_interval_seconds: float = 5.0
    commit_interval_seconds: float = 1.0
    stale_book_seconds: float = 5.0
    startup_timeout_seconds: float = 30.0
    run_seconds: float | None = None

    def validate(self) -> None:
        if not self.symbol or not self.symbol.isascii():
            raise ValueError("a non-empty ASCII futures symbol is required")
        for name, value in (
            ("health interval", self.health_interval_seconds),
            ("commit interval", self.commit_interval_seconds),
            ("stale book threshold", self.stale_book_seconds),
            ("startup timeout", self.startup_timeout_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.run_seconds is not None and (
            not math.isfinite(self.run_seconds) or self.run_seconds <= 0
        ):
            raise ValueError("run seconds must be positive when provided")
        if self.database_path == self.health_path:
            raise ValueError("database and health paths must be different")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso_from_ns(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.datetime.fromtimestamp(
        value / 1_000_000_000, tz=datetime.timezone.utc
    ).isoformat()


def _timestamp_ns(value: object, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} timestamp is invalid") from error
    if number <= 0:
        raise ValueError(f"{label} timestamp must be positive")
    if number < 100_000_000_000:
        return number * 1_000_000_000
    if number < 100_000_000_000_000:
        return number * 1_000_000
    if number < 100_000_000_000_000_000:
        return number * 1_000
    return number


def _positive_float(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is invalid") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def parse_book_message(message: dict, received_ts_ns: int) -> dict:
    """Validate a classic Futures Level 5 message and derive point-in-time data."""

    if message.get("type") != "message" or message.get("subject") != "level2":
        raise ValueError("not a Level 5 book message")
    data = message.get("data")
    if not isinstance(data, dict):
        raise ValueError("book data is missing")
    bids = _parse_levels(data.get("bids"), "bid")
    asks = _parse_levels(data.get("asks"), "ask")
    if bids[0][0] >= asks[0][0]:
        raise ValueError("crossed or locked order book")
    if any(bids[index][0] <= bids[index + 1][0] for index in range(4)):
        raise ValueError("bid levels are not strictly descending")
    if any(asks[index][0] >= asks[index + 1][0] for index in range(4)):
        raise ValueError("ask levels are not strictly ascending")
    sequence = int(data.get("sequence", message.get("sn")))
    if sequence <= 0:
        raise ValueError("book sequence must be positive")
    exchange_ts_ns = _timestamp_ns(
        data.get("ts", data.get("timestamp")), "book"
    )
    best_bid, best_bid_size = bids[0]
    best_ask, best_ask_size = asks[0]
    mid_price = (best_bid + best_ask) / 2
    total_bid_size = sum(size for _, size in bids)
    total_ask_size = sum(size for _, size in asks)
    depth_total = total_bid_size + total_ask_size
    imbalance = (
        (total_bid_size - total_ask_size) / depth_total
        if depth_total
        else 0.0
    )
    microprice = (
        best_ask * best_bid_size + best_bid * best_ask_size
    ) / (best_bid_size + best_ask_size)
    return {
        "sequence": sequence,
        "exchange_ts_ns": exchange_ts_ns,
        "received_ts_ns": received_ts_ns,
        "latency_ms": (received_ts_ns - exchange_ts_ns) / 1_000_000,
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid_price,
        "microprice": microprice,
        "spread_bps": (best_ask / best_bid - 1) * 10_000,
        "imbalance_5": imbalance,
        "payload_sha256": _canonical_hash(data),
    }


def _parse_levels(value: object, side: str) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) != DEPTH_LEVELS:
        raise ValueError(f"{side} book must contain exactly five levels")
    levels = []
    for index, raw_level in enumerate(value, start=1):
        if not isinstance(raw_level, (list, tuple)) or len(raw_level) < 2:
            raise ValueError(f"{side} level {index} is invalid")
        levels.append(
            (
                _positive_float(raw_level[0], f"{side} price {index}"),
                _positive_float(raw_level[1], f"{side} size {index}"),
            )
        )
    return levels


def parse_trade_message(message: dict, received_ts_ns: int) -> dict:
    """Validate a public futures execution message."""

    if message.get("type") != "message" or message.get("subject") != "match":
        raise ValueError("not a public trade message")
    data = message.get("data")
    if not isinstance(data, dict):
        raise ValueError("trade data is missing")
    side = str(data.get("side", "")).lower()
    if side not in {"buy", "sell"}:
        raise ValueError("trade side must be buy or sell")
    trade_id = str(data.get("tradeId", ""))
    if not trade_id:
        raise ValueError("trade id is missing")
    sequence = int(data.get("sequence", message.get("sn")))
    if sequence <= 0:
        raise ValueError("trade sequence must be positive")
    exchange_ts_ns = _timestamp_ns(
        data.get("ts", data.get("timestamp")), "trade"
    )
    return {
        "trade_id": trade_id,
        "sequence": sequence,
        "exchange_ts_ns": exchange_ts_ns,
        "received_ts_ns": received_ts_ns,
        "latency_ms": (received_ts_ns - exchange_ts_ns) / 1_000_000,
        "side": side,
        "price": _positive_float(data.get("price"), "trade price"),
        "size": _positive_float(data.get("size"), "trade size"),
        "payload_sha256": _canonical_hash(data),
    }


class ScalpingStore:
    """Batched append-only SQLite storage plus one-second materialization."""

    def __init__(self, config: ScalpingObserverConfig, session_id: str):
        config.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.session_id = session_id
        self.connection = sqlite3.connect(
            config.database_path, timeout=10
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self._create_schema()
        counts = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM book_events) AS book_events,
                (SELECT COUNT(*) FROM trade_events) AS trade_events,
                (SELECT COUNT(*) FROM second_buckets) AS second_buckets,
                (SELECT MIN(received_ts_ns) FROM book_events) AS first_book_ns,
                (SELECT MAX(received_ts_ns) FROM book_events) AS last_book_ns,
                (SELECT MAX(bucket_ts_s) FROM second_buckets) AS last_bucket_s
            """
        ).fetchone()
        self.book_events_count = int(counts["book_events"])
        self.trade_events_count = int(counts["trade_events"])
        self.second_buckets_count = int(counts["second_buckets"])
        self.first_book_ts_ns = counts["first_book_ns"]
        self.latest_book_ts_ns = counts["last_book_ns"]
        self.latest_bucket_ts_s = counts["last_bucket_s"]
        self.integrity_status = str(
            self.connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        self.last_integrity_check_monotonic = time.monotonic()
        self.started_at = _utc_now().isoformat()
        self.connection.execute(
            """
            UPDATE scalping_sessions
            SET ended_at = ?, status = 'interrupted',
                stop_reason = 'observer restarted before graceful close'
            WHERE status = 'running'
            """,
            (self.started_at,),
        )
        self.connection.execute(
            """
            INSERT INTO scalping_sessions(
                session_id, schema_version, symbol, started_at, status
            ) VALUES (?, ?, ?, ?, 'running')
            """,
            (
                self.session_id,
                SCHEMA_VERSION,
                config.symbol,
                self.started_at,
            ),
        )
        self.connection.commit()
        self.pending_events = 0
        self.last_commit_monotonic = time.monotonic()
        self.last_book_ts_ns: int | None = None
        self.last_trade_ts_ns: int | None = None
        self.last_book_latency_ms: float | None = None
        self.last_trade_latency_ms: float | None = None
        self.maximum_book_silence_seconds = 0.0

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scalping_sessions (
                session_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                stop_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS book_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                exchange_ts_ns INTEGER NOT NULL,
                received_ts_ns INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                bid_price_1 REAL NOT NULL, bid_size_1 REAL NOT NULL,
                bid_price_2 REAL NOT NULL, bid_size_2 REAL NOT NULL,
                bid_price_3 REAL NOT NULL, bid_size_3 REAL NOT NULL,
                bid_price_4 REAL NOT NULL, bid_size_4 REAL NOT NULL,
                bid_price_5 REAL NOT NULL, bid_size_5 REAL NOT NULL,
                ask_price_1 REAL NOT NULL, ask_size_1 REAL NOT NULL,
                ask_price_2 REAL NOT NULL, ask_size_2 REAL NOT NULL,
                ask_price_3 REAL NOT NULL, ask_size_3 REAL NOT NULL,
                ask_price_4 REAL NOT NULL, ask_size_4 REAL NOT NULL,
                ask_price_5 REAL NOT NULL, ask_size_5 REAL NOT NULL,
                mid_price REAL NOT NULL,
                microprice REAL NOT NULL,
                spread_bps REAL NOT NULL,
                imbalance_5 REAL NOT NULL,
                payload_sha256 TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES scalping_sessions(session_id),
                UNIQUE(sequence, exchange_ts_ns)
            );

            CREATE TABLE IF NOT EXISTS trade_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                trade_id TEXT NOT NULL UNIQUE,
                sequence INTEGER NOT NULL,
                exchange_ts_ns INTEGER NOT NULL,
                received_ts_ns INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                price REAL NOT NULL,
                size REAL NOT NULL,
                payload_sha256 TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES scalping_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS second_buckets (
                bucket_ts_s INTEGER PRIMARY KEY,
                book_event_count INTEGER NOT NULL DEFAULT 0,
                trade_event_count INTEGER NOT NULL DEFAULT 0,
                first_mid REAL,
                high_mid REAL,
                low_mid REAL,
                last_mid REAL,
                spread_bps_sum REAL NOT NULL DEFAULT 0,
                imbalance_5_sum REAL NOT NULL DEFAULT 0,
                buy_trade_size REAL NOT NULL DEFAULT 0,
                sell_trade_size REAL NOT NULL DEFAULT 0,
                buy_trade_count INTEGER NOT NULL DEFAULT 0,
                sell_trade_count INTEGER NOT NULL DEFAULT 0,
                last_bid REAL,
                last_ask REAL,
                maximum_latency_ms REAL
            );

            CREATE INDEX IF NOT EXISTS idx_book_received
                ON book_events(received_ts_ns);
            CREATE INDEX IF NOT EXISTS idx_trade_received
                ON trade_events(received_ts_ns);
            """
        )
        self.connection.commit()

    def record_book(self, event: dict) -> bool:
        values: list[object] = [
            self.session_id,
            event["sequence"],
            event["exchange_ts_ns"],
            event["received_ts_ns"],
            event["latency_ms"],
        ]
        for price, size in event["bids"]:
            values.extend((price, size))
        for price, size in event["asks"]:
            values.extend((price, size))
        values.extend(
            (
                event["mid_price"],
                event["microprice"],
                event["spread_bps"],
                event["imbalance_5"],
                event["payload_sha256"],
            )
        )
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO book_events(
                session_id, sequence, exchange_ts_ns, received_ts_ns,
                latency_ms,
                bid_price_1, bid_size_1, bid_price_2, bid_size_2,
                bid_price_3, bid_size_3, bid_price_4, bid_size_4,
                bid_price_5, bid_size_5,
                ask_price_1, ask_size_1, ask_price_2, ask_size_2,
                ask_price_3, ask_size_3, ask_price_4, ask_size_4,
                ask_price_5, ask_size_5,
                mid_price, microprice, spread_bps, imbalance_5,
                payload_sha256
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            values,
        )
        if cursor.rowcount != 1:
            return False
        bucket = event["received_ts_ns"] // 1_000_000_000
        if (
            self.latest_bucket_ts_s is None
            or bucket > self.latest_bucket_ts_s
        ):
            self.second_buckets_count += 1
            self.latest_bucket_ts_s = bucket
        self.connection.execute(
            """
            INSERT INTO second_buckets(
                bucket_ts_s, book_event_count, first_mid, high_mid,
                low_mid, last_mid, spread_bps_sum, imbalance_5_sum,
                last_bid, last_ask, maximum_latency_ms
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bucket_ts_s) DO UPDATE SET
                book_event_count = book_event_count + 1,
                first_mid = COALESCE(first_mid, excluded.first_mid),
                high_mid = CASE
                    WHEN high_mid IS NULL THEN excluded.high_mid
                    ELSE MAX(high_mid, excluded.high_mid)
                END,
                low_mid = CASE
                    WHEN low_mid IS NULL THEN excluded.low_mid
                    ELSE MIN(low_mid, excluded.low_mid)
                END,
                last_mid = excluded.last_mid,
                spread_bps_sum = spread_bps_sum + excluded.spread_bps_sum,
                imbalance_5_sum = imbalance_5_sum + excluded.imbalance_5_sum,
                last_bid = excluded.last_bid,
                last_ask = excluded.last_ask,
                maximum_latency_ms = MAX(
                    maximum_latency_ms, excluded.maximum_latency_ms
                )
            """,
            (
                bucket,
                event["mid_price"],
                event["mid_price"],
                event["mid_price"],
                event["mid_price"],
                event["spread_bps"],
                event["imbalance_5"],
                event["best_bid"],
                event["best_ask"],
                event["latency_ms"],
            ),
        )
        if self.last_book_ts_ns is not None:
            silence = (
                event["received_ts_ns"] - self.last_book_ts_ns
            ) / 1_000_000_000
            self.maximum_book_silence_seconds = max(
                self.maximum_book_silence_seconds, silence
            )
        self.last_book_ts_ns = event["received_ts_ns"]
        if self.first_book_ts_ns is None:
            self.first_book_ts_ns = event["received_ts_ns"]
        self.latest_book_ts_ns = event["received_ts_ns"]
        self.last_book_latency_ms = event["latency_ms"]
        self.book_events_count += 1
        self.pending_events += 1
        return True

    def record_trade(self, event: dict) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO trade_events(
                session_id, trade_id, sequence, exchange_ts_ns,
                received_ts_ns, latency_ms, side, price, size,
                payload_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id,
                event["trade_id"],
                event["sequence"],
                event["exchange_ts_ns"],
                event["received_ts_ns"],
                event["latency_ms"],
                event["side"],
                event["price"],
                event["size"],
                event["payload_sha256"],
            ),
        )
        if cursor.rowcount != 1:
            return False
        bucket = event["received_ts_ns"] // 1_000_000_000
        if (
            self.latest_bucket_ts_s is None
            or bucket > self.latest_bucket_ts_s
        ):
            self.second_buckets_count += 1
            self.latest_bucket_ts_s = bucket
        is_buy = event["side"] == "buy"
        self.connection.execute(
            """
            INSERT INTO second_buckets(
                bucket_ts_s, trade_event_count, buy_trade_size,
                sell_trade_size, buy_trade_count, sell_trade_count,
                maximum_latency_ms
            ) VALUES (?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(bucket_ts_s) DO UPDATE SET
                trade_event_count = trade_event_count + 1,
                buy_trade_size = buy_trade_size + excluded.buy_trade_size,
                sell_trade_size = sell_trade_size + excluded.sell_trade_size,
                buy_trade_count = buy_trade_count + excluded.buy_trade_count,
                sell_trade_count = sell_trade_count + excluded.sell_trade_count,
                maximum_latency_ms = MAX(
                    maximum_latency_ms, excluded.maximum_latency_ms
                )
            """,
            (
                bucket,
                event["size"] if is_buy else 0.0,
                0.0 if is_buy else event["size"],
                1 if is_buy else 0,
                0 if is_buy else 1,
                event["latency_ms"],
            ),
        )
        self.last_trade_ts_ns = event["received_ts_ns"]
        self.last_trade_latency_ms = event["latency_ms"]
        self.trade_events_count += 1
        self.pending_events += 1
        return True

    def commit_if_due(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or (
            self.pending_events
            and now - self.last_commit_monotonic
            >= self.config.commit_interval_seconds
        ):
            self.connection.commit()
            self.pending_events = 0
            self.last_commit_monotonic = now

    def health_counts(self) -> dict:
        self.commit_if_due(force=True)
        return {
            "book_events": self.book_events_count,
            "trade_events": self.trade_events_count,
            "second_buckets": self.second_buckets_count,
            "first_book_ns": self.first_book_ts_ns,
            "last_book_ns": self.latest_book_ts_ns,
        }

    def quick_check(self, *, force: bool = False) -> str:
        self.commit_if_due(force=True)
        now = time.monotonic()
        if (
            force
            or now - self.last_integrity_check_monotonic
            >= INTEGRITY_CHECK_INTERVAL_SECONDS
        ):
            self.integrity_status = str(
                self.connection.execute(
                    "PRAGMA quick_check"
                ).fetchone()[0]
            )
            self.last_integrity_check_monotonic = now
        return self.integrity_status

    def close(self, status: str, reason: str | None = None) -> None:
        self.commit_if_due(force=True)
        self.connection.execute(
            """
            UPDATE scalping_sessions
            SET ended_at = ?, status = ?, stop_reason = ?
            WHERE session_id = ?
            """,
            (_utc_now().isoformat(), status, reason, self.session_id),
        )
        self.connection.commit()
        self.connection.close()


def _read_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as input_file:
            value = json.load(input_file)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json_atomic(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_health(
    config: ScalpingObserverConfig,
    store: ScalpingStore,
    *,
    status: str,
    connected: bool,
    subscriptions_acknowledged: int,
    error: BaseException | None = None,
) -> dict:
    counts = store.health_counts()
    integrity = store.quick_check()
    now = _utc_now()
    last_book_age = (
        (
            time.time_ns() - store.last_book_ts_ns
        ) / 1_000_000_000
        if store.last_book_ts_ns is not None
        else None
    )
    healthy = (
        status == "healthy"
        and connected
        and counts["book_events"] > 0
        and integrity == "ok"
        and last_book_age is not None
        and last_book_age <= config.stale_book_seconds
    )
    database_bytes = sum(
        path.stat().st_size
        for path in (
            config.database_path,
            config.database_path.with_name(
                config.database_path.name + "-wal"
            ),
            config.database_path.with_name(
                config.database_path.name + "-shm"
            ),
        )
        if path.is_file()
    )
    value = {
        "schema_version": SCHEMA_VERSION,
        "mode": "scalping_research_only",
        "status": "healthy" if healthy else status,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "automatic_promotion": False,
        "symbol": config.symbol,
        "depth_levels": DEPTH_LEVELS,
        "book_push_interval_ms": BOOK_PUSH_INTERVAL_MS,
        "aggregation_interval_ms": AGGREGATION_INTERVAL_MS,
        "database_path": str(config.database_path),
        "database_bytes": database_bytes,
        "database_integrity": integrity,
        "session_id": store.session_id,
        "session_started_at": store.started_at,
        "connected": connected,
        "subscriptions_acknowledged": subscriptions_acknowledged,
        "book_events": counts["book_events"],
        "trade_events": counts["trade_events"],
        "second_buckets": counts["second_buckets"],
        "first_book_at": _iso_from_ns(counts["first_book_ns"]),
        "last_book_at": _iso_from_ns(counts["last_book_ns"]),
        "last_trade_at": _iso_from_ns(store.last_trade_ts_ns),
        "last_book_age_seconds": last_book_age,
        "last_book_latency_ms": store.last_book_latency_ms,
        "last_trade_latency_ms": store.last_trade_latency_ms,
        "maximum_session_book_silence_seconds": (
            store.maximum_book_silence_seconds
        ),
        "updated_at": now.isoformat(),
    }
    if healthy:
        value["last_success_at"] = now.isoformat()
    else:
        previous = _read_json(config.health_path)
        value["last_success_at"] = previous.get("last_success_at")
    if error is not None:
        value["error_type"] = type(error).__name__
        value["error"] = str(error)
    return value


async def _public_connection_details(
    session: typing.Any,
) -> tuple[str, str, float]:
    async with session.post(PUBLIC_TOKEN_URL) as response:
        response.raise_for_status()
        payload = await response.json()
    if payload.get("code") != "200000":
        raise RuntimeError("KuCoin public WebSocket token request failed")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("KuCoin public token data is missing")
    token = str(data.get("token", ""))
    servers = data.get("instanceServers")
    if not token or not isinstance(servers, list) or not servers:
        raise RuntimeError("KuCoin public connection details are incomplete")
    server = servers[0]
    if not isinstance(server, dict):
        raise RuntimeError("KuCoin public server entry is invalid")
    endpoint = str(server.get("endpoint", ""))
    if not endpoint.startswith("wss://"):
        raise RuntimeError("KuCoin public WebSocket endpoint is not secure")
    ping_interval_ms = _positive_float(
        server.get("pingInterval"), "ping interval"
    )
    return endpoint, token, ping_interval_ms / 1_000


def _connection_url(endpoint: str, token: str, connection_id: str) -> str:
    separator = "&" if "?" in endpoint else "?"
    return endpoint + separator + urllib.parse.urlencode(
        {"token": token, "connectId": connection_id}
    )


async def run_observer(config: ScalpingObserverConfig) -> dict:
    """Run until stopped or ``run_seconds`` elapses; never imports trading APIs."""

    import aiohttp

    config.validate()
    session_id = uuid.uuid4().hex
    store = ScalpingStore(config, session_id)
    started_monotonic = time.monotonic()
    last_health_monotonic = 0.0
    last_ping_monotonic = 0.0
    subscriptions_acknowledged = 0
    connected = False
    final_status = "stopped"
    final_reason = None
    try:
        _write_json_atomic(
            config.health_path,
            build_health(
                config,
                store,
                status="starting",
                connected=False,
                subscriptions_acknowledged=0,
            ),
        )
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            endpoint, token, ping_interval = (
                await _public_connection_details(session)
            )
            url = _connection_url(endpoint, token, session_id)
            async with session.ws_connect(
                url,
                autoping=True,
                heartbeat=None,
                max_msg_size=2 * 1024 * 1024,
            ) as websocket:
                connected = True
                for topic in (
                    BOOK_TOPIC_TEMPLATE.format(symbol=config.symbol),
                    TRADE_TOPIC_TEMPLATE.format(symbol=config.symbol),
                ):
                    await websocket.send_json(
                        {
                            "id": uuid.uuid4().hex,
                            "type": "subscribe",
                            "topic": topic,
                            "response": True,
                        }
                    )
                last_ping_monotonic = time.monotonic()
                while True:
                    now_monotonic = time.monotonic()
                    if (
                        config.run_seconds is not None
                        and now_monotonic - started_monotonic
                        >= config.run_seconds
                    ):
                        final_status = "completed"
                        break
                    try:
                        ws_message = await websocket.receive(timeout=0.5)
                    except asyncio.TimeoutError:
                        ws_message = None
                    received_ts_ns = time.time_ns()
                    if ws_message is not None:
                        if ws_message.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(ws_message.data)
                            if payload.get("type") == "ack":
                                subscriptions_acknowledged += 1
                            elif payload.get("type") == "message":
                                topic = str(payload.get("topic", ""))
                                if topic.startswith(
                                    "/contractMarket/level2Depth5:"
                                ):
                                    store.record_book(
                                        parse_book_message(
                                            payload, received_ts_ns
                                        )
                                    )
                                elif topic.startswith(
                                    "/contractMarket/execution:"
                                ):
                                    store.record_trade(
                                        parse_trade_message(
                                            payload, received_ts_ns
                                        )
                                    )
                        elif ws_message.type in {
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        }:
                            raise ConnectionError(
                                "KuCoin public WebSocket disconnected"
                            )
                    now_monotonic = time.monotonic()
                    if now_monotonic - last_ping_monotonic >= ping_interval:
                        await websocket.send_json(
                            {
                                "id": uuid.uuid4().hex,
                                "type": "ping",
                            }
                        )
                        last_ping_monotonic = now_monotonic
                    store.commit_if_due()
                    book_age = (
                        (time.time_ns() - store.last_book_ts_ns)
                        / 1_000_000_000
                        if store.last_book_ts_ns is not None
                        else None
                    )
                    elapsed = now_monotonic - started_monotonic
                    if (
                        store.last_book_ts_ns is None
                        and elapsed > config.startup_timeout_seconds
                    ):
                        raise TimeoutError(
                            "no Level 5 book event received before startup timeout"
                        )
                    if (
                        book_age is not None
                        and book_age > config.stale_book_seconds
                    ):
                        raise TimeoutError(
                            f"Level 5 book stale for {book_age:.3f} seconds"
                        )
                    if (
                        now_monotonic - last_health_monotonic
                        >= config.health_interval_seconds
                    ):
                        _write_json_atomic(
                            config.health_path,
                            build_health(
                                config,
                                store,
                                status=(
                                    "healthy"
                                    if store.last_book_ts_ns is not None
                                    else "starting"
                                ),
                                connected=True,
                                subscriptions_acknowledged=(
                                    subscriptions_acknowledged
                                ),
                            ),
                        )
                        last_health_monotonic = now_monotonic
        final_health = build_health(
            config,
            store,
            status=(
                "healthy"
                if store.last_book_ts_ns is not None
                else "completed"
            ),
            connected=connected,
            subscriptions_acknowledged=subscriptions_acknowledged,
        )
        _write_json_atomic(config.health_path, final_health)
        return final_health
    except BaseException as error:
        final_status = "failed"
        final_reason = str(error)
        _write_json_atomic(
            config.health_path,
            build_health(
                config,
                store,
                status="failed",
                connected=connected,
                subscriptions_acknowledged=subscriptions_acknowledged,
                error=error,
            ),
        )
        raise
    finally:
        store.close(final_status, final_reason)


def run(config: ScalpingObserverConfig) -> dict:
    return asyncio.run(run_observer(config))
