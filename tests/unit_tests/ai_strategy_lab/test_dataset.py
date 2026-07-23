import numpy

from octobot.ai_strategy_lab import dataset


def _candles(*rows):
    return numpy.asarray(rows, dtype=float)


def test_same_candle_target_and_stop_uses_conservative_stop():
    candles = _candles(
        (0, 100, 101, 99, 100, 1),
        (900, 100, 103, 98, 101, 1),
    )
    result = dataset._triple_barrier_label(
        candles,
        0,
        1,
        0.01,
        dataset.BarrierConfig(
            atr_multiplier=1,
            reward_risk_ratio=2,
            minimum_stop_pct=0.01,
            maximum_stop_pct=0.01,
            horizon_bars=1,
            fee_rate_per_fill=0,
            slippage_rate_per_fill=0,
        ),
    )
    assert result["outcome"] == dataset.OUTCOME_STOP
    assert result["exit_timestamp"] == 1800
    assert result["gross_return"] == -0.01


def test_timeout_closes_at_horizon_and_charges_costs():
    candles = _candles(
        (0, 100, 100, 100, 100, 1),
        (900, 100, 101, 99.5, 101, 1),
        (1800, 101, 102, 100.5, 102, 1),
    )
    result = dataset._triple_barrier_label(
        candles,
        0,
        1,
        0.02,
        dataset.BarrierConfig(
            atr_multiplier=1,
            reward_risk_ratio=2,
            minimum_stop_pct=0.02,
            maximum_stop_pct=0.02,
            horizon_bars=2,
            fee_rate_per_fill=0.001,
            slippage_rate_per_fill=0.0005,
        ),
    )
    assert result["outcome"] == dataset.OUTCOME_TIMEOUT
    assert result["duration_bars"] == 2
    assert result["exit_timestamp"] == 2700
    assert numpy.isclose(result["gross_return"], 0.02)
    assert numpy.isclose(result["net_return"], 0.02 - 0.001 * 2.02 - 0.001)


def test_signed_historical_funding_costs_long_and_credits_short():
    candles = _candles(
        (0, 100, 100, 100, 100, 1),
        (900, 100, 100.5, 99.5, 100, 1),
    )
    config = dataset.BarrierConfig(
        atr_multiplier=1,
        reward_risk_ratio=2,
        minimum_stop_pct=0.02,
        maximum_stop_pct=0.02,
        horizon_bars=1,
        fee_rate_per_fill=0,
        slippage_rate_per_fill=0,
    )
    funding = (
        numpy.asarray([1800], dtype=numpy.int64),
        numpy.asarray([0.001]),
    )
    long_result = dataset._triple_barrier_label(
        candles, 0, 1, 0.02, config, funding
    )
    short_result = dataset._triple_barrier_label(
        candles, 0, -1, 0.02, config, funding
    )
    assert numpy.isclose(long_result["net_return"], -0.001)
    assert numpy.isclose(short_result["net_return"], 0.001)


def test_dataset_round_trip(tmp_path):
    research_dataset = _minimal_dataset(12)
    output = tmp_path / "dataset.npz"
    source = tmp_path / "source.data"
    source.write_bytes(b"source")
    config = dataset.DatasetBuildConfig(candidate_stride=4)
    manifest = dataset.save_dataset(
        research_dataset,
        output,
        collector_paths=[source],
        config=config,
    )
    loaded = dataset.load_dataset(output)
    assert manifest["rows"] == 12
    assert manifest["config"]["candidate_stride"] == 4
    assert loaded.feature_names == research_dataset.feature_names
    assert numpy.array_equal(loaded.features, research_dataset.features)
    assert numpy.array_equal(loaded.outcome, research_dataset.outcome)


def _minimal_dataset(rows):
    timestamp = numpy.arange(rows, dtype=numpy.int64) * 900 + 10_000
    return dataset.ResearchDataset(
        features=numpy.column_stack(
            (numpy.linspace(-1, 1, rows), numpy.linspace(1, -1, rows))
        ).astype(numpy.float32),
        feature_names=("first", "second"),
        label=(numpy.arange(rows) % 2).astype(numpy.int8),
        outcome=numpy.where(
            numpy.arange(rows) % 2,
            dataset.OUTCOME_TARGET,
            dataset.OUTCOME_STOP,
        ).astype(numpy.int8),
        profitable=(numpy.arange(rows) % 2).astype(numpy.int8),
        net_return=numpy.where(numpy.arange(rows) % 2, 0.02, -0.01),
        gross_return=numpy.where(numpy.arange(rows) % 2, 0.021, -0.009),
        timestamp=timestamp,
        exit_timestamp=timestamp + 900,
        event_end_timestamp=timestamp + 3600,
        symbol=numpy.asarray(["BTC/USDT:USDT"] * rows),
        direction=numpy.where(numpy.arange(rows) % 2, 1, -1).astype(numpy.int8),
        entry_price=numpy.full(rows, 100.0),
        stop_price=numpy.full(rows, 99.0),
        target_price=numpy.full(rows, 102.0),
        duration_bars=numpy.ones(rows, dtype=numpy.int16),
        mfe_return=numpy.full(rows, 0.02),
        mae_return=numpy.full(rows, -0.01),
    )
