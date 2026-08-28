import json

import numpy

from octobot.ai_strategy_lab import quarter_hour_flow_v1 as quarter


def _cache(seconds=80_000):
    buy = numpy.zeros(seconds)
    sell = numpy.zeros(seconds)
    trades = numpy.zeros(seconds, dtype=numpy.int64)
    ask = numpy.full(seconds, 100.01)
    bid = numpy.full(seconds, 99.99)
    for boundary in range(0, seconds, quarter.BOUNDARY_SECONDS):
        buy[boundary : boundary + quarter.OBSERVATION_SECONDS] = 2.0
        sell[boundary : boundary + quarter.OBSERVATION_SECONDS] = 1.0
        trades[boundary : boundary + quarter.OBSERVATION_SECONDS] = 2
        exit_second = (
            boundary + quarter.OBSERVATION_SECONDS + quarter.HORIZON_SECONDS
        )
        if exit_second < seconds:
            bid[exit_second] = 101.99
    return {
        "start_second": 0,
        "end_second": seconds - 1,
        "buy_size": buy,
        "sell_size": sell,
        "trade_count": trades,
        "ask": ask,
        "bid": bid,
    }


def test_protocol_is_result_free_and_never_authorizes_orders(tmp_path):
    path = tmp_path / "protocol.json"
    protocol = quarter.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert quarter.write_or_verify_protocol(path) == protocol


def test_event_uses_opening_flow_then_future_executable_quotes():
    cache = _cache()
    events = quarter.build_events(cache, 0, cache["end_second"])

    assert events
    assert all(event["direction"] == 1 for event in events)
    assert all(event["imbalance"] > 0 for event in events)
    assert events[0]["gross_bps"] > quarter.ROUND_TRIP_COST_BPS
    metrics = quarter.event_metrics(events)
    assert metrics["mean_net_bps"] > 0


def test_event_signal_does_not_use_flow_after_opening_window():
    cache = _cache()
    original = quarter.build_events(cache, 0, cache["end_second"])
    changed = {key: value.copy() if isinstance(value, numpy.ndarray) else value for key, value in cache.items()}
    changed["buy_size"][quarter.OBSERVATION_SECONDS :] = 0
    changed["sell_size"][quarter.OBSERVATION_SECONDS :] = 1000
    # Preserve each later boundary's own opening observation, so only data
    # after the first decision and outside its ten-second window differ.
    for boundary in range(
        quarter.BOUNDARY_SECONDS,
        len(changed["buy_size"]),
        quarter.BOUNDARY_SECONDS,
    ):
        changed["buy_size"][boundary : boundary + 10] = 2
        changed["sell_size"][boundary : boundary + 10] = 1
    repeated = quarter.build_events(changed, 0, cache["end_second"])

    assert original[0] == repeated[0]


def test_failed_development_does_not_evaluate_confirmation(tmp_path, monkeypatch):
    protocol_path = tmp_path / "protocol.json"
    quarter.write_or_verify_protocol(protocol_path)
    cache = _cache(seconds=100)
    cache["end_second"] = 2_500_000
    monkeypatch.setattr(quarter, "load_source_cache", lambda _path: cache)
    monkeypatch.setattr(quarter.common, "_sha256", lambda _path: "0" * 64)
    monkeypatch.setattr(quarter, "_epoch", lambda value: {
        quarter.SOURCE_START: 0,
        quarter.DEVELOPMENT_END: 1_900_000,
        quarter.CONFIRMATION_END: 2_400_000,
    }[value])
    ranges = []

    def fake_events(_cache, start, end, *, extra_delay_seconds=0):
        ranges.append((start, end, extra_delay_seconds))
        return [
            {
                "timestamp": start,
                "direction": 1,
                "gross_bps": -1.0,
            }
        ] * 1600

    monkeypatch.setattr(quarter, "build_events", fake_events)
    original_metrics = quarter.event_metrics

    def losing_metrics(events, *, cost_bps=quarter.ROUND_TRIP_COST_BPS):
        result = original_metrics(events, cost_bps=cost_bps)
        result.update(
            {
                "mean_net_bps": -1.0,
                "profit_factor": 0.5,
                "hit_rate": 0.4,
                "positive_day_ratio": 0.4,
                "by_direction": {
                    "-1": {"events": 1, "mean_net_bps": -1.0},
                    "1": {"events": max(1, len(events)), "mean_net_bps": -1.0},
                },
            }
        )
        return result

    monkeypatch.setattr(quarter, "event_metrics", losing_metrics)
    cache_path = tmp_path / "unused.npz"
    cache_path.touch()
    result = quarter.evaluate_prelock(
        protocol_path,
        cache_path,
        tmp_path / "experiments",
    )
    report = result["report"]

    assert report["confirmation"] is None
    assert report["locked_test"]["authorized_to_materialize"] is False
    assert report["locked_test"]["materialized"] is False
    assert all(end <= 1_900_000 for _start, end, _delay in ranges)
    saved = json.loads(
        (
            tmp_path
            / "experiments"
            / result["directory"].split("/")[-1]
            / "report.json"
        ).read_text()
    )
    assert saved["verdict"] == "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
