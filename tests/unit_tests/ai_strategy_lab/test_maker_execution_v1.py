import json

import numpy
import pytest

from octobot.ai_strategy_lab import maker_execution_v1 as execution


def _book(timestamp_ns, *, bid=99_999.9, ask=100_000.0, size=8.0, imbalance=0.7):
    return execution.Book(
        timestamp_ns=timestamp_ns,
        bids=tuple((bid - 0.1 * level, size + level) for level in range(5)),
        asks=tuple((ask + 0.1 * level, size + level) for level in range(5)),
        mid=(bid + ask) / 2,
        imbalance=imbalance,
    )


def _window(*, include_fill=True, fallback_bid=99_999.9, fallback_ask=100_000.0):
    decision = 1_800_000_000_000_000_000
    arrival = decision + 500_000_000
    fill = arrival + 2_000_000_000
    books = tuple(sorted((
        _book(decision - 100_000_000),
        _book(arrival),
        _book(fill + 5_000_000_000, bid=100_000.0, ask=100_000.1),
        _book(fill + 60_000_000_000, bid=100_000.1, ask=100_000.2),
        _book(
            arrival + 60_500_000_000,
            bid=fallback_bid,
            ask=fallback_ask,
        ),
    ), key=lambda value: value.timestamp_ns))
    trades = (
        execution.Trade(fill, "sell", 99_999.9, 22.0),
    ) if include_fill else ()
    return execution.Window(decision, books, trades)


def test_protocol_is_result_free_and_cannot_query_lock():
    protocol = execution.frozen_protocol()
    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["validation"]["locked_rows_queryable_by_this_evaluator"] is False
    assert protocol["primary_policy"]["queue_ahead_multiplier_of_displayed_best_size"] == 1.25
    assert protocol["stress_policy"]["queue_ahead_multiplier_of_displayed_best_size"] == 2.0
    with pytest.raises(ValueError, match="locked rows"):
        execution.simulate_period(
            None,
            execution.DIAGNOSTIC_CONFIRMATION_END,
            execution.LOCKED_TEST_END,
            execution.PRIMARY_POLICY,
        )


def test_protocol_is_persisted_once_and_verified(tmp_path):
    path = tmp_path / "protocol.json"
    first = execution.write_or_verify_protocol(path)
    second = execution.write_or_verify_protocol(path)
    assert first == second
    assert first["protocol_sha256"] == execution._json_hash(
        execution.frozen_protocol()
    )
    mutated = json.loads(path.read_text(encoding="utf-8"))
    mutated["primary_policy"]["timeout_seconds"] = 61
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        execution.write_or_verify_protocol(path)


def test_conservative_queue_fill_beats_immediate_taker():
    result = execution.simulate_side(
        _window(include_fill=True), "buy", execution.PRIMARY_POLICY
    )
    assert result["completed"] is True
    assert result["maker_attempted"] is True
    assert result["maker_filled"] is True
    assert result["route"] == "maker_fill"
    assert result["quantity_contracts"] == 11
    assert result["saving_bps"] > 4.0
    assert result["adverse_5s_bps"] > 0


def test_imbalance_filter_uses_immediate_taker_for_unsafe_side():
    result = execution.simulate_side(
        _window(include_fill=True), "sell", execution.PRIMARY_POLICY
    )
    assert result["completed"] is True
    assert result["maker_attempted"] is False
    assert result["route"] == "immediate_taker_filter"
    assert result["saving_bps"] == 0.0


def test_unfilled_order_falls_back_without_fabricated_fill():
    result = execution.simulate_side(
        _window(
            include_fill=False,
            fallback_bid=100_009.9,
            fallback_ask=100_010.0,
        ),
        "buy",
        execution.PRIMARY_POLICY,
    )
    assert result["completed"] is True
    assert result["maker_attempted"] is True
    assert result["maker_filled"] is False
    assert result["route"] == "taker_fallback"
    assert result["saving_bps"] < 0


def test_top_five_vwap_requires_real_depth():
    book = _book(1)
    assert execution._vwap(book, "buy", 10) is not None
    assert execution._vwap(book, "sell", 10) is not None
    assert execution._vwap(book, "buy", 1_000_000) is None


def test_metrics_include_sides_days_folds_and_deterministic_bootstrap():
    start = execution.SOURCE_START
    start_ns = execution._epoch_ns(start)
    records = []
    for day in range(10):
        for side in ("buy", "sell"):
            records.append(
                {
                    "timestamp_ns": start_ns + day * 86_400 * 1_000_000_000,
                    "side": side,
                    "completed": True,
                    "exclusion": None,
                    "maker_attempted": True,
                    "maker_filled": day % 2 == 0,
                    "route": "maker_fill" if day % 2 == 0 else "taker_fallback",
                    "baseline_cost_bps": 6.0,
                    "policy_cost_bps": 5.0,
                    "saving_bps": 1.0,
                    "adverse_5s_bps": 0.1,
                    "adverse_60s_bps": 0.0,
                }
            )
    metrics = execution.execution_metrics(
        records,
        start=start,
        end=execution.DEVELOPMENT_END,
        folds=True,
    )
    assert metrics["mean_saving_bps"] == 1.0
    assert metrics["positive_operating_days_pct"] == 100.0
    assert metrics["by_side"]["buy"]["completed_rows"] == 10
    assert metrics["maker_fill_rate"] == 0.5
    assert metrics["daily_bootstrap_lower_mean_saving_bps_90pct"] == 1.0
    assert len(metrics["folds"]) == execution.WALK_FORWARD_FOLDS


def test_decision_grid_is_aligned_and_end_exclusive():
    start = execution._epoch_ns("2026-08-01T00:01:00+00:00")
    end = execution._epoch_ns("2026-08-01T01:00:00+00:00")
    values = execution._decision_timestamps(start, end)
    assert len(values) == 3
    assert all(
        value % (execution.DECISION_STRIDE_SECONDS * 1_000_000_000) == 0
        for value in values
    )
    assert values[-1] < end


def test_npz_record_arrays_keep_missing_values_explicit():
    row = {
        "timestamp_ns": 1,
        "side": "buy",
        "completed": False,
        "maker_attempted": False,
        "maker_filled": False,
        "quantity_contracts": None,
        "baseline_cost_bps": None,
        "policy_cost_bps": None,
        "saving_bps": None,
        "fill_timestamp_ns": None,
        "adverse_5s_bps": None,
        "adverse_60s_bps": None,
    }
    arrays = execution._records_arrays("test", [row])
    assert arrays["test_quantity_contracts"][0] == -1
    assert numpy.isnan(arrays["test_saving_bps"][0])
    assert arrays["test_fill_timestamp_ns"][0] == -1
