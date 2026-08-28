import datetime
import hashlib
import json

from octobot.ai_strategy_lab import forward_carry_gatekeeper
from octobot.ai_strategy_lab import forward_carry_strategy_v1
from octobot.ai_strategy_lab import forward_carry_strategy_v1_1


NOW = datetime.datetime(
    2026, 8, 28, 10, 0, tzinfo=datetime.timezone.utc
)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _artifacts(tmp_path, *, ready=False, unsafe_health=False):
    protocol = forward_carry_strategy_v1_1.frozen_protocol()
    protocol = {
        **protocol,
        "protocol_sha256": forward_carry_strategy_v1._json_hash(protocol),
    }
    protocol_path = tmp_path / "protocol.json"
    _write_json(protocol_path, protocol)
    journal = tmp_path / "market.jsonl"
    journal.write_text("frozen-prefix\n", encoding="utf-8")
    checks = {
        "journal_has_records": True,
        "symbol_count_exact": True,
        "minimum_span_reached": ready,
        "coverage_reached": True,
        "maximum_gap_respected": True,
        "settled_funding_reached": ready,
    }
    evidence = {
        "schema_version": 1,
        "research_only": True,
        "mode": "forward_evidence_only",
        "orders_authorized": False,
        "automatic_promotion": False,
        "real_income_authorized": False,
        "strategy_development_ready": ready,
        "created_at": NOW.isoformat(),
        "checks": checks,
        "thresholds": {
            "interval_minutes": 15,
            "minimum_span_days": 60,
            "minimum_coverage": 0.95,
            "maximum_gap_minutes": 60,
            "minimum_settlements_per_symbol": 171,
            "expected_symbol_count": 19,
        },
        "journal": {
            "observed_buckets": 3400,
            "coverage": 0.98,
            "maximum_gap_seconds": 2700,
            "covered_span_days": 60 if ready else 36,
            "symbol_count": 19,
        },
        "settled_funding": {
            "minimum_unique_points": 171 if ready else 111,
        },
        "readiness_progress": {
            "overall_minimum_progress": 1 if ready else 0.6,
            "earliest_span_ready_at_utc": "2026-09-21T12:00:00+00:00",
        },
        "source_journal": {
            "bytes": journal.stat().st_size,
            "sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
        },
    }
    evidence_path = tmp_path / "evidence.json"
    _write_json(evidence_path, evidence)
    health = {
        "status": "healthy",
        "mode": "observation_only",
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": unsafe_health,
        "archive_consistent": True,
        "record_hash": "a" * 64,
        "last_success_at": NOW.isoformat(),
    }
    health_path = tmp_path / "health.json"
    _write_json(health_path, health)
    archive = tmp_path / "records"
    archive.mkdir()
    config = forward_carry_gatekeeper.GatekeeperConfig(
        protocol_path=protocol_path,
        journal_path=journal,
        evidence_path=evidence_path,
        market_health_path=health_path,
        archive_root=archive,
        state_root=tmp_path / "gatekeeper",
    )
    return config, protocol, evidence, health


def _install_latch(config, protocol, *, phase, passed):
    state = config.state_root
    run_name = f"{phase}-test-run"
    run = state / "runs" / run_name
    run.mkdir(parents=True)
    gate_name = f"{phase}_gate"
    report = forward_carry_gatekeeper._write_hashed_json(
        run / f"{phase}-report.json",
        {
            "phase": phase,
            "protocol_sha256": protocol["protocol_sha256"],
            gate_name: {"passed": passed},
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        },
        "report_sha256",
    )
    manifest = forward_carry_gatekeeper._write_hashed_json(
        run / "run-manifest.json",
        {
            "phase": phase,
            "protocol_sha256": protocol["protocol_sha256"],
            "report_sha256": report["report_sha256"],
            "passed": passed,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        },
        "manifest_sha256",
    )
    del manifest
    return forward_carry_gatekeeper._write_hashed_json(
        state / f"{phase}-latch.json",
        {
            "schema_version": 1,
            "gatekeeper_version": (
                forward_carry_gatekeeper.GATEKEEPER_VERSION
            ),
            "phase": phase,
            "protocol_sha256": protocol["protocol_sha256"],
            "source_lock_sha256": "b" * 64,
            "run_directory": run_name,
            "report_sha256": report["report_sha256"],
            "passed": passed,
            "research_only": True,
            "orders_authorized": False,
            "paper_orders_authorized": False,
            "automatic_promotion": False,
        },
        "latch_sha256",
    )


def test_waiting_readiness_creates_no_economic_artifact(tmp_path):
    config, _, _, _ = _artifacts(tmp_path, ready=False)

    status = forward_carry_gatekeeper.run_once(config, now=NOW)

    assert status["healthy"] is True
    assert status["phase"] == "WAITING_READINESS"
    assert status["artifacts_created"] is False
    assert {path.name for path in config.state_root.iterdir()} == {
        "runner.lock",
        "status.json",
    }


def test_unsafe_collector_blocks_operationally(tmp_path):
    config, _, _, _ = _artifacts(
        tmp_path, ready=False, unsafe_health=True
    )

    status = forward_carry_gatekeeper.run_once(config, now=NOW)

    assert status["healthy"] is False
    assert status["phase"] == "BLOCKED_OPERATIONAL"
    assert "safety" in {value["id"] for value in status["blockers"]}


def test_copy_prefix_ignores_later_append_and_verifies_hash(tmp_path):
    source = tmp_path / "source.jsonl"
    prefix = b'{"value":1}\n'
    source.write_bytes(prefix + b'{"value":2}\n')
    destination = tmp_path / "frozen.jsonl"

    forward_carry_gatekeeper._copy_prefix(
        source,
        destination,
        len(prefix),
        hashlib.sha256(prefix).hexdigest(),
    )

    assert destination.read_bytes() == prefix


def test_archive_tail_must_match_frozen_journal(tmp_path):
    record = {"record_hash": "c" * 64, "value": 1}
    journal = tmp_path / "market.jsonl"
    _write_json(journal, record)
    archive = tmp_path / "records"
    archive.mkdir()
    _write_json(archive / f"20260828T100000Z-{record['record_hash']}.json", record)

    forward_carry_gatekeeper._verify_archive_tail(journal, archive)

    record["value"] = 2
    _write_json(archive / f"20260828T100000Z-{record['record_hash']}.json", record)
    try:
        forward_carry_gatekeeper._verify_archive_tail(journal, archive)
    except forward_carry_gatekeeper.GatekeeperError as error:
        assert "does not match archive" in str(error)
    else:
        raise AssertionError("tampered archive tail was accepted")


def test_source_lock_does_not_move_on_retry(tmp_path):
    config, protocol, evidence, health = _artifacts(tmp_path, ready=True)
    config.state_root.mkdir()
    first = forward_carry_gatekeeper._get_or_create_source_lock(
        config,
        protocol,
        evidence,
        health,
        phase="development",
        now_utc=NOW,
    )
    changed = dict(evidence)
    changed["created_at"] = (NOW + datetime.timedelta(hours=1)).isoformat()

    second = forward_carry_gatekeeper._get_or_create_source_lock(
        config,
        protocol,
        changed,
        health,
        phase="development",
        now_utc=NOW + datetime.timedelta(hours=1),
    )

    assert second == first
    assert second["evidence"]["created_at"] == NOW.isoformat()


def test_failed_development_latch_seals_confirmation(tmp_path):
    config, protocol, _, _ = _artifacts(tmp_path, ready=False)
    config.state_root.mkdir()
    _install_latch(config, protocol, phase="development", passed=False)

    status = forward_carry_gatekeeper.run_once(config, now=NOW)

    assert status["phase"] == "COMPLETE"
    assert status["official_verdict"] == "DEVELOPMENT_FAIL"
    assert status["confirmation"] is None


def test_passing_development_waits_for_confirmation_clock(tmp_path):
    config, protocol, _, _ = _artifacts(tmp_path, ready=False)
    config.state_root.mkdir()
    _install_latch(config, protocol, phase="development", passed=True)

    status = forward_carry_gatekeeper.run_once(config, now=NOW)

    assert status["phase"] == "WAITING_CONFIRMATION"
    assert status["official_verdict"] == "DEVELOPMENT_PASS"
    assert status["orders_authorized"] is False
