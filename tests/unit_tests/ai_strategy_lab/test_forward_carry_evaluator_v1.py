import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import forward_carry_dataset
from octobot.ai_strategy_lab import forward_carry_evaluator_v1 as evaluator
from octobot.ai_strategy_lab import forward_carry_strategy_v1 as v1
from octobot.ai_strategy_lab import forward_carry_strategy_v1_1 as v1_1


def _timestamp(value):
    return int(datetime.datetime.fromisoformat(value).timestamp() * 1000)


def _features(rows):
    names = forward_carry_dataset.FEATURE_NAMES
    values = numpy.zeros((rows, len(names)), dtype=numpy.float64)
    values[:, names.index("current_funding_rate")] = 0.0001
    values[:, names.index("predicted_funding_rate_filled")] = 0.0001
    values[:, names.index("predicted_funding_available")] = 1
    values[:, names.index("funding_granularity_hours")] = 8
    values[:, names.index("entry_basis_bps")] = 10
    values[:, names.index("instant_round_trip_book_width_bps")] = 3
    values[:, names.index("spot_spread_bps")] = 1
    values[:, names.index("futures_spread_bps")] = 1
    values[:, names.index("entry_capacity_usdt_depth20")] = 10_000
    values[:, names.index("instant_exit_capacity_usdt_depth20")] = 10_000
    values[:, names.index("open_interest_quote")] = numpy.linspace(
        1_000_000, 2_000_000, rows
    )
    values[:, names.index("mark_index_basis_bps")] = 2
    values[:, names.index("spot_conservative_taker_fee_rate")] = 0.001
    values[:, names.index("futures_conservative_taker_fee_rate")] = 0.0006
    return values


def _dataset(timestamps, symbols, returns, *, fees=None):
    timestamps = numpy.asarray(timestamps, dtype=numpy.int64)
    rows = len(timestamps)
    returns = numpy.asarray(returns, dtype=numpy.float64)
    fees = (
        numpy.full(rows, 0.0016, dtype=numpy.float64)
        if fees is None
        else numpy.asarray(fees, dtype=numpy.float64)
    )
    return {
        "schema_version": 1,
        "feature_names": forward_carry_dataset.FEATURE_NAMES,
        "features": _features(rows),
        "entry_timestamp_ms": timestamps,
        "exit_timestamp_ms": timestamps + evaluator.PRIMARY_HORIZON_MS,
        "symbols": numpy.asarray(symbols),
        "horizon_hours": numpy.full(rows, 168, dtype=numpy.int16),
        "spot_price_return": returns + fees,
        "futures_price_return": numpy.zeros(rows),
        "settled_funding_return": numpy.zeros(rows),
        "conservative_fee_return": fees,
        "net_pair_return": 0.5 * (returns + fees) - fees,
        "manifest": {
            "schema_version": 1,
            "research_only": True,
            "orders_authorized": False,
            "automatic_promotion": False,
            "feature_names": list(forward_carry_dataset.FEATURE_NAMES),
            "horizon_hours": [168],
            "leg_quote": 1000,
            "row_count": rows,
            "exclusions": {
                "entry_schema_incomplete": 0,
                "missing_exact_exit_bucket": 0,
                "exit_schema_incomplete": 0,
                "insufficient_entry_depth": 0,
                "insufficient_exit_depth": 0,
            },
            "exclusion_events": [],
            "output": {"sha256": "d" * 64},
        },
    }


def _curve(vwap):
    return {
        "target_quote": 1000.0,
        "filled_quote": 1000.0,
        "filled_base": 1000.0 / vwap,
        "vwap": vwap,
        "last_price": vwap,
        "sufficient_depth": True,
    }


def _levels(price):
    return [
        {
            "price": price,
            "base_quantity": 100_000.0,
            "quote_quantity": price * 100_000.0,
        }
    ]


def _symbol(*, spot_bid, spot_ask, futures_bid, futures_ask, funding):
    return {
        "spot": {
            "best_bid": spot_bid,
            "best_ask": spot_ask,
            "bid_vwap_by_quote": {"1000": _curve(spot_bid)},
            "ask_vwap_by_quote": {"1000": _curve(spot_ask)},
            "normalized_bids": _levels(spot_bid),
            "normalized_asks": _levels(spot_ask),
            "conservative_taker_fee_rate": 0.001,
        },
        "futures": {
            "best_bid": futures_bid,
            "best_ask": futures_ask,
            "bid_vwap_by_quote": {"1000": _curve(futures_bid)},
            "ask_vwap_by_quote": {"1000": _curve(futures_ask)},
            "normalized_bids": _levels(futures_bid),
            "normalized_asks": _levels(futures_ask),
            "conservative_taker_fee_rate": 0.0006,
        },
        "funding": {"settled_last_24h": funding},
    }


def test_phase_status_keeps_real_evidence_and_early_confirmation_locked():
    protocol = v1_1.frozen_protocol()
    evidence = {
        "mode": "forward_evidence_only",
        "strategy_development_ready": False,
        "checks": {"span": False},
        "orders_authorized": False,
        "automatic_promotion": False,
        "real_income_authorized": False,
    }

    locked = evaluator.phase_status(
        protocol,
        evidence,
        now=datetime.datetime(2026, 9, 21, tzinfo=datetime.timezone.utc),
    )
    assert locked["development"]["allowed"] is False
    assert locked["confirmation"]["allowed"] is False

    evidence["strategy_development_ready"] = True
    evidence["checks"]["span"] = True
    development = evaluator.phase_status(
        protocol,
        evidence,
        now=datetime.datetime(2026, 9, 21, 13, tzinfo=datetime.timezone.utc),
    )
    assert development["development"]["allowed"] is True
    assert development["confirmation"]["allowed"] is False

    too_early = evaluator.phase_status(
        protocol,
        evidence,
        now=datetime.datetime(
            2026, 10, 3, 11, 59, tzinfo=datetime.timezone.utc
        ),
        development_passed=True,
        model_sha256="a" * 64,
    )
    opened = evaluator.phase_status(
        protocol,
        evidence,
        now=datetime.datetime(
            2026, 10, 3, 12, 0, tzinfo=datetime.timezone.utc
        ),
        development_passed=True,
        model_sha256="a" * 64,
    )
    assert too_early["confirmation"]["allowed"] is False
    assert opened["confirmation"]["allowed"] is True


def test_protocol_loader_accepts_only_frozen_v1_1(tmp_path):
    corrected = tmp_path / "corrected.json"
    v1_1.write_or_verify_protocol(corrected)
    assert evaluator.load_protocol(corrected)["protocol_version"] == (
        v1_1.PROTOCOL_VERSION
    )

    original = tmp_path / "original.json"
    v1.write_or_verify_protocol(original)
    with pytest.raises(ValueError, match="differs from frozen evaluator"):
        evaluator.load_protocol(original)


def test_ridge_is_deterministic_and_persisted_exactly(tmp_path):
    protocol = v1_1.frozen_protocol()
    features = _features(64)
    target = numpy.linspace(-0.01, 0.02, 64)

    first = evaluator.fit_ridge_model(features, target, protocol)
    second = evaluator.fit_ridge_model(features, target, protocol)
    assert numpy.array_equal(first.predict(features), second.predict(features))

    path = tmp_path / "model.json"
    persisted = evaluator.save_model(
        first,
        path,
        protocol_sha256="a" * 64,
        dataset_sha256="b" * 64,
        dataset_manifest_sha256="c" * 64,
        training_rows=64,
    )
    loaded, payload = evaluator.load_model(
        path,
        expected_protocol_sha256="a" * 64,
    )
    assert payload == persisted
    assert numpy.array_equal(first.predict(features), loaded.predict(features))

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered.pop("model_sha256")
    tampered["scale"][0] = 0
    tampered["model_sha256"] = evaluator._json_hash(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="numerical invariant"):
        evaluator.load_model(
            path,
            expected_protocol_sha256="a" * 64,
        )


def test_passing_development_report_is_content_bound_to_model(tmp_path):
    protocol = {
        **v1_1.frozen_protocol(),
        "protocol_sha256": "a" * 64,
    }
    model = evaluator.fit_ridge_model(
        _features(64),
        numpy.linspace(-0.01, 0.02, 64),
        protocol,
    )
    model_payload = evaluator.save_model(
        model,
        tmp_path / "model.json",
        protocol_sha256=protocol["protocol_sha256"],
        dataset_sha256="b" * 64,
        dataset_manifest_sha256="c" * 64,
        training_rows=64,
    )
    report_path = tmp_path / "development.json"
    report = {
        "schema_version": evaluator.SCHEMA_VERSION,
        "evaluator_version": evaluator.EVALUATOR_VERSION,
        "phase": "development",
        "research_only": True,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "protocol_version": v1_1.PROTOCOL_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "dataset_sha256": "b" * 64,
        "dataset_manifest_sha256": "c" * 64,
        "development_gate": {"passed": True},
        "frozen_model": model_payload,
        "confirmation": {"authorized": True, "opened": False},
    }
    evaluator._write_hashed_report(report_path, report)

    loaded = evaluator._load_passing_development_report(
        report_path,
        protocol=protocol,
        model_payload=model_payload,
    )
    assert loaded["report_sha256"]

    tampered = json.loads(report_path.read_text(encoding="utf-8"))
    tampered.pop("report_sha256")
    tampered["orders_authorized"] = True
    tampered["report_sha256"] = evaluator._json_hash(tampered)
    report_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="did not pass integrity"):
        evaluator._load_passing_development_report(
            report_path,
            protocol=protocol,
            model_payload=model_payload,
        )


def test_portfolio_respects_five_slots_and_same_symbol_overlap():
    protocol = v1_1.frozen_protocol()
    first = _timestamp("2026-08-06T16:15:00+00:00")
    second = first + 8 * 3_600_000
    exit_time = first + evaluator.PRIMARY_HORIZON_MS
    timestamps = [first] * 6 + [second] * 2 + [exit_time] * 2
    symbols = ["A", "B", "C", "D", "E", "F", "A", "G", "A", "G"]
    dataset = _dataset(timestamps, symbols, [0.02] * len(timestamps))
    scores = numpy.linspace(0.02, 0.01, len(timestamps))

    trades = evaluator.select_portfolio(
        dataset,
        scores,
        protocol,
        start_ms=first,
        end_ms=exit_time + 1,
    )

    assert [trade["symbol"] for trade in trades[:5]] == ["A", "B", "C", "D", "E"]
    second_entries = [
        trade for trade in trades
        if trade["entry_timestamp_ms"] == second
    ]
    exit_entries = [
        trade for trade in trades
        if trade["entry_timestamp_ms"] == exit_time
    ]
    assert len(second_entries) == 0
    assert len(exit_entries) == 2


def test_stress_uses_next_bucket_and_doubles_fee_component():
    first = _timestamp("2026-08-06T16:15:00+00:00")
    delayed = first + evaluator.BUCKET_MS
    dataset = _dataset(
        [first, delayed],
        ["BTC", "BTC"],
        [0.03, 0.026],
        fees=[0.002, 0.003],
    )
    trade = evaluator._trade_from_row(dataset, 0, score=0.02, fold_id=0)

    stressed, missing = evaluator.stress_trades(dataset, [trade])

    assert missing == 0
    assert stressed[0]["entry_timestamp_ms"] == delayed
    assert stressed[0]["net_pair_return"] == pytest.approx(
        dataset["net_pair_return"][1]
        - dataset["conservative_fee_return"][1]
    )


def test_mark_to_market_reproduces_exact_forward_label(tmp_path):
    protocol = v1_1.frozen_protocol()
    entry = _timestamp("2026-08-06T16:15:00+00:00")
    exit_at = entry + evaluator.PRIMARY_HORIZON_MS
    settlement = entry + 4 * 3_600_000
    entry_symbol = _symbol(
        spot_bid=99,
        spot_ask=100,
        futures_bid=101,
        futures_ask=102,
        funding=[],
    )
    exit_symbol = _symbol(
        spot_bid=103,
        spot_ask=104,
        futures_bid=99,
        futures_ask=100,
        funding=[{"timestamp_ms": settlement, "rate": 0.0002}],
    )
    spot_return = 103 / 100 - 1
    futures_return = 1 - 100 / 101
    fee = (
        1000 * 0.001
        + 1030 * 0.001
        + 1000 * 0.0006
        + (1000 / 101 * 100) * 0.0006
    ) / 2000
    net = 0.5 * (spot_return + futures_return + 0.0002) - fee
    trade = {
        "symbol": "BTC",
        "entry_timestamp_ms": entry,
        "exit_timestamp_ms": exit_at,
        "net_pair_return": net,
    }
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            json.dumps(
                {
                    "bucket_start_utc": datetime.datetime.fromtimestamp(
                        timestamp / 1000,
                        tz=datetime.timezone.utc,
                    ).isoformat(),
                    "symbols": {"BTC": symbol},
                }
            )
            for timestamp, symbol in (
                (entry, entry_symbol),
                (exit_at, exit_symbol),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluator.mark_to_market_portfolios(
        journal,
        {"candidate": [trade]},
        protocol,
    )["candidate"]

    assert result["complete"] is True
    assert result["final_realized_equity"] == pytest.approx(10000 + net * 2000)
    assert result["equity_points"] == 2


def test_exclusion_audit_is_point_in_time_and_horizon_specific():
    timestamp = _timestamp("2026-08-06T16:15:00+00:00")
    dataset = _dataset([timestamp], ["BTC"], [0.02])
    dataset["manifest"]["exclusions"]["missing_exact_exit_bucket"] = 1
    dataset["manifest"]["exclusion_events"] = [
        {
            "entry_timestamp_ms": timestamp,
            "horizon_hours": 168,
            "base": "ETH",
            "reason": "missing_exact_exit_bucket",
        }
    ]

    audit = evaluator.exclusion_audit(
        dataset,
        start_ms=timestamp,
        end_ms=timestamp + 1,
    )

    assert audit["attempted_rows"] == 2
    assert audit["future_exit_exclusion_fraction"] == 0.5


def test_development_pipeline_runs_both_folds_and_all_omissions():
    protocol = v1_1.frozen_protocol()
    symbols = [f"S{index:02d}" for index in range(19)]
    training_times = [
        _timestamp(
            (
                datetime.datetime(
                    2026, 7, 24, 0, 15, tzinfo=datetime.timezone.utc
                )
                + datetime.timedelta(days=offset)
            ).isoformat()
        )
        for offset in range(6)
    ]
    test_times = [
        _timestamp("2026-08-06T16:15:00+00:00"),
        _timestamp("2026-08-13T16:15:00+00:00"),
    ]
    groups = training_times + test_times + [
        value + evaluator.BUCKET_MS for value in test_times
    ]
    timestamps = [value for value in groups for _ in symbols]
    row_symbols = symbols * len(groups)
    dataset = _dataset(
        timestamps,
        row_symbols,
        [0.03] * len(timestamps),
    )

    result, model, training_rows = evaluator.evaluate_development_core(
        dataset,
        protocol,
    )

    assert result["candidate"]["closed_pairs"] == 10
    assert result["stress"]["closed_pairs"] == 10
    assert result["stress"]["missing_delayed_rows"] == 0
    assert len(result["walk_forward_folds"]) == 2
    assert len(result["leave_one_symbol_out"]["omissions"]) == 19
    assert result["leave_one_symbol_out"]["non_negative_omissions"] == 19
    assert result["development_gate"]["passed"] is False
    assert model.feature_names == forward_carry_dataset.FEATURE_NAMES
    assert training_rows > len(forward_carry_dataset.FEATURE_NAMES)
