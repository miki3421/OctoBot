"""Read-only data-quality report, daily audit and verified local backups."""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import math
import os
import pathlib
import shutil
import socket
import sqlite3
import tempfile
import typing

from octobot.ai_strategy_lab import scalping_evaluation_protocol as scalping_protocol


SCHEMA_VERSION = 1
MODE = "local_monitoring_only"
FINAL_ORDER_STATUSES = {
    "canceled",
    "cancelled",
    "closed",
    "filled",
    "interrupted",
}
STATUS_RANK = {"green": 0, "yellow": 1, "red": 2}


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    values = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"invalid JSONL row {line_number}: {path}")
        values.append(value)
    return values


def _write_json_atomic(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = pathlib.Path(temporary_value)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _connect_readonly(path: pathlib.Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro", uri=True, timeout=15
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def _quick_check(connection: sqlite3.Connection) -> str:
    return str(connection.execute("PRAGMA quick_check").fetchone()[0])


def _age_seconds(value: object, now: datetime.datetime) -> float | None:
    if not value:
        return None
    try:
        timestamp = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, (now - timestamp).total_seconds())


def _main_summary(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {"available": False}
    with _connect_readonly(path) as connection:
        integrity = _quick_check(connection)
        decisions = connection.execute(
            """
            SELECT COUNT(*) AS decisions, MAX(created_at) AS latest_at,
                   COALESCE(SUM(approved), 0) AS approved
            FROM ai_decisions
            """
        ).fetchone()
        outcomes = connection.execute(
            """
            SELECT COUNT(*) AS outcomes,
                   COALESCE(SUM(
                       CASE WHEN net_pnl_excluding_funding > 0 THEN 1 ELSE 0 END
                   ), 0) AS wins,
                   COALESCE(SUM(net_pnl_excluding_funding), 0) AS net_pnl
            FROM ai_position_outcomes
            """
        ).fetchone()
        orders = connection.execute(
            """
            WITH latest AS (
                SELECT order_id, MAX(id) AS id
                FROM ai_order_events GROUP BY order_id
            )
            SELECT status FROM ai_order_events AS event
            JOIN latest ON latest.id = event.id
            """
        ).fetchall()
    open_orders = sum(
        1
        for row in orders
        if str(row["status"] or "").lower() not in FINAL_ORDER_STATUSES
    )
    return {
        "available": True,
        "integrity": integrity,
        "database_bytes": path.stat().st_size,
        "decisions": int(decisions["decisions"]),
        "approved_decisions": int(decisions["approved"]),
        "latest_decision_at": decisions["latest_at"],
        "closed_positions": int(outcomes["outcomes"]),
        "wins": int(outcomes["wins"]),
        "net_pnl_excluding_funding": float(outcomes["net_pnl"]),
        "journal_open_orders": open_orders,
    }


def _trade_outcome(exit_reason: str) -> str | None:
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
        outcome = _trade_outcome(str(row["exit_reason"]))
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
        "multiclass_brier": (
            sum(brier_values) / count if count else None
        ),
        "classes": {
            name: {
                "mean_predicted_pct": (
                    sum(probabilities[name]) * 100 / count if count else None
                ),
                "observed_pct": observed[name] * 100 / count if count else None,
                "observed_count": observed[name],
            }
            for name in ("TARGET", "STOP", "TIMEOUT")
        },
        "warning": (
            "Calibration uses only accepted trades that have closed; it is "
            "not a calibration of every rejected V5 forecast."
        ),
    }


def _v5_summary(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {"available": False}
    with _connect_readonly(path) as connection:
        integrity = _quick_check(connection)
        decisions = connection.execute(
            """
            SELECT COUNT(*) AS decisions, COALESCE(SUM(accepted), 0) AS accepted,
                   MIN(close_timestamp) AS first_at,
                   MAX(close_timestamp) AS last_at
            FROM decisions
            """
        ).fetchone()
        accepted_directions = {
            str(row["action"]): int(row["count"])
            for row in connection.execute(
                """
                SELECT action, COUNT(*) AS count FROM decisions
                WHERE accepted = 1 GROUP BY action
                """
            )
        }
        trade_rows = list(
            connection.execute(
                """
                SELECT direction, exit_reason, pnl, net_return_pct,
                       prediction_json FROM trades ORDER BY id
                """
            )
        )
    decision_count = int(decisions["decisions"])
    accepted_count = int(decisions["accepted"])
    first_at = decisions["first_at"]
    last_at = decisions["last_at"]
    span_days = (
        max(0.0, (int(last_at) - int(first_at)) / 86_400)
        if first_at is not None and last_at is not None
        else 0.0
    )
    trade_directions = {"LONG": 0, "SHORT": 0}
    for row in trade_rows:
        direction = str(row["direction"])
        trade_directions[direction] = trade_directions.get(direction, 0) + 1
    return {
        "available": True,
        "integrity": integrity,
        "database_bytes": path.stat().st_size,
        "decisions": decision_count,
        "accepted": accepted_count,
        "holds_or_rejections": decision_count - accepted_count,
        "span_days": span_days,
        "decisions_per_day": (
            decision_count / span_days if span_days else 0.0
        ),
        "accepted_per_day": (
            accepted_count / span_days if span_days else 0.0
        ),
        "accepted_by_direction": {
            "LONG": accepted_directions.get("LONG", 0),
            "SHORT": accepted_directions.get("SHORT", 0),
        },
        "trades": len(trade_rows),
        "trades_by_direction": trade_directions,
        "wins": sum(float(row["net_return_pct"]) > 0 for row in trade_rows),
        "total_pnl": sum(float(row["pnl"]) for row in trade_rows),
        "latest_close_timestamp": last_at,
        "calibration": _v5_calibration(trade_rows),
    }


def _scalping_summary(
    path: pathlib.Path, health: dict, previous: dict | None = None
) -> dict:
    result = {
        "available": False,
        "database_operational": health.get("database_operational") is True,
    }
    if not path.is_file():
        return result
    with _connect_readonly(path) as connection:
        stats = connection.execute(
            """
            SELECT MIN(bucket_ts_s) AS first_s, MAX(bucket_ts_s) AS last_s
            FROM second_buckets
            """
        ).fetchone()
        observed_from_health = health.get("second_buckets")
        observed = (
            int(observed_from_health)
            if observed_from_health is not None
            else int(
                connection.execute(
                    "SELECT COUNT(*) FROM second_buckets"
                ).fetchone()[0]
            )
        )
        previous = previous or {}
        previous_last_s = previous.get("last_bucket_s")
        first_s = stats["first_s"]
        last_s = stats["last_s"]
        can_extend_previous = (
            previous_last_s is not None
            and first_s == previous.get("first_bucket_s")
            and last_s is not None
            and int(previous_last_s) <= int(last_s)
        )
        scan_from = int(previous_last_s) if can_extend_previous else first_s
        gaps = connection.execute(
            """
            WITH ordered AS (
                SELECT bucket_ts_s,
                       LAG(bucket_ts_s) OVER (ORDER BY bucket_ts_s) AS previous_s
                FROM second_buckets
                WHERE bucket_ts_s >= ?
            )
            SELECT COUNT(*) AS gap_count,
                   COALESCE(SUM(bucket_ts_s - previous_s - 1), 0) AS missing_s,
                   COALESCE(MAX(bucket_ts_s - previous_s - 1), 0) AS max_gap_s,
                   COALESCE(SUM(
                       CASE WHEN bucket_ts_s - previous_s - 1 > 5
                            THEN 1 ELSE 0 END
                   ), 0) AS gaps_over_5s
            FROM ordered WHERE bucket_ts_s - previous_s > 1
            """,
            (scan_from,),
        ).fetchone()
        sessions = connection.execute(
            """
            SELECT COUNT(*) AS sessions,
                   COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)
                       AS failed,
                   COALESCE(SUM(
                       CASE WHEN status = 'interrupted' THEN 1 ELSE 0 END
                   ), 0) AS interrupted
            FROM scalping_sessions
            """
        ).fetchone()
    span_seconds = (
        int(last_s) - int(first_s) + 1
        if first_s is not None and last_s is not None
        else 0
    )
    base_gap_count = int(previous.get("gap_count", 0)) if can_extend_previous else 0
    base_gaps_over_5s = (
        int(previous.get("gaps_over_5s", 0)) if can_extend_previous else 0
    )
    base_maximum_gap = (
        int(previous.get("maximum_gap_seconds", 0))
        if can_extend_previous
        else 0
    )
    session_count = int(sessions["sessions"])
    return {
        "available": True,
        "database_operational": health.get("database_operational") is True,
        "database_integrity": health.get("database_integrity"),
        "database_bytes": path.stat().st_size,
        "first_bucket_s": first_s,
        "last_bucket_s": last_s,
        "span_days": span_seconds / 86_400,
        "observed_seconds": observed,
        "missing_seconds": max(0, span_seconds - observed),
        "coverage": observed / span_seconds if span_seconds else 0.0,
        "gap_count": base_gap_count + int(gaps["gap_count"]),
        "gaps_over_5s": base_gaps_over_5s + int(gaps["gaps_over_5s"]),
        "maximum_gap_seconds": max(
            base_maximum_gap, int(gaps["max_gap_s"])
        ),
        "sessions": session_count,
        "restarts": max(0, session_count - 1),
        "failed_sessions": int(sessions["failed"]),
        "interrupted_sessions": int(sessions["interrupted"]),
        "current_session_id": health.get("session_id"),
        "current_session_maximum_book_silence_seconds": health.get(
            "maximum_session_book_silence_seconds"
        ),
        "book_events": int(health.get("book_events", 0)),
        "trade_events": int(health.get("trade_events", 0)),
        "last_book_at": health.get("last_book_at"),
    }


def _disk_summary(path: pathlib.Path) -> dict:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_pct": usage.free * 100 / usage.total if usage.total else 0.0,
    }


def _port_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _status_for_threshold(
    value: float, *, green: float, yellow: float
) -> str:
    if value >= green:
        return "green"
    if value >= yellow:
        return "yellow"
    return "red"


def _float_or(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_fresh(
    value: object, now: datetime.datetime, maximum_age_seconds: float
) -> bool:
    age = _age_seconds(value, now)
    return age is not None and age < maximum_age_seconds


def _quality_checks(
    report: dict, *, now: datetime.datetime
) -> list[dict]:
    retired = set(report.get("retired_strategies", []))
    scalping = report["scalping"]
    market = report["market_evidence"]
    v5_health = report["health"]["v5"]
    shadow_health = report["health"]["shadow"]
    scalping_health = report["health"]["scalping"]
    market_health = report["health"]["market"]
    open_order_count = int(report["main"].get("journal_open_orders", 0))
    open_order_phrase = (
        "1 ordine aperto"
        if open_order_count == 1
        else f"{open_order_count} ordini aperti"
    )
    checks = [
        {
            "id": "port_5001",
            "label": "OctoBot paper · porta 5001",
            "status": "green" if report["ports"]["5001"] else "red",
            "detail": (
                "raggiungibile"
                if report["ports"]["5001"]
                else "non raggiungibile"
            ),
        },
        {
            "id": "port_5002",
            "label": "V5 paper · porta 5002",
            "status": (
                "green"
                if "v5" in retired or report["ports"]["5002"]
                else "red"
            ),
            "detail": (
                "ritirata intenzionalmente"
                if "v5" in retired
                else
                "raggiungibile"
                if report["ports"]["5002"]
                else "non raggiungibile"
            ),
        },
        {
            "id": "main_journal",
            "label": "Journal KuCoin paper",
            "status": (
                "green"
                if report["main"].get("integrity") == "ok"
                else "red"
            ),
            "detail": (
                f"{report['main'].get('decisions', 0)} decisioni · "
                f"{open_order_phrase} nel journal"
            ),
        },
        {
            "id": "v5_feed",
            "label": "V5 Binance 15m",
            "status": (
                "green"
                if "v5" in retired
                or v5_health.get("status") == "healthy"
                and _float_or(
                    v5_health.get("data_lag_seconds"), math.inf
                ) < 1800
                and _is_fresh(
                    v5_health.get("last_success_at"), now, 180
                )
                else "red"
            ),
            "detail": (
                "strategia ritirata · storico conservato"
                if "v5" in retired
                else
                f"{report['v5'].get('decisions', 0)} decisioni · "
                f"{report['v5'].get('trades', 0)} trade chiusi · "
                f"ultimo update {v5_health.get('last_success_at', '-')}"
            ),
        },
        {
            "id": "scalping_live",
            "label": "Scalping Level 5 live",
            "status": (
                "green"
                if scalping_health.get("status") == "healthy"
                and scalping_health.get("connected") is True
                and _is_fresh(
                    scalping_health.get("last_book_at"), now, 20
                )
                else "red"
            ),
            "detail": (
                f"{scalping.get('span_days', 0):.2f} giorni · "
                f"{scalping.get('book_events', 0)} book"
            ),
        },
        {
            "id": "scalping_coverage",
            "label": "Copertura scalping",
            "status": _status_for_threshold(
                float(scalping.get("coverage", 0.0)), green=0.95, yellow=0.90
            ),
            "detail": (
                f"{float(scalping.get('coverage', 0)) * 100:.3f}% · "
                f"{scalping.get('gaps_over_5s', 0)} gap >5s"
            ),
        },
        {
            "id": "scalping_sessions",
            "label": "Continuità collector scalping",
            "status": (
                "green"
                if scalping.get("restarts", 0) == 0
                else "yellow"
                if scalping.get("coverage", 0.0) >= 0.95
                else "red"
            ),
            "detail": (
                f"{scalping.get('sessions', 0)} sessioni · "
                f"{scalping.get('failed_sessions', 0)} disconnessioni/fallimenti"
            ),
        },
        {
            "id": "market_live",
            "label": "Observer multi-mercato live",
            "status": (
                "green"
                if market_health.get("status") == "healthy"
                and _is_fresh(
                    market_health.get("last_success_at"), now, 2700
                )
                else "red"
            ),
            "detail": (
                f"{market_health.get('symbol_count', 0)} mercati · "
                f"ultimo aggiornamento "
                f"{market_health.get('last_success_at', '-')}"
            ),
        },
        {
            "id": "market_coverage",
            "label": "Observer 19 mercati",
            "status": _status_for_threshold(
                float(market.get("journal", {}).get("coverage", 0.0)),
                green=0.95,
                yellow=0.90,
            ),
            "detail": (
                f"{float(market.get('journal', {}).get('coverage', 0)) * 100:.3f}% · "
                f"{market.get('journal', {}).get('missing_buckets', 0)} bucket mancanti"
            ),
        },
        {
            "id": "trend_shadow",
            "label": "Trend shadow giornaliero",
            "status": (
                "green"
                if "trend_shadow" in retired
                or shadow_health.get("status") == "healthy"
                and _is_fresh(
                    shadow_health.get("last_success_at"), now, 172800
                )
                else "red"
            ),
            "detail": (
                "V3/V14 ritirate · storico conservato"
                if "trend_shadow" in retired
                else f"ultimo giorno {shadow_health.get('as_of_date', '-')}"
            ),
        },
        {
            "id": "disk",
            "label": "Spazio disco dati",
            "status": _status_for_threshold(
                float(report["disk"].get("free_pct", 0.0)),
                green=20.0,
                yellow=10.0,
            ),
            "detail": f"{report['disk'].get('free_pct', 0):.1f}% libero",
        },
    ]
    return checks


def _verified_sqlite_backup(source: pathlib.Path, destination: pathlib.Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    source_connection = _connect_readonly(source)
    destination_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(
            destination_connection, pages=1024, sleep=0.01
        )
    finally:
        destination_connection.close()
        source_connection.close()
    with sqlite3.connect(temporary) as verification:
        integrity = str(
            verification.execute("PRAGMA integrity_check").fetchone()[0]
        )
    if integrity != "ok":
        temporary.unlink(missing_ok=True)
        raise sqlite3.DatabaseError(
            f"backup integrity failed for {source}: {integrity}"
        )
    os.replace(temporary, destination)
    return {
        "file": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": _file_hash(destination),
        "integrity": integrity,
        "source": str(source),
    }


def _daily_backups(
    backup_root: pathlib.Path,
    date_value: datetime.date,
    *,
    ai_database: pathlib.Path,
    v5_database: pathlib.Path,
    scalping_database: pathlib.Path,
    scalping: dict,
) -> dict:
    directory = backup_root / date_value.isoformat()
    manifest_path = directory / "manifest.json"
    if manifest_path.is_file():
        manifest = _read_json(manifest_path)
        verify_backup_manifest(directory)
        return manifest
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "ai_decisions": _verified_sqlite_backup(
            ai_database, directory / "ai-decisions.sqlite"
        ),
        "v5_paper": _verified_sqlite_backup(
            v5_database, directory / "v5-paper.sqlite"
        ),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "date_utc": date_value.isoformat(),
        "created_at": _utc_now().isoformat(),
        "same_volume_local_backup": True,
        "physical_disk_failure_protection": False,
        "artifacts": artifacts,
        "scalping": {
            "status": "deferred_until_offline_30_day_freeze",
            "source": str(scalping_database),
            "source_bytes": (
                scalping_database.stat().st_size
                if scalping_database.is_file()
                else 0
            ),
            "span_days": scalping.get("span_days", 0.0),
            "coverage": scalping.get("coverage", 0.0),
            "reason": (
                "do not scan and duplicate the live Level 5 database while "
                "the collector is latency-sensitive"
            ),
        },
    }
    manifest["manifest_sha256"] = _payload_hash(manifest)
    _write_json_atomic(manifest_path, manifest)
    return manifest


def verify_backup_manifest(directory_value: typing.Union[str, pathlib.Path]) -> dict:
    directory = pathlib.Path(directory_value).resolve()
    manifest = _read_json(directory / "manifest.json")
    if not manifest:
        raise FileNotFoundError(f"backup manifest missing: {directory}")
    persisted_hash = manifest.get("manifest_sha256")
    content = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if persisted_hash != _payload_hash(content):
        raise ValueError("backup manifest hash differs")
    for artifact in manifest.get("artifacts", {}).values():
        path = directory / artifact["file"]
        if not path.is_file() or _file_hash(path) != artifact["sha256"]:
            raise ValueError(f"backup artifact hash differs: {path}")
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            integrity = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
        if integrity != "ok":
            raise sqlite3.DatabaseError(
                f"backup artifact integrity failed: {path}"
            )
    return {"verified": True, "manifest": manifest}


def freeze_scalping_dataset(
    *,
    scalping_database: pathlib.Path,
    scalping_health_path: pathlib.Path,
    destination_root: pathlib.Path,
    protocol_path: pathlib.Path,
    lock_path: pathlib.Path,
    collector_confirmed_stopped: bool = False,
) -> dict:
    """Create the immutable 30-day dataset only after a manual collector stop."""

    if not collector_confirmed_stopped:
        raise PermissionError(
            "explicit --collector-confirmed-stopped acknowledgement required"
        )
    health = _read_json(scalping_health_path)
    if health.get("connected") is not False or health.get("status") != "stopped":
        raise RuntimeError(
            "scalping health does not confirm a graceful collector stop"
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        scalping = _scalping_summary(scalping_database, health)
        preliminary = scalping_protocol.readiness(scalping)
        required_checks = (
            "minimum_forward_days",
            "minimum_coverage",
            "database_operational",
        )
        failed = [
            name
            for name in required_checks
            if preliminary["checks"].get(name) is not True
        ]
        if failed:
            raise RuntimeError(
                "scalping freeze gate not reached: " + ", ".join(failed)
            )
        protocol = scalping_protocol.write_or_verify_protocol(protocol_path)
        freeze_identity = (
            f"{scalping['first_bucket_s']}-{scalping['last_bucket_s']}"
        )
        directory = destination_root / f"scalping-freeze-{freeze_identity}"
        manifest_path = directory / "manifest.json"
        if manifest_path.is_file():
            return verify_backup_manifest(directory)["manifest"]
        artifact = _verified_sqlite_backup(
            scalping_database,
            directory / "btc-futures-level5.sqlite",
        )
        audited_readiness = scalping_protocol.readiness(
            scalping, frozen_snapshot_verified=True
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "mode": "offline_scalping_dataset_freeze",
            "created_at": _utc_now().isoformat(),
            "collector_confirmed_stopped": True,
            "collector_health_status": health.get("status"),
            "orders_authorized": False,
            "automatic_promotion": False,
            "artifacts": {"scalping_level5": artifact},
            "scalping": scalping,
            "full_offline_integrity_and_gap_audit": True,
            "readiness": audited_readiness,
            "protocol_version": protocol["protocol_version"],
            "protocol_sha256": protocol["protocol_sha256"],
        }
        manifest["manifest_sha256"] = _payload_hash(manifest)
        _write_json_atomic(manifest_path, manifest)
        verify_backup_manifest(directory)
        return manifest


def verify_daily_journal(
    journal_value: typing.Union[str, pathlib.Path]
) -> dict:
    journal = pathlib.Path(journal_value)
    records = _read_jsonl(journal)
    previous_hash = None
    for index, record in enumerate(records, start=1):
        persisted_hash = record.get("record_sha256")
        content = {
            key: value
            for key, value in record.items()
            if key != "record_sha256"
        }
        if persisted_hash != _payload_hash(content):
            raise ValueError(f"daily report hash differs at row {index}")
        if record.get("previous_record_sha256") != previous_hash:
            raise ValueError(f"daily report chain differs at row {index}")
        previous_hash = persisted_hash
    return {
        "verified": True,
        "records": len(records),
        "last_record_sha256": previous_hash,
    }


def _append_daily(journal: pathlib.Path, report: dict) -> dict:
    records = _read_jsonl(journal)
    verify_daily_journal(journal)
    identity = report["date_utc"]
    for record in records:
        if record.get("date_utc") == identity:
            return {"appended": False, "record": record}
    previous_hash = records[-1].get("record_sha256") if records else None
    record = {**report, "previous_record_sha256": previous_hash}
    record["record_sha256"] = _payload_hash(record)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"appended": True, "record": record}


def run(
    *,
    ai_database: pathlib.Path,
    v5_database: pathlib.Path,
    scalping_database: pathlib.Path,
    scalping_health_path: pathlib.Path,
    v5_health_path: pathlib.Path,
    shadow_health_path: pathlib.Path,
    market_health_path: pathlib.Path,
    market_evidence_path: pathlib.Path,
    current_output: pathlib.Path,
    daily_journal: pathlib.Path,
    backup_root: pathlib.Path,
    protocol_path: pathlib.Path,
    lock_path: pathlib.Path,
    main_host: str = "octobot",
    main_port: int = 5001,
    v5_host: str = "v5-broker",
    v5_port: int = 5001,
    retired_strategies: typing.Iterable[str] = (),
    now: datetime.datetime | None = None,
) -> dict:
    """Create one status snapshot without changing any trading component."""

    current_time = (now or _utc_now()).astimezone(datetime.timezone.utc)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous_report = _read_json(current_output)
        scalping_health = _read_json(scalping_health_path)
        v5_health = _read_json(v5_health_path)
        shadow_health = _read_json(shadow_health_path)
        market_health = _read_json(market_health_path)
        market_evidence = _read_json(market_evidence_path)
        main = _main_summary(ai_database)
        v5 = _v5_summary(v5_database)
        scalping = _scalping_summary(
            scalping_database,
            scalping_health,
            previous_report.get("scalping", {}),
        )
        protocol = scalping_protocol.write_or_verify_protocol(protocol_path)
        date_value = current_time.date()
        backup = _daily_backups(
            backup_root,
            date_value,
            ai_database=ai_database,
            v5_database=v5_database,
            scalping_database=scalping_database,
            scalping=scalping,
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": MODE,
            "generated_at": current_time.isoformat(),
            "date_utc": date_value.isoformat(),
            "orders_authorized": False,
            "automatic_promotion": False,
            "retired_strategies": sorted(set(retired_strategies)),
            "main": main,
            "v5": v5,
            "scalping": scalping,
            "market_evidence": market_evidence,
            "health": {
                "scalping": scalping_health,
                "v5": v5_health,
                "shadow": shadow_health,
                "market": market_health,
            },
            "ports": {
                "5001": _port_reachable(main_host, main_port),
                "5002": _port_reachable(v5_host, v5_port),
            },
            "disk": _disk_summary(scalping_database.parent),
            "backup": {
                "manifest": str(
                    backup_root / date_value.isoformat() / "manifest.json"
                ),
                "verified": verify_backup_manifest(
                    backup_root / date_value.isoformat()
                )["verified"],
                "artifacts": backup.get("artifacts", {}),
                "scalping": backup.get("scalping", {}),
            },
            "scalping_evaluation": {
                **scalping_protocol.readiness(scalping),
                "protocol_sha256": protocol["protocol_sha256"],
                "protocol_path": str(protocol_path),
            },
        }
        report["quality_checks"] = _quality_checks(
            report, now=current_time
        )
        report["overall_status"] = max(
            (row["status"] for row in report["quality_checks"]),
            key=lambda status: STATUS_RANK[status],
            default="red",
        )
        daily = _append_daily(daily_journal, report)
        report["daily_report"] = {
            "journal": str(daily_journal),
            "appended": daily["appended"],
            "record_sha256": daily["record"]["record_sha256"],
            "chain_verified": verify_daily_journal(daily_journal)[
                "verified"
            ],
        }
        _write_json_atomic(current_output, report)
        return report
