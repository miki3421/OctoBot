#  Drakkar-Software OctoBot-Interfaces
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.

"""Read-only web view for the local guarded-AI SQLite decision journal."""

import ast
import datetime
import json
import os
import pathlib
import sqlite3

import flask

import tentacles.Services.Interfaces.web_interface.login as login


DEFAULT_AI_DECISIONS_DB_PATH = "/octobot/user/ai_decisions.sqlite"
DEFAULT_BACKTEST_METADATA_PATH = (
    "/octobot/user/data/DailyTradingMode/default_campaign/backtesting/metadata.json"
)
PROTECTED_CAPITAL_USDT = 10_000.0
MAX_DISPLAYED_DECISIONS = 25
MAX_DISPLAYED_OUTCOMES = 10


def _pretty_json(value: str) -> str:
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return value or ""


def _empty_summary() -> dict:
    return {
        "total": 0,
        "approved": 0,
        "rejected": 0,
        "buy": 0,
        "sell": 0,
        "hold": 0,
        "errors": 0,
        "approval_rate": 0.0,
    }


def _empty_capital_summary() -> dict:
    return {
        "protected_capital": PROTECTED_CAPITAL_USDT,
        "end_equity": None,
        "theoretical_surplus": 0.0,
        "gains": None,
        "return_pct": None,
        "run_name": None,
        "run_id": None,
        "period": None,
        "completed_at": None,
    }


def _empty_outcome_summary() -> dict:
    return {
        "order_events": 0,
        "interrupted_orders": 0,
        "closed_positions": 0,
        "wins": 0,
        "losses": 0,
        "net_pnl_excluding_funding": 0.0,
        "win_rate": 0.0,
        "gross_price_pnl": 0.0,
        "known_fees": 0.0,
        "profit_factor": None,
        "same_exit_inverse": 0.0,
    }


def _paper_execution_summary(
    decision: dict,
    latest_event: dict | None = None,
    outcome: dict | None = None,
    attempt: dict | None = None,
    covering_position: dict | None = None,
) -> dict:
    """Describe actual paper execution separately from signal approval."""

    if outcome:
        pnl = float(outcome.get("net_pnl_excluding_funding", 0.0) or 0.0)
        return {
            "kind": "closed",
            "label": "TRADE CHIUSO",
            "color": "success" if pnl > 0 else "danger",
            "detail": (
                f"{pnl:+.2f} USDT · "
                f"{str(outcome.get('side', '-')).upper()} · funding escluso"
            ),
        }
    if latest_event:
        status = str(latest_event.get("status", "unknown")).lower()
        reduce_only = bool(latest_event.get("reduce_only"))
        if status == "interrupted":
            label, color = "ORDINE INTERROTTO", "warning"
        elif status == "open":
            label, color = ("USCITA PROTETTIVA" if reduce_only else "ORDINE APERTO"), "warning"
        elif status == "filled" and not reduce_only:
            label, color = "INGRESSO ESEGUITO", "success"
        else:
            label, color = f"ORDINE {status.upper()}", "info"
        return {
            "kind": "order",
            "label": label,
            "color": color,
            "detail": (
                f"{str(latest_event.get('side', '-')).upper()} · "
                f"{latest_event.get('order_type') or '-'} · "
                f"qty {float(latest_event.get('quantity', 0.0) or 0.0):.8g}"
            ),
        }
    if attempt:
        descriptions = {
            "strategy_quarantined": ("STRATEGIA SOSPESA", "Nuovi ingressi in quarantena; le uscite protettive restano abilitate."),
            "side_disabled": ("LATO DISABILITATO", "BUY/SELL disabilitato nel profilo, non un errore di volume."),
            "position_already_open": ("POSIZIONE GIÀ APERTA", "Non si aumenta una posizione esistente."),
            "managed_exit_only": ("USCITA GIÀ GESTITA", "Il segnale opposto non chiude la posizione: uscita affidata a stop e timeout."),
            "state_unchanged": ("SEGNALE RIPETUTO", "Il motore opera sui cambi di stato: attende un nuovo stato, anche dopo una chiusura."),
            "execution_error": ("ERRORE DI ESECUZIONE", attempt.get("detail") or "Consultare i dettagli."),
            "submitted": ("INVIATO AL MOTORE", "Richiesta inoltrata, nessun evento ordine ancora registrato."),
            "orders_created": ("IN ATTESA DI RISCONTRO", "Il motore ha restituito ordini; manca il relativo evento nel journal."),
        }
        reason = attempt["reason"]
        label, detail = descriptions.get(reason, ("ESITO DA VERIFICARE", reason))
        return {"kind": "execution_attempt", "label": label,
                "color": "danger" if reason == "execution_error" else "warning",
                "detail": detail}
    if decision.get("approved") and decision.get("action") in {"BUY", "SELL"}:
        if covering_position:
            return {
                "kind": "position_context", "label": "DURANTE UN TRADE",
                "color": "info",
                "detail": f"Era aperto il trade #{covering_position['decision_id']}. "
                          "Nessun nuovo ordine; il motivo specifico non fu registrato.",
            }
        return {
            "kind": "signal_only",
            "label": "ESITO NON TRACCIATO",
            "color": "warning",
            "detail": "Nessun ordine nel journal. Il vecchio motore non registrava il motivo: non è dimostrato un errore di fondi.",
        }
    return {
        "kind": "not_executed",
        "label": "NON ESEGUITA",
        "color": "secondary",
        "detail": "HOLD o proposta bloccata",
    }


def _format_timestamp(timestamp: object) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(
            float(timestamp), tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return None


def _parse_end_equity(portfolio: object) -> float | None:
    if not isinstance(portfolio, str):
        return None
    try:
        holdings = ast.literal_eval(portfolio)
        return float(holdings["USDT"]["total"])
    except (KeyError, SyntaxError, TypeError, ValueError):
        return None


def _read_capital_summary(metadata_path: str) -> dict:
    """Return the latest completed backtest's theoretical surplus safely."""

    summary = _empty_capital_summary()
    path = pathlib.Path(metadata_path)
    if not path.is_file():
        return summary

    with path.open(encoding="utf-8") as metadata_file:
        runs = json.load(metadata_file).get("metadata", {})
    if not isinstance(runs, dict) or not runs:
        return summary

    latest_run_id, latest_run = max(
        runs.items(),
        key=lambda item: float(item[1].get("timestamp", 0) or 0),
    )
    if not isinstance(latest_run, dict):
        return summary

    end_equity = _parse_end_equity(latest_run.get("end portfolio"))
    summary.update(
        {
            "end_equity": end_equity,
            "theoretical_surplus": max(
                0.0, (end_equity or PROTECTED_CAPITAL_USDT) - PROTECTED_CAPITAL_USDT
            ),
            "gains": latest_run.get("gains"),
            "return_pct": latest_run.get("% gains"),
            "run_name": latest_run.get("name"),
            "run_id": latest_run_id,
            "completed_at": _format_timestamp(latest_run.get("timestamp")),
        }
    )
    start = _format_timestamp(latest_run.get("start_time"))
    end = _format_timestamp(latest_run.get("end_time"))
    if start and end:
        summary["period"] = f"{start} → {end}"
    return summary


def _read_decisions(database_path: str) -> tuple[list[dict], dict]:
    path = pathlib.Path(database_path)
    if not path.is_file():
        return [], _empty_summary()

    with sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=2
    ) as connection:
        connection.row_factory = sqlite3.Row
        summary_row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(approved), 0) AS approved,
                COALESCE(SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END), 0) AS buy,
                COALESCE(SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END), 0) AS sell,
                COALESCE(SUM(CASE WHEN action = 'HOLD' THEN 1 ELSE 0 END), 0) AS hold,
                COALESCE(SUM(CASE WHEN guard_reason = 'llm_or_schema_error' THEN 1 ELSE 0 END), 0) AS errors
            FROM ai_decisions
            """
        ).fetchone()
        summary = dict(summary_row)
        summary["rejected"] = summary["total"] - summary["approved"]
        summary["approval_rate"] = (
            round(summary["approved"] * 100 / summary["total"], 1)
            if summary["total"]
            else 0.0
        )

        rows = connection.execute(
            """
            SELECT id, created_at, exchange_name, cryptocurrency, symbol, model,
                   action, confidence, signal_strength, approved, guard_reason,
                   rationale, invalidation, horizon_minutes
            FROM ai_decisions
            ORDER BY id DESC
            LIMIT ?
            """,
            (MAX_DISPLAYED_DECISIONS,),
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        decision_ids = [int(row["id"]) for row in rows]
        latest_events = {}
        attempts, covering_positions = _execution_context(connection, decision_ids, tables)
        outcomes = {}
        if decision_ids:
            placeholders = ",".join("?" for _ in decision_ids)
            if "ai_order_events" in tables:
                event_rows = connection.execute(
                    f"""
                    SELECT id, decision_id, created_at, update_type, status,
                           side, order_type, quantity, filled_quantity, price,
                           average_price, reduce_only
                    FROM ai_order_events
                    WHERE decision_id IN ({placeholders})
                    ORDER BY reduce_only ASC, id DESC
                    """,
                    decision_ids,
                ).fetchall()
                # A protective SELL must never masquerade as the BUY entry.
                for row in event_rows:
                    latest_events.setdefault(int(row["decision_id"]), dict(row))
            if "ai_position_outcomes" in tables:
                outcome_rows = connection.execute(
                    f"""
                    SELECT id, decision_id, side, entry_at, exit_at,
                           entry_price, exit_price,
                           net_pnl_excluding_funding,
                           return_pct_excluding_funding, exit_reason
                    FROM ai_position_outcomes
                    WHERE decision_id IN ({placeholders})
                    ORDER BY id DESC
                    """,
                    decision_ids,
                ).fetchall()
                for outcome_row in outcome_rows:
                    outcomes.setdefault(
                        int(outcome_row["decision_id"]), dict(outcome_row)
                    )

    decisions = []
    for row in rows:
        decision = dict(row)
        decision_id = int(decision["id"])
        decision["paper_execution"] = _paper_execution_summary(
            decision,
            latest_events.get(decision_id),
            outcomes.get(decision_id),
            attempts.get(decision_id),
            covering_positions.get(decision_id),
        )
        decisions.append(decision)
    return decisions, summary


def _execution_context(connection, decision_ids, tables):
    attempts, covering = {}, {}
    if not decision_ids:
        return attempts, covering
    placeholders = ",".join("?" for _ in decision_ids)
    if "ai_execution_attempts" in tables:
        for row in connection.execute(
            f"SELECT * FROM ai_execution_attempts WHERE decision_id IN ({placeholders}) ORDER BY id DESC",
            decision_ids,
        ):
            attempts.setdefault(int(row["decision_id"]), dict(row))
    if "ai_position_outcomes" in tables:
        for row in connection.execute(
            f"""SELECT d.id, p.decision_id FROM ai_decisions d
            JOIN ai_position_outcomes p ON p.exchange_name=d.exchange_name AND p.symbol=d.symbol
            AND julianday(p.entry_at)<=julianday(d.created_at)
            AND julianday(d.created_at)<julianday(p.exit_at)
            WHERE d.id IN ({placeholders}) ORDER BY p.entry_at DESC""", decision_ids,
        ):
            covering.setdefault(int(row["id"]), dict(row))
    return attempts, covering


def _read_execution_policy(database_path):
    if not pathlib.Path(database_path).is_file():
        return None
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=2) as connection:
        connection.row_factory = sqlite3.Row
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ai_execution_policy_events'"
        ).fetchone():
            return None
        row = connection.execute(
            "SELECT * FROM ai_execution_policy_events WHERE exchange_name='kucoin' "
            "AND symbol='BTC/USDT:USDT' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def _read_decision_detail(database_path: str, decision_id: int) -> dict | None:
    """Read one full audit record without inflating the journal list page."""

    path = pathlib.Path(database_path)
    if not path.is_file():
        return None
    with sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=2
    ) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT id, created_at, exchange_name, cryptocurrency, symbol, model,
                   prompt_version, input_json, output_json, action, confidence,
                   signal_strength, eval_note, approved, guard_reason, rationale,
                   invalidation, horizon_minutes
            FROM ai_decisions
            WHERE id = ?
            """,
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        tables = {
            table_row[0]
            for table_row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        order_events = []
        outcome = None
        attempts, covering_positions = _execution_context(connection, [decision_id], tables)
        if "ai_order_events" in tables:
            order_events = [
                dict(event_row)
                for event_row in connection.execute(
                    """
                    SELECT id, created_at, update_type, status, side,
                           order_type, quantity, filled_quantity, price,
                           average_price, reduce_only
                    FROM ai_order_events
                    WHERE decision_id = ?
                    ORDER BY id
                    """,
                    (decision_id,),
                ).fetchall()
            ]
        if "ai_position_outcomes" in tables:
            outcome_row = connection.execute(
                """
                SELECT id, decision_id, side, entry_at, exit_at,
                       entry_price, exit_price, net_pnl_excluding_funding,
                       return_pct_excluding_funding, exit_reason
                FROM ai_position_outcomes
                WHERE decision_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (decision_id,),
            ).fetchone()
            outcome = dict(outcome_row) if outcome_row is not None else None
    decision = dict(row)
    decision["input_json"] = _pretty_json(decision["input_json"])
    decision["output_json"] = _pretty_json(decision["output_json"])
    decision["order_events"] = order_events
    decision["paper_outcome"] = outcome
    decision["paper_execution"] = _paper_execution_summary(
        decision,
        next((event for event in reversed(order_events) if not event["reduce_only"]),
             order_events[-1] if order_events else None),
        outcome,
        attempts.get(decision_id),
        covering_positions.get(decision_id),
    )
    return decision


def _read_outcomes(database_path: str) -> tuple[list[dict], dict]:
    path = pathlib.Path(database_path)
    if not path.is_file():
        return [], _empty_outcome_summary()
    with sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=2
    ) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {
            "ai_order_events",
            "ai_position_outcomes",
        }.issubset(tables):
            return [], _empty_outcome_summary()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM ai_order_events"
        ).fetchone()[0]
        interrupted_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM ai_order_events
            WHERE status = 'interrupted'
              AND update_type = 'startup_reconciliation'
            """
        ).fetchone()[0]
        summary_row = connection.execute(
            """
            SELECT
                COUNT(*) AS closed_positions,
                COALESCE(SUM(
                    CASE WHEN net_pnl_excluding_funding > 0 THEN 1 ELSE 0 END
                ), 0) AS wins,
                COALESCE(SUM(
                    CASE WHEN net_pnl_excluding_funding < 0 THEN 1 ELSE 0 END
                ), 0) AS losses,
                COALESCE(SUM(gross_price_pnl), 0) AS gross_price_pnl,
                COALESCE(SUM(known_fees), 0) AS known_fees,
                COALESCE(SUM(CASE WHEN net_pnl_excluding_funding>0 THEN net_pnl_excluding_funding ELSE 0 END), 0) AS positive_pnl,
                COALESCE(SUM(CASE WHEN net_pnl_excluding_funding<0 THEN -net_pnl_excluding_funding ELSE 0 END), 0) AS negative_pnl,
                COALESCE(SUM(net_pnl_excluding_funding), 0)
                    AS net_pnl_excluding_funding
            FROM ai_position_outcomes
            """
        ).fetchone()
        summary = dict(summary_row)
        summary["order_events"] = event_count
        summary["profit_factor"] = (
            summary["positive_pnl"] / summary["negative_pnl"] if summary["negative_pnl"] else None
        )
        summary["same_exit_inverse"] = -summary["gross_price_pnl"] - summary["known_fees"]
        summary["interrupted_orders"] = interrupted_count
        summary["win_rate"] = (
            round(
                summary["wins"] * 100 / summary["closed_positions"], 1
            )
            if summary["closed_positions"]
            else 0.0
        )
        rows = connection.execute(
            """
            SELECT outcome.id, outcome.exit_at, outcome.symbol, outcome.side,
                   outcome.quantity, outcome.entry_price, outcome.exit_price,
                   outcome.net_pnl_excluding_funding,
                   outcome.return_pct_excluding_funding,
                   outcome.exit_reason, outcome.decision_id,
                   decision.action, decision.confidence
            FROM ai_position_outcomes AS outcome
            JOIN ai_decisions AS decision
              ON decision.id = outcome.decision_id
            ORDER BY outcome.id DESC
            LIMIT ?
            """,
            (MAX_DISPLAYED_OUTCOMES,),
        ).fetchall()
    return [dict(row) for row in rows], summary


def register(blueprint):
    @blueprint.route("/ai_decisions")
    @login.login_required_when_activated
    def ai_decisions():
        database_path = os.getenv(
            "AI_DECISIONS_DB_PATH", DEFAULT_AI_DECISIONS_DB_PATH
        )
        error = None
        outcome_error = None
        backtest_error = None
        try:
            decisions, summary = _read_decisions(database_path)
        except (OSError, sqlite3.Error) as database_error:
            decisions, summary = [], _empty_summary()
            error = f"Unable to read the AI decision journal: {database_error}"
        try:
            execution_policy = _read_execution_policy(database_path)
        except (OSError, sqlite3.Error):
            execution_policy = None
        try:
            outcomes, outcome_summary = _read_outcomes(database_path)
        except (OSError, sqlite3.Error) as database_error:
            outcomes, outcome_summary = [], _empty_outcome_summary()
            outcome_error = (
                f"Unable to read paper trade outcomes: {database_error}"
            )
        try:
            capital = _read_capital_summary(
                os.getenv("BACKTEST_METADATA_PATH", DEFAULT_BACKTEST_METADATA_PATH)
            )
        except (OSError, ValueError, json.JSONDecodeError) as metadata_error:
            capital = _empty_capital_summary()
            backtest_error = f"Unable to read latest backtest metadata: {metadata_error}"
        return flask.render_template(
            "ai_decisions.html",
            decisions=decisions,
            execution_policy=execution_policy,
            summary=summary,
            database_ready=pathlib.Path(database_path).is_file(),
            error=error,
            outcomes=outcomes,
            outcome_summary=outcome_summary,
            outcome_error=outcome_error,
            backtest_error=backtest_error,
            capital=capital,
            display_limit=MAX_DISPLAYED_DECISIONS,
            outcome_display_limit=MAX_DISPLAYED_OUTCOMES,
        )

    @blueprint.route("/ai_decisions/<int:decision_id>")
    @login.login_required_when_activated
    def ai_decision_detail(decision_id):
        database_path = os.getenv(
            "AI_DECISIONS_DB_PATH", DEFAULT_AI_DECISIONS_DB_PATH
        )
        try:
            decision = _read_decision_detail(database_path, decision_id)
        except (OSError, sqlite3.Error):
            flask.abort(503)
        if decision is None:
            flask.abort(404)
        return flask.render_template(
            "ai_decision_detail.html",
            decision=decision,
        )
