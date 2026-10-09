from octobot.ai_strategy_lab.legacy_baseline_audit import closed_metrics, recost
import pytest


def test_inverse_does_not_reverse_fees():
    result = closed_metrics([{"gross_price_pnl": -100, "known_fees": 10,
                              "net_pnl_excluding_funding": -110}])
    assert result["net_ex_funding_usdt"] == -110
    assert result["same_exit_inverse_ex_funding_usdt"] == 90


def test_linear_short_denominator_and_real_triple_costs():
    trade = {"entry_price": 100, "exit_price": 90, "side": "short"}
    cost = .0008 * 1.9
    assert recost(trade) == pytest.approx(.1-cost)
    assert recost(trade, 3) == pytest.approx(.1-3*cost)
    assert .1-recost(trade, 3) == pytest.approx(3*(.1-recost(trade)))


def test_both_directions_pay_costs_even_on_a_flat_price():
    for side in ("long", "short"):
        assert recost({"entry_price": 100, "exit_price": 100, "side": side}) == -.0016
