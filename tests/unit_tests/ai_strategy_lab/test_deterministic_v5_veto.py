import sqlite3

import numpy

from octobot.ai_strategy_lab import deterministic_v5_veto as veto
from octobot.ai_strategy_lab import perfect_map_student_v5 as v5


def _candles(count=120):
    timestamp = 1_780_000_000
    timestamp -= timestamp % veto.CANDLE_SECONDS
    close = numpy.full(count, 100.0)
    return numpy.column_stack(
        (
            timestamp + numpy.arange(count) * veto.CANDLE_SECONDS,
            close,
            close + 0.1,
            close - 0.1,
            close,
            numpy.full(count, 1000.0),
        )
    )


def test_protocol_is_result_free_and_cannot_authorize_orders(tmp_path):
    protocol = veto.frozen_protocol()

    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["implementation"]["results_in_this_protocol"] is False
    assert protocol["veto"]["can_create_signal"] is False

    path = veto.write_protocol(tmp_path)
    assert path.is_file()


def test_veto_requires_direction_threshold_and_margin():
    allowed = veto.veto_decision(
        direction=v5.DIRECTIONS[0],
        long_expected_net_pct=0.12,
        short_expected_net_pct=0.02,
    )
    opposite = veto.veto_decision(
        direction=v5.DIRECTIONS[0],
        long_expected_net_pct=0.08,
        short_expected_net_pct=0.10,
    )
    low_score = veto.veto_decision(
        direction=v5.DIRECTIONS[0],
        long_expected_net_pct=0.07,
        short_expected_net_pct=0.01,
    )
    low_margin = veto.veto_decision(
        direction=v5.DIRECTIONS[0],
        long_expected_net_pct=0.09,
        short_expected_net_pct=0.07,
    )

    assert allowed[:2] == (True, "allowed")
    assert opposite[:2] == (
        False,
        "v5_prefers_opposite_direction",
    )
    assert low_score[:2] == (
        False,
        "v5_expected_net_below_threshold",
    )
    assert low_margin[:2] == (
        False,
        "v5_direction_margin_below_threshold",
    )


def test_fixed_trade_uses_stop_first_in_ambiguous_candle():
    candles = _candles()
    candles[1, 2] = 105.0
    candles[1, 3] = 97.0

    trade = veto.simulate_fixed_trade(
        candles=candles,
        entry_index=0,
        direction=v5.DIRECTIONS[0],
        round_trip_cost_pct=veto.ROUND_TRIP_COST_PCT,
        funding_timestamps=numpy.asarray([], dtype=numpy.int64),
        funding_rates=numpy.asarray([], dtype=float),
    )

    assert trade["outcome"] == "STOP"
    assert trade["exit_price"] == 98.0
    assert numpy.isclose(trade["net_return_pct"], -2.16)


def test_fixed_trade_applies_signed_funding():
    candles = _candles()
    candles[4, 2] = 105.0
    entry_timestamp = int(candles[0, 0]) + veto.CANDLE_SECONDS
    funding_timestamp = entry_timestamp + 2 * veto.CANDLE_SECONDS

    trade = veto.simulate_fixed_trade(
        candles=candles,
        entry_index=0,
        direction=v5.DIRECTIONS[0],
        round_trip_cost_pct=veto.ROUND_TRIP_COST_PCT,
        funding_timestamps=numpy.asarray(
            [funding_timestamp], dtype=numpy.int64
        ),
        funding_rates=numpy.asarray([0.001], dtype=float),
    )

    assert trade["outcome"] == "TARGET"
    assert numpy.isclose(trade["funding_return_pct"], -0.1)
    assert numpy.isclose(trade["net_return_pct"], 3.74)


def test_incomplete_horizon_matures_when_stop_is_already_known():
    candles = _candles(12)
    candles[8, 3] = 97.0

    stopped = veto.simulate_fixed_trade(
        candles=candles,
        entry_index=0,
        direction=v5.DIRECTIONS[0],
        round_trip_cost_pct=veto.ROUND_TRIP_COST_PCT,
        funding_timestamps=numpy.asarray([], dtype=numpy.int64),
        funding_rates=numpy.asarray([], dtype=float),
    )
    still_open = veto.simulate_fixed_trade(
        candles=_candles(12),
        entry_index=0,
        direction=v5.DIRECTIONS[0],
        round_trip_cost_pct=veto.ROUND_TRIP_COST_PCT,
        funding_timestamps=numpy.asarray([], dtype=numpy.int64),
        funding_rates=numpy.asarray([], dtype=float),
    )

    assert stopped["outcome"] == "STOP"
    assert still_open is None


def test_decision_loader_deduplicates_and_rejects_conflicts(tmp_path):
    path = tmp_path / "decisions.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE ai_decisions (
            id INTEGER PRIMARY KEY,
            triggered_at INTEGER,
            action TEXT,
            confidence REAL,
            signal_strength REAL,
            symbol TEXT,
            model TEXT,
            approved INTEGER
        )
        """
    )
    rows = [
        (1, 100, "BUY", 0.8, 0.4),
        (2, 100, "BUY", 0.9, 0.5),
        (3, 200, "BUY", 0.8, 0.4),
        (4, 200, "SELL", 0.8, 0.4),
        (5, 300, "SELL", 0.8, 0.4),
    ]
    connection.executemany(
        """
        INSERT INTO ai_decisions
        VALUES (?, ?, ?, ?, ?, ?, 'deterministic-alignment', 1)
        """,
        [row + (veto.SYMBOL,) for row in rows],
    )
    connection.commit()
    connection.close()

    decisions, diagnostics = veto.load_decisions(path)

    assert [row["decision_timestamp"] for row in decisions] == [100, 300]
    assert decisions[0]["decision_id"] == 2
    assert diagnostics["duplicate_rows_removed"] == 1
    assert diagnostics["ambiguous_timestamps_rejected"] == 1


def test_trade_metrics_include_direction_and_drawdown():
    trades = [
        {
            "net_return_pct": 3.84,
            "direction": v5.DIRECTIONS[0],
            "outcome": "TARGET",
        },
        {
            "net_return_pct": -2.16,
            "direction": v5.DIRECTIONS[1],
            "outcome": "STOP",
        },
    ]

    metrics = veto.trade_metrics(trades)

    assert metrics["trades"] == 2
    assert metrics["profit_factor"] > 1
    assert metrics["maximum_drawdown_pct"] > 2
    assert metrics["by_direction"]["LONG"]["trades"] == 1
    assert metrics["by_direction"]["SHORT"]["trades"] == 1
