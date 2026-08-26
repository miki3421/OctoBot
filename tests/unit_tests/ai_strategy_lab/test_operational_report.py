import datetime
import json
import sqlite3

from octobot.ai_strategy_lab import operational_report


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _ai_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE ai_decisions (
            id INTEGER PRIMARY KEY, created_at TEXT, approved INTEGER
        );
        CREATE TABLE ai_position_outcomes (
            id INTEGER PRIMARY KEY, net_pnl_excluding_funding REAL
        );
        CREATE TABLE ai_order_events (
            id INTEGER PRIMARY KEY, order_id TEXT, status TEXT
        );
        INSERT INTO ai_decisions VALUES
            (1, '2026-08-02T10:00:00+00:00', 1);
        INSERT INTO ai_position_outcomes VALUES (1, 2.5);
        INSERT INTO ai_order_events VALUES (1, 'order-1', 'filled');
        """
    )
    connection.commit()
    connection.close()


def _v5_database(path):
    prediction = json.dumps(
        {
            "target_probability_pct": 30.0,
            "stop_probability_pct": 50.0,
            "timeout_probability_pct": 20.0,
        }
    )
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE decisions (
            id INTEGER PRIMARY KEY, close_timestamp INTEGER,
            action TEXT, accepted INTEGER
        );
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, direction TEXT, exit_reason TEXT,
            pnl REAL, net_return_pct REAL, prediction_json TEXT
        );
        INSERT INTO decisions VALUES (1, 1000, 'SHORT', 1);
        INSERT INTO decisions VALUES (2, 87400, 'HOLD', 0);
        """
    )
    connection.execute(
        "INSERT INTO trades VALUES (1, 'SHORT', 'initial_stop', -10, -1, ?)",
        (prediction,),
    )
    connection.commit()
    connection.close()


def _scalping_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE second_buckets (bucket_ts_s INTEGER PRIMARY KEY);
        CREATE TABLE scalping_sessions (
            session_id TEXT PRIMARY KEY, status TEXT
        );
        INSERT INTO second_buckets VALUES (1000), (1001), (1003);
        INSERT INTO scalping_sessions VALUES ('one', 'running');
        """
    )
    connection.commit()
    connection.close()


def test_report_is_idempotent_and_backups_are_verified(tmp_path, monkeypatch):
    ai = tmp_path / "ai.sqlite"
    v5 = tmp_path / "v5.sqlite"
    scalping = tmp_path / "scalping.sqlite"
    _ai_database(ai)
    _v5_database(v5)
    _scalping_database(scalping)
    health_root = tmp_path / "health"
    _write_json(
        health_root / "scalping.json",
        {
            "status": "healthy",
            "connected": True,
            "database_operational": True,
            "database_integrity": "deferred_offline",
            "last_book_at": "2026-08-02T11:59:59+00:00",
            "book_events": 30,
            "trade_events": 4,
            "session_id": "one",
        },
    )
    _write_json(
        health_root / "v5.json",
        {
            "status": "healthy",
            "data_lag_seconds": 100,
            "last_success_at": "2026-08-02T11:59:00+00:00",
        },
    )
    _write_json(
        health_root / "shadow.json",
        {
            "status": "healthy",
            "last_success_at": "2026-08-02T06:00:00+00:00",
            "as_of_date": "2026-08-01",
        },
    )
    _write_json(
        health_root / "market-health.json",
        {
            "status": "healthy",
            "last_success_at": "2026-08-02T11:59:00+00:00",
            "symbol_count": 19,
        },
    )
    _write_json(
        health_root / "market.json",
        {
            "journal": {"coverage": 0.96, "missing_buckets": 2}
        },
    )
    monkeypatch.setattr(
        operational_report, "_port_reachable", lambda *args, **kwargs: True
    )
    arguments = {
        "ai_database": ai,
        "v5_database": v5,
        "scalping_database": scalping,
        "scalping_health_path": health_root / "scalping.json",
        "v5_health_path": health_root / "v5.json",
        "shadow_health_path": health_root / "shadow.json",
        "market_health_path": health_root / "market-health.json",
        "market_evidence_path": health_root / "market.json",
        "current_output": tmp_path / "operations" / "current.json",
        "daily_journal": tmp_path / "operations" / "daily.jsonl",
        "backup_root": tmp_path / "operations" / "backups",
        "protocol_path": tmp_path / "operations" / "protocol.json",
        "lock_path": tmp_path / "operations" / "runner.lock",
        "now": datetime.datetime(
            2026, 8, 2, 12, tzinfo=datetime.timezone.utc
        ),
    }

    first = operational_report.run(**arguments)
    second = operational_report.run(**arguments)

    assert first["orders_authorized"] is False
    assert first["backup"]["verified"] is True
    assert first["backup"]["scalping"]["status"].startswith("deferred")
    assert first["v5"]["accepted_by_direction"]["SHORT"] == 1
    assert first["v5"]["calibration"]["mature_accepted_trades"] == 1
    assert next(
        row for row in first["quality_checks"] if row["id"] == "v5_feed"
    )["status"] == "green"
    first["health"]["v5"]["last_success_at"] = "2026-08-02T06:00:00+00:00"
    assert next(
        row
        for row in operational_report._quality_checks(
            first, now=arguments["now"]
        )
        if row["id"] == "v5_feed"
    )["status"] == "red"
    assert first["scalping"]["missing_seconds"] == 1
    assert second["scalping"]["gap_count"] == first["scalping"]["gap_count"]
    assert first["daily_report"]["appended"] is True
    assert first["daily_report"]["chain_verified"] is True
    assert second["daily_report"]["appended"] is False
    assert len(arguments["daily_journal"].read_text().splitlines()) == 1
    backup_directory = arguments["backup_root"] / "2026-08-02"
    assert operational_report.verify_backup_manifest(backup_directory)[
        "verified"
    ]
    assert operational_report.verify_daily_journal(
        arguments["daily_journal"]
    )["records"] == 1


def test_scalping_freeze_requires_stop_and_gate(tmp_path, monkeypatch):
    scalping = tmp_path / "scalping.sqlite"
    _scalping_database(scalping)
    health_path = tmp_path / "health.json"
    protocol_path = tmp_path / "protocol.json"
    lock_path = tmp_path / "freeze.lock"
    _write_json(
        health_path,
        {
            "status": "healthy",
            "connected": True,
            "database_operational": True,
        },
    )
    try:
        operational_report.freeze_scalping_dataset(
            scalping_database=scalping,
            scalping_health_path=health_path,
            destination_root=tmp_path / "freezes",
            protocol_path=protocol_path,
            lock_path=lock_path,
            collector_confirmed_stopped=True,
        )
    except RuntimeError as error:
        assert "does not confirm a graceful collector stop" in str(error)
    else:
        raise AssertionError("live collector freeze should have failed")

    _write_json(
        health_path,
        {
            "status": "stopped",
            "connected": False,
            "database_operational": True,
        },
    )
    monkeypatch.setattr(
        operational_report.scalping_protocol, "MINIMUM_FORWARD_DAYS", 0.0
    )
    monkeypatch.setattr(
        operational_report.scalping_protocol, "MINIMUM_COVERAGE", 0.50
    )
    manifest = operational_report.freeze_scalping_dataset(
        scalping_database=scalping,
        scalping_health_path=health_path,
        destination_root=tmp_path / "freezes",
        protocol_path=protocol_path,
        lock_path=lock_path,
        collector_confirmed_stopped=True,
    )

    assert manifest["collector_confirmed_stopped"] is True
    assert manifest["readiness"]["ready"] is True
    assert manifest["full_offline_integrity_and_gap_audit"] is True
