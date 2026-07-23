import numpy

from octobot.ai_strategy_lab import dataset
from octobot.ai_strategy_lab import experts


def test_expert_masks_are_directional_and_short_expert_is_short_only():
    names = (
        "4h_adx",
        "1h_adx",
        "directional_4h_ema_spread_pct",
        "directional_4h_ema_slope_pct",
        "directional_1h_ema_spread_pct",
        "directional_1h_ema_slope_pct",
        "directional_15m_bb_position",
        "directional_15m_rsi_centered",
        "directional_15m_macd_hist_pct",
        "directional_15m_return_4",
        "15m_volume_zscore",
        "directional_1h_return_4",
    )
    row = [0.30, 0.30, 0.01, 0.01, 0.01, 0.01, 0.0, 0.0, 0.01, 0.01, 2.0, 0.01]
    research = _dataset(names, numpy.asarray([row, row]), numpy.asarray([1, -1]))
    masks = experts.expert_masks(research)
    assert masks["trend_pullback_v1"].tolist() == [True, True]
    assert masks["breakout_v1"].tolist() == [False, False]
    assert masks["short_momentum_v1"].tolist() == [False, True]


def _dataset(feature_names, features, direction):
    rows = len(direction)
    timestamps = numpy.arange(rows, dtype=numpy.int64) * 900 + 1_700_000_000
    return dataset.ResearchDataset(
        features=features,
        feature_names=feature_names,
        label=numpy.zeros(rows, dtype=numpy.int8),
        outcome=numpy.zeros(rows, dtype=numpy.int8),
        profitable=numpy.zeros(rows, dtype=numpy.int8),
        net_return=numpy.zeros(rows),
        gross_return=numpy.zeros(rows),
        timestamp=timestamps,
        exit_timestamp=timestamps + 900,
        event_end_timestamp=timestamps + 900,
        symbol=numpy.asarray(["BTC/USDT:USDT"] * rows),
        direction=direction,
        entry_price=numpy.ones(rows),
        stop_price=numpy.ones(rows),
        target_price=numpy.ones(rows),
        duration_bars=numpy.ones(rows, dtype=numpy.int16),
        mfe_return=numpy.zeros(rows),
        mae_return=numpy.zeros(rows),
    )
