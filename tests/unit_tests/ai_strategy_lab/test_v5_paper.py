import pathlib
import json
import urllib.parse

import numpy

from octobot.ai_strategy_lab import v5_paper


def _decision(direction="LONG"):
    return {
        "close_timestamp": 900,
        "close_at": "1970-01-01T00:15:00+00:00",
        "close_price": 100.0,
        "action": direction,
        "accepted": True,
        "reason": "v5_expected_net_gate",
        "expected_net_pct": 0.1,
        "opposite_expected_net_pct": 0.0,
        "direction_margin_pct": 0.1,
        "target_probability_pct": 60.0,
        "stop_probability_pct": 20.0,
        "timeout_probability_pct": 20.0,
        "target_profit_pct": 1.5,
        "activation_pct": 1.7,
        "initial_stop_pct": 1.0,
        "horizon_hours": 1,
        "threshold_pct": 0.075,
    }


def _candle(open_timestamp, high, low, close):
    return numpy.asarray(
        [open_timestamp, 100.0, high, low, close, 1.0]
    )


def test_same_candle_stop_wins_over_activation():
    trade = v5_paper.open_trade_from_decision(
        _decision(), equity=10_000
    )

    updated, event, closed = v5_paper.advance_open_trade(
        trade, _candle(900, 102.0, 98.0, 101.0)
    )

    assert updated is None
    assert event["event_type"] == "trade_closed"
    assert closed["exit_reason"] == "initial_stop"
    assert closed["exit_price"] == 99.0


def test_profit_lock_activates_then_closes_from_next_candle():
    trade = v5_paper.open_trade_from_decision(
        _decision(), equity=10_000
    )

    updated, event, closed = v5_paper.advance_open_trade(
        trade, _candle(900, 101.8, 101.4, 101.6)
    )

    assert closed is None
    assert event["event_type"] == "profit_lock_activated"
    assert updated["activated_at"] == 1800

    updated, event, closed = v5_paper.advance_open_trade(
        updated, _candle(1800, 101.7, 101.4, 101.5)
    )

    assert updated is None
    assert closed["exit_reason"] == "profit_lock"
    assert numpy.isclose(closed["gross_return_pct"], 1.5)


def test_horizon_closes_at_candle_close():
    trade = v5_paper.open_trade_from_decision(
        _decision(), equity=10_000
    )
    updated = trade
    for index in range(1, 5):
        updated, _, closed = v5_paper.advance_open_trade(
            updated,
            _candle(index * 900, 100.5, 99.5, 100.25),
        )

    assert updated is None
    assert closed["exit_reason"] == "horizon"
    assert closed["exit_price"] == 100.25


def test_store_persists_open_trade_across_restart(tmp_path):
    path = pathlib.Path(tmp_path) / "paper.sqlite"
    store = v5_paper.PaperStore(path)
    state = {
        "schema_version": v5_paper.SCHEMA_VERSION,
        "last_close_timestamp": 900,
        "equity": 10_000.0,
        "open_trade": v5_paper.open_trade_from_decision(
            _decision(), equity=10_000
        ),
    }
    store.seed(state, 900)
    store.close()

    restored = v5_paper.PaperStore(path)

    assert restored.load_state() == state
    assert restored.integrity == "ok"
    restored.close()


def test_fetch_window_keeps_latest_closed_candle(monkeypatch):
    now = 200 * v5_paper.CANDLE_SECONDS + 60
    current_open = now // v5_paper.CANDLE_SECONDS * v5_paper.CANDLE_SECONDS
    seen = {}
    data = []
    first_open = current_open - (
        v5_paper.HISTORY_CANDLES * v5_paper.CANDLE_SECONDS
    )
    for timestamp in range(
        first_open, current_open, v5_paper.CANDLE_SECONDS
    ):
        data.append(
            [
                timestamp * 1000,
                "100",
                "101",
                "99",
                "100",
                "1",
            ]
        )

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _urlopen(request, timeout):
        del timeout
        seen["query"] = urllib.parse.parse_qs(
            urllib.parse.urlparse(request.full_url).query
        )
        response = _Response()
        response.read = lambda: json.dumps(data).encode()
        return response

    monkeypatch.setattr(v5_paper.urllib.request, "urlopen", _urlopen)

    candles = v5_paper.fetch_closed_candles(
        timeout_seconds=1,
        now_timestamp=now,
    )

    assert seen["query"]["symbol"] == ["BTCUSDT"]
    assert seen["query"]["interval"] == ["15m"]
    assert seen["query"]["limit"] == [
        str(v5_paper.HISTORY_CANDLES)
    ]
    assert int(seen["query"]["endTime"][0]) == current_open * 1000 - 1
    assert len(candles) == v5_paper.HISTORY_CANDLES
    assert int(candles[-1, 0]) + v5_paper.CANDLE_SECONDS == current_open


def test_fetch_recovery_paginates_from_saved_warmup(monkeypatch):
    candle_count = 1600
    current_open = 2_000_000 * v5_paper.CANDLE_SECONDS
    start_open = current_open - candle_count * v5_paper.CANDLE_SECONDS
    calls = []

    class _Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.data).encode()

    def _urlopen(request, timeout):
        del timeout
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(request.full_url).query
        )
        calls.append(query)
        cursor = int(query["startTime"][0]) // 1000
        limit = int(query["limit"][0])
        rows = []
        for timestamp in range(
            cursor,
            min(current_open, cursor + limit * v5_paper.CANDLE_SECONDS),
            v5_paper.CANDLE_SECONDS,
        ):
            rows.append(
                [timestamp * 1000, "100", "101", "99", "100", "1"]
            )
        return _Response(rows)

    monkeypatch.setattr(v5_paper.urllib.request, "urlopen", _urlopen)

    candles = v5_paper.fetch_closed_candles(
        timeout_seconds=1,
        now_timestamp=current_open + 60,
        start_timestamp=start_open,
    )

    assert len(calls) == 2
    assert calls[0]["limit"] == [str(v5_paper.BINANCE_MAX_CANDLES)]
    assert len(candles) == candle_count
    assert int(candles[0, 0]) == start_open
    assert int(candles[-1, 0]) + v5_paper.CANDLE_SECONDS == current_open
