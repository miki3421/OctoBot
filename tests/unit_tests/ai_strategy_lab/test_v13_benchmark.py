"""Independent accounting and point-in-time checks for the frozen comparison."""

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest

from octobot.ai_strategy_lab import trend
from octobot.ai_strategy_lab import v13_benchmark as benchmark


def market(prices, funding=None):
    closes = np.asarray(prices, dtype=float)
    if closes.ndim == 1:
        closes = closes[:, None]
    rates = np.zeros_like(closes) if funding is None else np.asarray(funding, dtype=float)
    if rates.ndim == 1:
        rates = rates[:, None]
    returns = np.zeros_like(closes)
    returns[1:] = closes[1:] / closes[:-1] - 1
    return {
        "dates": [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(len(closes))],
        "symbols": [f"ASSET{i}/USDT:USDT" for i in range(closes.shape[1])],
        "closes": closes,
        "returns": returns,
        "funding": rates,
    }


def config():
    return trend.TrendConfig(
        name="synthetic_comparison", signal_kind="dual_momentum", fast_days=5,
        slow_days=30, volatility_lookback_days=20, rebalance_days=7,
        target_annual_volatility=0.135, maximum_gross_exposure=0.9,
        maximum_asset_exposure=0.315,
    )


def synthetic_market(days=90):
    index = np.arange(days, dtype=float)
    daily = np.column_stack([
        0.003 + 0.009 * np.sin(index * 0.7),
        0.003 + 0.04 * np.sin(index * 0.8),
        -0.001 + 0.08 * np.cos(index * 0.6),
    ])
    return market(100 * np.exp(np.cumsum(daily, axis=0)))


def test_ew_control_really_equal_weight_despite_unequal_asset_volatilities():
    panel, cfg = synthetic_market(), config()
    targets = benchmark.build_targets(panel, cfg)
    for weights in targets["ew_vol_budget"].values():
        assert weights[0] > 0
        np.testing.assert_allclose(weights, weights[0], rtol=0, atol=0)
        assert sum(weights) <= cfg.maximum_gross_exposure + 1e-12
        assert max(weights) <= cfg.maximum_asset_exposure + 1e-12
    # Check the actual ex-ante risk budget, independently from target builder.
    index = cfg.slow_days
    covariance = np.cov(panel["returns"][index - 19:index + 1], rowvar=False) * 365
    unit = np.ones(3) / 3
    sigma = np.sqrt(unit @ covariance @ unit)
    assert sum(targets["ew_vol_budget"][index]) == pytest.approx(0.135 / sigma)


def test_matched_gross_preserves_v13_schedule_and_gross_not_its_signs():
    targets = benchmark.build_targets(synthetic_market(), config())
    assert targets["ew_v13_gross"].keys() == targets["v13_quantities"].keys()
    for index, weights in targets["v13_quantities"].items():
        control = targets["ew_v13_gross"][index]
        assert np.all(control >= 0)
        np.testing.assert_allclose(control, np.abs(weights).sum() / 3)
    assert len(targets["buy_hold_90pct"]) == 1
    np.testing.assert_allclose(targets["buy_hold_90pct"][30], [0.3, 0.3, 0.3])
    assert targets["cash"] == {}


def test_targets_do_not_change_when_future_prices_are_absent_or_changed():
    panel, cfg = synthetic_market(), config()
    prefix = {key: value[:66] if key != "symbols" else value for key, value in panel.items()}
    original = benchmark.build_targets(panel, cfg)
    truncated = benchmark.build_targets(prefix, cfg)
    modified = market(panel["closes"].copy())
    modified["closes"][66:] *= np.array([0.05, 20, 4])
    future_changed = benchmark.build_targets(modified, cfg)
    for name in benchmark.NAMES:
        for index, weights in truncated[name].items():
            np.testing.assert_array_equal(weights, original[name][index])
            np.testing.assert_array_equal(weights, future_changed[name][index])


def test_zero_estimated_volatility_produces_flat_risk_budget_control():
    targets = benchmark.build_targets(market(np.full((60, 3), 100.0)), config())
    assert all(np.count_nonzero(weights) == 0 for weights in targets["ew_vol_budget"].values())


def test_delayed_trade_receives_no_price_or_funding_pnl_before_execution():
    panel = market([100, 100, 200, 300], [0, 0.8, 0.7, 0.01])
    result = benchmark.simulate(panel, {1: [0.5]}, 1, 0, 0, delay_days=1)
    assert result["trajectory"]["equity"] == pytest.approx([10000, 10000, 10000, 12450])
    assert result["assets"][0]["final_quantity"] == 25
    assert result["funding_pnl"] == -50
    assert result["price_pnl"] == 2500


def test_delay_outside_horizon_does_not_charge_or_create_a_trade():
    result = benchmark.simulate(market([100, 100, 200]), {2: [0.9]}, 1, 0.01, 0.02, delay_days=1)
    assert result["final_equity"] == 10000
    assert result["fills"] == result["rebalance_dates_executed"] == 0
    assert result["delayed_targets_outside_window"] == 1


def test_buy_hold_keeps_quantities_and_reports_gross_drift():
    result = benchmark.simulate(market([100, 100, 200, 100]), {1: [0.5]}, 1, 0, 0)
    assert result["trajectory"]["equity"] == [10000, 10000, 15000, 10000]
    assert result["trajectory"]["gross"] == pytest.approx([0.5, 2/3, 0.5])
    assert result["assets"][0]["final_quantity"] == 50
    assert result["turnover_usdt"] == 5000
    assert result["fills"] == 1
    assert result["max_drawdown"] == pytest.approx(1/3)


def test_signed_funding_attribution_fees_and_terminal_mark_reconcile():
    panel = market([[100, 200], [100, 200], [120, 180]], [[0, 0], [.8, .9], [.001, -.002]])
    result = benchmark.simulate(panel, {1: [.5, -.25]}, 1, .0006, .0002)
    assert result["price_pnl"] == 1250
    assert result["funding_pnl"] == -10
    assert result["fees"] == pytest.approx(4.5)
    assert result["slippage"] == pytest.approx(1.5)
    assert result["final_equity"] == pytest.approx(11234)
    assert result["turnover_usdt"] == 7500
    assert result["fills"] == 2  # Initial fills only; no implicit terminal closing.
    assert result["hypothetical_terminal_cost_excluded"] == pytest.approx(6.6)
    assert sum(asset["net_pnl"] for asset in result["assets"]) == pytest.approx(result["net_pnl"])
    assert result["reconciliation_residual"] == pytest.approx(0)


def test_cash_is_zero_return_even_with_large_moves_and_funding():
    result = benchmark.simulate(market([100, 30, 200], [.1, -.2, .5]), {}, 1, .1, .2)
    assert result["final_equity"] == 10000
    assert result["price_pnl"] == result["funding_pnl"] == result["transaction_costs"] == 0
    assert result["max_actual_gross_exposure"] == result["max_drawdown"] == 0
    assert result["sharpe_zero_rate"] is None


def test_rebalance_uses_drifted_notional_and_stress_recomputes_quantity():
    panel, targets = market([100, 100, 200]), {1: [.5], 2: [.5]}
    base = benchmark.simulate(panel, targets, 1, .0006, .0004)
    stress = benchmark.simulate(panel, targets, 1, .0018, .0012)
    assert base["turnover_usdt"] == pytest.approx(7502.5)
    assert base["assets"][0]["final_quantity"] == pytest.approx(37.4875)
    assert base["final_equity"] == pytest.approx(14992.4975)
    assert stress["turnover_usdt"] == pytest.approx(7507.5)
    assert stress["assets"][0]["final_quantity"] == pytest.approx(37.4625)
    assert stress["final_equity"] == pytest.approx(14977.4775)
    assert abs(stress["final_equity"] - (base["final_equity"] - 2 * base["transaction_costs"])) > .01


@pytest.mark.parametrize("date_offsets", [[0, 1, 3], [0, 1, 1], [0, 2, 1]])
def test_nonconsecutive_duplicate_and_reversed_calendars_rejected(date_offsets):
    panel = market([100, 101, 102])
    panel["dates"] = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in date_offsets]
    with pytest.raises(ValueError, match="calendar"):
        benchmark.simulate(panel, {}, 1, 0, 0)


@pytest.mark.parametrize("field,bad", [("closes", np.nan), ("closes", np.inf), ("closes", 0), ("funding", np.nan)])
def test_invalid_market_numbers_rejected(field, bad):
    panel = market([100, 101, 102])
    panel[field][1, 0] = bad
    with pytest.raises(ValueError, match="market"):
        benchmark.simulate(panel, {}, 1, 0, 0)


@pytest.mark.parametrize("targets", [{1: [np.nan]}, {1: [1, 2]}, {0: [.5]}, {3: [.5]}])
def test_invalid_target_schedule_rejected(targets):
    with pytest.raises(ValueError, match="target"):
        benchmark.simulate(market([100, 101, 102]), targets, 1, 0, 0)


def test_compare_runs_all_frozen_conventions_costs_and_paired_controls():
    panel, cfg = synthetic_market(), config()
    result = benchmark.compare(panel, cfg)
    assert {(row["delay_days"], row["cost_multiplier"]) for row in result["scenarios"]} == {(0, 1), (0, 3), (1, 1), (1, 3)}
    for scenario in result["scenarios"]:
        assert set(scenario["portfolios"]) == set(benchmark.NAMES)
        assert set(scenario["v13_minus_control"]) == set(benchmark.NAMES[1:])
        assert all("trajectory" not in value for value in scenario["portfolios"].values())
        assert scenario["portfolios"]["cash"]["net_total_return"] == 0
        assert scenario["v13_minus_control"]["cash"]["beta_descriptive"] is None
    base, stress = result["scenarios"][:2]
    assert base["portfolios"]["ew_vol_budget"]["assets"][0]["final_quantity"] != stress["portfolios"]["ew_vol_budget"]["assets"][0]["final_quantity"]


def test_calendar_periods_flag_incomplete_edges():
    panel = market(np.full(75, 100.0))
    result = benchmark.simulate(panel, {}, 1, 0, 0)
    assert [(row["period"], row["partial"]) for row in result["months"]] == [
        ("2026-01", True), ("2026-02", False), ("2026-03", True),
    ]
    assert result["years"][0]["partial"] is True


@pytest.mark.parametrize("section,key,value", [
    (None, "results", {}),
    (None, "automatic_promotion", True),
    ("historical", "initial_equity", 20000),
    ("historical", "cost_multipliers", [1, 2]),
    ("historical", "cost_multipliers", [True, 3]),
    ("historical", "execution_conventions", ["same_close_diagnostic"]),
])
def test_changed_method_fails_before_loading_inputs(tmp_path, monkeypatch, section, key, value):
    path = Path(__file__).resolve().parents[3] / "reports/v13-benchmark-method-2026-09-13.json"
    method = json.loads(path.read_text())
    (method if section is None else method[section])[key] = value
    changed = tmp_path / "changed-method.json"
    changed.write_text(json.dumps(method))

    def forbidden_loader(_):
        pytest.fail("invalid method must be rejected before market access")

    monkeypatch.setattr(benchmark.trainer, "_load_trend_component", forbidden_loader)
    with pytest.raises(ValueError, match="method|comparison"):
        benchmark.run_comparison("unused", changed)
