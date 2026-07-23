import datetime
import json

import pytest

from octobot.ai_strategy_lab import shadow_runner


def _config(tmp_path):
    return shadow_runner.ShadowRunnerConfig(
        output_root=tmp_path / "reports",
        journal_path=tmp_path / "shadow" / "journal.jsonl",
        health_path=tmp_path / "shadow" / "health.json",
        lock_path=tmp_path / "shadow" / "runner.lock",
        history_days=250,
    )


def _install_success_mocks(monkeypatch):
    def fetch_market(config, output):
        output.write_bytes(b"collector")
        return {
            "collector": {"sha256": "collector-hash"},
            "coverage": {
                symbol: {"rows": 6000, "gap_count": 0}
                for symbol in config.symbol_mapping
            },
        }

    def fetch_funding(*args, **kwargs):
        return {"rates": {}}

    def save_funding(payload, output):
        output.write_text("{}", encoding="utf-8")
        return {
            "sha256": "funding-hash",
            "points": {
                symbol: 750
                for symbol in shadow_runner.KUCOIN_FUTURES_SYMBOLS
            },
        }

    def evaluate(*args, **kwargs):
        strategy = {
            "evaluation_end_date": "2026-07-22",
            "ending_weights": {"BTC/USDT:USDT": 0.0},
            "latest_rebalance_target_weights": {
                "BTC/USDT:USDT": 0.0
            },
            "latest_signal": {"BTC/USDT:USDT": 0},
            "latest_close": {"BTC/USDT:USDT": 70_000.0},
            "latest_daily_funding": {"BTC/USDT:USDT": 0.0001},
            "days_until_next_rebalance": 4,
            "config": {
                "fee_per_turnover": 0.0018,
                "slippage_per_turnover": 0.0006,
            },
        }
        return {
            "research_only": True,
            "reports": {
                shadow_runner.DEFAULT_STRATEGY: strategy,
            },
        }

    monkeypatch.setattr(
        shadow_runner.market_data_module,
        "fetch_kucoin_futures_hourly",
        fetch_market,
    )
    monkeypatch.setattr(
        shadow_runner.funding_module,
        "fetch_kucoin_funding",
        fetch_funding,
    )
    monkeypatch.setattr(
        shadow_runner.funding_module, "save_funding", save_funding
    )
    monkeypatch.setattr(
        shadow_runner.trend_module, "evaluate_trend", evaluate
    )


def test_runner_publishes_report_journal_and_health_atomically(
    tmp_path, monkeypatch
):
    _install_success_mocks(monkeypatch)
    config = _config(tmp_path)
    result = shadow_runner.run_shadow_once(
        config, as_of_date=datetime.date(2026, 7, 22)
    )
    assert result["status"] == "healthy"
    assert result["orders_authorized"] is False
    assert config.journal_path.is_file()
    assert len(config.journal_path.read_text().splitlines()) == 1
    health = json.loads(config.health_path.read_text())
    assert health["report_sha256"] == result["report_sha256"]
    assert (config.output_root / "trend-shadow-20260722.json").is_file()
    record = json.loads(config.journal_path.read_text())
    assert record["rebalance_weekday_utc"] == 6
    assert record["initialized"] is True
    assert record["cost_per_turnover"] == 0.0024


def test_runner_failure_writes_health_but_no_report_or_journal(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("public endpoint unavailable")

    monkeypatch.setattr(
        shadow_runner.market_data_module,
        "fetch_kucoin_futures_hourly",
        fail,
    )
    try:
        shadow_runner.run_shadow_once(
            config, as_of_date=datetime.date(2026, 7, 22)
        )
    except RuntimeError as error:
        assert "endpoint unavailable" in str(error)
    else:
        raise AssertionError("runner failure must propagate")
    assert not config.journal_path.exists()
    assert not (
        config.output_root / "trend-shadow-20260722.json"
    ).exists()
    health = json.loads(config.health_path.read_text())
    assert health["status"] == "failed"
    assert health["orders_authorized"] is False


def test_shadow_weights_change_only_on_fixed_rebalance_day():
    previous = {
        "market_end_date": "2026-07-22",
        "target_weights": {"BTC": 0.10, "ETH": 0.0},
    }
    candidate = {"BTC": 0.0, "ETH": 0.20}
    carried = shadow_runner._select_applied_weights(
        candidate,
        previous,
        as_of=datetime.date(2026, 7, 23),
        rebalance_due=False,
    )
    rebalanced = shadow_runner._select_applied_weights(
        candidate,
        previous,
        as_of=datetime.date(2026, 7, 26),
        rebalance_due=True,
    )
    assert carried == previous["target_weights"]
    assert rebalanced == candidate


def test_missing_shadow_dates_are_strictly_sequential(tmp_path):
    journal = tmp_path / "journal.jsonl"
    records = [
        {
            "strategy_name": shadow_runner.DEFAULT_STRATEGY,
            "market_end_date": date,
        }
        for date in ("2026-07-22", "2026-07-23")
    ]
    journal.write_text(
        "\n".join(json.dumps(value) for value in records) + "\n",
        encoding="utf-8",
    )

    dates = shadow_runner.missing_shadow_dates(
        journal,
        strategy_name=shadow_runner.DEFAULT_STRATEGY,
        target_date=datetime.date(2026, 7, 25),
        max_catchup_days=7,
    )

    assert dates == [
        datetime.date(2026, 7, 24),
        datetime.date(2026, 7, 25),
    ]


def test_missing_shadow_dates_reject_existing_gap_and_excess(tmp_path):
    journal = tmp_path / "journal.jsonl"
    records = [
        {
            "strategy_name": shadow_runner.DEFAULT_STRATEGY,
            "market_end_date": date,
        }
        for date in ("2026-07-22", "2026-07-24")
    ]
    journal.write_text(
        "\n".join(json.dumps(value) for value in records) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="already contains a gap"):
        shadow_runner.missing_shadow_dates(
            journal,
            strategy_name=shadow_runner.DEFAULT_STRATEGY,
            target_date=datetime.date(2026, 7, 25),
            max_catchup_days=7,
        )

    journal.write_text(
        json.dumps(
            {
                "strategy_name": shadow_runner.DEFAULT_STRATEGY,
                "market_end_date": "2026-07-22",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires 3 days"):
        shadow_runner.missing_shadow_dates(
            journal,
            strategy_name=shadow_runner.DEFAULT_STRATEGY,
            target_date=datetime.date(2026, 7, 25),
            max_catchup_days=2,
        )


def test_catchup_runs_each_missing_day_and_reports_new_dates(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    config.journal_path.parent.mkdir(parents=True)
    config.journal_path.write_text(
        json.dumps(
            {
                "strategy_name": shadow_runner.DEFAULT_STRATEGY,
                "market_end_date": "2026-07-22",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    called = []

    def run_once(_config, *, as_of_date):
        called.append(as_of_date)
        return {"as_of_date": str(as_of_date), "status": "healthy"}

    monkeypatch.setattr(shadow_runner, "run_shadow_once", run_once)
    result = shadow_runner.run_shadow_catchup(
        config,
        max_catchup_days=7,
        today_utc=datetime.date(2026, 7, 25),
    )

    assert called == [
        datetime.date(2026, 7, 23),
        datetime.date(2026, 7, 24),
    ]
    assert result["caught_up_days"] == 2
    assert result["cycles"] == 2


def test_catchup_limit_failure_updates_health(tmp_path):
    config = _config(tmp_path)
    config.journal_path.parent.mkdir(parents=True)
    config.journal_path.write_text(
        json.dumps(
            {
                "strategy_name": shadow_runner.DEFAULT_STRATEGY,
                "market_end_date": "2026-07-20",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="limit=2"):
        shadow_runner.run_shadow_catchup(
            config,
            max_catchup_days=2,
            today_utc=datetime.date(2026, 7, 25),
        )

    health = json.loads(config.health_path.read_text(encoding="utf-8"))
    assert health["status"] == "failed"
    assert health["orders_authorized"] is False
