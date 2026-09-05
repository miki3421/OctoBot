#  Drakkar-Software OctoBot-Interfaces
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This file is part of the local, paper-only OctoBot distribution.

"""Read-only operational and forward-research status page."""

from __future__ import annotations

import datetime
import json
import math
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
DEFAULT_DIVERSIFIED_FORWARD_HEALTH_PATH = (
    "/diversified-forward/health.json"
)
DEFAULT_DIVERSIFIED_FORWARD_LOCK_PATH = (
    "/diversified-forward/implementation-lock.json"
)
DEFAULT_DIVERSIFIED_FORWARD_GATE_LOCK_PATH = (
    "/diversified-forward/gate-lock.json"
)
DEFAULT_DIVERSIFIED_FORWARD_GATEKEEPER_HEALTH_PATH = (
    "/diversified-forward/gate-runtime/health.json"
)
DEFAULT_DIVERSIFIED_FORWARD_DECISIONS_PATH = (
    "/diversified-forward/decisions.jsonl"
)
DEFAULT_DIVERSIFIED_PAPER_HEALTH_PATH = "/diversified-paper/health.json"
DEFAULT_DIVERSIFIED_PAPER_DB_PATH = "/diversified-paper/paper.sqlite"
DEFAULT_DIVERSIFIED_FORWARD_PROTOCOL_PATH = (
    "/octobot/backtesting/research/diversified-trend-cointegration-v1/"
    "forward-protocol-v1.json"
)
DEFAULT_BREADTH_FORWARD_HEALTH_PATH = "/breadth-forward/health.json"
DEFAULT_BREADTH_FORWARD_LOCK_PATH = (
    "/breadth-forward/implementation-lock.json"
)
DEFAULT_CROSS_VENUE_HEALTH_PATH = "/cross-venue/health.json"
DEFAULT_PROJECT_HISTORY_PATH = "/workspace/HISTORY.md"
DEFAULT_MIGRATION_AUDIT_PATH = "/workspace/MIGRATION_AUDIT_2026-09-02.md"
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


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    with path.open(encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("JSONL record is not an object")
            records.append(value)
    return records


def _read_diversified_paper_chart_rows(
    database_path: str,
) -> list[dict]:
    path = pathlib.Path(database_path)
    if not path.is_file():
        return []

    def read_rows(uri: str) -> list[sqlite3.Row]:
        with sqlite3.connect(uri, uri=True, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                """
                SELECT bar_date, paper_equity, turnover, estimated_cost,
                       order_count
                FROM decisions
                ORDER BY id
                """
            ).fetchall()

    try:
        rows = read_rows(f"file:{path}?mode=ro")
    except sqlite3.OperationalError:
        wal_path = pathlib.Path(f"{path}-wal")
        if wal_path.is_file() and wal_path.stat().st_size:
            raise
        # A read-only WAL mount cannot create its first -shm file. When no
        # WAL payload exists, immutable mode safely reads the checkpointed DB.
        rows = read_rows(f"file:{path}?mode=ro&immutable=1")
    return [dict(row) for row in rows]


def _diversified_equity_chart(
    records: list[dict],
    protocol_sha256: str | None,
    implementation_lock_sha256: str | None,
    paper: dict,
    paper_database_path: str,
) -> dict:
    """Build read-only forward and paper series for the Operations chart."""

    if not records:
        return {"available": False}
    dates = []
    trend_equity = []
    cointegration_equity = []
    portfolio_equity = []
    previous_date = None
    for record in records:
        payload = record.get("decision_payload")
        if not isinstance(payload, dict):
            raise ValueError(
                "diversified chart record has no decision payload"
            )
        for field in (
            "orders_authorized",
            "paper_orders_authorized",
            "automatic_promotion",
            "credentials_used",
        ):
            if payload.get(field) is not False:
                raise ValueError(
                    f"diversified chart safety invariant differs: {field}"
                )
        lineage = payload.get("lineage", {})
        if (
            not isinstance(lineage, dict)
            or lineage.get("forward_protocol_sha256") != protocol_sha256
            or lineage.get("implementation_lock_sha256")
            != implementation_lock_sha256
        ):
            raise ValueError("diversified chart lineage differs")
        try:
            bar_date = datetime.date.fromisoformat(str(payload["bar_date"]))
            base = payload["base"]
            values = (
                float(base["trend_equity"]),
                float(base["cointegration_equity"]),
                float(base["portfolio_equity"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("diversified chart record is invalid") from error
        if previous_date is not None and bar_date <= previous_date:
            raise ValueError(
                "diversified chart dates are not strictly ordered"
            )
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("diversified chart equity is invalid")
        dates.append(bar_date.isoformat())
        trend_equity.append(10_000.0 * values[0])
        cointegration_equity.append(10_000.0 * values[1])
        portfolio_equity.append(10_000.0 * values[2])
        previous_date = bar_date

    baseline_date = (
        datetime.date.fromisoformat(dates[0]) - datetime.timedelta(days=1)
    ).isoformat()
    dates.insert(0, baseline_date)
    trend_equity.insert(0, 10_000.0)
    cointegration_equity.insert(0, 10_000.0)
    portfolio_equity.insert(0, 10_000.0)

    paper_dates = []
    paper_equity = []
    paper_hover = []
    paper_marker_sizes = []
    paper_marker_symbols = []
    if paper.get("available"):
        try:
            boundary = datetime.date.fromisoformat(
                str(paper["activation_boundary_bar"])
            )
            initial_equity = float(paper["initial_equity"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "diversified paper chart boundary is invalid"
            ) from error
        if not math.isfinite(initial_equity) or initial_equity <= 0:
            raise ValueError(
                "diversified paper chart initial equity is invalid"
            )
        paper_dates.append(boundary.isoformat())
        paper_equity.append(initial_equity)
        paper_hover.append("Attivazione causale; nessun rendimento precedente")
        paper_marker_sizes.append(11)
        paper_marker_symbols.append("diamond-open")
        previous_paper_date = boundary
        for row in _read_diversified_paper_chart_rows(paper_database_path):
            try:
                bar_date = datetime.date.fromisoformat(str(row["bar_date"]))
                equity = float(row["paper_equity"])
                turnover = float(row["turnover"])
                estimated_cost = float(row["estimated_cost"])
                order_count = int(row["order_count"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "diversified paper chart row is invalid"
                ) from error
            if bar_date <= previous_paper_date:
                raise ValueError(
                    "diversified paper chart dates are not strictly ordered"
                )
            if (
                not math.isfinite(equity)
                or equity <= 0
                or not math.isfinite(turnover)
                or turnover < 0
                or not math.isfinite(estimated_cost)
                or estimated_cost < 0
                or order_count < 0
            ):
                raise ValueError("diversified paper chart row is invalid")
            paper_dates.append(bar_date.isoformat())
            paper_equity.append(equity)
            paper_hover.append(
                f"Ribilanciamento: {order_count} fill virtuali; "
                f"turnover {100 * turnover:.2f}%; "
                f"costo stimato {estimated_cost:.2f} USDT"
            )
            paper_marker_sizes.append(12 if order_count else 8)
            paper_marker = "diamond" if order_count else "circle"
            paper_marker_symbols.append(paper_marker)
            previous_paper_date = bar_date

    return {
        "available": True,
        "forward_point_count": len(records),
        "dates": dates,
        "trend_equity": trend_equity,
        "cointegration_equity": cointegration_equity,
        "portfolio_equity": portfolio_equity,
        "paper_available": bool(paper_dates),
        "paper_dates": paper_dates,
        "paper_equity": paper_equity,
        "paper_hover": paper_hover,
        "paper_marker_sizes": paper_marker_sizes,
        "paper_marker_symbols": paper_marker_symbols,
        "orders_authorized": False,
    }


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


def _cross_venue_summary(health: dict) -> dict:
    if not health:
        return {"available": False}
    for field in (
        "orders_authorized",
        "paper_orders_authorized",
        "automatic_promotion",
        "credentials_used",
    ):
        if health.get(field) is not False:
            raise ValueError(f"cross-venue safety invariant differs: {field}")
    if (
        health.get("observer_type")
        != "binance_kucoin_cross_venue_books_v1"
        or health.get("mode") != "observation_only"
        or health.get("public_data_only") is not True
        or health.get("archive_consistent") is not True
        or health.get("full_payload_duplicate_journal") is not False
    ):
        raise ValueError("cross-venue observer mode differs")
    return {
        "available": True,
        "healthy": health.get("status") == "healthy",
        "status": str(health.get("status", "unknown")),
        "symbol_count": int(health.get("symbol_count", 0) or 0),
        "archived_records": int(health.get("archived_records", 0) or 0),
        "forward_observed_days": int(
            health.get("forward_observed_days", 0) or 0
        ),
        "last_success_at": health.get("last_success_at"),
        "compressed_archive_megabytes": float(
            health.get("compressed_archive_bytes", 0) or 0
        )
        / (1024 * 1024),
    }


def _breadth_forward_summary(health: dict, implementation_lock: dict) -> dict:
    if not health or not implementation_lock:
        return {"available": False}
    for name, value in (
        ("health", health),
        ("implementation lock", implementation_lock),
    ):
        for field in (
            "orders_authorized",
            "paper_orders_authorized",
            "automatic_promotion",
        ):
            if value.get(field) is not False:
                raise ValueError(
                    f"breadth forward {name} safety invariant differs: {field}"
                )
    if (
        health.get("observer_type")
        != "liquid_market_breadth_forward_observer_v2"
        or implementation_lock.get("observer_type")
        != "liquid_market_breadth_forward_observer_v2"
        or health.get("mode") != "forward_observation_only"
        or health.get("research_only") is not True
        or implementation_lock.get("research_only") is not True
        or health.get("public_data_only") is not True
        or health.get("network_required") is not False
        or implementation_lock.get("network_capability_required") is not False
        or health.get("credentials_used") is not False
        or health.get("gate_evaluation_authorized") is not False
        or health.get("pre_cutoff_aggregate_metrics_calculated") is not False
    ):
        raise ValueError("breadth forward observer mode differs")
    if (
        health.get("protocol_sha256")
        != implementation_lock.get("protocol_sha256")
        or health.get("implementation_lock_sha256")
        != implementation_lock.get("implementation_lock_sha256")
    ):
        raise ValueError("breadth forward lineage hash differs")
    phase = str(health.get("phase", "unknown"))
    if phase not in {"warmup", "forward", "waiting_for_gate_cutoff"}:
        raise ValueError("breadth forward phase differs")
    official_records = int(health.get("official_market_records", 0) or 0)
    decision_records = int(health.get("decision_records", 0) or 0)
    mature_outcomes = int(health.get("mature_outcomes", 0) or 0)
    blockers = health.get("current_blockers", [])
    if not isinstance(blockers, list):
        blockers = []
    healthy = health.get("status") == "healthy"
    return {
        "available": True,
        "healthy": healthy,
        "color": "info" if healthy else "danger",
        "status": str(health.get("status", "unknown")),
        "phase": phase,
        "phase_label": phase.replace("_", " ").upper(),
        "warmup_records": int(health.get("warmup_records", 0) or 0),
        "official_records": official_records,
        "minimum_days": 180,
        "decision_records": decision_records,
        "mature_outcomes": mature_outcomes,
        "required_mature_outcomes": 179,
        "progress_pct": min(100.0, 100.0 * official_records / 180),
        "last_decision_bar": health.get("last_decision_bar"),
        "last_success_at": health.get("last_success_at"),
        "earliest_gate": health.get(
            "earliest_gate_evaluation_not_before_utc"
        ),
        "blockers": [str(value) for value in blockers],
        "protocol_sha256": health.get("protocol_sha256"),
        "implementation_lock_sha256": health.get(
            "implementation_lock_sha256"
        ),
        "orders_authorized": False,
    }


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


def _diversified_forward_summary(
    health: dict,
    protocol: dict,
    implementation_lock: dict,
    gate_lock: dict | None = None,
    gatekeeper_health: dict | None = None,
    latest_record: dict | None = None,
) -> dict:
    if not health or not protocol or not implementation_lock:
        return {"available": False}
    for name, value in (
        ("health", health),
        ("protocol", protocol),
        ("implementation lock", implementation_lock),
    ):
        for field in (
            "orders_authorized",
            "paper_orders_authorized",
            "automatic_promotion",
        ):
            if value.get(field) is not False:
                raise ValueError(
                    f"diversified forward {name} safety invariant differs: "
                    f"{field}"
                )
    if (
        health.get("mode") != "forward_observation_only"
        or health.get("public_data_only") is not True
        or health.get("gate_evaluation_authorized") is not False
        or protocol.get("protocol_version")
        != "crypto_diversified_trend_cointegration_forward_v1"
        or protocol.get("results") is not None
    ):
        raise ValueError("diversified forward mode or protocol differs")
    if (
        health.get("protocol_sha256") != protocol.get("protocol_sha256")
        or health.get("implementation_lock_sha256")
        != implementation_lock.get("implementation_lock_sha256")
        or implementation_lock.get("protocol_sha256")
        != protocol.get("protocol_sha256")
    ):
        raise ValueError("diversified forward lineage hash differs")
    phase = str(health.get("phase", "unknown"))
    if phase not in {"warmup", "forward"}:
        raise ValueError("diversified forward phase differs")
    gate_lock = gate_lock or {}
    gatekeeper_health = gatekeeper_health or {}
    if bool(gate_lock) != bool(gatekeeper_health):
        raise ValueError("diversified forward gatekeeper evidence is incomplete")
    gatekeeper_available = bool(gate_lock)
    gatekeeper_healthy = True
    gatekeeper_phase = None
    if gatekeeper_available:
        for name, value in (
            ("gate lock", gate_lock),
            ("gatekeeper health", gatekeeper_health),
        ):
            for field in (
                "orders_authorized",
                "paper_orders_authorized",
                "automatic_promotion",
            ):
                if value.get(field) is not False:
                    raise ValueError(
                        f"diversified forward {name} safety invariant "
                        f"differs: {field}"
                    )
        if (
            gate_lock.get("gate_version")
            != "crypto_diversified_trend_cointegration_forward_gate_v1"
            or gate_lock.get("status")
            != "immutable_result_free_pre_forward_gate_lock"
            or gate_lock.get("forward_protocol_sha256")
            != protocol.get("protocol_sha256")
            or gate_lock.get("observer_implementation_lock_sha256")
            != implementation_lock.get("implementation_lock_sha256")
        ):
            raise ValueError("diversified forward gate lock lineage differs")
        gatekeeper_phase = str(gatekeeper_health.get("phase", "unknown"))
        if (
            gatekeeper_health.get("service")
            != "diversified_forward_gatekeeper_v1"
            or gatekeeper_health.get("research_only") is not True
            or gatekeeper_health.get(
                "pre_cutoff_economic_metrics_calculated"
            )
            is not False
            or gatekeeper_phase
            not in {
                "waiting_for_cutoff",
                "waiting_for_complete_evidence",
                "official_evaluation_running",
                "official_evaluation_complete",
                "official_evaluation_failed_closed",
                "readiness_failed_closed",
            }
        ):
            raise ValueError("diversified forward gatekeeper mode differs")
        gatekeeper_healthy = gatekeeper_health.get("status") == "healthy"
    official_records = int(health.get("official_records", 0) or 0)
    warmup_records = int(health.get("warmup_records", 0) or 0)
    decision_records = int(health.get("decision_records", 0) or 0)
    timeline = protocol.get("timeline", {})
    first_bar = datetime.date.fromisoformat(
        str(timeline["official_first_bar_open_utc"])[:10]
    )
    warmup_start = datetime.date.fromisoformat(
        str(timeline["warmup_start_bar_utc"])[:10]
    )
    warmup_required = (first_bar - warmup_start).days
    minimum_days = int(timeline.get("minimum_calendar_days", 180) or 180)
    minimum_observed = int(
        protocol.get("forward_gate", {}).get("minimum_observed_days", 165)
        or 165
    )
    observer_healthy = health.get("status") == "healthy"
    healthy = observer_healthy and gatekeeper_healthy
    blockers = []
    if phase == "warmup":
        blockers.append(
            {
                "id": "official_start",
                "detail": (
                    "Il campione economico parte il "
                    f"{first_bar.isoformat()}; il warm-up non conta."
                ),
            }
        )
    if official_records < minimum_observed:
        blockers.append(
            {
                "id": "observed_days",
                "detail": (
                    f"{official_records} / {minimum_observed} giorni "
                    "forward osservati minimi"
                ),
            }
        )
    if not health.get("gate_calendar_complete"):
        gate_at = str(
            timeline.get("earliest_gate_evaluation_not_before_utc", "-")
        )
        blockers.append(
            {
                "id": "calendar_cutoff",
                "detail": (
                    "Valutazione non prima del "
                    f"{gate_at[:16]} UTC"
                ),
            }
        )
    if not observer_healthy:
        blockers.append(
            {
                "id": "observer_health",
                "detail": str(health.get("error", "observer non healthy")),
            }
        )
    if gatekeeper_available and not gatekeeper_healthy:
        blockers.append(
            {
                "id": "gatekeeper_health",
                "detail": str(
                    gatekeeper_health.get(
                        "detail", "gatekeeper non healthy"
                    )
                ),
            }
        )
    storage = health.get("storage_bytes", {})
    if not isinstance(storage, dict):
        storage = {}
    latest = _diversified_latest_metrics(
        latest_record or {},
        protocol.get("protocol_sha256"),
        implementation_lock.get("implementation_lock_sha256"),
    )
    return {
        "available": True,
        "healthy": healthy,
        "color": "info" if healthy else "danger",
        "phase": phase,
        "phase_label": "WARM-UP" if phase == "warmup" else "FORWARD OOS",
        "configuration_id": "trend50_cointegration50",
        "trend_weight_pct": 50.0,
        "cointegration_weight_pct": 50.0,
        "warmup_records": warmup_records,
        "warmup_required": warmup_required,
        "official_records": official_records,
        "minimum_days": minimum_days,
        "minimum_observed": minimum_observed,
        "decision_records": decision_records,
        "progress_pct": min(100.0, 100.0 * official_records / minimum_days),
        "last_archived_bar": health.get("last_archived_bar"),
        "latest_mature_bar": health.get("latest_mature_bar"),
        "official_start": first_bar.isoformat(),
        "earliest_gate": timeline.get(
            "earliest_gate_evaluation_not_before_utc"
        ),
        "protocol_sha256": protocol.get("protocol_sha256"),
        "implementation_lock_sha256": implementation_lock.get(
            "implementation_lock_sha256"
        ),
        "gatekeeper_available": gatekeeper_available,
        "gatekeeper_healthy": gatekeeper_healthy,
        "gatekeeper_phase": gatekeeper_phase,
        "gate_lock_sha256": gate_lock.get("gate_lock_sha256"),
        "last_market_record_hash": health.get("last_market_record_hash"),
        "last_journal_hash": health.get("last_journal_hash"),
        "storage_megabytes": sum(
            int(value or 0) for value in storage.values()
        )
        / (1024 * 1024),
        "blockers": blockers,
        "latest": latest,
        "gate_evaluation_authorized": False,
        "orders_authorized": False,
    }


def _diversified_latest_metrics(
    record: dict,
    protocol_sha256: str | None,
    implementation_lock_sha256: str | None,
) -> dict:
    if not record:
        return {"available": False, "allocations": []}
    payload = record.get("decision_payload")
    if not isinstance(payload, dict):
        raise ValueError("diversified latest record has no decision payload")
    for field in (
        "orders_authorized",
        "paper_orders_authorized",
        "automatic_promotion",
        "credentials_used",
    ):
        if payload.get(field) is not False:
            raise ValueError(
                f"diversified latest decision safety invariant differs: {field}"
            )
    lineage = payload.get("lineage", {})
    if (
        not isinstance(lineage, dict)
        or lineage.get("forward_protocol_sha256") != protocol_sha256
        or lineage.get("implementation_lock_sha256")
        != implementation_lock_sha256
    ):
        raise ValueError("diversified latest decision lineage differs")
    base = payload.get("base", {})
    stress = payload.get("stress_3x_cost", {})
    targets = payload.get("research_targets", {})
    if not all(isinstance(value, dict) for value in (base, stress, targets)):
        raise ValueError("diversified latest decision metrics are incomplete")
    try:
        base_equity = float(base["portfolio_equity"])
        base_daily_return = float(base["portfolio_daily_return"])
        stress_equity = float(stress["portfolio_equity"])
        stress_daily_return = float(stress["portfolio_daily_return"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("diversified latest numeric metrics are invalid") from error
    if not all(
        math.isfinite(value)
        for value in (
            base_equity,
            base_daily_return,
            stress_equity,
            stress_daily_return,
        )
    ):
        raise ValueError("diversified latest metrics are not finite")

    combined_weights: dict[str, float] = {}
    for field in (
        "trend_effective_portfolio_weights",
        "cointegration_effective_portfolio_weights",
    ):
        weights = targets.get(field, {})
        if not isinstance(weights, dict):
            raise ValueError("diversified latest weights are invalid")
        for symbol, raw_weight in weights.items():
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError) as error:
                raise ValueError("diversified latest weight is invalid") from error
            if not math.isfinite(weight):
                raise ValueError("diversified latest weight is not finite")
            combined_weights[str(symbol)] = (
                combined_weights.get(str(symbol), 0.0) + weight
            )
    allocations = [
        {
            "symbol": symbol,
            "side": "LONG" if weight > 0 else "SHORT",
            "weight_pct": 100.0 * weight,
        }
        for symbol, weight in combined_weights.items()
        if abs(weight) > 1e-12
    ]
    allocations.sort(key=lambda value: abs(value["weight_pct"]), reverse=True)
    return {
        "available": True,
        "bar_date": payload.get("bar_date"),
        "target_bar": payload.get("target_return_bearing_bar"),
        "base_equity": base_equity,
        "base_return_pct": 100.0 * (base_equity - 1.0),
        "base_daily_return_pct": 100.0 * base_daily_return,
        "stress_equity": stress_equity,
        "stress_return_pct": 100.0 * (stress_equity - 1.0),
        "stress_daily_return_pct": 100.0 * stress_daily_return,
        "allocations": allocations,
        "gross_weight_pct": sum(
            abs(value["weight_pct"]) for value in allocations
        ),
    }


def _diversified_paper_summary(health: dict) -> dict:
    if not health:
        return {"available": False}
    if (
        health.get("status") != "healthy"
        or health.get("mode")
        != "diversified_trend_cointegration_manual_paper_v1"
        or health.get("paper_only") is not True
        or health.get("public_data_only") is not True
        or health.get("network_required") is not False
        or health.get("credentials_used") is not False
        or health.get("orders_authorized") is not False
        or health.get("paper_orders_authorized") is not True
        or health.get("automatic_promotion") is not False
        or health.get("upstream_observer_remains_orderless") is not True
        or health.get("prior_forward_return_credited") is not False
        or health.get("database_integrity") != "ok"
    ):
        raise ValueError("diversified manual paper invariant differs")
    phase = str(health.get("phase", "unknown"))
    if phase not in {"armed_waiting_next_decision", "active"}:
        raise ValueError("diversified manual paper phase differs")
    numeric_fields = (
        "initial_equity",
        "paper_equity",
        "paper_return_pct",
        "paper_pnl",
        "gross_weight_pct",
        "net_weight_pct",
    )
    numbers = {}
    for field in numeric_fields:
        try:
            numbers[field] = float(health[field])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"diversified manual paper {field} is invalid"
            ) from error
        if not math.isfinite(numbers[field]):
            raise ValueError(
                f"diversified manual paper {field} is not finite"
            )
    positions = health.get("positions", [])
    if not isinstance(positions, list):
        raise ValueError("diversified manual paper positions are invalid")
    return {
        "available": True,
        "healthy": True,
        "phase": phase,
        "phase_label": (
            "ARMATO" if phase == "armed_waiting_next_decision" else "ATTIVO"
        ),
        **numbers,
        "position_count": int(health.get("position_count", 0) or 0),
        "decision_count": int(health.get("decision_count", 0) or 0),
        "order_event_count": int(health.get("order_event_count", 0) or 0),
        "activation_boundary_bar": health.get("activation_boundary_bar"),
        "last_processed_bar": health.get("last_processed_bar"),
        "positions": positions,
        "last_success_at": health.get("last_success_at"),
        "orders_authorized": False,
        "paper_orders_authorized": True,
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


def _register_legacy_dashboard(blueprint):
    """Kept as an implementation archive; the compact dashboard is below."""
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
        diversified_forward_health_path = pathlib.Path(
            os.getenv(
                "DIVERSIFIED_FORWARD_HEALTH_PATH",
                DEFAULT_DIVERSIFIED_FORWARD_HEALTH_PATH,
            )
        )
        diversified_forward_lock_path = pathlib.Path(
            os.getenv(
                "DIVERSIFIED_FORWARD_LOCK_PATH",
                DEFAULT_DIVERSIFIED_FORWARD_LOCK_PATH,
            )
        )
        diversified_forward_gate_lock_path = pathlib.Path(
            os.getenv(
                "DIVERSIFIED_FORWARD_GATE_LOCK_PATH",
                DEFAULT_DIVERSIFIED_FORWARD_GATE_LOCK_PATH,
            )
        )
        diversified_forward_gatekeeper_health_path = pathlib.Path(
            os.getenv(
                "DIVERSIFIED_FORWARD_GATEKEEPER_HEALTH_PATH",
                DEFAULT_DIVERSIFIED_FORWARD_GATEKEEPER_HEALTH_PATH,
            )
        )
        diversified_forward_protocol_path = pathlib.Path(
            os.getenv(
                "DIVERSIFIED_FORWARD_PROTOCOL_PATH",
                DEFAULT_DIVERSIFIED_FORWARD_PROTOCOL_PATH,
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
        try:
            diversified_forward = _diversified_forward_summary(
                _read_json(diversified_forward_health_path),
                _read_json(diversified_forward_protocol_path),
                _read_json(diversified_forward_lock_path),
                _read_json(diversified_forward_gate_lock_path),
                _read_json(diversified_forward_gatekeeper_health_path),
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            diversified_forward = {"available": False}
            errors.append(f"diversified_forward: {error}")
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
            diversified_forward=diversified_forward,
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


def register(blueprint):
    @blueprint.route("/strategy_status")
    @login.login_required_when_activated
    def strategy_status():
        errors = []

        def load_json(path: pathlib.Path, label: str) -> dict:
            try:
                return _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"{label}: {error}")
                return {}

        def load_last_jsonl(path: pathlib.Path, label: str) -> dict:
            try:
                return _read_last_jsonl(path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"{label}: {error}")
                return {}

        def load_jsonl(path: pathlib.Path, label: str) -> list[dict]:
            try:
                return _read_jsonl(path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"{label}: {error}")
                return []

        database_path = os.getenv(
            "AI_DECISIONS_DB_PATH", DEFAULT_AI_DECISIONS_DB_PATH
        )
        shadow_root = pathlib.Path(
            os.getenv("SHADOW_STATUS_ROOT", DEFAULT_SHADOW_ROOT)
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

        market_health = load_json(
            shadow_root / "market" / "health.json", "market collector"
        )
        market_evidence = load_json(
            shadow_root / "market" / "evidence.json", "market evidence"
        )
        data_quality = load_json(
            shadow_root / "operations" / "current.json",
            "operations report",
        )
        scalping_health = load_json(
            pathlib.Path(
                os.getenv(
                    "SCALPING_HEALTH_PATH", DEFAULT_SCALPING_HEALTH_PATH
                )
            ),
            "Level-5 collector",
        )

        try:
            execution_shadow = _execution_shadow_summary(
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "EXECUTION_SHADOW_HEALTH_PATH",
                            DEFAULT_EXECUTION_SHADOW_HEALTH_PATH,
                        )
                    ),
                    "execution shadow",
                )
            )
        except (TypeError, ValueError) as error:
            execution_shadow = {"available": False}
            errors.append(f"execution shadow: {error}")

        try:
            cross_venue = _cross_venue_summary(
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "CROSS_VENUE_HEALTH_PATH",
                            DEFAULT_CROSS_VENUE_HEALTH_PATH,
                        )
                    ),
                    "cross-venue collector",
                )
            )
        except (TypeError, ValueError) as error:
            cross_venue = {"available": False}
            errors.append(f"cross-venue collector: {error}")

        carry_protocol = load_json(
            pathlib.Path(
                os.getenv(
                    "CARRY_PROTOCOL_PATH", DEFAULT_CARRY_PROTOCOL_PATH
                )
            ),
            "Carry protocol",
        )
        try:
            carry_gatekeeper = _carry_gatekeeper_summary(
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "CARRY_GATEKEEPER_STATUS_PATH",
                            DEFAULT_CARRY_GATEKEEPER_STATUS_PATH,
                        )
                    ),
                    "Carry gatekeeper",
                )
            )
        except (TypeError, ValueError) as error:
            carry_gatekeeper = {"available": False}
            errors.append(f"Carry gatekeeper: {error}")
        carry_protocol_status = forward_carry_dashboard.protocol_status(
            carry_protocol
        )
        carry = forward_carry_dashboard.readiness_summary(
            market_evidence,
            market_health,
            carry_protocol_status,
        )

        diversified_protocol = load_json(
            pathlib.Path(
                os.getenv(
                    "DIVERSIFIED_FORWARD_PROTOCOL_PATH",
                    DEFAULT_DIVERSIFIED_FORWARD_PROTOCOL_PATH,
                )
            ),
            "diversified protocol",
        )
        diversified_lock = load_json(
            pathlib.Path(
                os.getenv(
                    "DIVERSIFIED_FORWARD_LOCK_PATH",
                    DEFAULT_DIVERSIFIED_FORWARD_LOCK_PATH,
                )
            ),
            "diversified lock",
        )
        diversified_decisions = load_jsonl(
            pathlib.Path(
                os.getenv(
                    "DIVERSIFIED_FORWARD_DECISIONS_PATH",
                    DEFAULT_DIVERSIFIED_FORWARD_DECISIONS_PATH,
                )
            ),
            "diversified decisions",
        )
        try:
            diversified_forward = _diversified_forward_summary(
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "DIVERSIFIED_FORWARD_HEALTH_PATH",
                            DEFAULT_DIVERSIFIED_FORWARD_HEALTH_PATH,
                        )
                    ),
                    "diversified observer",
                ),
                diversified_protocol,
                diversified_lock,
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "DIVERSIFIED_FORWARD_GATE_LOCK_PATH",
                            DEFAULT_DIVERSIFIED_FORWARD_GATE_LOCK_PATH,
                        )
                    ),
                    "diversified gate lock",
                ),
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "DIVERSIFIED_FORWARD_GATEKEEPER_HEALTH_PATH",
                            DEFAULT_DIVERSIFIED_FORWARD_GATEKEEPER_HEALTH_PATH,
                        )
                    ),
                    "diversified gatekeeper",
                ),
                diversified_decisions[-1] if diversified_decisions else {},
            )
        except (KeyError, TypeError, ValueError) as error:
            diversified_forward = {"available": False}
            errors.append(f"diversified observer: {error}")

        diversified_paper_health = load_json(
            pathlib.Path(
                os.getenv(
                    "DIVERSIFIED_PAPER_HEALTH_PATH",
                    DEFAULT_DIVERSIFIED_PAPER_HEALTH_PATH,
                )
            ),
            "diversified manual paper",
        )
        try:
            diversified_paper = _diversified_paper_summary(
                diversified_paper_health
            )
        except (KeyError, TypeError, ValueError) as error:
            diversified_paper = {"available": False}
            errors.append(f"diversified manual paper: {error}")

        try:
            diversified_chart = _diversified_equity_chart(
                diversified_decisions,
                diversified_protocol.get("protocol_sha256"),
                diversified_lock.get("implementation_lock_sha256"),
                diversified_paper,
                os.getenv(
                    "DIVERSIFIED_PAPER_DB_PATH",
                    DEFAULT_DIVERSIFIED_PAPER_DB_PATH,
                ),
            )
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ) as error:
            diversified_chart = {"available": False}
            errors.append(f"diversified chart: {error}")

        try:
            breadth_forward = _breadth_forward_summary(
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "BREADTH_FORWARD_HEALTH_PATH",
                            DEFAULT_BREADTH_FORWARD_HEALTH_PATH,
                        )
                    ),
                    "breadth observer",
                ),
                load_json(
                    pathlib.Path(
                        os.getenv(
                            "BREADTH_FORWARD_LOCK_PATH",
                            DEFAULT_BREADTH_FORWARD_LOCK_PATH,
                        )
                    ),
                    "breadth lock",
                ),
            )
        except (TypeError, ValueError) as error:
            breadth_forward = {"available": False}
            errors.append(f"breadth observer: {error}")

        return flask.render_template(
            "strategy_status.html",
            latest_decision=latest_decision,
            orders=orders,
            positions=positions,
            operational=_operational_summary(
                latest_decision, orders, positions
            ),
            market_health=market_health,
            evidence=market_evidence,
            cross_venue=cross_venue,
            scalping_health=scalping_health,
            scalping_summary=_scalping_summary(scalping_health),
            execution_shadow=execution_shadow,
            carry=carry,
            carry_gatekeeper=carry_gatekeeper,
            diversified_forward=diversified_forward,
            diversified_paper=diversified_paper,
            diversified_chart=diversified_chart,
            breadth_forward=breadth_forward,
            data_quality=data_quality,
            errors=errors,
        )

    @blueprint.route("/research_archive")
    @login.login_required_when_activated
    def research_archive():
        return flask.render_template("research_archive.html")

    @blueprint.route("/research_archive/history")
    @login.login_required_when_activated
    def project_history():
        path = pathlib.Path(
            os.getenv("PROJECT_HISTORY_PATH", DEFAULT_PROJECT_HISTORY_PATH)
        )
        if not path.is_file():
            flask.abort(404)
        return flask.send_file(
            path,
            mimetype="text/markdown",
            as_attachment=False,
            download_name="HISTORY.md",
        )

    @blueprint.route("/research_archive/migration_audit")
    @login.login_required_when_activated
    def migration_audit():
        path = pathlib.Path(
            os.getenv("MIGRATION_AUDIT_PATH", DEFAULT_MIGRATION_AUDIT_PATH)
        )
        if not path.is_file():
            flask.abort(404)
        return flask.send_file(
            path,
            mimetype="text/markdown",
            as_attachment=False,
            download_name="MIGRATION_AUDIT_2026-09-02.md",
        )
