import datetime
import json

import pytest

from octobot.ai_strategy_lab import forward_evidence
from octobot.ai_strategy_lab import microstructure


START = datetime.datetime(
    2026, 7, 23, 12, 0, tzinfo=datetime.timezone.utc
)


def _record(bucket, *, previous_hash, points):
    value = {
        "schema_version": microstructure.SCHEMA_VERSION,
        "mode": "observation_only",
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "bucket_start_utc": bucket.isoformat(),
        "interval_minutes": 15,
        "previous_record_hash": previous_hash,
        "symbols": {
            "BTC": {
                "funding": {
                    "settled_last_24h": [
                        {"timestamp_ms": timestamp, "rate": rate}
                        for timestamp, rate in points
                    ]
                }
            }
        },
    }
    value["record_hash"] = microstructure._record_hash(value)
    return value


def _write_journal(path, offsets_minutes):
    records = []
    previous_hash = None
    for index, offset in enumerate(offsets_minutes):
        record = _record(
            START + datetime.timedelta(minutes=offset),
            previous_hash=previous_hash,
            points=[
                (1_753_228_800_000, 0.00008),
                (
                    1_753_257_600_000,
                    0.00009 + index * 0.0,
                ),
            ],
        )
        records.append(record)
        previous_hash = record["record_hash"]
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def test_default_gate_stays_closed_for_short_single_symbol_sample(tmp_path):
    path = tmp_path / "market.jsonl"
    _write_journal(path, [0])

    report = forward_evidence.evaluate_forward_market_evidence(path)

    assert report["strategy_development_ready"] is False
    assert report["checks"]["journal_has_records"] is True
    assert report["checks"]["symbol_count_exact"] is False
    assert report["journal"]["coverage"] == 1
    assert report["journal"]["observed_buckets"] == 1
    assert report["settled_funding"]["minimum_unique_points"] == 2
    assert report["orders_authorized"] is False
    assert report["automatic_promotion"] is False
    assert report["real_income_authorized"] is False
    assert report["source_journal"]["sha256"]
    assert report["readiness_progress"][
        "required_span_buckets"
    ] == 5760
    assert report["readiness_progress"][
        "required_observed_buckets_at_minimum_coverage"
    ] == 5472
    assert report["readiness_progress"][
        "remaining_span_buckets"
    ] == 5759
    assert report["readiness_progress"][
        "minimum_remaining_settlements"
    ] == 169


def test_gate_opens_only_when_all_configured_readiness_checks_pass(tmp_path):
    path = tmp_path / "market.jsonl"
    _write_journal(path, [0, 15, 30, 45])
    config = forward_evidence.ForwardEvidenceConfig(
        minimum_span_days=1 / 24,
        minimum_coverage=1.0,
        maximum_gap_minutes=15,
        minimum_settlements_per_symbol=2,
        expected_symbol_count=1,
    )

    report = forward_evidence.evaluate_forward_market_evidence(
        path, config=config
    )

    assert report["strategy_development_ready"] is True
    assert all(report["checks"].values())
    assert report["journal"]["expected_buckets"] == 4
    assert report["journal"]["missing_buckets"] == 0
    assert report["journal"]["covered_span_days"] == pytest.approx(
        1 / 24
    )
    assert report["readiness_progress"]["overall_minimum_progress"] == 1
    assert report["readiness_progress"]["remaining_span_buckets"] == 0
    assert report["readiness_progress"][
        "minimum_remaining_settlements"
    ] == 0


def test_gap_over_limit_keeps_readiness_closed(tmp_path):
    path = tmp_path / "market.jsonl"
    _write_journal(path, [0, 75])
    config = forward_evidence.ForwardEvidenceConfig(
        minimum_span_days=1 / 24,
        minimum_coverage=0.30,
        maximum_gap_minutes=60,
        minimum_settlements_per_symbol=2,
        expected_symbol_count=1,
    )

    report = forward_evidence.evaluate_forward_market_evidence(
        path, config=config
    )

    assert report["strategy_development_ready"] is False
    assert report["checks"]["maximum_gap_respected"] is False
    assert report["journal"]["maximum_gap_seconds"] == 4500
    assert report["journal"]["missing_buckets"] == 4
    assert report["journal"]["gaps_over_interval"][0][
        "missing_buckets"
    ] == 4


def test_conflicting_settled_rate_is_rejected(tmp_path):
    path = tmp_path / "market.jsonl"
    first = _record(
        START,
        previous_hash=None,
        points=[(1_753_228_800_000, 0.00008)],
    )
    second = _record(
        START + datetime.timedelta(minutes=15),
        previous_hash=first["record_hash"],
        points=[(1_753_228_800_000, 0.00009)],
    )
    path.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="settled funding changed"):
        forward_evidence.evaluate_forward_market_evidence(path)
