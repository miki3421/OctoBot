#  Drakkar-Software OctoBot-Tentacles
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.

"""Quantitative market-regime features for deterministic research strategies."""

import math

import numpy
import tulipy

import octobot_commons.constants as commons_constants
import octobot_commons.enums as enums
import octobot_commons.data_util as data_util
import octobot_evaluators.evaluators as evaluators
import octobot_evaluators.util as evaluators_util
import octobot_trading.api as trading_api


class MarketRegimeEvaluator(evaluators.TAEvaluator):
    """Publish a directional note plus explicit, auditable regime metadata."""

    SCHEMA_VERSION = 1

    def __init__(self, tentacles_setup_config):
        super().__init__(tentacles_setup_config)
        self.adx_period = 14
        self.trend_adx_threshold = 25.0
        self.range_adx_threshold = 20.0
        self.fast_ema_period = 20
        self.slow_ema_period = 50
        self.minimum_ema_spread_pct = 0.25
        self.bollinger_period = 20
        self.bollinger_stddev = 2.0
        self.volatility_lookback = 100
        self.high_volatility_percentile = 0.90
        self.atr_period = 14

    def init_user_inputs(self, inputs: dict) -> None:
        defaults = self.get_default_config()
        self.adx_period = self.UI.user_input(
            "adx_period", enums.UserInputTypes.INT, defaults["adx_period"], inputs,
            min_val=2, title="ADX period used by the regime classifier.",
        )
        self.trend_adx_threshold = self.UI.user_input(
            "trend_adx_threshold", enums.UserInputTypes.FLOAT,
            defaults["trend_adx_threshold"], inputs, min_val=1,
            title="Minimum ADX required to classify a trend.",
        )
        self.range_adx_threshold = self.UI.user_input(
            "range_adx_threshold", enums.UserInputTypes.FLOAT,
            defaults["range_adx_threshold"], inputs, min_val=0,
            title="Maximum ADX used to classify a range.",
        )
        self.fast_ema_period = self.UI.user_input(
            "fast_ema_period", enums.UserInputTypes.INT,
            defaults["fast_ema_period"], inputs, min_val=2,
            title="Fast EMA period used for trend direction.",
        )
        self.slow_ema_period = self.UI.user_input(
            "slow_ema_period", enums.UserInputTypes.INT,
            defaults["slow_ema_period"], inputs, min_val=3,
            title="Slow EMA period used for trend direction.",
        )
        self.minimum_ema_spread_pct = self.UI.user_input(
            "minimum_ema_spread_pct", enums.UserInputTypes.FLOAT,
            defaults["minimum_ema_spread_pct"], inputs, min_val=0,
            title="Minimum absolute EMA spread percentage required for a trend.",
        )
        self.bollinger_period = self.UI.user_input(
            "bollinger_period", enums.UserInputTypes.INT,
            defaults["bollinger_period"], inputs, min_val=2,
            title="Bollinger Bands period.",
        )
        self.bollinger_stddev = self.UI.user_input(
            "bollinger_stddev", enums.UserInputTypes.FLOAT,
            defaults["bollinger_stddev"], inputs, min_val=0.1,
            title="Bollinger Bands standard-deviation multiplier.",
        )
        self.volatility_lookback = self.UI.user_input(
            "volatility_lookback", enums.UserInputTypes.INT,
            defaults["volatility_lookback"], inputs, min_val=20,
            title="Bollinger bandwidth percentile lookback.",
        )
        self.high_volatility_percentile = self.UI.user_input(
            "high_volatility_percentile", enums.UserInputTypes.FLOAT,
            defaults["high_volatility_percentile"], inputs,
            min_val=0.5, max_val=1.0,
            title="Percentile at which volatility is classified as high.",
        )
        self.atr_period = self.UI.user_input(
            "atr_period", enums.UserInputTypes.INT, defaults["atr_period"], inputs,
            min_val=2, title="ATR period used for normalized volatility.",
        )
        if self.range_adx_threshold >= self.trend_adx_threshold:
            raise ValueError("range_adx_threshold must be below trend_adx_threshold")
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be below slow_ema_period")

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "adx_period": 14,
            "trend_adx_threshold": 25.0,
            "range_adx_threshold": 20.0,
            "fast_ema_period": 20,
            "slow_ema_period": 50,
            "minimum_ema_spread_pct": 0.25,
            "bollinger_period": 20,
            "bollinger_stddev": 2.0,
            "volatility_lookback": 100,
            "high_volatility_percentile": 0.90,
            "atr_period": 14,
        }

    def _minimum_candles(self) -> int:
        return max(
            self.slow_ema_period,
            self.bollinger_period + self.volatility_lookback,
            self.adx_period + 12,
            self.atr_period + 1,
        )

    async def ohlcv_callback(
        self, exchange: str, exchange_id: str, cryptocurrency: str,
        symbol: str, time_frame, candle, inc_in_construction_data,
    ):
        symbol_candles = self.get_exchange_symbol_data(exchange, exchange_id, symbol)
        close = trading_api.get_symbol_close_candles(
            symbol_candles, time_frame, include_in_construction=inc_in_construction_data
        )
        high = trading_api.get_symbol_high_candles(
            symbol_candles, time_frame, include_in_construction=inc_in_construction_data
        )
        low = trading_api.get_symbol_low_candles(
            symbol_candles, time_frame, include_in_construction=inc_in_construction_data
        )
        await self.evaluate(cryptocurrency, symbol, time_frame, close, high, low, candle)

    async def evaluate(
        self, cryptocurrency, symbol, time_frame, close, high, low, candle
    ):
        self.eval_note = commons_constants.START_PENDING_EVAL_NOTE
        metadata = None
        if min(len(close), len(high), len(low)) >= self._minimum_candles():
            metadata = self.compute_snapshot(close, high, low)
            direction = metadata["direction"]
            self.eval_note = -1.0 if direction == "BULLISH" else 1.0
        await self.evaluation_completed(
            cryptocurrency,
            symbol,
            time_frame,
            eval_time=evaluators_util.get_eval_time(
                full_candle=candle, time_frame=time_frame
            ),
            eval_note_description=(
                None if metadata is None else
                f"regime={metadata['regime']}; direction={metadata['direction']}; "
                f"ADX={metadata['adx']:.2f}; ATR={metadata['atr_pct']:.2f}%"
            ),
            eval_note_metadata=metadata,
        )

    def compute_snapshot(self, close, high, low) -> dict:
        close = numpy.asarray(close, dtype=float)
        high = numpy.asarray(high, dtype=float)
        low = numpy.asarray(low, dtype=float)

        adx_values = data_util.drop_nan(
            tulipy.adx(high, low, close, self.adx_period)
        )
        atr_values = data_util.drop_nan(
            tulipy.atr(high, low, close, self.atr_period)
        )
        fast_ema = float(tulipy.ema(close, self.fast_ema_period)[-1])
        slow_ema = float(tulipy.ema(close, self.slow_ema_period)[-1])
        lower, middle, upper = tulipy.bbands(
            close, self.bollinger_period, self.bollinger_stddev
        )

        valid_middle = numpy.where(middle == 0, numpy.nan, middle)
        bandwidths = data_util.drop_nan((upper - lower) / valid_middle * 100)
        recent_bandwidths = bandwidths[-self.volatility_lookback:]
        current_bandwidth = float(recent_bandwidths[-1])
        bandwidth_percentile = float(
            numpy.mean(recent_bandwidths <= current_bandwidth)
        )
        band_range = float(upper[-1] - lower[-1])
        bb_position = 0.5 if band_range == 0 else float(
            (close[-1] - lower[-1]) / band_range
        )

        current_close = float(close[-1])
        current_adx = float(adx_values[-1])
        atr_pct = 0.0 if current_close == 0 else float(
            atr_values[-1] / current_close * 100
        )
        ema_spread_pct = 0.0 if slow_ema == 0 else float(
            abs(fast_ema - slow_ema) / abs(slow_ema) * 100
        )
        direction = "BULLISH" if fast_ema >= slow_ema else "BEARISH"

        if (
            current_adx >= self.trend_adx_threshold
            and ema_spread_pct >= self.minimum_ema_spread_pct
        ):
            regime = "trend"
        elif current_adx <= self.range_adx_threshold:
            regime = "range"
        else:
            regime = "transition"

        values = {
            "schema_version": self.SCHEMA_VERSION,
            "regime": regime,
            "direction": direction,
            "adx": current_adx,
            "atr_pct": atr_pct,
            "ema_spread_pct": ema_spread_pct,
            "bb_width_pct": current_bandwidth,
            "bb_width_percentile": bandwidth_percentile,
            "bb_position": bb_position,
            "high_volatility": bandwidth_percentile >= self.high_volatility_percentile,
        }
        if any(
            isinstance(value, float) and not math.isfinite(value)
            for value in values.values()
        ):
            raise ValueError("Market regime computation produced a non-finite value")
        return values
