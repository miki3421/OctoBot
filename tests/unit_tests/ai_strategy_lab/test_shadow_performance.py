import json
import datetime

from octobot.ai_strategy_lab import shadow_performance


def _record(day, close, weight=0.10):
    return {
        "schema_version": 2,
        "market_end_date": f"2026-01-{day:02d}",
        "target_weights": {"BTC": weight},
        "latest_close": {"BTC": close},
        "latest_daily_funding": {"BTC": 0.0},
        "cost_per_turnover": 0.0024,
    }


def test_forward_performance_uses_prior_close_weights(tmp_path):
    journal = tmp_path / "shadow.jsonl"
    records = [_record(1, 100.0), _record(2, 110.0)]
    journal.write_text(
        "\n".join(json.dumps(value) for value in records) + "\n",
        encoding="utf-8",
    )
    report = shadow_performance.evaluate_shadow_performance(journal)
    # Opening cost is 10% * 0.24%; next-day market P&L is 10% * 10%.
    expected = (1 - 0.10 * 0.0024) * (1 + 0.10 * 0.10) - 1
    assert abs(report["metrics"]["total_return"] - expected) < 1e-12
    assert report["observed_return_days"] == 2
    assert report["missing_forward_days"] == 0
    assert report["metrics"]["calendar_months"] == 0
    assert report["metrics"]["monthly_returns"] == {}
    assert "2026-01" in report["metrics"]["month_to_date_returns"]
    assert report["metrics"]["excluded_incomplete_months"] == ["2026-01"]
    assert report["paper_review_gate"]["passed"] is False
    assert report["automatic_promotion"] is False


def test_forward_performance_marks_calendar_gaps(tmp_path):
    journal = tmp_path / "shadow.jsonl"
    records = [_record(1, 100.0), _record(3, 110.0)]
    journal.write_text(
        "\n".join(json.dumps(value) for value in records) + "\n",
        encoding="utf-8",
    )
    report = shadow_performance.evaluate_shadow_performance(journal)
    assert report["missing_forward_days"] == 1
    assert report["skipped_intervals"] == 1
    assert (
        report["paper_review_gate"]["checks"][
            "no_missing_forward_days"
        ]
        is False
    )


def test_forward_monitor_activates_only_a_fully_prefunded_block(tmp_path):
    journal = tmp_path / "shadow.jsonl"
    start = datetime.date(2026, 1, 1)
    records = []
    close = 100.0
    for offset in range(75):
        date = start + datetime.timedelta(days=offset)
        if offset:
            close *= 1.02
        records.append(
            {
                "schema_version": 2,
                "market_end_date": str(date),
                "target_weights": {"BTC": 0.10},
                "latest_close": {"BTC": close},
                "latest_daily_funding": {"BTC": 0.0},
                "cost_per_turnover": 0.0,
            }
        )
    journal.write_text(
        "\n".join(json.dumps(value) for value in records) + "\n",
        encoding="utf-8",
    )

    report = shadow_performance.evaluate_shadow_performance(journal)
    readiness = report["prefunded_income_readiness"]

    assert readiness["status"] == "finite_block_fully_prefunded"
    assert readiness["reserve_target"] == 600
    assert readiness["finite_block_guaranteed"] is True
    assert readiness["guaranteed_future_payments"] > 0
    assert readiness["guaranteed_future_income"] <= 600
    assert readiness["guarantee_breaches"] == 0
    assert readiness["real_payments_authorized"] is False
    assert report["metrics"]["calendar_months"] == 2
    assert set(report["metrics"]["monthly_returns"]) == {
        "2026-01",
        "2026-02",
    }


def test_complete_month_returns_rejects_missing_day():
    dates = [
        datetime.date(2026, 1, day)
        for day in range(1, 32)
        if day != 10
    ]
    complete, excluded = shadow_performance._complete_month_returns(
        dates, {"2026-01": 0.10}
    )

    assert complete == {}
    assert excluded == ["2026-01"]


def test_forward_performance_uses_per_instrument_costs(tmp_path):
    journal = tmp_path / "shadow.jsonl"
    record = _record(1, 100.0)
    record["strategy_name"] = "v14"
    record["cost_per_turnover"] = None
    record["target_weights"] = {"trend:BTC": 0.10, "spot:BTC": 0.05}
    record["latest_close"] = {"trend:BTC": 100.0, "spot:BTC": 100.0}
    record["latest_daily_funding"] = {
        "trend:BTC": 0.0,
        "spot:BTC": 0.0,
    }
    record["cost_per_turnover_by_instrument"] = {
        "trend:BTC": 0.0024,
        "spot:BTC": 0.0036,
    }
    journal.write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = shadow_performance.evaluate_shadow_performance(
        journal, expected_strategy_name="v14"
    )

    assert report["strategy_name"] == "v14"
    assert report["total_cost_return"] == 0.10 * 0.0024 + 0.05 * 0.0036


def test_forward_performance_rejects_wrong_strategy_identity(tmp_path):
    journal = tmp_path / "shadow.jsonl"
    record = _record(1, 100.0)
    record["strategy_name"] = "v3"
    journal.write_text(json.dumps(record) + "\n", encoding="utf-8")

    try:
        shadow_performance.evaluate_shadow_performance(
            journal, expected_strategy_name="v14"
        )
    except ValueError as error:
        assert "expected strategy" in str(error)
    else:
        raise AssertionError("strategy mismatch must fail closed")
