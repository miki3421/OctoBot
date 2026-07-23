import datetime
import json

from octobot.ai_strategy_lab import carry
from octobot.ai_strategy_lab import carry_shadow_runner


def _config(tmp_path):
    return carry_shadow_runner.CarryShadowRunnerConfig(
        output_root=tmp_path / "reports",
        journal_path=tmp_path / "shadow" / "journal.jsonl",
        health_path=tmp_path / "shadow" / "health.json",
        lock_path=tmp_path / "shadow" / "runner.lock",
        history_days=250,
    )


def test_instrument_state_keeps_trend_and_carry_legs_separate():
    carry_config = carry.CarryConfig(
        name="test",
        lookback_settlements=3,
        entry_average_rate=0.0,
        entry_min_monthly_gross=0.0,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=10,
        spot_fee_per_fill=0.003,
        futures_fee_per_fill=0.0018,
        slippage_per_fill=0.0006,
    )
    state = carry_shadow_runner._instrument_state(
        {"BTC/USDT:USDT": 0.30},
        {"BTC/USDT:USDT": 1},
        [("BTC", "BTC/USDT:USDT", "BTC/USDT")],
        [{"position_open_at_end": True}],
        {"BTC/USDT:USDT": 100.0},
        {"BTC/USDT": 99.0},
        {"BTC/USDT:USDT": 0.001},
        carry_config,
        trend_cost_per_turnover=0.0024,
        max_overlay_fraction=0.20,
    )

    assert state["weights"]["trend:BTC/USDT:USDT"] == 0.30
    assert state["weights"]["carry-futures:BTC/USDT:USDT"] == -0.10
    assert state["weights"]["carry-spot:BTC/USDT"] == 0.10
    assert state["conservative_gross_exposure"] == 0.50
    assert state["costs"]["trend:BTC/USDT:USDT"] == 0.0024
    assert state["costs"]["carry-futures:BTC/USDT:USDT"] == 0.0024
    assert state["costs"]["carry-spot:BTC/USDT"] == 0.0036


def test_v14_trend_weights_change_only_on_sunday():
    candidate = {"BTC/USDT:USDT": 0.20}
    previous = {
        "market_end_date": "2026-07-22",
        "target_weights": {
            "trend:BTC/USDT:USDT": 0.10,
            "carry-futures:BTC/USDT:USDT": -0.05,
            "carry-spot:BTC/USDT": 0.05,
        },
    }
    carried = carry_shadow_runner._select_applied_trend_weights(
        candidate,
        previous,
        as_of=datetime.date(2026, 7, 23),
        rebalance_due=False,
    )
    rebalanced = carry_shadow_runner._select_applied_trend_weights(
        candidate,
        previous,
        as_of=datetime.date(2026, 7, 26),
        rebalance_due=True,
    )

    assert carried == {"BTC/USDT:USDT": 0.10}
    assert rebalanced == candidate


def test_v14_runner_publishes_only_no_order_artifacts(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)

    def fetch_market(_config, output):
        output.write_bytes(b"collector")
        return {
            "collector": {"sha256": f"hash-{output.name}"},
            "coverage": {},
        }

    def fetch_funding(*_args, **_kwargs):
        return {"rates": {}}

    def save_funding(_payload, output):
        output.write_text("{}", encoding="utf-8")
        return {"sha256": "funding-hash", "points": {}}

    def build_report(*_args, **_kwargs):
        weights = {
            "trend:BTC/USDT:USDT": 0.10,
            "carry-futures:BTC/USDT:USDT": -0.05,
            "carry-spot:BTC/USDT": 0.05,
        }
        return {
            "research_only": True,
            "orders_authorized": False,
            "reports": {
                carry_shadow_runner.STRATEGY_NAME: {
                    "evaluation_end_date": "2026-07-22",
                    "ending_weights": weights,
                    "latest_rebalance_target_weights": weights,
                    "shadow_applied_weights": weights,
                    "latest_signal": {
                        key: 0 for key in weights
                    },
                    "latest_close": {
                        key: 100.0 for key in weights
                    },
                    "latest_daily_funding": {
                        key: 0.0 for key in weights
                    },
                    "days_until_next_rebalance": 4,
                }
            },
            "shadow_runner": {
                "rebalance_weekday_utc": 6,
                "rebalance_due": False,
                "initialized": True,
                "cost_per_turnover": None,
                "cost_per_turnover_by_instrument": {
                    key: 0.0024 for key in weights
                },
            },
        }

    monkeypatch.setattr(
        carry_shadow_runner.market_data_module,
        "fetch_kucoin_futures_hourly",
        fetch_market,
    )
    monkeypatch.setattr(
        carry_shadow_runner.market_data_module,
        "fetch_kucoin_spot_hourly",
        fetch_market,
    )
    monkeypatch.setattr(
        carry_shadow_runner.funding_module,
        "fetch_kucoin_funding",
        fetch_funding,
    )
    monkeypatch.setattr(
        carry_shadow_runner.funding_module,
        "save_funding",
        save_funding,
    )
    monkeypatch.setattr(
        carry_shadow_runner, "_build_report", build_report
    )

    result = carry_shadow_runner.run_shadow_once(
        config, as_of_date=datetime.date(2026, 7, 22)
    )

    assert result["status"] == "healthy"
    assert result["orders_authorized"] is False
    record = json.loads(config.journal_path.read_text(encoding="utf-8"))
    assert record["strategy_name"] == carry_shadow_runner.STRATEGY_NAME
    assert record["orders_authorized"] is False
    assert record["cost_per_turnover_by_instrument"]


def test_v14_catchup_uses_v14_identity(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.journal_path.parent.mkdir(parents=True)
    config.journal_path.write_text(
        json.dumps(
            {
                "strategy_name": carry_shadow_runner.STRATEGY_NAME,
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

    monkeypatch.setattr(carry_shadow_runner, "run_shadow_once", run_once)
    result = carry_shadow_runner.run_shadow_catchup(
        config,
        max_catchup_days=7,
        today_utc=datetime.date(2026, 7, 25),
    )

    assert called == [
        datetime.date(2026, 7, 23),
        datetime.date(2026, 7, 24),
    ]
    assert result["strategy_name"] == carry_shadow_runner.STRATEGY_NAME
    assert result["caught_up_days"] == 2
