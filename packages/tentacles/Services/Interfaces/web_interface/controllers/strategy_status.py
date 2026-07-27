#  Drakkar-Software OctoBot-Interfaces
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This file is part of the local, paper-only OctoBot distribution.

"""Read-only operational and forward-research status page."""

import datetime
import json
import os
import pathlib
import sqlite3
import urllib.parse

import flask

import tentacles.Services.Interfaces.web_interface.login as login
import tentacles.Services.Interfaces.web_interface.models as models


DEFAULT_AI_DECISIONS_DB_PATH = "/octobot/user/ai_decisions.sqlite"
DEFAULT_SHADOW_ROOT = "/shadow"
DEFAULT_SCALPING_HEALTH_PATH = "/scalping/health.json"
DEFAULT_V5_PAPER_HEALTH_PATH = "/v5-paper/binance/health.json"
DEFAULT_V5_PAPER_DB_PATH = "/v5-paper/binance/v5-paper.sqlite"
V5_EV_SERIES_LIMIT = 2_880
SCALPING_RESEARCH_DAYS = 30.0


def _service_url(port: int, path: str) -> str:
    parsed = urllib.parse.urlsplit(flask.request.host_url)
    hostname = parsed.hostname or "localhost"
    netloc = (
        f"[{hostname}]:{port}"
        if ":" in hostname
        else f"{hostname}:{port}"
    )
    return urllib.parse.urlunsplit(
        (parsed.scheme or "http", netloc, path, "", "")
    )


def _read_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as input_file:
        value = json.load(input_file)
    return value if isinstance(value, dict) else {}


def _read_last_jsonl(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    last_line = ""
    with path.open(encoding="utf-8") as input_file:
        for line in input_file:
            if line.strip():
                last_line = line
    if not last_line:
        return {}
    value = json.loads(last_line)
    return value if isinstance(value, dict) else {}


def _read_latest_decision(database_path: str) -> dict:
    path = pathlib.Path(database_path)
    if not path.is_file():
        return {}
    with sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=2
    ) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT id, created_at, symbol, action, confidence, signal_strength,
                   approved, guard_reason
            FROM ai_decisions
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row is not None else {}


def _clean_rows(rows: object) -> list[dict]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _operational_summary(
    latest_decision: dict, orders: list[dict], positions: list[dict]
) -> dict:
    if positions:
        return {
            "kind": "position",
            "color": "warning",
            "title": "POSIZIONE PAPER APERTA",
            "description": (
                "Il simulatore ha una posizione effettiva non nulla. "
                "Il P&L non realizzato è mostrato nella tabella."
            ),
        }
    if orders:
        return {
            "kind": "order",
            "color": "info",
            "title": "ORDINE PAPER PENDENTE — NESSUNA POSIZIONE APERTA",
            "description": (
                "L'ordine attende l'esecuzione. Finché non viene riempito, "
                "non esiste esposizione di posizione."
            ),
        }
    if latest_decision.get("approved") and latest_decision.get("action") in {
        "BUY",
        "SELL",
    }:
        return {
            "kind": "signal",
            "color": "secondary",
            "title": "SEGNALE APPROVATO — NESSUN ORDINE O POSIZIONE",
            "description": (
                "Il Risk Guard ha accettato la proposta, ma lo stato live "
                "non contiene ordini pendenti né posizioni."
            ),
        }
    return {
        "kind": "flat",
        "color": "success",
        "title": "NESSUN ORDINE E NESSUNA POSIZIONE",
        "description": "Il simulatore è attualmente senza esposizione.",
    }


def _shadow_allocations(record: dict) -> list[dict]:
    weights = record.get("target_weights", {})
    if not isinstance(weights, dict):
        return []
    allocations = []
    for symbol, raw_weight in weights.items():
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            continue
        if abs(weight) <= 1e-12:
            continue
        allocations.append(
            {
                "symbol": symbol,
                "side": "LONG" if weight > 0 else "SHORT",
                "weight": weight,
            }
        )
    return sorted(allocations, key=lambda item: abs(item["weight"]), reverse=True)


def _scalping_summary(health: dict) -> dict:
    summary = {
        "span_days": 0.0,
        "progress": 0.0,
        "book_events_per_second": 0.0,
        "required_days": SCALPING_RESEARCH_DAYS,
    }
    try:
        first = datetime.datetime.fromisoformat(health["first_book_at"])
        last = datetime.datetime.fromisoformat(health["last_book_at"])
        span_seconds = max(0.0, (last - first).total_seconds())
        span_days = span_seconds / 86_400
        summary["span_days"] = span_days
        summary["progress"] = min(
            1.0, span_days / SCALPING_RESEARCH_DAYS
        )
        if span_seconds > 0:
            summary["book_events_per_second"] = (
                float(health.get("book_events", 0)) / span_seconds
            )
    except (KeyError, TypeError, ValueError):
        pass
    return summary


def _timestamp_iso(timestamp: object) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(
            int(timestamp), tz=datetime.timezone.utc
        ).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _v5_forward_summary(
    database_path: str, expected_net_threshold_pct: float
) -> dict:
    """Read descriptive V5 forward statistics without mutating its journal."""

    path = pathlib.Path(database_path)
    if not path.is_file():
        return {"available": False}
    with sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=2
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        integrity = str(
            connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        if integrity != "ok":
            raise sqlite3.DatabaseError(
                f"V5 paper database integrity={integrity}"
            )
        decision = connection.execute(
            """
            SELECT
                COUNT(*) AS decisions,
                COALESCE(SUM(accepted), 0) AS accepted,
                COALESCE(
                    SUM(CASE WHEN expected_net_pct > 0 THEN 1 ELSE 0 END),
                    0
                ) AS positive_expected_net,
                MIN(close_timestamp) AS first_close_timestamp,
                MAX(close_timestamp) AS last_close_timestamp,
                AVG(expected_net_pct) AS mean_expected_net_pct,
                MAX(expected_net_pct) AS max_expected_net_pct
            FROM decisions
            """
        ).fetchone()
        trades = connection.execute(
            """
            SELECT
                COUNT(*) AS trades,
                COALESCE(
                    SUM(CASE WHEN net_return_pct > 0 THEN 1 ELSE 0 END),
                    0
                ) AS wins,
                COALESCE(
                    SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END),
                    0
                ) AS gross_profit,
                COALESCE(
                    -SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END),
                    0
                ) AS gross_loss,
                COALESCE(SUM(pnl), 0) AS total_pnl
            FROM trades
            """
        ).fetchone()
        target_distribution = [
            dict(row)
            for row in connection.execute(
                """
                SELECT target_profit_pct AS value, COUNT(*) AS count
                FROM decisions
                WHERE target_profit_pct IS NOT NULL
                GROUP BY target_profit_pct
                ORDER BY target_profit_pct
                """
            )
        ]
        horizon_distribution = [
            dict(row)
            for row in connection.execute(
                """
                SELECT horizon_hours AS value, COUNT(*) AS count
                FROM decisions
                WHERE horizon_hours IS NOT NULL
                GROUP BY horizon_hours
                ORDER BY horizon_hours
                """
            )
        ]
        reason_distribution = [
            dict(row)
            for row in connection.execute(
                """
                SELECT reason AS value, COUNT(*) AS count
                FROM decisions
                GROUP BY reason
                ORDER BY count DESC, reason
                """
            )
        ]
        ev_rows = list(
            connection.execute(
                """
                SELECT close_timestamp, expected_net_pct, accepted
                FROM (
                    SELECT id, close_timestamp, expected_net_pct, accepted
                    FROM decisions
                    WHERE expected_net_pct IS NOT NULL
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id
                """,
                (V5_EV_SERIES_LIMIT,),
            )
        )

    decisions = int(decision["decisions"])
    accepted = int(decision["accepted"])
    trade_count = int(trades["trades"])
    first_timestamp = decision["first_close_timestamp"]
    last_timestamp = decision["last_close_timestamp"]
    span_hours = (
        max(0.0, (int(last_timestamp) - int(first_timestamp)) / 3600)
        if first_timestamp is not None and last_timestamp is not None
        else 0.0
    )
    for distribution in (target_distribution, horizon_distribution):
        for row in distribution:
            row["share_pct"] = (
                float(row["count"]) * 100 / decisions if decisions else 0.0
            )
    max_expected_net = decision["max_expected_net_pct"]
    gross_profit = float(trades["gross_profit"])
    gross_loss = float(trades["gross_loss"])
    return {
        "available": True,
        "integrity": integrity,
        "decisions": decisions,
        "accepted": accepted,
        "holds": decisions - accepted,
        "acceptance_rate_pct": (
            accepted * 100 / decisions if decisions else 0.0
        ),
        "positive_expected_net": int(decision["positive_expected_net"]),
        "mean_expected_net_pct": decision["mean_expected_net_pct"],
        "max_expected_net_pct": max_expected_net,
        "expected_net_threshold_pct": expected_net_threshold_pct,
        "distance_to_gate_pct": (
            expected_net_threshold_pct - float(max_expected_net)
            if max_expected_net is not None
            else None
        ),
        "first_close_at": _timestamp_iso(first_timestamp),
        "last_close_at": _timestamp_iso(last_timestamp),
        "span_hours": span_hours,
        "trades": trade_count,
        "wins": int(trades["wins"]),
        "win_rate_pct": (
            int(trades["wins"]) * 100 / trade_count
            if trade_count
            else None
        ),
        "profit_factor": (
            gross_profit / gross_loss if gross_loss else None
        ),
        "total_pnl": float(trades["total_pnl"]),
        "calibration_status": (
            "in_attesa_di_trade_chiusi"
            if not trade_count
            else "descrittiva_preliminare"
        ),
        "target_distribution": target_distribution,
        "horizon_distribution": horizon_distribution,
        "reason_distribution": reason_distribution,
        "ev_series": {
            "timestamps": [
                _timestamp_iso(row["close_timestamp"])
                for row in ev_rows
            ],
            "expected_net_pct": [
                float(row["expected_net_pct"]) for row in ev_rows
            ],
            "accepted": [
                bool(row["accepted"]) for row in ev_rows
            ],
            "threshold_pct": expected_net_threshold_pct,
            "maximum_points": V5_EV_SERIES_LIMIT,
        },
    }


def register(blueprint):
    @blueprint.route("/strategy_status")
    @login.login_required_when_activated
    def strategy_status():
        errors = []
        database_path = os.getenv(
            "AI_DECISIONS_DB_PATH", DEFAULT_AI_DECISIONS_DB_PATH
        )
        shadow_root = pathlib.Path(
            os.getenv("SHADOW_STATUS_ROOT", DEFAULT_SHADOW_ROOT)
        )
        scalping_health_path = pathlib.Path(
            os.getenv(
                "SCALPING_HEALTH_PATH", DEFAULT_SCALPING_HEALTH_PATH
            )
        )
        v5_paper_health_path = pathlib.Path(
            os.getenv(
                "V5_PAPER_HEALTH_PATH", DEFAULT_V5_PAPER_HEALTH_PATH
            )
        )
        v5_paper_db_path = os.getenv(
            "V5_PAPER_DB_PATH", DEFAULT_V5_PAPER_DB_PATH
        )

        try:
            latest_decision = _read_latest_decision(database_path)
        except (OSError, sqlite3.Error) as error:
            latest_decision = {}
            errors.append(f"Decision journal: {error}")

        try:
            orders = _clean_rows(models.get_all_orders_data())
            positions = _clean_rows(models.get_all_positions_data())
        except (RuntimeError, ValueError) as error:
            orders, positions = [], []
            errors.append(f"Paper runtime: {error}")

        files = {
            "market_health": shadow_root / "market" / "health.json",
            "market_evidence": shadow_root / "market" / "evidence.json",
            "shadow_health": shadow_root / "health.json",
            "performance": shadow_root / "performance.json",
            "income_objective": shadow_root / "income-objective.json",
            "shadow_journal": shadow_root / "trend_shadow.jsonl",
        }
        loaded = {}
        for name, path in files.items():
            try:
                loaded[name] = (
                    _read_last_jsonl(path)
                    if name == "shadow_journal"
                    else _read_json(path)
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                loaded[name] = {}
                errors.append(f"{name}: {error}")
        try:
            scalping_health = _read_json(scalping_health_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            scalping_health = {}
            errors.append(f"scalping_health: {error}")
        try:
            v5_paper_health = _read_json(v5_paper_health_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            v5_paper_health = {}
            errors.append(f"v5_paper_health: {error}")
        try:
            v5_forward_summary = _v5_forward_summary(
                v5_paper_db_path,
                float(
                    v5_paper_health.get(
                        "expected_net_threshold_pct", 0.075
                    )
                ),
            )
        except (OSError, TypeError, ValueError, sqlite3.Error) as error:
            v5_forward_summary = {"available": False}
            errors.append(f"v5_forward_summary: {error}")

        return flask.render_template(
            "strategy_status.html",
            latest_decision=latest_decision,
            orders=orders,
            positions=positions,
            operational=_operational_summary(
                latest_decision, orders, positions
            ),
            market_health=loaded["market_health"],
            evidence=loaded["market_evidence"],
            shadow_health=loaded["shadow_health"],
            performance=loaded["performance"],
            income=loaded["income_objective"],
            shadow_record=loaded["shadow_journal"],
            shadow_allocations=_shadow_allocations(
                loaded["shadow_journal"]
            ),
            scalping_health=scalping_health,
            scalping_summary=_scalping_summary(scalping_health),
            v5_paper_health=v5_paper_health,
            v5_forward_summary=v5_forward_summary,
            v5_paper_url=_service_url(5002, "/trading"),
            shadow_ready=all(
                path.is_file()
                for name, path in files.items()
                if name != "shadow_journal"
            ),
            errors=errors,
        )
