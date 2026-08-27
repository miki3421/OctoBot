import datetime

import pytest

from octobot.ai_strategy_lab import forward_carry_dashboard as dashboard


def _protocol_status():
    protocol = {
        "protocol_version": dashboard.PROTOCOL_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "results": None,
        "validation": {
            "locked_confirmation": {
                "earliest_open_utc": "2026-10-03T12:00:00+00:00"
            }
        },
    }
    protocol_hash = dashboard._json_hash(protocol)
    protocol["protocol_sha256"] = protocol_hash
    return dashboard.protocol_status(
        protocol,
        expected_sha256=protocol_hash,
    )


def _evidence(*, ready=False):
    return {
        "created_at": "2026-08-27T09:55:00+00:00",
        "mode": "forward_evidence_only",
        "orders_authorized": False,
        "automatic_promotion": False,
        "real_income_authorized": False,
        "strategy_development_ready": ready,
        "journal": {
            "coverage": 0.9791,
            "covered_span_days": 60.0 if ready else 34.9,
            "maximum_gap_seconds": 2700,
            "missing_buckets": 70,
            "observed_buckets": 5472 if ready else 3281,
            "symbol_count": 19,
        },
        "thresholds": {
            "expected_symbol_count": 19,
            "maximum_gap_minutes": 60,
            "minimum_coverage": 0.95,
            "minimum_settlements_per_symbol": 171,
            "minimum_span_days": 60,
        },
        "checks": {
            "coverage_reached": True,
            "journal_has_records": True,
            "maximum_gap_respected": True,
            "minimum_span_reached": ready,
            "settled_funding_reached": ready,
            "symbol_count_exact": True,
        },
        "readiness_progress": {
            "earliest_span_ready_at_utc": "2026-09-21T12:00:00+00:00",
            "minimum_remaining_settlements": 0 if ready else 63,
            "overall_minimum_progress": 1.0 if ready else 0.581,
            "remaining_observed_buckets_at_minimum_span": (
                0 if ready else 2191
            ),
            "required_span_buckets": 5760,
        },
        "settled_funding": {
            "minimum_unique_points": 171 if ready else 108,
        },
    }


def _health():
    return {
        "status": "healthy",
        "archive_consistent": True,
        "orders_authorized": False,
        "last_success_at": "2026-08-27T09:58:00+00:00",
        "bucket_start_utc": "2026-08-27T09:45:00+00:00",
    }


def test_protocol_requires_exact_hash_and_orderless_safety():
    valid = _protocol_status()

    assert valid["valid"] is True
    assert valid["confirmation_at"] == "2026-10-03T12:00:00+00:00"

    unsafe = {
        "protocol_version": dashboard.PROTOCOL_VERSION,
        "research_only": True,
        "orders_authorized": True,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "results": None,
    }
    unsafe_hash = dashboard._json_hash(unsafe)
    unsafe["protocol_sha256"] = unsafe_hash

    assert dashboard.protocol_status(
        unsafe,
        expected_sha256=unsafe_hash,
    )["valid"] is False


def test_summary_lists_only_active_quantitative_blockers():
    summary = dashboard.readiness_summary(
        _evidence(),
        _health(),
        _protocol_status(),
        now=datetime.datetime(
            2026, 8, 27, 10, 0, tzinfo=datetime.timezone.utc
        ),
    )

    assert summary["state"] == "IN RACCOLTA — BLOCCATO"
    assert summary["color"] == "warning"
    assert summary["progress_pct"] == pytest.approx(58.1)
    assert [value["id"] for value in summary["blockers"]] == [
        "minimum_span_reached",
        "settled_funding_reached",
    ]
    assert summary["estimated_at"] == "2026-09-21T12:00:00+00:00"
    assert summary["estimated_remaining"] == "circa 25g 2h"
    assert summary["orders_authorized"] is False


def test_summary_becomes_ready_only_when_every_gate_passes():
    evidence = _evidence(ready=True)
    evidence["created_at"] = "2026-09-21T11:55:00+00:00"
    health = _health()
    health["last_success_at"] = "2026-09-21T11:58:00+00:00"
    summary = dashboard.readiness_summary(
        evidence,
        health,
        _protocol_status(),
        now=datetime.datetime(
            2026, 9, 21, 12, 0, tzinfo=datetime.timezone.utc
        ),
    )

    assert summary["ready"] is True
    assert summary["state"] == "PRONTO PER SVILUPPO"
    assert summary["blockers"] == []


def test_stale_evidence_is_an_operational_blocker():
    summary = dashboard.readiness_summary(
        _evidence(),
        _health(),
        _protocol_status(),
        now=datetime.datetime(
            2026, 8, 27, 11, 0, tzinfo=datetime.timezone.utc
        ),
    )

    assert summary["color"] == "danger"
    assert "evidence_fresh" in {
        value["id"] for value in summary["blockers"]
    }
