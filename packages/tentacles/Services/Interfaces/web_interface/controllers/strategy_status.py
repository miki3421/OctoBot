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

import flask

import tentacles.Services.Interfaces.web_interface.login as login
import tentacles.Services.Interfaces.web_interface.models as models


DEFAULT_AI_DECISIONS_DB_PATH = "/octobot/user/ai_decisions.sqlite"
DEFAULT_SHADOW_ROOT = "/shadow"
DEFAULT_SCALPING_HEALTH_PATH = "/scalping/health.json"
SCALPING_RESEARCH_DAYS = 30.0


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
            shadow_ready=all(
                path.is_file()
                for name, path in files.items()
                if name != "shadow_journal"
            ),
            errors=errors,
        )
