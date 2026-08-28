import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import maker_execution_v1 as v1
from octobot.ai_strategy_lab import maker_execution_v2 as v2


def _book(timestamp_ns, *, bid=99_999.9, ask=100_000.0, size=10.0, imbalance=0.3):
    return v1.Book(
        timestamp_ns=timestamp_ns,
        bids=tuple((bid - level * 0.1, size + level) for level in range(5)),
        asks=tuple((ask + level * 0.1, size + level) for level in range(5)),
        mid=(bid + ask) / 2,
        imbalance=imbalance,
    )


def _rich_window(*, fill=True, future_trade_size=0.0):
    decision = v1._epoch_ns("2026-07-30T12:00:00+00:00")
    primary_arrival = decision + 500_000_000
    stress_arrival = decision + 1_000_000_000
    fill_time = primary_arrival + 2_000_000_000
    books = tuple(
        sorted(
            (
                _book(decision - 31_000_000_000, bid=99_999.0, ask=99_999.1),
                _book(decision - 30_000_000_000, bid=99_999.1, ask=99_999.2),
                _book(decision - 5_000_000_000, bid=99_999.7, ask=99_999.8),
                _book(decision - 100_000_000),
                _book(primary_arrival),
                _book(stress_arrival),
                _book(fill_time + 5_000_000_000, bid=100_000.0, ask=100_000.1),
                _book(stress_arrival + 31_000_000_000),
                _book(primary_arrival + 60_500_000_000),
                _book(fill_time + 60_000_000_000, bid=100_000.1, ask=100_000.2),
            ),
            key=lambda value: value.timestamp_ns,
        )
    )
    trades = [
        v1.Trade(decision - 4_000_000_000, "buy", 99_999.8, 5.0),
        v1.Trade(decision - 2_000_000_000, "sell", 99_999.7, 2.0),
    ]
    if fill:
        trades.append(v1.Trade(fill_time, "sell", 99_999.9, 25.0))
    if future_trade_size:
        trades.append(
            v1.Trade(
                primary_arrival + 10_000_000_000,
                "buy",
                100_000.0,
                future_trade_size,
            )
        )
    base = v1.Window(decision, books, tuple(sorted(trades, key=lambda value: value.timestamp_ns)))
    return v2.RichWindow(
        base=base,
        microprices=numpy.asarray([book.mid + 0.01 for book in books]),
        spreads_bps=numpy.asarray(
            [(book.asks[0][0] / book.bids[0][0] - 1) * 10_000 for book in books]
        ),
        latencies_ms=numpy.full(len(books), 120.0),
    )


def test_protocol_is_fixed_and_keeps_confirmation_and_lock_gated():
    protocol = v2.frozen_protocol()
    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["features"]["names"] == list(v2.FEATURE_NAMES)
    assert protocol["model"]["hyperparameter_search"] is False
    assert protocol["model"]["attempt_gate"]["minimum_predicted_fill_probability"] == 0.10
    assert protocol["validation"]["confirmation_read_only_after_complete_development_pass"] is True
    with pytest.raises(ValueError, match="locked rows"):
        v2.build_rows(None, v2.DIAGNOSTIC_CONFIRMATION_END, v2.LOCKED_TEST_END)


def test_protocol_write_is_idempotent_and_detects_mutation(tmp_path):
    path = tmp_path / "protocol.json"
    first = v2.write_or_verify_protocol(path)
    assert first == v2.write_or_verify_protocol(path)
    mutated = json.loads(path.read_text(encoding="utf-8"))
    mutated["model"]["stage_two"]["alpha"] = 24.0
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        v2.write_or_verify_protocol(path)


def test_features_are_causal_and_future_trades_do_not_change_them():
    first = v2._features(_rich_window(future_trade_size=0.0), "buy")
    second = v2._features(_rich_window(future_trade_size=100_000.0), "buy")
    assert first is not None
    assert first.shape == (len(v2.FEATURE_NAMES),)
    assert numpy.all(numpy.isfinite(first))
    numpy.testing.assert_allclose(first, second, rtol=0, atol=0)


def test_unconditional_label_requires_observed_queue_consumption():
    filled = v2._unconditional_outcome(
        _rich_window(fill=True), "buy", v1.PRIMARY_POLICY
    )
    not_filled = v2._unconditional_outcome(
        _rich_window(fill=False), "buy", v1.PRIMARY_POLICY
    )
    assert filled["completed"] is True
    assert filled["filled"] is True
    assert filled["saving_bps"] > 4.0
    assert not_filled["completed"] is True
    assert not_filled["filled"] is False


def test_two_stage_model_is_deterministic_and_reloadable(tmp_path):
    random = numpy.random.default_rng(7)
    features = random.normal(size=(600, len(v2.FEATURE_NAMES)))
    logits = 1.2 * features[:, 1] - 0.8 * features[:, 4]
    filled = random.random(600) < (1.0 / (1.0 + numpy.exp(-logits)))
    savings = numpy.where(
        filled,
        4.0 + 0.2 * features[:, 3],
        -0.5 + features[:, 7] - 0.3 * features[:, 8],
    )
    first = v2._fit_model(features, filled, savings)
    second = v2._fit_model(features, filled, savings)
    for left, right in zip(first.predict(features), second.predict(features)):
        numpy.testing.assert_allclose(left, right, rtol=0, atol=0)
    path = tmp_path / "model.npz"
    v2._save_model(path, first)
    loaded = v2._load_model(path)
    for left, right in zip(first.predict(features), loaded.predict(features)):
        numpy.testing.assert_allclose(left, right, rtol=0, atol=1e-12)


def test_selection_requires_probability_and_economic_margin():
    probability = numpy.asarray([0.09, 0.10, 0.50])
    expected = numpy.asarray([10.0, 0.25, 0.251])
    assert v2._selection(probability, expected).tolist() == [False, False, True]


def test_auc_handles_perfect_ranking_and_single_class():
    labels = numpy.asarray([False, False, True, True])
    scores = numpy.asarray([0.1, 0.2, 0.8, 0.9])
    assert v2._roc_auc(labels, scores) == 1.0
    assert v2._roc_auc(numpy.asarray([True, True]), numpy.asarray([0.2, 0.8])) is None


def _synthetic_rows():
    random = numpy.random.default_rng(12)
    rows = []
    start = v1._epoch_ns(v2.SOURCE_START)
    end = v1._epoch_ns(v2.DEVELOPMENT_END)
    timestamps = numpy.arange(start, end, v1.DECISION_STRIDE_SECONDS * 1_000_000_000)
    for timestamp in timestamps:
        for side in ("buy", "sell"):
            features = random.normal(size=len(v2.FEATURE_NAMES))
            features[0] = 1.0 if side == "buy" else -1.0
            features[v2.MAKER_SAVING_FEATURE_INDEX] = 4.1
            probability = 1.0 / (1.0 + numpy.exp(-1.5 * features[1] + 0.7 * features[10]))
            filled = bool(random.random() < probability)
            primary_saving = 4.1 if filled else float(0.8 * features[7] - 0.2)
            stress_filled = bool(filled and random.random() < 0.6)
            stress_saving = 6.1 if stress_filled else float(0.5 * features[7] - 0.3)
            rows.append(
                {
                    "timestamp_ns": int(timestamp),
                    "side": side,
                    "features": features,
                    "primary": {"filled": filled, "saving_bps": primary_saving},
                    "stress": {"filled": stress_filled, "saving_bps": stress_saving},
                }
            )
    return rows


def test_development_evaluation_is_strictly_out_of_sample():
    rows = _synthetic_rows()
    source = {
        "expected_rows": len(rows),
        "usable_rows": len(rows),
        "coverage": 1.0,
        "exclusions": {},
    }
    report, predictions, models = v2.evaluate_development(rows, source)
    assert len(models) == len(v2.FOLD_WINDOWS)
    assert report["oos_rows"] == len(predictions["selected"])
    assert report["fill_calibration"]["auc"] > 0.5
    assert min(value["train_rows"] for value in report["fold_details"]) >= 200
    for detail, (start, _) in zip(report["fold_details"], v2.FOLD_WINDOWS):
        assert detail["test_rows"] > 0
        assert v1._epoch_ns(start) > v1._epoch_ns(v2.SOURCE_START)


def test_economic_metrics_preserve_side_and_fold_attribution():
    rows = _synthetic_rows()[:40]
    selected = numpy.asarray([index % 2 == 0 for index in range(len(rows))])
    folds = numpy.asarray([1] * 20 + [2] * 20)
    metrics = v2._economic_metrics(
        rows, selected, outcome="primary", fold_ids=folds
    )
    assert metrics["selected_attempts"] == 20
    assert metrics["by_side"]["buy"]["selected_attempts"] == 20
    assert metrics["by_side"]["sell"]["selected_attempts"] == 0
    assert len(metrics["folds"]) == 2
