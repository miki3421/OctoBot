import json

import numpy
import pytest

from octobot.ai_strategy_lab import scalping_strategy_search as v1
from octobot.ai_strategy_lab import scalping_strategy_search_v2 as v2
from octobot.ai_strategy_lab import scalping_strategy_search_v3 as v3


def test_v3_protocol_is_result_free_and_keeps_locked_test_sealed():
    protocol = v3.frozen_protocol()

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["frozen_source"]["locked_test"] == [
        v2.DIAGNOSTIC_CONFIRMATION_END,
        v2.LOCKED_TEST_END,
    ]
    assert protocol["features"]["original_aggregate_features"] == len(
        v1.FEATURE_NAMES
    )
    assert protocol["features"]["new_queue_flow_features"] == 56
    assert protocol["candidate_family"]["selection_candidates"] == 4
    assert protocol["costs"]["maker_fill_assumptions"] is False


def test_v3_protocol_write_is_immutable(tmp_path):
    path = tmp_path / "protocol.json"
    first = v3.write_or_verify_protocol(path)

    assert v3.write_or_verify_protocol(path) == first
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["protocol_sha256"] == v3._json_hash(
        v3.frozen_protocol()
    )

    persisted["model"]["target_clip_bps"] = 59.0
    path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        v3.write_or_verify_protocol(path)


def test_side_flow_uses_price_priority_for_bid_and_ask():
    assert v3._side_flow(100.0, 10.0, 100.0, 13.0, bid=True) == 3.0
    assert v3._side_flow(100.0, 10.0, 101.0, 7.0, bid=True) == 7.0
    assert v3._side_flow(100.0, 10.0, 99.0, 7.0, bid=True) == -10.0
    assert v3._side_flow(101.0, 8.0, 101.0, 5.0, bid=False) == -3.0
    assert v3._side_flow(101.0, 8.0, 100.0, 5.0, bid=False) == 5.0
    assert v3._side_flow(101.0, 8.0, 102.0, 5.0, bid=False) == -8.0


def test_queue_feature_builder_is_causal_and_finite():
    length = 90
    source = v1.DenseSource(
        start_second=1_000,
        end_second=1_000 + length - 1,
        values=v1._empty_dense_values(length),
    )
    source.values["buy_trade_size"][:] = 4.0
    source.values["sell_trade_size"][:] = 2.0
    queue = v3._empty_queue_values(length)
    queue["event_count"][:] = 10
    queue["normalized_ofi_sum"][:] = 2.0
    queue["normalized_ofi_abs_sum"][:] = 3.0
    queue["depletion_asymmetry_sum"][:] = 1.0
    queue["refill_asymmetry_sum"][:] = 0.5
    queue["depth1_imbalance_sum"][:] = 4.0
    queue["depth5_imbalance_sum"][:] = 2.0
    queue["microprice_change_bps_sum"][:] = 0.1
    queue["quote_up_count"][:] = 3
    queue["quote_down_count"][:] = 1
    queue["depth1_sum"][:] = 1_000.0
    queue["depth5_sum"][:] = 5_000.0
    queue["top_depth_concentration_sum"][:] = 2.0
    candidates = numpy.asarray([60, 61], dtype=numpy.int64)

    features = v3._build_queue_features(source, queue, candidates)

    assert features.shape == (2, len(v3.QUEUE_FEATURE_NAMES))
    assert numpy.all(numpy.isfinite(features))
    assert numpy.allclose(features[:, 0], 0.2)
    assert numpy.allclose(features[:, 6], 0.5)
    assert numpy.allclose(features[:, 10], 10.0)


def test_squared_boosting_regressor_round_trip(tmp_path):
    random = numpy.random.RandomState(7)
    features = random.normal(size=(800, 3)).astype(numpy.float32)
    targets = 4.0 * features[:, 0] - 2.0 * features[:, 1]
    config = v3.model_module.BoostingConfig(
        trees=12,
        max_depth=2,
        bins=12,
        learning_rate=0.1,
        l2=5.0,
        minimum_leaf_rows=20,
        minimum_gain=0.001,
        feature_fraction=1.0,
        seed=7,
    )
    model = v3.NumpySquaredBoostingRegressor.fit(
        features,
        targets,
        feature_names=("a", "b", "c"),
        config=config,
    )
    predictions = model.predict(features)

    assert numpy.corrcoef(predictions, targets)[0, 1] > 0.9
    path = tmp_path / "regressor.npz"
    model.save(path)
    reloaded = v3.NumpySquaredBoostingRegressor.load(path)
    assert numpy.array_equal(predictions, reloaded.predict(features))


def test_v3_scores_require_positive_expectancy_margin_and_non_overlap():
    rows = 5
    timestamps = numpy.arange(1_700_000_000, 1_700_000_000 + rows * 15, 15)
    shape = (rows, len(v2.CONFIGURATIONS))
    exits = numpy.column_stack((timestamps + 20, timestamps + 40))
    dataset = v3.ScalpingV3Dataset(
        timestamps=timestamps,
        features=numpy.zeros((rows, len(v3.FEATURE_NAMES)), dtype=numpy.float32),
        primary_long_return=numpy.full(shape, 0.001, dtype=numpy.float32),
        primary_short_return=numpy.full(shape, -0.001, dtype=numpy.float32),
        primary_long_exit=exits.copy(),
        primary_short_exit=exits.copy(),
        stress_long_return=numpy.full(shape, 0.0005, dtype=numpy.float32),
        stress_short_return=numpy.full(shape, -0.0015, dtype=numpy.float32),
        stress_long_exit=exits.copy(),
        stress_short_exit=exits.copy(),
    )
    indices = numpy.arange(rows, dtype=numpy.int64)
    trades = v3._simulate_scores(
        dataset,
        0,
        indices,
        numpy.asarray([5.0, 5.0, -1.0, 4.0, 5.0]),
        numpy.asarray([1.0, 1.0, -2.0, 3.0, 1.0]),
        2.0,
        stress=False,
    )

    assert trades["rows"].tolist() == [0, 4]
    assert trades["directions"].tolist() == [1, 1]
