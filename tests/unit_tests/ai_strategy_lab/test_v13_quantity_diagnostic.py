import datetime

import numpy as np
import pytest

from octobot.ai_strategy_lab import v13_quantity_diagnostic as diagnostic


def panel(prices, rates=None):
    return {
        "closes": np.asarray(prices, dtype=float)[:, None],
        "funding": np.asarray(rates if rates is not None else [0] * len(prices))[:, None],
        "dates": [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(len(prices))],
    }


def test_quantities_stay_fixed_between_rebalances():
    result = diagnostic.account_targets(panel([100, 100, 120, 100]), {1: [0.5]}, 1, 0)
    assert result["final_equity"] == 10000  # 50 units held, not daily 50% weight.
    assert result["turnover_usdt"] == 5000
    assert result["max_drawdown"] == pytest.approx(1 - 10000 / 11000)


def test_rebalance_charges_actual_drifted_notional_and_costs_once():
    result = diagnostic.account_targets(panel([100, 100, 200]), {1: [0.5], 2: [0.5]}, 1, 0.001)
    # Entry50units costs5. Equity14995; next target37.4875units sells12.5125.
    assert result["turnover_usdt"] == pytest.approx(7502.5)
    assert result["transaction_costs_usdt"] == pytest.approx(7.5025)
    assert result["final_equity"] == pytest.approx(14992.4975)


@pytest.mark.parametrize("weight,expected", [(0.5, -5), (-0.5, 5)])
def test_funding_signed_from_existing_quantity_not_new_target(weight, expected):
    result = diagnostic.account_targets(panel([100, 100, 100], [0, 0.9, 0.001]), {1: [weight]}, 1, 0)
    assert result["funding_pnl_usdt"] == expected
    assert result["final_equity"] == 10000 + expected


def test_short_uses_linear_not_inverse_contract_return():
    result = diagnostic.account_targets(panel([100, 100, 80]), {1: [-0.5]}, 1, 0)
    assert result["final_equity"] == 11000


def test_bad_market_and_target_fail_closed():
    with pytest.raises(ValueError, match="inputs"):
        diagnostic.account_targets(panel([100, 0, 80]), {1: [-0.5]}, 1, 0)
    with pytest.raises(ValueError, match="target"):
        diagnostic.account_targets(panel([100, 100, 80]), {1: [float("nan")]}, 1, 0)
