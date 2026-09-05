import numpy

from octobot.ai_strategy_lab import semantic_trend_v2_research as research


def _candles(prices):
    values = numpy.zeros((len(prices), 6), dtype=float)
    values[:, 0] = 1_700_000_000 + numpy.arange(len(prices)) * 900
    values[:, 1] = prices
    values[:, 2] = prices * 1.001
    values[:, 3] = prices * 0.999
    values[:, 4] = prices
    values[:, 5] = 1
    return values


def test_protocol_is_terminal_and_orderless():
    protocol = research.frozen_protocol()

    assert protocol["results"] is None
    assert protocol["candidate"]["parameter_search"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["interpretation"]["failure_action"].startswith("reject")


def test_long_stop_is_conservative():
    candles = _candles(numpy.full(100, 100.0))
    candles[1, 3] = 98.5

    trade = research._simulate_trade(candles, 0, "long")

    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_price"] == 99.0
    assert trade["gross_return"] < 0


def test_profit_lock_applies_after_activation():
    candles = _candles(numpy.full(100, 100.0))
    candles[1, 2] = 101.3
    candles[2, 3] = 100.9

    trade = research._simulate_trade(candles, 0, "long")

    assert trade["exit_reason"] == "locked_profit"
    assert trade["exit_price"] == 101.0
    assert trade["gross_return"] > 0


def test_gates_are_conjunctive():
    good = {
        "base": {"trades": 12, "total_return": 0.02, "profit_factor": 1.2},
        "stress": {
            "total_return": 0.01,
            "profit_factor": 1.1,
            "maximum_drawdown": 0.01,
            "positive_active_month_fraction": 0.67,
        },
    }
    legacy = {"stress": {"total_return": -0.01}}
    sides = {"long": {"approved": True}, "short": {"approved": False}}

    assert research.evaluate_gates(good, legacy, sides)["all_passed"] is True
    good["stress"]["profit_factor"] = 0.99
    assert research.evaluate_gates(good, legacy, sides)["all_passed"] is False
