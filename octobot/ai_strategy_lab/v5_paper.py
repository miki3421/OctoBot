"""Persistent forward paper runner for the frozen V5 BTC path model.

The runner reads public KuCoin Futures 15-minute candles, evaluates only closed
candles, and simulates the exact V5 activation/protected-stop/horizon lifecycle.
It never authenticates to an exchange and cannot create exchange orders.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime
import hashlib
import json
import math
import os
import pathlib
import sqlite3
import tempfile
import time
import typing
import urllib.parse
import urllib.error
import urllib.request
import uuid

import numpy

from octobot.ai_strategy_lab import funding
from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import perfect_map_student as v1
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


SCHEMA_VERSION = 1
MODE = "v5_forward_paper"
SYMBOL = "BTC/USDT:USDT"
EXCHANGE = "binance"
REMOTE_SYMBOL = "BTCUSDT"
KLINE_URL = "https://fapi.binance.com/fapi/v1/klines"
CANDLE_SECONDS = 900
HISTORY_CANDLES = 200
BINANCE_MAX_CANDLES = 1500
MAX_RECOVERY_CANDLES = 30 * 24 * 4 + HISTORY_CANDLES
INITIAL_EQUITY = 10_000.0
MAX_NOTIONAL_FRACTION = 0.10


@dataclasses.dataclass(frozen=True)
class PaperConfig:
    model_directory: pathlib.Path
    protocol_path: pathlib.Path
    database_path: pathlib.Path
    health_path: pathlib.Path
    poll_seconds: float = 30.0
    timeout_seconds: float = 30.0
    run_seconds: float | None = None
    broker_url: str | None = None
    broker_token_path: pathlib.Path | None = None

    def validate(self) -> None:
        if self.database_path == self.health_path:
            raise ValueError("V5 paper database and health paths must differ")
        if not self.model_directory.is_dir():
            raise ValueError("V5 model directory does not exist")
        if not self.protocol_path.is_file():
            raise ValueError("V5 protocol does not exist")
        for name, value in (
            ("poll seconds", self.poll_seconds),
            ("timeout seconds", self.timeout_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.run_seconds is not None and (
            not math.isfinite(self.run_seconds) or self.run_seconds <= 0
        ):
            raise ValueError("run seconds must be positive")
        if bool(self.broker_url) != bool(self.broker_token_path):
            raise ValueError(
                "broker URL and token path must be configured together"
            )
        if self.broker_token_path is not None:
            if not self.broker_token_path.is_file():
                raise ValueError("broker token file does not exist")
            if len(
                self.broker_token_path.read_text(
                    encoding="utf-8"
                ).strip()
            ) < 32:
                raise ValueError("broker token is invalid")


class PaperStore:
    def __init__(self, path: pathlib.Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, timeout=15)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=15000")
        self._create_schema()
        self.integrity = str(
            self.connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        if self.integrity != "ok":
            raise RuntimeError(f"V5 paper database integrity={self.integrity}")

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                stop_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                close_timestamp INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                reason TEXT NOT NULL,
                expected_net_pct REAL,
                opposite_expected_net_pct REAL,
                target_probability_pct REAL,
                stop_probability_pct REAL,
                timeout_probability_pct REAL,
                target_profit_pct REAL,
                activation_pct REAL,
                horizon_hours INTEGER,
                close_price REAL NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opened_at INTEGER NOT NULL,
                closed_at INTEGER NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                target_profit_pct REAL NOT NULL,
                activation_pct REAL NOT NULL,
                horizon_hours INTEGER NOT NULL,
                notional REAL NOT NULL,
                gross_return_pct REAL NOT NULL,
                fee_pct REAL NOT NULL,
                funding_cost_pct REAL,
                net_return_pct REAL NOT NULL,
                pnl REAL NOT NULL,
                maximum_favorable_excursion_pct REAL NOT NULL,
                maximum_adverse_excursion_pct REAL NOT NULL,
                prediction_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                close_timestamp INTEGER,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def start_session(self) -> str:
        now = _utc_now_iso()
        self.connection.execute(
            """
            UPDATE sessions
            SET ended_at = ?, status = 'interrupted',
                stop_reason = 'runner restarted before graceful close'
            WHERE status = 'running'
            """,
            (now,),
        )
        session_id = str(uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO sessions(session_id, started_at, status)
            VALUES (?, ?, 'running')
            """,
            (session_id, now),
        )
        self.connection.commit()
        return session_id

    def finish_session(self, session_id: str, reason: str) -> None:
        self.connection.execute(
            """
            UPDATE sessions
            SET ended_at = ?, status = 'stopped', stop_reason = ?
            WHERE session_id = ?
            """,
            (_utc_now_iso(), reason, session_id),
        )
        self.connection.commit()

    def load_state(self) -> dict:
        row = self.connection.execute(
            "SELECT payload_json FROM state WHERE id = 1"
        ).fetchone()
        if row is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "last_close_timestamp": None,
                "equity": INITIAL_EQUITY,
                "open_trade": None,
            }
        payload = json.loads(row["payload_json"])
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported V5 paper state schema")
        return payload

    def commit_candle(
        self,
        state: dict,
        decision: dict,
        events: list[dict],
        closed_trade: dict | None,
    ) -> None:
        now = _utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO decisions(
                    close_timestamp, created_at, action, accepted, reason,
                    expected_net_pct, opposite_expected_net_pct,
                    target_probability_pct, stop_probability_pct,
                    timeout_probability_pct, target_profit_pct,
                    activation_pct, horizon_hours, close_price, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision["close_timestamp"],
                    now,
                    decision["action"],
                    int(decision["accepted"]),
                    decision["reason"],
                    decision.get("expected_net_pct"),
                    decision.get("opposite_expected_net_pct"),
                    decision.get("target_probability_pct"),
                    decision.get("stop_probability_pct"),
                    decision.get("timeout_probability_pct"),
                    decision.get("target_profit_pct"),
                    decision.get("activation_pct"),
                    decision.get("horizon_hours"),
                    decision["close_price"],
                    _canonical_json(decision),
                ),
            )
            for event in events:
                self.connection.execute(
                    """
                    INSERT INTO events(
                        created_at, close_timestamp, event_type, payload_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        now,
                        event.get("close_timestamp"),
                        event["event_type"],
                        _canonical_json(event),
                    ),
                )
            if closed_trade is not None:
                self.connection.execute(
                    """
                    INSERT INTO trades(
                        opened_at, closed_at, direction, entry_price,
                        exit_price, exit_reason, target_profit_pct,
                        activation_pct, horizon_hours, notional,
                        gross_return_pct, fee_pct, funding_cost_pct,
                        net_return_pct, pnl,
                        maximum_favorable_excursion_pct,
                        maximum_adverse_excursion_pct, prediction_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?)
                    """,
                    (
                        closed_trade["opened_at"],
                        closed_trade["closed_at"],
                        closed_trade["direction"],
                        closed_trade["entry_price"],
                        closed_trade["exit_price"],
                        closed_trade["exit_reason"],
                        closed_trade["target_profit_pct"],
                        closed_trade["activation_pct"],
                        closed_trade["horizon_hours"],
                        closed_trade["notional"],
                        closed_trade["gross_return_pct"],
                        closed_trade["fee_pct"],
                        closed_trade.get("funding_cost_pct"),
                        closed_trade["net_return_pct"],
                        closed_trade["pnl"],
                        closed_trade[
                            "maximum_favorable_excursion_pct"
                        ],
                        closed_trade[
                            "maximum_adverse_excursion_pct"
                        ],
                        _canonical_json(closed_trade["prediction"]),
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO state(id, payload_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (_canonical_json(state), now),
            )

    def seed(self, state: dict, close_timestamp: int) -> None:
        state["last_close_timestamp"] = close_timestamp
        event = {
            "event_type": "forward_seed",
            "close_timestamp": close_timestamp,
            "reason": "first startup waits for the next unseen candle",
        }
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO events(
                    created_at, close_timestamp, event_type, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    _utc_now_iso(),
                    close_timestamp,
                    event["event_type"],
                    _canonical_json(event),
                ),
            )
            self.connection.execute(
                """
                INSERT INTO state(id, payload_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    _canonical_json(state),
                    _utc_now_iso(),
                ),
            )

    def metrics(self) -> dict:
        values = self.connection.execute(
            """
            SELECT
                COUNT(*) AS trades,
                COALESCE(SUM(CASE WHEN net_return_pct > 0 THEN 1 ELSE 0 END), 0)
                    AS wins,
                COALESCE(SUM(CASE WHEN funding_cost_pct IS NULL THEN 1 ELSE 0 END), 0)
                    AS funding_missing_trades,
                COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0)
                    AS gross_profit,
                COALESCE(-SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END), 0)
                    AS gross_loss,
                COALESCE(SUM(pnl), 0) AS total_pnl
            FROM trades
            """
        ).fetchone()
        trades = int(values["trades"])
        wins = int(values["wins"])
        gross_profit = float(values["gross_profit"])
        gross_loss = float(values["gross_loss"])
        return {
            "trades": trades,
            "wins": wins,
            "funding_missing_trades": int(
                values["funding_missing_trades"]
            ),
            "win_rate_pct": wins * 100 / trades if trades else None,
            "profit_factor": (
                gross_profit / gross_loss if gross_loss else None
            ),
            "total_pnl": float(values["total_pnl"]),
        }

    def latest_decision(self) -> dict | None:
        row = self.connection.execute(
            "SELECT payload_json FROM decisions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def close(self) -> None:
        self.connection.close()


class V5PaperRunner:
    def __init__(self, config: PaperConfig):
        config.validate()
        self.config = config
        self.model = v5.V5Model.load(config.model_directory)
        self.protocol = json.loads(
            config.protocol_path.read_text(encoding="utf-8")
        )
        if self.protocol.get("protocol_sha256") != v5._json_hash(
            v5.frozen_protocol()
        ):
            raise ValueError("V5 paper protocol differs from frozen code")
        self.store = PaperStore(config.database_path)
        self.state = self.store.load_state()
        self.session_id = self.store.start_session()
        self.model_sha256 = _sha256(
            config.model_directory / "primary.npz"
        )
        self.started_at = _utc_now_iso()
        self.last_success_at: str | None = None
        self.last_error: str | None = None
        self.last_candles: numpy.ndarray | None = None
        self.last_broker_status: dict | None = None

    def run(self) -> None:
        started = time.monotonic()
        reason = "run_seconds_elapsed"
        try:
            while True:
                try:
                    self.run_once()
                    self.last_success_at = _utc_now_iso()
                    self.last_error = None
                except Exception as error:
                    self.last_error = f"{type(error).__name__}: {error}"
                self.write_health()
                if (
                    self.config.run_seconds is not None
                    and time.monotonic() - started
                    >= self.config.run_seconds
                ):
                    break
                time.sleep(self.config.poll_seconds)
        except KeyboardInterrupt:
            reason = "keyboard_interrupt"
        finally:
            self.store.finish_session(self.session_id, reason)
            self.write_health(status="stopped")
            self.store.close()

    def run_once(
        self, *, now_timestamp: int | None = None
    ) -> list[dict]:
        if self.config.broker_url:
            self.last_broker_status = _broker_status(
                self.config.broker_url,
                timeout_seconds=self.config.timeout_seconds,
            )
            if (
                not self.last_broker_status.get("ready")
                or self.last_broker_status.get("exchange") != EXCHANGE
                or not self.last_broker_status.get("simulated_trader")
                or self.last_broker_status.get("real_trader")
            ):
                raise RuntimeError(
                    "isolated Binance V5 paper broker is not ready"
                )
        previous = self.state.get("last_close_timestamp")
        candles = fetch_closed_candles(
            timeout_seconds=self.config.timeout_seconds,
            now_timestamp=now_timestamp,
            start_timestamp=(
                int(previous) - HISTORY_CANDLES * CANDLE_SECONDS
                if previous is not None
                else None
            ),
        )
        self.last_candles = candles
        close_timestamps = candles[:, 0].astype(numpy.int64) + CANDLE_SECONDS
        latest_close = int(close_timestamps[-1])
        if previous is None:
            self.store.seed(self.state, latest_close)
            return []
        previous = int(previous)
        if previous < int(close_timestamps[0]):
            raise RuntimeError(
                "V5 paper downtime exceeds available candle recovery window"
            )
        rows = numpy.flatnonzero(close_timestamps > previous)
        if not len(rows):
            return []
        if int(close_timestamps[rows[0]]) != previous + CANDLE_SECONDS:
            raise RuntimeError("V5 paper encountered a closed-candle gap")
        feature_values, feature_names = v1.sequence_features(candles)
        if feature_names != self.model.primary_model.feature_names:
            raise ValueError("V5 paper feature schema differs from model")
        decisions = []
        for row in rows:
            if not numpy.all(numpy.isfinite(feature_values[row])):
                raise ValueError("V5 paper latest features are not finite")
            previous_state = copy.deepcopy(self.state)
            try:
                decision, events, closed_trade = self._process_candle(
                    candles[row], feature_values[row]
                )
            except Exception:
                self.state = previous_state
                raise
            self.state["last_close_timestamp"] = int(
                close_timestamps[row]
            )
            self.store.commit_candle(
                self.state, decision, events, closed_trade
            )
            decisions.append(decision)
        return decisions

    def _process_candle(
        self, candle: numpy.ndarray, features: numpy.ndarray
    ) -> tuple[dict, list[dict], dict | None]:
        close_timestamp = int(candle[0]) + CANDLE_SECONDS
        events = []
        closed_trade = None
        exited_this_candle = False
        if self.state.get("open_trade") is not None:
            updated, event, closed_trade = advance_open_trade(
                self.state["open_trade"], candle
            )
            self.state["open_trade"] = updated
            if event is not None:
                if (
                    event["event_type"] == "profit_lock_activated"
                    and self.config.broker_url
                ):
                    broker = self.state["open_trade"].get("paper_broker", {})
                    event["paper_broker"] = self._broker_command(
                        {
                            "event_id": (
                                f"protect:{self.state['open_trade']['opened_at']}:"
                                f"{close_timestamp}"
                            ),
                            "action": "protect",
                            "symbol": SYMBOL,
                            "stop_order_id": broker["stop_order_id"],
                            "locked_stop_price": self.state[
                                "open_trade"
                            ]["locked_stop_price"],
                        }
                    )
                events.append(event)
            if closed_trade is not None:
                if self.config.broker_url:
                    closed_trade["paper_broker_close"] = (
                        self._broker_command(
                            {
                                "event_id": (
                                    f"close:{closed_trade['opened_at']}:"
                                    f"{closed_trade['closed_at']}"
                                ),
                                "action": "close",
                                "symbol": SYMBOL,
                            }
                        )
                    )
                funding_cost, funding_error = _funding_cost_pct(
                    closed_trade["opened_at"],
                    closed_trade["closed_at"],
                    closed_trade["direction"],
                    timeout_seconds=self.config.timeout_seconds,
                )
                closed_trade["funding_cost_pct"] = funding_cost
                closed_trade["funding_error"] = funding_error
                closed_trade["fee_pct"] = v5.ROUND_TRIP_COST_PCT
                closed_trade["net_return_pct"] = (
                    closed_trade["gross_return_pct"]
                    - closed_trade["fee_pct"]
                    - (funding_cost or 0.0)
                )
                closed_trade["pnl"] = (
                    closed_trade["notional"]
                    * closed_trade["net_return_pct"]
                    / 100
                )
                self.state["equity"] += closed_trade["pnl"]
                exited_this_candle = True
        prediction = self.model.predict(features[None, :])
        decision = prediction_to_decision(
            prediction,
            close_timestamp=close_timestamp,
            close_price=float(candle[4]),
            threshold_pct=self.model.expected_net_threshold_pct,
        )
        if self.state.get("open_trade") is not None:
            decision["accepted"] = False
            decision["reason"] = "one_trade_at_a_time"
        elif exited_this_candle:
            decision["accepted"] = False
            decision["reason"] = "no_reentry_on_exit_candle"
        elif decision["action"] in DIRECTIONS:
            decision["accepted"] = True
            decision["reason"] = "v5_expected_net_gate"
            opened = open_trade_from_decision(
                decision, equity=float(self.state["equity"])
            )
            if self.config.broker_url:
                paper_broker = self._broker_command(
                    {
                        "event_id": f"open:{close_timestamp}",
                        "action": "open",
                        "symbol": SYMBOL,
                        "direction": decision["action"],
                        "notional_fraction": MAX_NOTIONAL_FRACTION,
                        "initial_stop_pct": v5.INITIAL_STOP_PCT,
                    }
                )
                opened = open_trade_from_decision(
                    decision,
                    equity=float(self.state["equity"]),
                    entry_price=float(paper_broker["entry_price"]),
                    notional=float(paper_broker["notional"]),
                )
                opened["paper_broker"] = paper_broker
            self.state["open_trade"] = opened
            events.append(
                {
                    "event_type": "trade_opened",
                    "close_timestamp": close_timestamp,
                    "trade": opened,
                }
            )
        else:
            decision["accepted"] = False
            decision["reason"] = "below_v5_expected_net_gate"
        return decision, events, closed_trade

    def _broker_command(self, payload: dict) -> dict:
        return _broker_command(
            self.config.broker_url,
            self.config.broker_token_path,
            payload,
            timeout_seconds=self.config.timeout_seconds,
        )

    def write_health(self, *, status: str | None = None) -> None:
        metrics = self.store.metrics()
        latest_close = self.state.get("last_close_timestamp")
        data_lag_seconds = (
            max(0, int(time.time()) - int(latest_close))
            if latest_close
            else None
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "mode": MODE,
            "status": status or (
                "healthy" if self.last_error is None else "degraded"
            ),
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "remote_symbol": REMOTE_SYMBOL,
            "time_frame": "15m",
            "public_data_only": True,
            "credentials_used": False,
            "orders_authorized": False,
            "paper_orders_authorized": bool(self.config.broker_url),
            "paper_broker_ready": bool(
                self.last_broker_status
                and self.last_broker_status.get("ready")
            ),
            "paper_broker_status": self.last_broker_status,
            "automatic_promotion": False,
            "model_protocol_version": v5.PROTOCOL_VERSION,
            "protocol_sha256": self.protocol["protocol_sha256"],
            "primary_model_sha256": self.model_sha256,
            "expected_net_threshold_pct": (
                self.model.expected_net_threshold_pct
            ),
            "started_at": self.started_at,
            "last_success_at": self.last_success_at,
            "updated_at": _utc_now_iso(),
            "last_error": self.last_error,
            "last_close_timestamp": latest_close,
            "last_close_at": (
                _iso_timestamp(latest_close) if latest_close else None
            ),
            "next_evaluation_at": (
                _iso_timestamp(int(latest_close) + CANDLE_SECONDS)
                if latest_close
                else None
            ),
            "data_lag_seconds": data_lag_seconds,
            "database_path": str(self.config.database_path),
            "database_bytes": (
                self.config.database_path.stat().st_size
                if self.config.database_path.exists()
                else 0
            ),
            "database_integrity": self.store.integrity,
            "equity": float(self.state["equity"]),
            "open_trade": self.state.get("open_trade"),
            "latest_decision": self.store.latest_decision(),
            "metrics": metrics,
        }
        _write_json_atomic(self.config.health_path, payload)


DIRECTIONS = (percentage_engine.LONG, percentage_engine.SHORT)


def fetch_closed_candles(
    *,
    timeout_seconds: float,
    now_timestamp: int | None = None,
    start_timestamp: int | None = None,
) -> numpy.ndarray:
    now = int(now_timestamp or time.time())
    current_open = now // CANDLE_SECONDS * CANDLE_SECONDS
    by_timestamp = {}
    cursor = max(0, int(start_timestamp or 0))
    while True:
        parameters = {
            "symbol": REMOTE_SYMBOL,
            "interval": "15m",
            "limit": (
                HISTORY_CANDLES
                if start_timestamp is None
                else min(
                    BINANCE_MAX_CANDLES,
                    max(1, math.ceil((current_open - cursor) / CANDLE_SECONDS)),
                )
            ),
            "endTime": current_open * 1000 - 1,
        }
        if start_timestamp is not None:
            parameters["startTime"] = cursor * 1000
        query = urllib.parse.urlencode(parameters)
        request = urllib.request.Request(
            f"{KLINE_URL}?{query}",
            headers={"User-Agent": "OctoBot-V5-Forward-Paper/1"},
        )
        with urllib.request.urlopen(
            request, timeout=timeout_seconds
        ) as response:
            payload = json.load(response)
        if not isinstance(payload, list):
            raise RuntimeError("Binance V5 paper candle request failed")
        for row in payload:
            timestamp = int(row[0]) // 1000
            if timestamp + CANDLE_SECONDS > now:
                continue
            by_timestamp[timestamp] = [
                timestamp,
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5]),
            ]
        if start_timestamp is None or not payload:
            break
        next_cursor = int(payload[-1][0]) // 1000 + CANDLE_SECONDS
        if next_cursor <= cursor or next_cursor >= current_open:
            break
        cursor = next_cursor
        if len(by_timestamp) > MAX_RECOVERY_CANDLES:
            raise RuntimeError("V5 paper recovery exceeds 30-day safety limit")
    candles = numpy.asarray(
        [by_timestamp[key] for key in sorted(by_timestamp)],
        dtype=numpy.float64,
    )
    if len(candles) < 150:
        raise ValueError("insufficient closed Binance 15m candles")
    if start_timestamp is None:
        candles = candles[-HISTORY_CANDLES:]
    if numpy.any(
        numpy.diff(candles[:, 0].astype(numpy.int64)) != CANDLE_SECONDS
    ):
        raise ValueError("Binance V5 paper candles contain gaps")
    latest_close = int(candles[-1, 0]) + CANDLE_SECONDS
    if current_open - latest_close > CANDLE_SECONDS:
        raise ValueError("Binance V5 paper candle feed is stale")
    if numpy.any(~numpy.isfinite(candles)) or numpy.any(candles[:, 1:] <= 0):
        raise ValueError("Binance V5 paper candles are invalid")
    if numpy.any(candles[:, 3] > candles[:, 2]):
        raise ValueError("Binance V5 paper candle ranges are invalid")
    return candles


def prediction_to_decision(
    prediction: dict[str, numpy.ndarray],
    *,
    close_timestamp: int,
    close_price: float,
    threshold_pct: float,
) -> dict:
    labels = v5.decision_labels(prediction, threshold_pct)
    label = int(labels[0])
    action = (
        percentage_engine.LONG
        if label == v1.LONG
        else percentage_engine.SHORT
        if label == v1.SHORT
        else "HOLD"
    )
    direction_index = (
        0
        if action == percentage_engine.LONG
        else 1
        if action == percentage_engine.SHORT
        else int(numpy.argmax(prediction["expected_net_pct"][0]))
    )
    target_index = int(
        prediction["target_index"][0, direction_index]
    )
    horizon_index = int(
        prediction["horizon_index"][0, direction_index]
    )
    expected = float(
        prediction["expected_net_pct"][0, direction_index]
    )
    opposite = float(
        prediction["expected_net_pct"][0, 1 - direction_index]
    )
    target = float(v5.TARGET_PROFITS_PCT[target_index])
    return {
        "close_timestamp": close_timestamp,
        "close_at": _iso_timestamp(close_timestamp),
        "close_price": close_price,
        "action": action,
        "accepted": False,
        "reason": "not_processed",
        "expected_net_pct": expected,
        "opposite_expected_net_pct": opposite,
        "direction_margin_pct": abs(expected - opposite),
        "target_probability_pct": float(
            prediction["target_probability"][0, direction_index] * 100
        ),
        "stop_probability_pct": float(
            prediction["stop_probability"][0, direction_index] * 100
        ),
        "timeout_probability_pct": float(
            prediction["timeout_probability"][0, direction_index] * 100
        ),
        "target_profit_pct": target,
        "activation_pct": target + v5.ACTIVATION_BUFFER_PCT,
        "initial_stop_pct": v5.INITIAL_STOP_PCT,
        "horizon_hours": int(v5.HORIZON_HOURS[horizon_index]),
        "threshold_pct": threshold_pct,
    }


def open_trade_from_decision(
    decision: dict,
    *,
    equity: float,
    entry_price: float | None = None,
    notional: float | None = None,
) -> dict:
    direction = decision["action"]
    sign = 1 if direction == percentage_engine.LONG else -1
    entry = float(
        decision["close_price"] if entry_price is None else entry_price
    )
    target = float(decision["target_profit_pct"])
    return {
        "direction": direction,
        "opened_at": int(decision["close_timestamp"]),
        "entry_price": entry,
        "notional": (
            equity * MAX_NOTIONAL_FRACTION
            if notional is None
            else float(notional)
        ),
        "target_profit_pct": target,
        "activation_pct": float(decision["activation_pct"]),
        "horizon_hours": int(decision["horizon_hours"]),
        "initial_stop_price": entry * (
            1 - sign * v5.INITIAL_STOP_PCT / 100
        ),
        "activation_price": entry * (
            1 + sign * float(decision["activation_pct"]) / 100
        ),
        "locked_stop_price": entry * (1 + sign * target / 100),
        "activated_at": None,
        "maximum_favorable_excursion_pct": 0.0,
        "maximum_adverse_excursion_pct": 0.0,
        "prediction": dict(decision),
    }


def advance_open_trade(
    trade: dict, candle: numpy.ndarray
) -> tuple[dict | None, dict | None, dict | None]:
    updated = dict(trade)
    close_timestamp = int(candle[0]) + CANDLE_SECONDS
    high = float(candle[2])
    low = float(candle[3])
    close = float(candle[4])
    direction = trade["direction"]
    entry = float(trade["entry_price"])
    if direction == percentage_engine.LONG:
        favorable = (high / entry - 1) * 100
        adverse = (low / entry - 1) * 100
    else:
        favorable = (1 - low / entry) * 100
        adverse = (1 - high / entry) * 100
    updated["maximum_favorable_excursion_pct"] = max(
        float(trade["maximum_favorable_excursion_pct"]), favorable
    )
    updated["maximum_adverse_excursion_pct"] = min(
        float(trade["maximum_adverse_excursion_pct"]), adverse
    )
    exit_price = None
    exit_reason = None
    event = None
    if trade.get("activated_at") is None:
        stop_touched = (
            low <= trade["initial_stop_price"]
            if direction == percentage_engine.LONG
            else high >= trade["initial_stop_price"]
        )
        activation_touched = (
            high >= trade["activation_price"]
            if direction == percentage_engine.LONG
            else low <= trade["activation_price"]
        )
        if stop_touched:
            exit_price = float(trade["initial_stop_price"])
            exit_reason = "initial_stop"
        elif activation_touched:
            updated["activated_at"] = close_timestamp
            event = {
                "event_type": "profit_lock_activated",
                "close_timestamp": close_timestamp,
                "activation_price": trade["activation_price"],
                "locked_stop_price": trade["locked_stop_price"],
            }
    else:
        locked_stop_touched = (
            low <= trade["locked_stop_price"]
            if direction == percentage_engine.LONG
            else high >= trade["locked_stop_price"]
        )
        if locked_stop_touched:
            exit_price = float(trade["locked_stop_price"])
            exit_reason = "profit_lock"
    elapsed_bars = (
        close_timestamp - int(trade["opened_at"])
    ) // CANDLE_SECONDS
    if (
        exit_price is None
        and elapsed_bars >= int(trade["horizon_hours"]) * 4
    ):
        exit_price = close
        exit_reason = (
            "horizon_after_lock"
            if updated.get("activated_at") is not None
            else "horizon"
        )
    if exit_price is None:
        return updated, event, None
    gross = (
        (exit_price / entry - 1) * 100
        if direction == percentage_engine.LONG
        else (1 - exit_price / entry) * 100
    )
    closed = {
        **updated,
        "closed_at": close_timestamp,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_return_pct": gross,
    }
    return (
        None,
        {
            "event_type": "trade_closed",
            "close_timestamp": close_timestamp,
            "exit_reason": exit_reason,
            "gross_return_pct": gross,
        },
        closed,
    )


def _funding_cost_pct(
    opened_at: int,
    closed_at: int,
    direction: str,
    *,
    timeout_seconds: float,
) -> tuple[float | None, str | None]:
    del timeout_seconds
    try:
        payload = funding.fetch_binance_funding(
            {SYMBOL: REMOTE_SYMBOL},
            opened_at * 1000,
            closed_at * 1000,
        )
        rate = sum(
            float(point["rate"])
            for point in payload["rates"].get(SYMBOL, [])
        )
        sign = 1 if direction == percentage_engine.LONG else -1
        return sign * rate * 100, None
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"


def _write_json_atomic(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _iso_timestamp(value: int) -> str:
    return datetime.datetime.fromtimestamp(
        value, datetime.timezone.utc
    ).isoformat()


def _broker_status(url: str, *, timeout_seconds: float) -> dict:
    status_url = url.rsplit("/", 1)[0] + "/status"
    request = urllib.request.Request(
        status_url,
        headers={"User-Agent": "OctoBot-V5-Paper/1"},
    )
    with urllib.request.urlopen(
        request, timeout=timeout_seconds
    ) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("V5 paper broker returned invalid status")
    return payload


def _broker_command(
    url: str,
    token_path: pathlib.Path,
    payload: dict,
    *,
    timeout_seconds: float,
) -> dict:
    token = token_path.read_text(encoding="utf-8").strip()
    request = urllib.request.Request(
        url,
        data=_canonical_json(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "OctoBot-V5-Paper/1",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout_seconds
        ) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"V5 paper broker rejected command with HTTP {error.code}"
        ) from error
    if not isinstance(result, dict) or not result.get("paper_only"):
        raise RuntimeError("V5 paper broker returned an unsafe response")
    if result.get("exchange_order_authorized") is not False:
        raise RuntimeError("V5 paper broker real-order invariant failed")
    return result


def main(argv: typing.Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-directory", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--health", required=True)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--run-seconds", type=float)
    parser.add_argument("--broker-url")
    parser.add_argument("--broker-token")
    args = parser.parse_args(argv)
    runner = V5PaperRunner(
        PaperConfig(
            model_directory=pathlib.Path(args.model_directory).resolve(),
            protocol_path=pathlib.Path(args.protocol).resolve(),
            database_path=pathlib.Path(args.database).resolve(),
            health_path=pathlib.Path(args.health).resolve(),
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
            run_seconds=args.run_seconds,
            broker_url=args.broker_url,
            broker_token_path=(
                pathlib.Path(args.broker_token).resolve()
                if args.broker_token
                else None
            ),
        )
    )
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
