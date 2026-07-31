import json
import sqlite3
import time

import pytest

from octobot.ai_strategy_lab import scalping_observer


def _config(tmp_path):
    return scalping_observer.ScalpingObserverConfig(
        database_path=tmp_path / "scalping.sqlite",
        health_path=tmp_path / "health.json",
    )


def _book_message(timestamp_ms, sequence=123):
    return {
        "type": "message",
        "subject": "level2",
        "topic": "/contractMarket/level2Depth5:XBTUSDTM",
        "data": {
            "sequence": sequence,
            "timestamp": timestamp_ms,
            "bids": [
                ["100.0", "10"],
                ["99.9", "8"],
                ["99.8", "6"],
                ["99.7", "4"],
                ["99.6", "2"],
            ],
            "asks": [
                ["100.1", "5"],
                ["100.2", "5"],
                ["100.3", "5"],
                ["100.4", "5"],
                ["100.5", "5"],
            ],
        },
    }


def _trade_message(timestamp_ns, trade_id="t-1", side="buy"):
    return {
        "type": "message",
        "subject": "match",
        "topic": "/contractMarket/execution:XBTUSDTM",
        "data": {
            "symbol": "XBTUSDTM",
            "sequence": 456,
            "side": side,
            "size": 3,
            "price": "100.1",
            "tradeId": trade_id,
            "ts": timestamp_ns,
        },
    }


def test_parse_book_derives_point_in_time_microstructure():
    received_ns = 1_800_000_000_020_000_000
    event = scalping_observer.parse_book_message(
        _book_message(1_800_000_000_000), received_ns
    )

    assert event["exchange_ts_ns"] == 1_800_000_000_000_000_000
    assert event["latency_ms"] == pytest.approx(20)
    assert event["best_bid"] == 100
    assert event["best_ask"] == 100.1
    assert event["mid_price"] == pytest.approx(100.05)
    assert event["spread_bps"] == pytest.approx(10)
    assert event["imbalance_5"] == pytest.approx((30 - 25) / 55)
    assert event["microprice"] == pytest.approx(
        (100.1 * 10 + 100 * 5) / 15
    )
    assert len(event["payload_sha256"]) == 64


def test_parse_book_rejects_crossed_or_incomplete_depth():
    crossed = _book_message(1_800_000_000_000)
    crossed["data"]["asks"][0][0] = "99.9"
    with pytest.raises(ValueError, match="crossed"):
        scalping_observer.parse_book_message(
            crossed, 1_800_000_000_020_000_000
        )

    incomplete = _book_message(1_800_000_000_000)
    incomplete["data"]["bids"].pop()
    with pytest.raises(ValueError, match="exactly five"):
        scalping_observer.parse_book_message(
            incomplete, 1_800_000_000_020_000_000
        )


def test_parse_trade_preserves_aggressor_and_nanosecond_timestamp():
    exchange_ns = 1_800_000_000_000_000_000
    event = scalping_observer.parse_trade_message(
        _trade_message(exchange_ns),
        exchange_ns + 8_000_000,
    )

    assert event["trade_id"] == "t-1"
    assert event["side"] == "buy"
    assert event["price"] == pytest.approx(100.1)
    assert event["size"] == pytest.approx(3)
    assert event["latency_ms"] == pytest.approx(8)


def test_store_is_append_only_deduplicated_and_materializes_seconds(
    tmp_path,
):
    config = _config(tmp_path)
    store = scalping_observer.ScalpingStore(config, "session-1")
    base_ns = 1_800_000_000_000_000_000
    trade = scalping_observer.parse_trade_message(
        _trade_message(base_ns), base_ns + 10_000_000
    )
    book = scalping_observer.parse_book_message(
        _book_message(1_800_000_000_000), base_ns + 20_000_000
    )

    assert store.record_trade(trade) is True
    assert store.record_trade(trade) is False
    assert store.record_book(book) is True
    assert store.record_book(book) is False
    store.commit_if_due(force=True)

    bucket = store.connection.execute(
        "SELECT * FROM second_buckets"
    ).fetchone()
    assert bucket["book_event_count"] == 1
    assert bucket["trade_event_count"] == 1
    assert bucket["first_mid"] == pytest.approx(100.05)
    assert bucket["high_mid"] == pytest.approx(100.05)
    assert bucket["low_mid"] == pytest.approx(100.05)
    assert bucket["buy_trade_size"] == pytest.approx(3)
    assert bucket["buy_trade_count"] == 1
    assert bucket["sell_trade_count"] == 0
    assert store.quick_check() == "ok"
    store.close("completed")

    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM book_events"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM trade_events"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM scalping_sessions"
        ).fetchone()[0] == "completed"


def test_health_is_fail_closed_and_never_authorizes_orders(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    store = scalping_observer.ScalpingStore(config, "session-1")
    now_ns = time.time_ns()
    store.record_book(
        scalping_observer.parse_book_message(
            _book_message(now_ns // 1_000_000),
            now_ns,
        )
    )

    def fail_if_full_check_runs():
        raise AssertionError("live health must not scan the full database")

    monkeypatch.setattr(store, "quick_check", fail_if_full_check_runs)

    health = scalping_observer.build_health(
        config,
        store,
        status="healthy",
        connected=True,
        subscriptions_acknowledged=2,
    )

    assert health["status"] == "healthy"
    assert health["mode"] == "scalping_research_only"
    assert health["public_data_only"] is True
    assert health["credentials_used"] is False
    assert health["orders_authorized"] is False
    assert health["automatic_promotion"] is False
    assert health["book_push_interval_ms"] == 100
    assert health["database_operational"] is True
    assert health["database_integrity"] == "deferred_offline"
    assert (
        health["database_integrity_check_mode"]
        == "explicit_offline_only"
    )
    assert health["book_events"] == 1
    store.close("completed")


def test_health_reports_unhealthy_when_database_is_not_operational(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    store = scalping_observer.ScalpingStore(config, "session-1")
    now_ns = time.time_ns()
    store.record_book(
        scalping_observer.parse_book_message(
            _book_message(now_ns // 1_000_000),
            now_ns,
        )
    )
    monkeypatch.setattr(store, "operational_check", lambda: False)

    health = scalping_observer.build_health(
        config,
        store,
        status="healthy",
        connected=True,
        subscriptions_acknowledged=2,
    )

    assert health["status"] == "unhealthy"
    assert health["database_operational"] is False
    assert health["orders_authorized"] is False
    store.close("completed")


def test_restarted_store_restores_counters_without_rescanning_health(
    tmp_path,
):
    config = _config(tmp_path)
    base_ns = 1_800_000_000_000_000_000
    first = scalping_observer.ScalpingStore(config, "session-1")
    first.record_book(
        scalping_observer.parse_book_message(
            _book_message(1_800_000_000_000, sequence=1),
            base_ns + 20_000_000,
        )
    )
    first.close("completed")

    second = scalping_observer.ScalpingStore(config, "session-2")
    assert second.health_counts()["book_events"] == 1
    second.record_book(
        scalping_observer.parse_book_message(
            _book_message(1_800_000_000_000, sequence=2),
            base_ns + 40_000_000,
        )
    )
    counts = second.health_counts()

    assert counts["book_events"] == 2
    assert counts["second_buckets"] == 1
    assert second.quick_check() == "ok"
    second.close("completed")


def test_restart_marks_unclosed_previous_session_as_interrupted(tmp_path):
    config = _config(tmp_path)
    first = scalping_observer.ScalpingStore(config, "session-1")
    first.connection.commit()
    first.connection.close()

    second = scalping_observer.ScalpingStore(config, "session-2")
    sessions = second.connection.execute(
        """
        SELECT session_id, status, stop_reason
        FROM scalping_sessions
        ORDER BY started_at, session_id
        """
    ).fetchall()

    assert tuple(sessions[0]) == (
        "session-1",
        "interrupted",
        "observer restarted before graceful close",
    )
    assert tuple(sessions[1]) == ("session-2", "running", None)
    second.close("completed")


def test_atomic_health_writer_produces_valid_json(tmp_path):
    path = tmp_path / "health.json"
    scalping_observer._write_json_atomic(
        path,
        {
            "status": "healthy",
            "orders_authorized": False,
        },
    )

    assert json.loads(path.read_text()) == {
        "orders_authorized": False,
        "status": "healthy",
    }
