#  Drakkar-Software OctoBot-Interfaces
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This file is part of the local, paper-only OctoBot distribution.

"""Read-only operational and forward-research status page."""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import sqlite3
import urllib.parse

import flask

import tentacles.Services.Interfaces.web_interface.login as login
import tentacles.Services.Interfaces.web_interface.models as models
from octobot.ai_strategy_lab import forward_carry_dashboard


DEFAULT_AI_DECISIONS_DB_PATH = "/octobot/user/ai_decisions.sqlite"
DEFAULT_SHADOW_ROOT = "/shadow"
DEFAULT_SCALPING_HEALTH_PATH = "/scalping/health.json"
DEFAULT_EXECUTION_SHADOW_HEALTH_PATH = "/execution-shadow/health.json"
DEFAULT_V5_PAPER_HEALTH_PATH = "/v5-paper/binance/health.json"
DEFAULT_V5_PAPER_DB_PATH = "/v5-paper/binance/v5-paper.sqlite"
DEFAULT_CARRY_PROTOCOL_PATH = (
    "/octobot/backtesting/research/forward-carry-v1_1/protocol.json"
)
DEFAULT_CARRY_GATEKEEPER_STATUS_PATH = (
    "/octobot/backtesting/research/forward-carry-v1_1/gatekeeper/status.json"
)
DEFAULT_MICROSTRUCTURE_ROOT = (
    "/octobot/backtesting/research/microstructure-regime-v1"
)
DEFAULT_MICROSTRUCTURE_V2_ROOT = (
    "/octobot/backtesting/research/microstructure-regime-v2"
)
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


def _shadow_allocations(
    record: dict, field: str = "target_weights"
) -> list[dict]:
    weights = record.get(field, {})
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


def _shadow_last_rebalance_date(path: pathlib.Path) -> str | None:
    """Return the most recent date on which candidate weights were applied."""

    if not path.is_file():
        return None
    last_date = None
    with path.open(encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict) and record.get("rebalance_due") is True:
                last_date = record.get("market_end_date")
    return last_date


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


def _execution_shadow_summary(health: dict) -> dict:
    if not health:
        return {"available": False}
    for field in (
        "orders_authorized",
        "paper_orders_authorized",
        "automatic_promotion",
    ):
        if health.get(field) is not False:
            raise ValueError(f"execution shadow safety invariant differs: {field}")
    if health.get("mode") != "execution_shadow_only":
        raise ValueError("execution shadow mode differs")
    counts = health.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    predicted = int(counts.get("predicted", 0) or 0)
    missed = int(counts.get("missed", 0) or 0)
    selected = int(counts.get("selected", 0) or 0)
    completed = int(counts.get("completed_outcomes", 0) or 0)
    scheduled = predicted + missed
    healthy = health.get("healthy") is True
    status = str(health.get("status", "UNKNOWN"))
    return {
        "available": True,
        "healthy": healthy,
        "color": "success" if healthy else "danger",
        "status": status,
        "forward_start": health.get("forward_start"),
        "forward_end": health.get("forward_end_exclusive"),
        "progress_pct": float(health.get("progress_pct", 0.0) or 0.0),
        "predicted": predicted,
        "missed": missed,
        "selected": selected,
        "completed_outcomes": completed,
        "incomplete_outcomes": int(
            counts.get("incomplete_outcomes", 0) or 0
        ),
        "prediction_coverage_pct": (
            100.0 * predicted / scheduled if scheduled else 0.0
        ),
        "selection_pct": 100.0 * selected / predicted if predicted else 0.0,
        "outcome_completion_pct": (
            100.0 * completed / predicted if predicted else 0.0
        ),
        "collector_healthy": health.get("collector_healthy") is True,
        "journal_tail_verified": health.get("journal_tail_verified") is True,
        "journal_bytes": int(health.get("journal_bytes", 0) or 0),
        "protocol_sha256": health.get("protocol_sha256"),
        "last_success_at": health.get("last_success_at"),
        "official_evaluation_materialized": (
            health.get("official_evaluation_materialized") is True
        ),
        "official_verdict": health.get("official_verdict"),
    }


def _carry_gatekeeper_summary(status: dict) -> dict:
    if not status:
        return {"available": False}
    for field in (
        "orders_authorized",
        "paper_orders_authorized",
        "automatic_promotion",
        "real_income_authorized",
    ):
        if status.get(field) is not False:
            raise ValueError(f"Carry gatekeeper safety invariant differs: {field}")
    if status.get("research_only") is not True:
        raise ValueError("Carry gatekeeper is not research-only")
    allowed_phases = {
        "WAITING_READINESS",
        "RUNNING_DEVELOPMENT",
        "WAITING_CONFIRMATION",
        "RUNNING_CONFIRMATION",
        "COMPLETE",
        "BLOCKED_OPERATIONAL",
    }
    phase = str(status.get("phase", "UNKNOWN"))
    if phase not in allowed_phases:
        raise ValueError("Carry gatekeeper phase is invalid")
    healthy = status.get("healthy") is True
    if phase == "COMPLETE":
        color = "success" if status.get("official_verdict") == "CONFIRMATION_PASS" else "secondary"
    elif healthy:
        color = "info" if phase.startswith("RUNNING") else "warning"
    else:
        color = "danger"
    blockers = status.get("blockers", [])
    if not isinstance(blockers, list):
        blockers = []
    return {
        "available": True,
        "healthy": healthy,
        "color": color,
        "phase": phase,
        "phase_detail": str(status.get("phase_detail", "")),
        "updated_at": status.get("updated_at"),
        "progress_pct": float(status.get("progress_pct", 0.0) or 0.0),
        "official_verdict": status.get("official_verdict"),
        "artifacts_created": status.get("artifacts_created") is True,
        "blockers": [
            {
                "id": str(value.get("id", "unknown")),
                "detail": str(value.get("detail", "")),
            }
            for value in blockers
            if isinstance(value, dict)
        ],
    }


def _microstructure_summary(root: pathlib.Path) -> dict:
    protocol = _read_json(root / "protocol.json")
    experiment_root = root / "experiments"
    reports = sorted(experiment_root.glob("*/report.json"), reverse=True)
    if not protocol or not reports:
        return {
            "available": False,
            "protocol_available": bool(protocol),
        }
    report = _read_json(reports[0])
    protocol_sha256 = protocol.get("protocol_sha256")
    if report.get("protocol", {}).get("sha256") != protocol_sha256:
        raise ValueError("microstructure report protocol hash differs")
    if protocol.get("results") is not None:
        raise ValueError("microstructure protocol is not result-free")
    for value in (protocol, report):
        if value.get("orders_authorized") is not False:
            raise ValueError("microstructure report authorizes orders")
        if value.get("paper_orders_authorized") is not False:
            raise ValueError("microstructure report authorizes paper orders")
    if report.get("dataset", {}).get("locked_test_materialized") is not False:
        raise ValueError("microstructure report opened locked data")

    models = report.get("models", {})
    price = models.get("price_only", {})
    book = models.get("book_only", {})
    combined = models.get("combined", {})
    gate = report.get("diagnostic_advancement_gate", {})
    horizon_values = {
        int(item.get("horizon_seconds", 0)): item
        for item in report.get("diagnostics_only", {}).get("horizons", [])
        if isinstance(item, dict)
    }
    dataset_manifest = _read_json(
        root / "diagnostic-dataset.manifest.json"
    )
    combined_distribution = combined.get(
        "probability_distribution", {}
    ).get("both_directions", {})
    passed = gate.get("passed") is True
    return {
        "available": True,
        "state": "PASS DIAGNOSTICO" if passed else "V1 RESPINTA",
        "color": "success" if passed else "danger",
        "experiment_id": report.get("experiment_id"),
        "created_at": report.get("created_at"),
        "protocol_sha256": protocol_sha256,
        "rows": int(report.get("dataset", {}).get("rows", 0)),
        "first_decision": dataset_manifest.get("first_decision"),
        "last_decision": dataset_manifest.get("last_decision"),
        "price_auc": price.get("probability", {}).get("auc"),
        "book_auc": book.get("probability", {}).get("auc"),
        "combined_auc": combined.get("probability", {}).get("auc"),
        "relative_brier_improvement_pct": (
            float(gate.get("relative_brier_improvement_vs_price", 0.0))
            * 100.0
        ),
        "book_improvement_folds": int(
            gate.get("book_improvement_folds", 0)
        ),
        "total_folds": 4,
        "combined_probability_max_pct": (
            float(combined_distribution["maximum"]) * 100.0
            if combined_distribution.get("maximum") is not None
            else None
        ),
        "probability_threshold_pct": (
            float(
                report.get("primary_task", {}).get(
                    "probability_threshold", 0.0
                )
            )
            * 100.0
        ),
        "target_rate_4h_pct": (
            float(horizon_values[14_400]["target_rate"]) * 100.0
            if 14_400 in horizon_values
            else None
        ),
        "target_rate_8h_pct": (
            float(horizon_values[28_800]["target_rate"]) * 100.0
            if 28_800 in horizon_values
            else None
        ),
        "passed_checks": int(gate.get("passed_checks", 0)),
        "total_checks": int(gate.get("total_checks", 0)),
        "locked_test_materialized": False,
        "orders_authorized": False,
        "conclusion": report.get("conclusion"),
    }


def _microstructure_v2_summary(root: pathlib.Path) -> dict:
    """Return a fail-closed read-only summary of two-stage research V2."""

    protocol = _read_json(root / "protocol.json")
    reports = sorted((root / "experiments").glob("*/report.json"), reverse=True)
    if not protocol or not reports:
        return {
            "available": False,
            "protocol_available": bool(protocol),
        }
    report = _read_json(reports[0])
    protocol_sha256 = protocol.get("protocol_sha256")
    if report.get("protocol", {}).get("sha256") != protocol_sha256:
        raise ValueError("microstructure V2 report protocol hash differs")
    if protocol.get("results") is not None:
        raise ValueError("microstructure V2 protocol is not result-free")
    for value in (protocol, report):
        if value.get("orders_authorized") is not False:
            raise ValueError("microstructure V2 report authorizes orders")
        if value.get("paper_orders_authorized") is not False:
            raise ValueError("microstructure V2 report authorizes paper orders")
    dataset = report.get("dataset", {})
    if dataset.get("locked_test_materialized") is not False:
        raise ValueError("microstructure V2 report opened locked data")

    stages = report.get("stages", {})
    arms = report.get("arms", {})
    primary_arm = arms.get("book_filter", {})
    residual_arm = arms.get("book_filter_residual", {})
    economic = primary_arm.get("primary", {})
    stress = primary_arm.get("stress", {})
    gate = report.get("diagnostic_advancement_gate", {})
    passed = gate.get("passed") is True

    def _metric(group: dict, name: str) -> object:
        value = group.get(name)
        return value if isinstance(value, (int, float)) else None

    return {
        "available": True,
        "state": "PASS DIAGNOSTICO" if passed else "V2 RESPINTA",
        "color": "success" if passed else "danger",
        "experiment_id": report.get("experiment_id"),
        "created_at": report.get("created_at"),
        "protocol_sha256": protocol_sha256,
        "rows": int(dataset.get("rows", 0)),
        "oos_rows": int(dataset.get("oos_rows", 0)),
        "barrier_events": int(dataset.get("barrier_events", 0)),
        "known_direction_events": int(
            dataset.get("known_direction_events", 0)
        ),
        "ambiguous_barrier_events": int(
            dataset.get("ambiguous_barrier_events", 0)
        ),
        "price_activity_auc": _metric(
            stages.get("price_activity", {}), "auc"
        ),
        "filtered_activity_auc": _metric(
            stages.get("filtered_activity", {}), "auc"
        ),
        "price_direction_auc": _metric(
            stages.get("price_direction", {}), "auc"
        ),
        "book_direction_auc": _metric(
            stages.get("book_direction", {}), "auc"
        ),
        "residual_direction_auc": _metric(
            stages.get("residual_direction", {}), "auc"
        ),
        "target_auc": _metric(
            primary_arm.get("target_probability", {}), "auc"
        ),
        "relative_activity_brier_improvement_pct": (
            float(
                gate.get(
                    "relative_activity_brier_improvement_vs_price", 0.0
                )
            )
            * 100.0
        ),
        "activity_improvement_folds": int(
            gate.get("activity_improvement_folds", 0)
        ),
        "total_folds": 4,
        "trades": int(economic.get("trades", 0)),
        "win_rate_pct": float(economic.get("win_rate", 0.0)) * 100.0,
        "profit_factor": _metric(economic, "profit_factor"),
        "total_return_pct": float(economic.get("total_return", 0.0)) * 100.0,
        "average_instrument_return_bps": _metric(
            economic, "average_instrument_return_bps"
        ),
        "stress_return_pct": float(stress.get("total_return", 0.0)) * 100.0,
        "residual_trades": int(
            residual_arm.get("primary", {}).get("trades", 0)
        ),
        "residual_return_pct": float(
            residual_arm.get("primary", {}).get("total_return", 0.0)
        )
        * 100.0,
        "positive_folds": int(gate.get("positive_folds", 0)),
        "passed_checks": int(gate.get("passed_checks", 0)),
        "total_checks": int(gate.get("total_checks", 0)),
        "locked_test_materialized": False,
        "orders_authorized": False,
        "conclusion": report.get("conclusion"),
    }


def _timestamp_iso(timestamp: object) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(
            int(timestamp), tz=datetime.timezone.utc
        ).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _v5_trade_outcome(exit_reason: str) -> str | None:
    if exit_reason == "initial_stop":
        return "STOP"
    if exit_reason in {"profit_lock", "horizon_after_lock"}:
        return "TARGET"
    if exit_reason == "horizon":
        return "TIMEOUT"
    return None


def _v5_calibration(rows: list[sqlite3.Row]) -> dict:
    probabilities = {"TARGET": [], "STOP": [], "TIMEOUT": []}
    observed = {"TARGET": 0, "STOP": 0, "TIMEOUT": 0}
    brier_values = []
    for row in rows:
        outcome = _v5_trade_outcome(str(row["exit_reason"]))
        if outcome is None:
            continue
        try:
            prediction = json.loads(row["prediction_json"])
            current = {
                "TARGET": float(prediction["target_probability_pct"]) / 100,
                "STOP": float(prediction["stop_probability_pct"]) / 100,
                "TIMEOUT": float(prediction["timeout_probability_pct"]) / 100,
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        observed[outcome] += 1
        for name, probability in current.items():
            probabilities[name].append(probability)
        brier_values.append(
            sum(
                (probability - (1.0 if name == outcome else 0.0)) ** 2
                for name, probability in current.items()
            )
        )
    count = len(brier_values)
    return {
        "mature_accepted_trades": count,
        "status": "preliminary" if count else "waiting_for_closed_trade",
        "multiclass_brier": sum(brier_values) / count if count else None,
        "classes": [
            {
                "name": name,
                "mean_predicted_pct": (
                    sum(probabilities[name]) * 100 / count if count else None
                ),
                "observed_pct": (
                    observed[name] * 100 / count if count else None
                ),
                "observed_count": observed[name],
            }
            for name in ("TARGET", "STOP", "TIMEOUT")
        ],
        "warning": (
            "Calibrazione limitata ai trade accettati e già chiusi; "
            "non misura le previsioni V5 rifiutate."
        ),
    }


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
        accepted_direction_distribution = [
            dict(row)
            for row in connection.execute(
                """
                SELECT action AS value, COUNT(*) AS count
                FROM decisions
                WHERE accepted = 1
                GROUP BY action
                ORDER BY action
                """
            )
        ]
        trade_rows = list(
            connection.execute(
                """
                SELECT direction, exit_reason, prediction_json
                FROM trades
                ORDER BY id
                """
            )
        )
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
    span_days = span_hours / 24
    for distribution in (target_distribution, horizon_distribution):
        for row in distribution:
            row["share_pct"] = (
                float(row["count"]) * 100 / decisions if decisions else 0.0
            )
    max_expected_net = decision["max_expected_net_pct"]
    gross_profit = float(trades["gross_profit"])
    gross_loss = float(trades["gross_loss"])
    trade_direction_counts = {"LONG": 0, "SHORT": 0}
    for row in trade_rows:
        direction = str(row["direction"])
        trade_direction_counts[direction] = (
            trade_direction_counts.get(direction, 0) + 1
        )
    accepted_direction_counts = {"LONG": 0, "SHORT": 0}
    for row in accepted_direction_distribution:
        accepted_direction_counts[str(row["value"])] = int(row["count"])
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
        "decisions_per_day": decisions / span_days if span_days else 0.0,
        "accepted_per_day": accepted / span_days if span_days else 0.0,
        "accepted_by_direction": accepted_direction_counts,
        "trades": trade_count,
        "trades_by_direction": trade_direction_counts,
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
        "calibration": _v5_calibration(trade_rows),
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
        execution_shadow_health_path = pathlib.Path(
            os.getenv(
                "EXECUTION_SHADOW_HEALTH_PATH",
                DEFAULT_EXECUTION_SHADOW_HEALTH_PATH,
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
        carry_protocol_path = pathlib.Path(
            os.getenv(
                "CARRY_PROTOCOL_PATH", DEFAULT_CARRY_PROTOCOL_PATH
            )
        )
        carry_gatekeeper_status_path = pathlib.Path(
            os.getenv(
                "CARRY_GATEKEEPER_STATUS_PATH",
                DEFAULT_CARRY_GATEKEEPER_STATUS_PATH,
            )
        )
        microstructure_root = pathlib.Path(
            os.getenv(
                "MICROSTRUCTURE_RESEARCH_ROOT",
                DEFAULT_MICROSTRUCTURE_ROOT,
            )
        )
        microstructure_v2_root = pathlib.Path(
            os.getenv(
                "MICROSTRUCTURE_V2_RESEARCH_ROOT",
                DEFAULT_MICROSTRUCTURE_V2_ROOT,
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
        operations_path = shadow_root / "operations" / "current.json"
        scalping_protocol_path = (
            shadow_root / "operations" / "scalping-evaluation-protocol.json"
        )
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
            data_quality = _read_json(operations_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            data_quality = {}
            errors.append(f"data_quality: {error}")
        try:
            scalping_protocol = _read_json(scalping_protocol_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            scalping_protocol = {}
            errors.append(f"scalping_protocol: {error}")
        try:
            shadow_last_rebalance_date = _shadow_last_rebalance_date(
                files["shadow_journal"]
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            shadow_last_rebalance_date = None
            errors.append(f"shadow_last_rebalance: {error}")
        try:
            scalping_health = _read_json(scalping_health_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            scalping_health = {}
            errors.append(f"scalping_health: {error}")
        try:
            execution_shadow = _execution_shadow_summary(
                _read_json(execution_shadow_health_path)
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            execution_shadow = {"available": False}
            errors.append(f"execution_shadow: {error}")
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
        try:
            carry_protocol = _read_json(carry_protocol_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            carry_protocol = {}
            errors.append(f"carry_protocol: {error}")
        try:
            carry_gatekeeper = _carry_gatekeeper_summary(
                _read_json(carry_gatekeeper_status_path)
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            carry_gatekeeper = {"available": False}
            errors.append(f"carry_gatekeeper: {error}")
        try:
            microstructure = _microstructure_summary(
                microstructure_root
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            microstructure = {"available": False}
            errors.append(f"microstructure_research: {error}")
        try:
            microstructure_v2 = _microstructure_v2_summary(
                microstructure_v2_root
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            microstructure_v2 = {"available": False}
            errors.append(f"microstructure_v2_research: {error}")
        carry_protocol_status = forward_carry_dashboard.protocol_status(
            carry_protocol
        )
        carry_readiness = forward_carry_dashboard.readiness_summary(
            loaded["market_evidence"],
            loaded["market_health"],
            carry_protocol_status,
        )

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
            carry=carry_readiness,
            carry_gatekeeper=carry_gatekeeper,
            shadow_health=loaded["shadow_health"],
            performance=loaded["performance"],
            income=loaded["income_objective"],
            shadow_record=loaded["shadow_journal"],
            shadow_allocations=_shadow_allocations(
                loaded["shadow_journal"]
            ),
            shadow_candidates=_shadow_allocations(
                loaded["shadow_journal"], "candidate_target_weights"
            ),
            shadow_last_rebalance_date=shadow_last_rebalance_date,
            scalping_health=scalping_health,
            scalping_summary=_scalping_summary(scalping_health),
            execution_shadow=execution_shadow,
            scalping_protocol=scalping_protocol,
            microstructure=microstructure,
            microstructure_v2=microstructure_v2,
            data_quality=data_quality,
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
