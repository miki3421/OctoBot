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
MAX_DISPLAYED_DECISIONS = 250
MAX_DISPLAYED_OUTCOMES = 50


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
                   prompt_version, input_json, output_json, action, confidence,
                   signal_strength, eval_note, approved, guard_reason, rationale,
                   invalidation, horizon_minutes
            FROM ai_decisions
            ORDER BY id DESC
            LIMIT ?
            """,
            (MAX_DISPLAYED_DECISIONS,),
        ).fetchall()

    decisions = []
    for row in rows:
        decision = dict(row)
        decision["input_json"] = _pretty_json(decision["input_json"])
        decision["output_json"] = _pretty_json(decision["output_json"])
        decisions.append(decision)
    return decisions, summary


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
                COALESCE(SUM(net_pnl_excluding_funding), 0)
                    AS net_pnl_excluding_funding
            FROM ai_position_outcomes
            """
        ).fetchone()
        summary = dict(summary_row)
        summary["order_events"] = event_count
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
