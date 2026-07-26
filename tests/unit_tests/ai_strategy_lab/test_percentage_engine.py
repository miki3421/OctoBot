import math

import pytest

from octobot.ai_strategy_lab import percentage_engine


def _candles(rows):
    return {
        "times": [f"t{index}" for index in range(len(rows))],
        "opens": [row[0] for row in rows],
        "highs": [row[1] for row in rows],
        "lows": [row[2] for row in rows],
        "closes": [row[3] for row in rows],
    }


def test_long_profit_lock_activates_then_exits_on_following_candle():
    values = _candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 101.3, 99.5, 101.1),
            (101.1, 101.4, 100.8, 101.2),
            (101.2, 101.3, 101.1, 101.2),
        ]
    )
    config = percentage_engine.PercentageEngineConfig(exclude_last_candle=False)

    result = percentage_engine.simulate_trade(
        values["times"],
        values["highs"],
        values["lows"],
        values["closes"],
        0,
        percentage_engine.LONG,
        3,
        config,
    )

    assert result["target_reached"] is True
    assert result["activation_index"] == 1
    assert result["exit_index"] == 2
    assert result["exit_reason"] == "profit_lock"
    assert result["exit_price"] == pytest.approx(101)
    assert result["gross_return_pct"] == pytest.approx(1)


def test_initial_stop_wins_when_stop_and_activation_share_a_candle():
    values = _candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 101.3, 98.9, 100.5),
            (100.5, 101, 100, 100.8),
        ]
    )
    config = percentage_engine.PercentageEngineConfig(exclude_last_candle=False)

    result = percentage_engine.simulate_trade(
        values["times"],
        values["highs"],
        values["lows"],
        values["closes"],
        0,
        percentage_engine.LONG,
        2,
        config,
    )

    assert result["target_reached"] is False
    assert result["exit_reason"] == "initial_stop"
    assert result["exit_price"] == pytest.approx(99)
    assert result["gross_return_pct"] == pytest.approx(-1)


def test_short_profit_lock_is_symmetric():
    values = _candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 100.5, 98.7, 98.9),
            (98.9, 99.2, 98.5, 98.8),
            (98.8, 99, 98.5, 98.7),
        ]
    )
    config = percentage_engine.PercentageEngineConfig(exclude_last_candle=False)

    result = percentage_engine.simulate_trade(
        values["times"],
        values["highs"],
        values["lows"],
        values["closes"],
        0,
        percentage_engine.SHORT,
        3,
        config,
    )

    assert result["target_reached"] is True
    assert result["activation_index"] == 1
    assert result["exit_index"] == 2
    assert result["exit_reason"] == "profit_lock"
    assert result["exit_price"] == pytest.approx(99)
    assert result["gross_return_pct"] == pytest.approx(1)


def test_analyzer_excludes_open_candle_and_never_authorizes_orders():
    values = _candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 101.3, 99.5, 101.1),
            (101.1, 101.4, 100.8, 101.2),
            (101.2, 103, 98, 102),
        ]
    )

    result = percentage_engine.analyze_percentage_opportunities(**values)

    assert result["mode"] == "hindsight_percentage_research_only"
    assert result["uses_future_outcomes"] is True
    assert result["orders_authorized"] is False
    assert result["automatic_promotion"] is False
    assert result["summary"]["closed_candles"] == 3
    assert all(trade["exit_index"] <= 2 for trade in result["trades"])


def test_analyzer_marks_right_edge_as_provisional():
    rows = [(100, 101.5, 99.5, 100.5)] * 8
    values = _candles(rows)
    config = percentage_engine.PercentageEngineConfig(
        horizon_candles=3,
        exclude_last_candle=False,
    )

    result = percentage_engine.analyze_percentage_opportunities(
        **values, config=config
    )

    assert result["schema_version"] == 2
    assert result["maturity"] == {
        "full_horizon_candles": 3,
        "last_closed_index": 7,
        "last_closed_time": "t7",
        "last_mature_entry_index": 4,
        "last_mature_entry_time": "t4",
        "provisional_start_index": 5,
        "provisional_start_time": "t5",
        "provisional_entry_candles": 2,
    }
    assert result["summary"]["confirmed_evaluated_setups"] == 10
    assert result["summary"]["provisional_evaluated_setups"] == 4


def test_analyzer_handles_history_shorter_than_full_horizon():
    values = _candles([(100, 101, 99, 100)] * 4)
    config = percentage_engine.PercentageEngineConfig(
        horizon_candles=24,
        exclude_last_candle=False,
    )

    result = percentage_engine.analyze_percentage_opportunities(
        **values, config=config
    )

    assert result["maturity"]["last_mature_entry_index"] is None
    assert result["maturity"]["last_mature_entry_time"] is None
    assert result["maturity"]["provisional_start_index"] == 0
    assert result["summary"]["confirmed_evaluated_setups"] == 0
    assert result["summary"]["provisional_evaluated_setups"] == 6
    assert result["summary"]["historical_hit_rate_pct"] == 0


def test_non_overlapping_selection_maximizes_compounded_return():
    candidates = [
        {"entry_index": 0, "exit_index": 2, "direction": "LONG", "gross_return_pct": 2.0},
        {"entry_index": 0, "exit_index": 1, "direction": "LONG", "gross_return_pct": 1.0},
        {"entry_index": 2, "exit_index": 3, "direction": "SHORT", "gross_return_pct": 1.5},
    ]

    selected = percentage_engine._select_non_overlapping_maximum_compound(candidates)

    assert [(trade["entry_index"], trade["exit_index"]) for trade in selected] == [
        (0, 1),
        (2, 3),
    ]
    assert math.prod(1 + trade["gross_return_pct"] / 100 for trade in selected) == pytest.approx(
        1.01 * 1.015
    )


@pytest.mark.parametrize(
    "config",
    [
        percentage_engine.PercentageEngineConfig(minimum_profit_pct=0),
        percentage_engine.PercentageEngineConfig(
            minimum_profit_pct=1, activation_pct=1
        ),
        percentage_engine.PercentageEngineConfig(initial_stop_pct=0),
        percentage_engine.PercentageEngineConfig(horizon_candles=0),
        percentage_engine.PercentageEngineConfig(directions=("LONG", "LONG")),
    ],
)
def test_invalid_configuration_is_rejected(config):
    with pytest.raises(ValueError):
        config.validate()
