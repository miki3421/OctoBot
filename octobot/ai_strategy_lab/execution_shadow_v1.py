"""Orderless forward shadow for the locked BTC passive-execution model.

Predictions are append-only and must be recorded within fifteen seconds of a
quarter-hour decision.  Outcomes are stored in a separate append-only table
only after their full simulation horizon has matured.  Late predictions are
permanently marked missed rather than reconstructed.  This module has no
exchange client, credentials, or order path.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import fcntl
import json
import math
import pathlib
import sqlite3
import time
import typing

import numpy

from octobot.ai_strategy_lab import maker_execution_locked_v2 as locked_v2
from octobot.ai_strategy_lab import maker_execution_v1 as v1
from octobot.ai_strategy_lab import maker_execution_v2 as v2


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "btc_futures_learned_passive_execution_forward_shadow_v1"
PREREGISTRATION_DATE = "2026-08-28"

LOCK_PROTOCOL_SHA256 = (
    "0d6c1cd814799280358c350f9bec6917fb61f1e92e4c3a42842e5ffc5310789e"
)
LOCK_REPORT_SHA256 = (
    "bd6c85f0091050b95a2e7dc17e23a9038d6b355b62d893a8fb105d0068219fee"
)
LOCK_MANIFEST_FILE_SHA256 = (
    "0164c0c87fa5bb263895e0b584febbe90105307a2fb3be7938cf28bcc53e50d8"
)
LOCK_MANIFEST_CONTENT_SHA256 = (
    "3c638f8ab3598260d5540d9a267b4b4a629598a52231e18a144e2f3b76c58791"
)
FEE_AUDIT_FILE_SHA256 = (
    "f08259a4c893d463cf4fd7c9c48c19bb3b1cc8e7d9b08f3a006c7840ca41643f"
)
FEE_AUDIT_CONTENT_SHA256 = (
    "6979eb6f00009d06450a3fbd7748e73d62a780276b8800ac2a0436832398b711"
)
MODEL_SHA256 = locked_v2.PARENT_MODEL_SHA256

PREDICTION_READY_SECONDS = 2
PREDICTION_DEADLINE_SECONDS = 15
OUTCOME_MATURITY_SECONDS = 125
OUTCOME_DEADLINE_SECONDS = 180
FORWARD_DAYS = 30
COLLECTOR_MAX_AGE_SECONDS = 15


def _iso_ns(value: int) -> str:
    return datetime.datetime.fromtimestamp(
        value / 1_000_000_000, tz=datetime.timezone.utc
    ).isoformat()


def _parse_forward_start(value: str) -> tuple[int, str]:
    start_ns = v1._epoch_ns(value)
    stride_ns = v1.DECISION_STRIDE_SECONDS * 1_000_000_000
    if start_ns % stride_ns:
        raise ValueError("forward start must be aligned to a UTC quarter hour")
    return start_ns, _iso_ns(start_ns)


def frozen_protocol(forward_start: str) -> dict:
    start_ns, normalized_start = _parse_forward_start(forward_start)
    end_ns = start_ns + FORWARD_DAYS * 86_400 * 1_000_000_000
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_orderless_forward_shadow_protocol",
        "mode": "execution_shadow_only",
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "directional_alpha_claim": False,
        "evidence": {
            "locked_protocol_sha256": LOCK_PROTOCOL_SHA256,
            "locked_report_sha256": LOCK_REPORT_SHA256,
            "locked_manifest_file_sha256": LOCK_MANIFEST_FILE_SHA256,
            "locked_manifest_content_sha256": LOCK_MANIFEST_CONTENT_SHA256,
            "fee_audit_file_sha256": FEE_AUDIT_FILE_SHA256,
            "fee_audit_content_sha256": FEE_AUDIT_CONTENT_SHA256,
            "model_sha256": MODEL_SHA256,
        },
        "source": {
            "exchange": "kucoin",
            "symbol": "XBTUSDTM",
            "database_open_mode": "read-only live WAL",
            "second_collector_authorized": False,
            "raw_data_copy_authorized": False,
            "collector_max_age_seconds": COLLECTOR_MAX_AGE_SECONDS,
        },
        "prediction": {
            "schedule": "each UTC quarter hour, buy and sell",
            "forward_start": normalized_start,
            "forward_end_exclusive": _iso_ns(end_ns),
            "feature_ready_seconds": PREDICTION_READY_SECONDS,
            "deadline_seconds": PREDICTION_DEADLINE_SECONDS,
            "late_action": "append permanent MISSED record; never backfill",
            "feature_names": list(v2.FEATURE_NAMES),
            "minimum_predicted_fill_probability": (
                v2.MINIMUM_PREDICTED_FILL_PROBABILITY
            ),
            "minimum_expected_saving_bps_strict": (
                v2.EXPECTED_SAVING_THRESHOLD_BPS
            ),
            "model_refit": False,
        },
        "outcome": {
            "earliest_materialization_seconds": OUTCOME_MATURITY_SECONDS,
            "finalization_deadline_seconds": OUTCOME_DEADLINE_SECONDS,
            "tables_separate_from_predictions": True,
            "primary_policy_unchanged": True,
            "frozen_stress_policy_unchanged": True,
            "fee_neutral_stress_identity": (
                "frozen stress saving minus 2 bps for each maker fill"
            ),
        },
        "journal": {
            "format": "sqlite",
            "append_only": True,
            "updates_forbidden": True,
            "deletes_forbidden": True,
            "hash_chained_by_table": True,
            "raw_book_or_trade_rows_stored": False,
        },
        "official_forward_gate": {
            "observation_days": FORWARD_DAYS,
            "one_time_cutoff": _iso_ns(end_ns),
            "minimum_prediction_coverage": 0.95,
            "minimum_outcome_coverage": 0.95,
            "minimum_valid_predictions": 1_200,
            "minimum_selected_attempts": 300,
            "minimum_selected_attempts_per_side": 100,
            "minimum_selected_pct": 10.0,
            "maximum_selected_pct": 60.0,
            "minimum_selected_fill_rate": 0.10,
            "minimum_fill_auc": 0.52,
            "fill_brier_better_than_constant": True,
            "minimum_primary_mean_saving_bps": 0.25,
            "primary_each_side_strictly_positive": True,
            "minimum_positive_operating_days_pct": 50.0,
            "bootstrap_lower_mean_saving_bps_strictly_positive": True,
            "fee_neutral_stress_strictly_positive": True,
            "fee_neutral_stress_each_side_strictly_positive": True,
            "all_checks_conjunctive": True,
            "verdict_is_latched": True,
        },
        "advancement_consequence": (
            "a pass permits only later paper integration with an independently "
            "validated parent signal; no autonomous or real orders"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
    forward_start: str,
    *,
    now_ns: int | None = None,
) -> dict:
    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol(forward_start)
    payload = {**protocol, "protocol_sha256": v2._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted execution-shadow protocol differs")
        return persisted
    current_ns = time.time_ns() if now_ns is None else int(now_ns)
    start_ns = v1._epoch_ns(protocol["prediction"]["forward_start"])
    if start_ns <= current_ns:
        raise ValueError("new forward protocol must start in the future")
    v2._atomic_json(path, payload)
    return payload


@dataclasses.dataclass(frozen=True)
class ShadowConfig:
    protocol_path: pathlib.Path
    model_path: pathlib.Path
    locked_report_path: pathlib.Path
    locked_manifest_path: pathlib.Path
    fee_audit_path: pathlib.Path
    source_database_path: pathlib.Path
    collector_health_path: pathlib.Path
    journal_path: pathlib.Path
    health_path: pathlib.Path
    lock_path: pathlib.Path
    evaluation_path: pathlib.Path

    def validate(self) -> None:
        paths = dataclasses.asdict(self)
        if len({str(value.resolve()) for value in paths.values()}) != len(paths):
            raise ValueError("execution-shadow paths must be distinct")
        if self.source_database_path.resolve() == self.journal_path.resolve():
            raise ValueError("source and shadow journal must be different")


def _verify_evidence(config: ShadowConfig, protocol: dict) -> v2.ExecutionModel:
    expected = {
        config.model_path: MODEL_SHA256,
        config.locked_report_path: LOCK_REPORT_SHA256,
        config.locked_manifest_path: LOCK_MANIFEST_FILE_SHA256,
        config.fee_audit_path: FEE_AUDIT_FILE_SHA256,
    }
    for path, digest in expected.items():
        if not path.is_file() or v2._sha256(path) != digest:
            raise ValueError(f"execution-shadow evidence differs: {path.name}")
    report = json.loads(config.locked_report_path.read_text(encoding="utf-8"))
    manifest = json.loads(
        config.locked_manifest_path.read_text(encoding="utf-8")
    )
    audit = json.loads(config.fee_audit_path.read_text(encoding="utf-8"))
    locked_v2._verify_content_manifest(manifest)
    checks = (
        protocol["evidence"]["model_sha256"] == MODEL_SHA256,
        report.get("protocol_sha256") == LOCK_PROTOCOL_SHA256,
        report.get("verdict")
        == "LOCKED_PASS_EXECUTION_OVERLAY_SHADOW_ELIGIBLE",
        report.get("locked_test", {}).get("gate", {}).get("passed") is True,
        report.get("orders_authorized") is False,
        report.get("paper_orders_authorized") is False,
        manifest.get("content_sha256") == LOCK_MANIFEST_CONTENT_SHA256,
        manifest.get("parent_model_sha256") == MODEL_SHA256,
        audit.get("content_sha256") == FEE_AUDIT_CONTENT_SHA256,
        audit.get("new_market_rows_queried") is False,
        audit.get("finding", {}).get("per_side_stress_robustness_demonstrated")
        is False,
    )
    if not all(checks):
        raise ValueError("execution-shadow advancement evidence differs")
    model = v2._load_model(config.model_path)
    if tuple(model.logistic.feature_names) != v2.FEATURE_NAMES:
        raise ValueError("execution-shadow model feature schema differs")
    return model


def _open_source(path: pathlib.Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro", uri=True, timeout=5
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    required = {"book_events", "trade_events", "scalping_sessions"}
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not required.issubset(present):
        connection.close()
        raise ValueError("execution-shadow source schema is incomplete")
    return connection


def _open_journal(path: pathlib.Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_ns INTEGER NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('buy','sell')),
            recorded_at_ns INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PREDICTED','MISSED')),
            reason TEXT,
            features_json TEXT,
            features_sha256 TEXT,
            fill_probability REAL,
            predicted_fallback_saving_bps REAL,
            expected_saving_bps REAL,
            selected INTEGER CHECK(selected IN (0,1)),
            model_sha256 TEXT NOT NULL,
            previous_record_hash TEXT,
            record_hash TEXT NOT NULL UNIQUE,
            UNIQUE(decision_ns, side)
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_ns INTEGER NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('buy','sell')),
            decision_record_hash TEXT NOT NULL,
            recorded_at_ns INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('COMPLETED','INCOMPLETE')),
            reason TEXT,
            primary_filled INTEGER CHECK(primary_filled IN (0,1)),
            primary_saving_bps REAL,
            stress_filled INTEGER CHECK(stress_filled IN (0,1)),
            stress_saving_bps REAL,
            fee_neutral_stress_saving_bps REAL,
            previous_record_hash TEXT,
            record_hash TEXT NOT NULL UNIQUE,
            UNIQUE(decision_ns, side),
            FOREIGN KEY(decision_record_hash) REFERENCES decisions(record_hash)
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY CHECK(id=1),
            cutoff_ns INTEGER NOT NULL,
            recorded_at_ns INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        );
        CREATE TRIGGER IF NOT EXISTS metadata_no_update
        BEFORE UPDATE ON metadata BEGIN SELECT RAISE(ABORT, 'append-only metadata'); END;
        CREATE TRIGGER IF NOT EXISTS metadata_no_delete
        BEFORE DELETE ON metadata BEGIN SELECT RAISE(ABORT, 'append-only metadata'); END;
        CREATE TRIGGER IF NOT EXISTS decisions_no_update
        BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT, 'append-only decisions'); END;
        CREATE TRIGGER IF NOT EXISTS decisions_no_delete
        BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT, 'append-only decisions'); END;
        CREATE TRIGGER IF NOT EXISTS outcomes_no_update
        BEFORE UPDATE ON outcomes BEGIN SELECT RAISE(ABORT, 'append-only outcomes'); END;
        CREATE TRIGGER IF NOT EXISTS outcomes_no_delete
        BEFORE DELETE ON outcomes BEGIN SELECT RAISE(ABORT, 'append-only outcomes'); END;
        CREATE TRIGGER IF NOT EXISTS evaluations_no_update
        BEFORE UPDATE ON evaluations BEGIN SELECT RAISE(ABORT, 'append-only evaluations'); END;
        CREATE TRIGGER IF NOT EXISTS evaluations_no_delete
        BEFORE DELETE ON evaluations BEGIN SELECT RAISE(ABORT, 'append-only evaluations'); END;
        """
    )
    connection.commit()
    return connection


def _initialize_metadata(connection: sqlite3.Connection, protocol: dict) -> None:
    expected = {
        "schema_version": str(SCHEMA_VERSION),
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "model_sha256": MODEL_SHA256,
        "lock_report_sha256": LOCK_REPORT_SHA256,
        "fee_audit_sha256": FEE_AUDIT_FILE_SHA256,
        "forward_start": protocol["prediction"]["forward_start"],
        "forward_end_exclusive": protocol["prediction"][
            "forward_end_exclusive"
        ],
        "orders_authorized": "false",
        "paper_orders_authorized": "false",
    }
    rows = {
        str(row["key"]): str(row["value"])
        for row in connection.execute("SELECT key, value FROM metadata")
    }
    if rows:
        if rows != expected:
            raise ValueError("execution-shadow journal metadata differs")
        return
    for key, value in expected.items():
        record_hash = v2._json_hash({"key": key, "value": value})
        connection.execute(
            "INSERT INTO metadata(key,value,record_hash) VALUES(?,?,?)",
            (key, value, record_hash),
        )
    connection.commit()


def _last_hash(connection: sqlite3.Connection, table: str) -> str | None:
    if table not in {"decisions", "outcomes"}:
        raise ValueError("unsupported execution-shadow chain")
    row = connection.execute(
        f"SELECT record_hash FROM {table} ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else None


def _append_decision(
    connection: sqlite3.Connection,
    *,
    decision_ns: int,
    side: str,
    recorded_at_ns: int,
    status: str,
    reason: str | None,
    features: numpy.ndarray | None,
    fill_probability: float | None,
    predicted_fallback: float | None,
    expected_saving: float | None,
    selected: bool | None,
) -> str:
    features_json = (
        json.dumps(features.tolist(), separators=(",", ":"), allow_nan=False)
        if features is not None
        else None
    )
    previous = _last_hash(connection, "decisions")
    payload = {
        "decision_ns": decision_ns,
        "side": side,
        "recorded_at_ns": recorded_at_ns,
        "status": status,
        "reason": reason,
        "features_json": features_json,
        "features_sha256": (
            v2._json_hash(features.tolist()) if features is not None else None
        ),
        "fill_probability": fill_probability,
        "predicted_fallback_saving_bps": predicted_fallback,
        "expected_saving_bps": expected_saving,
        "selected": int(selected) if selected is not None else None,
        "model_sha256": MODEL_SHA256,
        "previous_record_hash": previous,
    }
    record_hash = v2._json_hash(payload)
    connection.execute(
        """
        INSERT INTO decisions(
            decision_ns,side,recorded_at_ns,status,reason,features_json,
            features_sha256,fill_probability,predicted_fallback_saving_bps,
            expected_saving_bps,selected,model_sha256,previous_record_hash,
            record_hash
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            decision_ns,
            side,
            recorded_at_ns,
            status,
            reason,
            features_json,
            payload["features_sha256"],
            fill_probability,
            predicted_fallback,
            expected_saving,
            payload["selected"],
            MODEL_SHA256,
            previous,
            record_hash,
        ),
    )
    return record_hash


def _append_outcome(
    connection: sqlite3.Connection,
    decision: sqlite3.Row,
    *,
    recorded_at_ns: int,
    primary: dict,
    stress: dict,
) -> str:
    completed = bool(primary["completed"] and stress["completed"])
    status = "COMPLETED" if completed else "INCOMPLETE"
    reason = None if completed else (
        f"primary:{primary.get('exclusion')};stress:{stress.get('exclusion')}"
    )
    fee_neutral = None
    if completed:
        fee_neutral = float(stress["saving_bps"]) - (
            2.0 if stress["filled"] else 0.0
        )
    previous = _last_hash(connection, "outcomes")
    payload = {
        "decision_ns": int(decision["decision_ns"]),
        "side": str(decision["side"]),
        "decision_record_hash": str(decision["record_hash"]),
        "recorded_at_ns": recorded_at_ns,
        "status": status,
        "reason": reason,
        "primary_filled": int(primary["filled"]) if completed else None,
        "primary_saving_bps": (
            float(primary["saving_bps"]) if completed else None
        ),
        "stress_filled": int(stress["filled"]) if completed else None,
        "stress_saving_bps": (
            float(stress["saving_bps"]) if completed else None
        ),
        "fee_neutral_stress_saving_bps": fee_neutral,
        "previous_record_hash": previous,
    }
    record_hash = v2._json_hash(payload)
    connection.execute(
        """
        INSERT INTO outcomes(
            decision_ns,side,decision_record_hash,recorded_at_ns,status,reason,
            primary_filled,primary_saving_bps,stress_filled,stress_saving_bps,
            fee_neutral_stress_saving_bps,previous_record_hash,record_hash
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            payload["decision_ns"],
            payload["side"],
            payload["decision_record_hash"],
            recorded_at_ns,
            status,
            reason,
            payload["primary_filled"],
            payload["primary_saving_bps"],
            payload["stress_filled"],
            payload["stress_saving_bps"],
            fee_neutral,
            previous,
            record_hash,
        ),
    )
    return record_hash


def _read_collector_health(path: pathlib.Path, now_ns: int) -> tuple[dict, bool]:
    try:
        health = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, False
    invariants = (
        health.get("public_data_only") is True,
        health.get("credentials_used") is False,
        health.get("orders_authorized") is False,
        health.get("symbol") == "XBTUSDTM",
    )
    if not all(invariants):
        raise ValueError("execution-shadow collector safety invariant differs")
    try:
        last = datetime.datetime.fromisoformat(health["last_success_at"])
        if last.tzinfo is None:
            raise ValueError
        age = now_ns / 1_000_000_000 - last.timestamp()
    except (KeyError, TypeError, ValueError):
        return health, False
    healthy = (
        health.get("status") == "healthy"
        and health.get("connected") is True
        and health.get("database_operational") is True
        and -1.0 <= age <= COLLECTOR_MAX_AGE_SECONDS
    )
    return health, healthy


def _decision_range(protocol: dict, now_ns: int) -> list[int]:
    start = v1._epoch_ns(protocol["prediction"]["forward_start"])
    end = v1._epoch_ns(protocol["prediction"]["forward_end_exclusive"])
    upper = min(now_ns + 1, end)
    if upper <= start:
        return []
    return v1._decision_timestamps(start, upper)


def _process_predictions(
    source: sqlite3.Connection,
    journal: sqlite3.Connection,
    protocol: dict,
    model: v2.ExecutionModel,
    *,
    now_ns: int,
    collector_healthy: bool,
) -> dict:
    inserted = 0
    missed = 0
    existing = {
        (int(row["decision_ns"]), str(row["side"]))
        for row in journal.execute("SELECT decision_ns, side FROM decisions")
    }
    ready_ns = PREDICTION_READY_SECONDS * 1_000_000_000
    deadline_ns = PREDICTION_DEADLINE_SECONDS * 1_000_000_000
    for decision_ns in _decision_range(protocol, now_ns):
        missing_sides = [
            side
            for side in ("buy", "sell")
            if (decision_ns, side) not in existing
        ]
        if not missing_sides or now_ns < decision_ns + ready_ns:
            continue
        if now_ns > decision_ns + deadline_ns:
            for side in missing_sides:
                _append_decision(
                    journal,
                    decision_ns=decision_ns,
                    side=side,
                    recorded_at_ns=now_ns,
                    status="MISSED",
                    reason="prediction_deadline_missed",
                    features=None,
                    fill_probability=None,
                    predicted_fallback=None,
                    expected_saving=None,
                    selected=None,
                )
                missed += 1
            journal.commit()
            continue
        if not collector_healthy:
            continue
        window = v2._load_window(source, decision_ns)
        for side in missing_sides:
            features = v2._features(window, side)
            if features is None:
                continue
            probability, fallback, expected = model.predict(
                features.reshape(1, -1)
            )
            selected = bool(v2._selection(probability, expected)[0])
            _append_decision(
                journal,
                decision_ns=decision_ns,
                side=side,
                recorded_at_ns=now_ns,
                status="PREDICTED",
                reason=None,
                features=features,
                fill_probability=float(probability[0]),
                predicted_fallback=float(fallback[0]),
                expected_saving=float(expected[0]),
                selected=selected,
            )
            inserted += 1
        journal.commit()
    return {"predicted": inserted, "missed": missed}


def _process_outcomes(
    source: sqlite3.Connection,
    journal: sqlite3.Connection,
    *,
    now_ns: int,
) -> dict:
    pending = journal.execute(
        """
        SELECT d.* FROM decisions d
        LEFT JOIN outcomes o
          ON o.decision_ns=d.decision_ns AND o.side=d.side
        WHERE d.status='PREDICTED' AND o.id IS NULL
          AND d.decision_ns <= ?
        ORDER BY d.decision_ns, d.side
        """,
        (now_ns - OUTCOME_MATURITY_SECONDS * 1_000_000_000,),
    ).fetchall()
    completed = 0
    incomplete = 0
    windows: dict[int, v2.RichWindow] = {}
    for decision in pending:
        decision_ns = int(decision["decision_ns"])
        window = windows.get(decision_ns)
        if window is None:
            window = v2._load_window(source, decision_ns)
            windows[decision_ns] = window
        side = str(decision["side"])
        primary = v2._unconditional_outcome(window, side, v1.PRIMARY_POLICY)
        stress = v2._unconditional_outcome(window, side, v1.STRESS_POLICY)
        if not (primary["completed"] and stress["completed"]) and now_ns < (
            decision_ns + OUTCOME_DEADLINE_SECONDS * 1_000_000_000
        ):
            continue
        _append_outcome(
            journal,
            decision,
            recorded_at_ns=now_ns,
            primary=primary,
            stress=stress,
        )
        if primary["completed"] and stress["completed"]:
            completed += 1
        else:
            incomplete += 1
    journal.commit()
    return {"completed": completed, "incomplete": incomplete}


def _daily_metrics(
    protocol: dict,
    completed_rows: list[sqlite3.Row],
    value_column: str,
) -> dict:
    start = v1._epoch_ns(protocol["prediction"]["forward_start"])
    end = v1._epoch_ns(protocol["prediction"]["forward_end_exclusive"])
    by_key = {
        (int(row["decision_ns"]), str(row["side"])): (
            float(row[value_column]) if int(row["selected"]) else 0.0
        )
        for row in completed_rows
    }
    day_values: dict[int, list[float]] = {}
    for decision_ns in v1._decision_timestamps(start, end):
        day = decision_ns // (86_400 * 1_000_000_000)
        for side in ("buy", "sell"):
            day_values.setdefault(day, []).append(
                by_key.get((decision_ns, side), 0.0)
            )
    daily = numpy.asarray(
        [numpy.mean(day_values[day]) for day in sorted(day_values)],
        dtype=numpy.float64,
    )
    return {
        "calendar_days": len(daily),
        "positive_operating_days_pct": (
            100.0 * float(numpy.mean(daily > 0)) if len(daily) else 0.0
        ),
        "daily_bootstrap_lower_policy_saving_bps_90pct": (
            v2._bootstrap_lower(daily)
        ),
    }


def _metric_rows(rows: list[sqlite3.Row]) -> list[dict]:
    return [
        {
            "timestamp_ns": int(row["decision_ns"]),
            "side": str(row["side"]),
            "primary": {
                "filled": bool(row["primary_filled"]),
                "saving_bps": float(row["primary_saving_bps"]),
            },
            "stress": {
                "filled": bool(row["stress_filled"]),
                "saving_bps": float(row["stress_saving_bps"]),
            },
            "fee_neutral": {
                "filled": bool(row["stress_filled"]),
                "saving_bps": float(row["fee_neutral_stress_saving_bps"]),
            },
        }
        for row in rows
    ]


def _forward_gate(report: dict, protocol: dict) -> dict:
    gate = protocol["official_forward_gate"]
    source = report["source"]
    primary = report["primary"]
    fee_neutral = report["fee_neutral_stress"]
    calibration = report["fill_calibration"]
    checks = {
        "minimum_prediction_coverage": (
            source["prediction_coverage"] >= gate["minimum_prediction_coverage"]
        ),
        "minimum_outcome_coverage": (
            source["outcome_coverage"] >= gate["minimum_outcome_coverage"]
        ),
        "minimum_valid_predictions": (
            source["valid_predictions"] >= gate["minimum_valid_predictions"]
        ),
        "minimum_selected_attempts": (
            primary["selected_attempts"] >= gate["minimum_selected_attempts"]
        ),
        "minimum_selected_attempts_per_side": all(
            primary["by_side"][side]["selected_attempts"]
            >= gate["minimum_selected_attempts_per_side"]
            for side in ("buy", "sell")
        ),
        "minimum_selected_pct": (
            source["selected_pct"] >= gate["minimum_selected_pct"]
        ),
        "maximum_selected_pct": (
            source["selected_pct"] <= gate["maximum_selected_pct"]
        ),
        "minimum_selected_fill_rate": (
            primary["selected_fill_rate"]
            >= gate["minimum_selected_fill_rate"]
        ),
        "minimum_fill_auc": (
            calibration["auc"] is not None
            and calibration["auc"] >= gate["minimum_fill_auc"]
        ),
        "fill_brier_better_than_constant": (
            calibration["brier"] < calibration["constant_brier"]
        ),
        "minimum_primary_mean_saving_bps": (
            primary["mean_selected_saving_bps"] is not None
            and primary["mean_selected_saving_bps"]
            >= gate["minimum_primary_mean_saving_bps"]
        ),
        "primary_each_side_strictly_positive": all(
            primary["by_side"][side]["mean_selected_saving_bps"] is not None
            and primary["by_side"][side]["mean_selected_saving_bps"] > 0
            for side in ("buy", "sell")
        ),
        "minimum_positive_operating_days_pct": (
            primary["positive_operating_days_pct"]
            >= gate["minimum_positive_operating_days_pct"]
        ),
        "bootstrap_lower_mean_saving_bps_strictly_positive": (
            primary["daily_bootstrap_lower_policy_saving_bps_90pct"] is not None
            and primary["daily_bootstrap_lower_policy_saving_bps_90pct"] > 0
        ),
        "fee_neutral_stress_strictly_positive": (
            fee_neutral["mean_selected_saving_bps"] is not None
            and fee_neutral["mean_selected_saving_bps"] > 0
        ),
        "fee_neutral_stress_each_side_strictly_positive": all(
            fee_neutral["by_side"][side]["mean_selected_saving_bps"] is not None
            and fee_neutral["by_side"][side]["mean_selected_saving_bps"] > 0
            for side in ("buy", "sell")
        ),
    }
    return {
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "passed": all(checks.values()),
    }


def _materialize_evaluation(
    journal: sqlite3.Connection,
    protocol: dict,
    model: v2.ExecutionModel,
    evaluation_path: pathlib.Path,
    *,
    now_ns: int,
) -> dict | None:
    existing = journal.execute(
        "SELECT payload_json FROM evaluations WHERE id=1"
    ).fetchone()
    if existing:
        payload = json.loads(existing[0])
        if evaluation_path.is_file():
            persisted = json.loads(evaluation_path.read_text(encoding="utf-8"))
            if persisted != payload:
                raise ValueError("execution-shadow evaluation mirror differs")
        else:
            v2._atomic_json(evaluation_path, payload)
        return payload
    cutoff_ns = v1._epoch_ns(
        protocol["prediction"]["forward_end_exclusive"]
    )
    if now_ns < cutoff_ns + OUTCOME_DEADLINE_SECONDS * 1_000_000_000:
        return None
    expected = len(
        v1._decision_timestamps(
            v1._epoch_ns(protocol["prediction"]["forward_start"]), cutoff_ns
        )
    ) * 2
    counts = journal.execute(
        """
        SELECT
          SUM(CASE WHEN status='PREDICTED' THEN 1 ELSE 0 END) valid_predictions,
          SUM(CASE WHEN status='MISSED' THEN 1 ELSE 0 END) missed_predictions,
          SUM(CASE WHEN status='PREDICTED' AND selected=1 THEN 1 ELSE 0 END) selected
        FROM decisions WHERE decision_ns < ?
        """,
        (cutoff_ns,),
    ).fetchone()
    rows = journal.execute(
        """
        SELECT d.decision_ns,d.side,d.selected,d.fill_probability,
               o.primary_filled,o.primary_saving_bps,o.stress_filled,
               o.stress_saving_bps,o.fee_neutral_stress_saving_bps
        FROM decisions d JOIN outcomes o
          ON o.decision_ns=d.decision_ns AND o.side=d.side
        WHERE d.status='PREDICTED' AND o.status='COMPLETED'
          AND d.decision_ns < ?
        ORDER BY d.decision_ns,d.side
        """,
        (cutoff_ns,),
    ).fetchall()
    valid = int(counts["valid_predictions"] or 0)
    selected_count = int(counts["selected"] or 0)
    completed = len(rows)
    metric_rows = _metric_rows(rows)
    selected = numpy.asarray([bool(row["selected"]) for row in rows])
    if rows:
        primary = v2._economic_metrics(
            metric_rows, selected, outcome="primary"
        )
        stress = v2._economic_metrics(metric_rows, selected, outcome="stress")
        fee_neutral = v2._economic_metrics(
            metric_rows, selected, outcome="fee_neutral"
        )
        primary.update(_daily_metrics(protocol, rows, "primary_saving_bps"))
        fee_neutral.update(
            _daily_metrics(
                protocol, rows, "fee_neutral_stress_saving_bps"
            )
        )
        labels = numpy.asarray(
            [bool(row["primary_filled"]) for row in rows], dtype=numpy.bool_
        )
        probabilities = numpy.asarray(
            [float(row["fill_probability"]) for row in rows],
            dtype=numpy.float64,
        )
        constants = numpy.full(
            len(rows), model.training_fill_rate, dtype=numpy.float64
        )
        calibration = v2._calibration(labels, probabilities, constants)
    else:
        primary = stress = fee_neutral = {
            "selected_attempts": 0,
            "selected_fill_rate": 0.0,
            "mean_selected_saving_bps": None,
            "positive_operating_days_pct": 0.0,
            "daily_bootstrap_lower_policy_saving_bps_90pct": None,
            "by_side": {
                side: {"selected_attempts": 0, "mean_selected_saving_bps": None}
                for side in ("buy", "sell")
            },
        }
        calibration = {
            "auc": None,
            "brier": 1.0,
            "constant_brier": 0.0,
            "rows": 0,
        }
    report = {
        "source": {
            "expected_predictions": expected,
            "valid_predictions": valid,
            "missed_predictions": int(counts["missed_predictions"] or 0),
            "completed_outcomes": completed,
            "prediction_coverage": valid / expected if expected else 0.0,
            "outcome_coverage": completed / valid if valid else 0.0,
            "selected_pct": 100.0 * selected_count / valid if valid else 0.0,
        },
        "fill_calibration": calibration,
        "primary": primary,
        "frozen_stress": stress,
        "fee_neutral_stress": fee_neutral,
    }
    gate = _forward_gate(report, protocol)
    result = v2._json_safe(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "mode": "execution_shadow_only",
            "forward_start": protocol["prediction"]["forward_start"],
            "forward_end_exclusive": protocol["prediction"][
                "forward_end_exclusive"
            ],
            "recorded_at": _iso_ns(now_ns),
            "model_refit": False,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
            "report": report,
            "gate": gate,
            "verdict": "FORWARD_PASS_PAPER_INTEGRATION_ELIGIBLE"
            if gate["passed"]
            else "FORWARD_REJECTED",
        }
    )
    payload = {**result, "content_sha256": v2._json_hash(result)}
    payload_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    record_hash = v2._json_hash(
        {
            "cutoff_ns": cutoff_ns,
            "recorded_at_ns": now_ns,
            "payload_json": payload_json,
        }
    )
    journal.execute(
        "INSERT INTO evaluations(id,cutoff_ns,recorded_at_ns,payload_json,record_hash) VALUES(1,?,?,?,?)",
        (cutoff_ns, now_ns, payload_json, record_hash),
    )
    journal.commit()
    v2._atomic_json(evaluation_path, payload)
    return payload


def _counts(journal: sqlite3.Connection) -> dict:
    row = journal.execute(
        """
        SELECT
          COUNT(*) decisions,
          SUM(CASE WHEN status='PREDICTED' THEN 1 ELSE 0 END) predicted,
          SUM(CASE WHEN status='MISSED' THEN 1 ELSE 0 END) missed,
          SUM(CASE WHEN status='PREDICTED' AND selected=1 THEN 1 ELSE 0 END) selected
        FROM decisions
        """
    ).fetchone()
    outcome = journal.execute(
        """
        SELECT COUNT(*) outcomes,
          SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) completed,
          SUM(CASE WHEN status='INCOMPLETE' THEN 1 ELSE 0 END) incomplete
        FROM outcomes
        """
    ).fetchone()
    return {
        "decisions": int(row["decisions"] or 0),
        "predicted": int(row["predicted"] or 0),
        "missed": int(row["missed"] or 0),
        "selected": int(row["selected"] or 0),
        "outcomes": int(outcome["outcomes"] or 0),
        "completed_outcomes": int(outcome["completed"] or 0),
        "incomplete_outcomes": int(outcome["incomplete"] or 0),
    }


def _verify_tail(journal: sqlite3.Connection) -> bool:
    for row in journal.execute("SELECT key,value,record_hash FROM metadata"):
        if row["record_hash"] != v2._json_hash(
            {"key": str(row["key"]), "value": str(row["value"])}
        ):
            return False
    decision_rows = journal.execute(
        "SELECT * FROM decisions ORDER BY id DESC LIMIT 2"
    ).fetchall()
    if decision_rows:
        row = decision_rows[0]
        payload = {
            "decision_ns": int(row["decision_ns"]),
            "side": str(row["side"]),
            "recorded_at_ns": int(row["recorded_at_ns"]),
            "status": str(row["status"]),
            "reason": row["reason"],
            "features_json": row["features_json"],
            "features_sha256": row["features_sha256"],
            "fill_probability": row["fill_probability"],
            "predicted_fallback_saving_bps": row[
                "predicted_fallback_saving_bps"
            ],
            "expected_saving_bps": row["expected_saving_bps"],
            "selected": row["selected"],
            "model_sha256": str(row["model_sha256"]),
            "previous_record_hash": row["previous_record_hash"],
        }
        if row["record_hash"] != v2._json_hash(payload):
            return False
        if len(decision_rows) == 2 and (
            row["previous_record_hash"] != decision_rows[1]["record_hash"]
        ):
            return False
        if len(decision_rows) == 1 and row["previous_record_hash"] is not None:
            return False
    outcome_rows = journal.execute(
        "SELECT * FROM outcomes ORDER BY id DESC LIMIT 2"
    ).fetchall()
    if outcome_rows:
        row = outcome_rows[0]
        payload = {
            "decision_ns": int(row["decision_ns"]),
            "side": str(row["side"]),
            "decision_record_hash": str(row["decision_record_hash"]),
            "recorded_at_ns": int(row["recorded_at_ns"]),
            "status": str(row["status"]),
            "reason": row["reason"],
            "primary_filled": row["primary_filled"],
            "primary_saving_bps": row["primary_saving_bps"],
            "stress_filled": row["stress_filled"],
            "stress_saving_bps": row["stress_saving_bps"],
            "fee_neutral_stress_saving_bps": row[
                "fee_neutral_stress_saving_bps"
            ],
            "previous_record_hash": row["previous_record_hash"],
        }
        if row["record_hash"] != v2._json_hash(payload):
            return False
        if len(outcome_rows) == 2 and (
            row["previous_record_hash"] != outcome_rows[1]["record_hash"]
        ):
            return False
        if len(outcome_rows) == 1 and row["previous_record_hash"] is not None:
            return False
    evaluation = journal.execute(
        "SELECT cutoff_ns,recorded_at_ns,payload_json,record_hash FROM evaluations WHERE id=1"
    ).fetchone()
    if evaluation and evaluation["record_hash"] != v2._json_hash(
        {
            "cutoff_ns": int(evaluation["cutoff_ns"]),
            "recorded_at_ns": int(evaluation["recorded_at_ns"]),
            "payload_json": str(evaluation["payload_json"]),
        }
    ):
        return False
    return True


def _health_payload(
    config: ShadowConfig,
    protocol: dict,
    collector: dict,
    collector_healthy: bool,
    journal: sqlite3.Connection,
    evaluation: dict | None,
    now_ns: int,
) -> dict:
    start_ns = v1._epoch_ns(protocol["prediction"]["forward_start"])
    end_ns = v1._epoch_ns(protocol["prediction"]["forward_end_exclusive"])
    progress = min(1.0, max(0.0, (now_ns - start_ns) / (end_ns - start_ns)))
    counts = _counts(journal)
    status = "FORWARD_COMPLETE" if evaluation is not None else (
        "COLLECTING" if now_ns >= start_ns else "WAITING_FOR_START"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "execution_shadow_only",
        "status": status,
        "healthy": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "directional_alpha_claim": False,
        "protocol_sha256": protocol["protocol_sha256"],
        "model_sha256": MODEL_SHA256,
        "forward_start": protocol["prediction"]["forward_start"],
        "forward_end_exclusive": protocol["prediction"][
            "forward_end_exclusive"
        ],
        "progress_pct": 100.0 * progress,
        "updated_at": _iso_ns(now_ns),
        "last_success_at": _iso_ns(now_ns),
        "collector_healthy": collector_healthy,
        "collector_last_success_at": collector.get("last_success_at"),
        "journal_path": str(config.journal_path),
        "journal_bytes": config.journal_path.stat().st_size,
        "journal_tail_verified": _verify_tail(journal),
        "counts": counts,
        "official_evaluation_materialized": evaluation is not None,
        "official_verdict": evaluation.get("verdict") if evaluation else None,
        "evaluation_path": str(config.evaluation_path),
    }


def run_once(config: ShadowConfig, *, now_ns: int | None = None) -> dict:
    config.validate()
    current_ns = time.time_ns() if now_ns is None else int(now_ns)
    for path in (
        config.journal_path.parent,
        config.health_path.parent,
        config.lock_path.parent,
        config.evaluation_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
    previous_health = {}
    if config.health_path.is_file():
        try:
            previous_health = json.loads(
                config.health_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            previous_health = {}
    with config.lock_path.open("a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("execution-shadow runner is already active") from error
        try:
            protocol = json.loads(config.protocol_path.read_text(encoding="utf-8"))
            expected_protocol = {
                **frozen_protocol(protocol["prediction"]["forward_start"]),
            }
            expected_protocol["protocol_sha256"] = v2._json_hash(
                expected_protocol
            )
            if protocol != expected_protocol:
                raise ValueError("execution-shadow protocol differs")
            model = _verify_evidence(config, protocol)
            collector, collector_healthy = _read_collector_health(
                config.collector_health_path, current_ns
            )
            journal = _open_journal(config.journal_path)
            source = _open_source(config.source_database_path)
            try:
                _initialize_metadata(journal, protocol)
                prediction_result = _process_predictions(
                    source,
                    journal,
                    protocol,
                    model,
                    now_ns=current_ns,
                    collector_healthy=collector_healthy,
                )
                outcome_result = _process_outcomes(
                    source, journal, now_ns=current_ns
                )
                evaluation = _materialize_evaluation(
                    journal,
                    protocol,
                    model,
                    config.evaluation_path,
                    now_ns=current_ns,
                )
                health = _health_payload(
                    config,
                    protocol,
                    collector,
                    collector_healthy,
                    journal,
                    evaluation,
                    current_ns,
                )
                health["last_cycle"] = {
                    "predictions": prediction_result,
                    "outcomes": outcome_result,
                }
            finally:
                source.close()
                journal.close()
            v2._atomic_json(config.health_path, health)
            return health
        except Exception as error:
            failed = {
                "schema_version": SCHEMA_VERSION,
                "mode": "execution_shadow_only",
                "status": "FAILED",
                "healthy": False,
                "orders_authorized": False,
                "paper_orders_authorized": False,
                "automatic_promotion": False,
                "updated_at": _iso_ns(current_ns),
                "last_success_at": previous_health.get("last_success_at"),
                "error_type": type(error).__name__,
                "error": str(error),
            }
            v2._atomic_json(config.health_path, failed)
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write-protocol")
    write.add_argument("--output", required=True)
    write.add_argument("--forward-start", required=True)
    run = subparsers.add_parser("run-once")
    run.add_argument("--protocol", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--locked-report", required=True)
    run.add_argument("--locked-manifest", required=True)
    run.add_argument("--fee-audit", required=True)
    run.add_argument("--source-database", required=True)
    run.add_argument("--collector-health", required=True)
    run.add_argument("--journal", required=True)
    run.add_argument("--health", required=True)
    run.add_argument("--lock", required=True)
    run.add_argument("--evaluation", required=True)
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "write-protocol":
        result = write_or_verify_protocol(
            arguments.output, arguments.forward_start
        )
    else:
        result = run_once(
            ShadowConfig(
                protocol_path=pathlib.Path(arguments.protocol),
                model_path=pathlib.Path(arguments.model),
                locked_report_path=pathlib.Path(arguments.locked_report),
                locked_manifest_path=pathlib.Path(arguments.locked_manifest),
                fee_audit_path=pathlib.Path(arguments.fee_audit),
                source_database_path=pathlib.Path(arguments.source_database),
                collector_health_path=pathlib.Path(arguments.collector_health),
                journal_path=pathlib.Path(arguments.journal),
                health_path=pathlib.Path(arguments.health),
                lock_path=pathlib.Path(arguments.lock),
                evaluation_path=pathlib.Path(arguments.evaluation),
            )
        )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
