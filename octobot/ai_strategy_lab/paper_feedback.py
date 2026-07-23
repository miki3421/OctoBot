"""Read-only export of paper decisions and realized position outcomes."""

from __future__ import annotations

import datetime
import json
import pathlib
import sqlite3
import typing


FEEDBACK_SCHEMA_VERSION = 1
BIAS_CODES = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}
MINIMUM_TRAINING_ROWS = 200
MINIMUM_CALENDAR_DAYS = 365
MINIMUM_ROWS_PER_DIRECTION = 50
MINIMUM_ROWS_PER_OUTCOME_CLASS = 40


def export_paper_feedback(
    journal_path: typing.Union[str, pathlib.Path],
) -> dict:
    path = pathlib.Path(journal_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"paper journal does not exist: {path}")
    with sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=5
    ) as connection:
        connection.row_factory = sqlite3.Row
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"paper journal integrity check failed: {integrity}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required = {
            "ai_decisions",
            "ai_order_events",
            "ai_position_outcomes",
        }
        missing = required - tables
        if missing:
            raise ValueError(
                f"paper feedback schema is incomplete: {sorted(missing)}"
            )
        rows = connection.execute(
            """
            SELECT decision.id AS decision_id, decision.created_at,
                   decision.exchange_name, decision.symbol,
                   decision.triggered_at, decision.model,
                   decision.prompt_version, decision.input_json,
                   decision.action, decision.confidence,
                   decision.signal_strength, decision.approved,
                   decision.guard_reason,
                   outcome.id AS outcome_id, outcome.exit_at,
                   outcome.side AS position_side, outcome.quantity,
                   outcome.entry_price, outcome.exit_price,
                   outcome.gross_price_pnl, outcome.known_fees,
                   outcome.net_pnl_excluding_funding,
                   outcome.return_pct_excluding_funding,
                   outcome.exit_reason
            FROM ai_decisions AS decision
            LEFT JOIN ai_position_outcomes AS outcome
              ON outcome.decision_id = decision.id
            ORDER BY decision.id, outcome.id
            """
        ).fetchall()
        snapshot = {
            "max_decision_id": _maximum_id(connection, "ai_decisions"),
            "max_order_event_id": _maximum_id(
                connection, "ai_order_events"
            ),
            "max_outcome_id": _maximum_id(
                connection, "ai_position_outcomes"
            ),
            "decision_rows": connection.execute(
                "SELECT COUNT(*) FROM ai_decisions"
            ).fetchone()[0],
            "order_event_rows": connection.execute(
                "SELECT COUNT(*) FROM ai_order_events"
            ).fetchone()[0],
            "outcome_rows": connection.execute(
                "SELECT COUNT(*) FROM ai_position_outcomes"
            ).fetchone()[0],
        }

    exported = []
    feature_names = set()
    invalid_inputs = 0
    for row in rows:
        try:
            input_data = json.loads(row["input_json"])
            features = _flatten_decision_features(input_data)
        except (json.JSONDecodeError, TypeError, ValueError):
            features = {}
            invalid_inputs += 1
        feature_names.update(features)
        outcome_available = row["outcome_id"] is not None
        training_eligible = bool(row["approved"]) and outcome_available
        exported.append(
            {
                "decision_id": row["decision_id"],
                "created_at": row["created_at"],
                "exchange_name": row["exchange_name"],
                "symbol": row["symbol"],
                "triggered_at": row["triggered_at"],
                "model": row["model"],
                "prompt_version": row["prompt_version"],
                "action": row["action"],
                "confidence": row["confidence"],
                "signal_strength": row["signal_strength"],
                "approved": bool(row["approved"]),
                "guard_reason": row["guard_reason"],
                "features": features,
                "outcome_available": outcome_available,
                "eligible_for_supervised_training": training_eligible,
                "label": (
                    {
                        "outcome_id": row["outcome_id"],
                        "exit_at": row["exit_at"],
                        "position_side": row["position_side"],
                        "quantity": row["quantity"],
                        "entry_price": row["entry_price"],
                        "exit_price": row["exit_price"],
                        "gross_price_pnl": row["gross_price_pnl"],
                        "known_fees": row["known_fees"],
                        "net_pnl_excluding_funding": row[
                            "net_pnl_excluding_funding"
                        ],
                        "return_pct_excluding_funding": row[
                            "return_pct_excluding_funding"
                        ],
                        "profitable_excluding_funding": (
                            row["net_pnl_excluding_funding"] > 0
                        ),
                        "exit_reason": row["exit_reason"],
                    }
                    if outcome_available
                    else None
                ),
            }
        )
    feature_schema = sorted(feature_names)
    for row in exported:
        row["features"] = {
            name: row["features"].get(name) for name in feature_schema
        }
    eligible = sum(
        row["eligible_for_supervised_training"] for row in exported
    )
    training_readiness = _training_readiness(
        exported, invalid_inputs=invalid_inputs
    )
    return {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "created_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "source": {
            "path": str(path),
            "integrity_check": integrity,
            "snapshot": snapshot,
        },
        "label_contract": {
            "eligible": (
                "approved decision with a linked, closed paper position"
            ),
            "economic_value": (
                "net price P&L after known order fees, excluding funding"
            ),
            "unlabelled_controls": (
                "HOLD, rejected and still-open decisions retain label=null"
            ),
        },
        "feature_schema": feature_schema,
        "summary": {
            "exported_rows": len(exported),
            "eligible_training_rows": eligible,
            "unlabelled_rows": len(exported) - eligible,
            "invalid_input_json_rows": invalid_inputs,
        },
        "training_readiness": training_readiness,
        "rows": exported,
    }


def _maximum_id(connection, table):
    return connection.execute(
        f"SELECT COALESCE(MAX(id), 0) FROM {table}"
    ).fetchone()[0]


def _flatten_decision_features(input_data):
    if not isinstance(input_data, dict):
        raise ValueError("decision input must be an object")
    result = {}
    for timeframe, evaluations in input_data.items():
        if not isinstance(evaluations, list):
            continue
        for evaluation in evaluations:
            if not isinstance(evaluation, dict):
                continue
            evaluator = evaluation.get("evaluator")
            if not evaluator:
                continue
            prefix = f"{timeframe}.{evaluator}"
            note = _numeric_or_none(evaluation.get("eval_note"))
            if note is not None:
                result[f"{prefix}.eval_note"] = note
            bias = str(evaluation.get("bias", "")).upper()
            if bias in BIAS_CODES:
                result[f"{prefix}.bias_code"] = BIAS_CODES[bias]
            metadata = evaluation.get("metadata")
            if isinstance(metadata, dict):
                _flatten_numeric(metadata, f"{prefix}.metadata", result)
    return result


def _flatten_numeric(value, prefix, result):
    for key, item in sorted(value.items()):
        name = f"{prefix}.{key}"
        if isinstance(item, dict):
            _flatten_numeric(item, name, result)
        else:
            numeric = _numeric_or_none(item)
            if numeric is not None:
                result[name] = numeric


def _numeric_or_none(value):
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _training_readiness(rows, *, invalid_inputs):
    eligible = [
        row for row in rows
        if row["eligible_for_supervised_training"]
    ]
    action_counts = {
        action: sum(row["action"] == action for row in eligible)
        for action in ("BUY", "SELL")
    }
    profitable = sum(
        row["label"]["profitable_excluding_funding"]
        for row in eligible
    )
    losing = len(eligible) - profitable
    timestamps = sorted(
        int(row["triggered_at"])
        for row in eligible
        if row["triggered_at"] is not None
    )
    calendar_days = (
        (timestamps[-1] - timestamps[0]) / 86400.0
        if len(timestamps) > 1
        else 0.0
    )
    checks = {
        "at_least_200_closed_outcomes": (
            len(eligible) >= MINIMUM_TRAINING_ROWS
        ),
        "at_least_365_calendar_days": (
            calendar_days >= MINIMUM_CALENDAR_DAYS
        ),
        "at_least_50_long_outcomes": (
            action_counts["BUY"] >= MINIMUM_ROWS_PER_DIRECTION
        ),
        "at_least_50_short_outcomes": (
            action_counts["SELL"] >= MINIMUM_ROWS_PER_DIRECTION
        ),
        "at_least_40_profitable_outcomes": (
            profitable >= MINIMUM_ROWS_PER_OUTCOME_CLASS
        ),
        "at_least_40_non_profitable_outcomes": (
            losing >= MINIMUM_ROWS_PER_OUTCOME_CLASS
        ),
        "no_invalid_feature_inputs": invalid_inputs == 0,
        "funding_included_in_economic_labels": False,
    }
    return {
        "passed": all(checks.values()),
        "status": (
            "ready_for_offline_fitting"
            if all(checks.values())
            else "insufficient_evidence"
        ),
        "automatic_training_authorized": False,
        "requirements": {
            "minimum_closed_outcomes": MINIMUM_TRAINING_ROWS,
            "minimum_calendar_days": MINIMUM_CALENDAR_DAYS,
            "minimum_outcomes_per_direction": (
                MINIMUM_ROWS_PER_DIRECTION
            ),
            "minimum_outcomes_per_class": (
                MINIMUM_ROWS_PER_OUTCOME_CLASS
            ),
        },
        "observed": {
            "closed_outcomes": len(eligible),
            "calendar_days": calendar_days,
            "long_outcomes": action_counts["BUY"],
            "short_outcomes": action_counts["SELL"],
            "profitable_outcomes_excluding_funding": profitable,
            "non_profitable_outcomes_excluding_funding": losing,
            "invalid_feature_inputs": invalid_inputs,
        },
        "checks": checks,
    }
