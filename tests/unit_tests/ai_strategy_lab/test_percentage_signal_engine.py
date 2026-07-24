import copy

import pytest

from octobot.ai_strategy_lab import percentage_engine
from octobot.ai_strategy_lab import percentage_signal_engine


def _rising_candles(count=140):
    closes = [100 * (1.001**index) for index in range(count)]
    opens = [closes[0], *closes[:-1]]
    highs = [max(open_, close) * 1.0005 for open_, close in zip(opens, closes)]
    lows = [min(open_, close) * 0.9995 for open_, close in zip(opens, closes)]
    return {
        "times": [f"t{index}" for index in range(count)],
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": [1000 + index for index in range(count)],
    }


def _permissive_trend_rule():
    return percentage_signal_engine.PercentageSignalRule(
        maximum_atr_pct=1,
        minimum_directional_ema_spread_pct=0.0001,
        minimum_directional_ema_slope_pct=0.0001,
        round_trip_cost_pct=0.16,
    )


def test_causal_rule_creates_only_resolved_non_overlapping_long_trades():
    candles = _rising_candles()

    result = percentage_signal_engine.analyze_causal_percentage_signals(
        **candles,
        rule=_permissive_trend_rule(),
    )

    assert result["signal_uses_future_outcomes"] is False
    assert result["evaluation_uses_future_outcomes"] is True
    assert result["orders_authorized"] is False
    assert result["automatic_promotion"] is False
    assert result["trades"]
    assert all(trade["direction"] == percentage_engine.LONG for trade in result["trades"])
    assert all(trade["signal_uses_future"] is False for trade in result["trades"])
    assert all(
        trade["entry_index"] + result["percentage_config"]["horizon_candles"]
        <= result["chart_summary"]["closed_candles"] - 1
        for trade in result["trades"]
    )
    assert all(
        left["exit_index"] < right["entry_index"]
        for left, right in zip(result["trades"], result["trades"][1:])
    )


def test_entry_features_do_not_change_when_only_future_candles_change():
    candles = _rising_candles()
    changed = copy.deepcopy(candles)
    entry_index = 80
    for index in range(entry_index + 1, len(changed["closes"])):
        changed["opens"][index] *= 1.5
        changed["highs"][index] *= 1.5
        changed["lows"][index] *= 1.5
        changed["closes"][index] *= 1.5
        changed["volumes"][index] *= 10

    original_features = percentage_signal_engine._build_feature_arrays(
        candles["opens"],
        candles["highs"],
        candles["lows"],
        candles["closes"],
        candles["volumes"],
    )
    changed_features = percentage_signal_engine._build_feature_arrays(
        changed["opens"],
        changed["highs"],
        changed["lows"],
        changed["closes"],
        changed["volumes"],
    )

    original_match = percentage_signal_engine._matches_rule(
        original_features,
        entry_index,
        percentage_engine.LONG,
        _permissive_trend_rule(),
    )
    changed_match = percentage_signal_engine._matches_rule(
        changed_features,
        entry_index,
        percentage_engine.LONG,
        _permissive_trend_rule(),
    )

    assert changed_match == original_match


def test_round_trip_cost_is_deducted_from_every_completed_trade():
    result = percentage_signal_engine.analyze_causal_percentage_signals(
        **_rising_candles(),
        rule=_permissive_trend_rule(),
    )

    for trade in result["trades"]:
        assert trade["net_return_pct"] == pytest.approx(
            trade["gross_return_pct"] - 0.16
        )


def test_frozen_evidence_fails_count_and_frequency_without_authorizing_orders():
    result = percentage_signal_engine.analyze_causal_percentage_signals(
        **_rising_candles(),
        rule=_permissive_trend_rule(),
    )

    assert result["evidence_gate"]["passed"] is False
    assert result["evidence_gate"]["checks"] == {
        "enough_test_trades": False,
        "profit_factor": True,
        "win_rate": True,
        "frequency": False,
    }
    assert result["orders_authorized"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("volumes", []),
        ("volumes", [1, -1]),
    ],
)
def test_invalid_volume_inputs_are_rejected(field, value):
    candles = _rising_candles()
    candles[field] = value

    with pytest.raises(ValueError):
        percentage_signal_engine.analyze_causal_percentage_signals(
            **candles,
            rule=_permissive_trend_rule(),
        )
