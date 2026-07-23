import json

from octobot.ai_strategy_lab import shadow


def _write_report(path):
    path.write_text(
        json.dumps(
            {
                "research_only": True,
                "reports": {
                    "strategy": {
                        "evaluation_end_date": "2026-07-22",
                        "days_until_next_rebalance": 4,
                        "latest_signal": {"BTC": 0, "ETH": 1},
                        "latest_close": {"BTC": 100.0, "ETH": 50.0},
                        "latest_daily_funding": {
                            "BTC": 0.0001,
                            "ETH": 0.0002,
                        },
                        "ending_weights": {"BTC": 0.0, "ETH": 0.1},
                        "latest_rebalance_target_weights": {
                            "BTC": 0.0,
                            "ETH": 0.12,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_shadow_journal_is_append_only_and_deduplicated(tmp_path):
    report = tmp_path / "trend.json"
    journal = tmp_path / "shadow.jsonl"
    _write_report(report)
    first = shadow.record_trend_shadow(report, "strategy", journal)
    second = shadow.record_trend_shadow(report, "strategy", journal)
    assert first["appended"] is True
    assert second["appended"] is False
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["orders_authorized"] is False
    assert record["target_gross_exposure"] == 0.12
    assert record["candidate_target_weights"]["ETH"] == 0.12


def test_shadow_rejects_non_research_report(tmp_path):
    report = tmp_path / "trend.json"
    report.write_text(json.dumps({"research_only": False}), encoding="utf-8")
    try:
        shadow.record_trend_shadow(report, "strategy", tmp_path / "journal")
    except ValueError as error:
        assert "research_only" in str(error)
    else:
        raise AssertionError("non-research reports must be rejected")


def test_shadow_rejects_conflicting_snapshot_for_same_market_day(tmp_path):
    report = tmp_path / "trend.json"
    journal = tmp_path / "shadow.jsonl"
    _write_report(report)
    shadow.record_trend_shadow(report, "strategy", journal)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["reports"]["strategy"][
        "latest_rebalance_target_weights"
    ]["ETH"] = -0.12
    report.write_text(json.dumps(payload), encoding="utf-8")
    try:
        shadow.record_trend_shadow(report, "strategy", journal)
    except ValueError as error:
        assert "conflicting shadow snapshot" in str(error)
    else:
        raise AssertionError("same-day conflicting snapshot must fail")
