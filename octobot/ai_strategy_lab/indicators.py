"""Small NumPy-only technical indicator implementation for offline research."""

import math

import numpy


def ema(values: numpy.ndarray, period: int) -> numpy.ndarray:
    result = numpy.full(values.shape, numpy.nan, dtype=float)
    if period < 1 or len(values) < period:
        return result
    initial = float(numpy.mean(values[:period]))
    result[period - 1] = initial
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        result[index] = alpha * values[index] + (1.0 - alpha) * result[index - 1]
    return result


def atr(high: numpy.ndarray, low: numpy.ndarray, close: numpy.ndarray, period: int = 14) -> numpy.ndarray:
    true_range = numpy.full(close.shape, numpy.nan, dtype=float)
    if not len(close):
        return true_range
    true_range[0] = high[0] - low[0]
    if len(close) > 1:
        true_range[1:] = numpy.maximum.reduce(
            (
                high[1:] - low[1:],
                numpy.abs(high[1:] - close[:-1]),
                numpy.abs(low[1:] - close[:-1]),
            )
        )
    return _wilder_average(true_range, period)


def rsi(close: numpy.ndarray, period: int = 14) -> numpy.ndarray:
    result = numpy.full(close.shape, numpy.nan, dtype=float)
    if len(close) <= period:
        return result
    changes = numpy.diff(close, prepend=close[0])
    gains = numpy.maximum(changes, 0.0)
    losses = numpy.maximum(-changes, 0.0)
    average_gain = _wilder_average(gains, period, start_index=1)
    average_loss = _wilder_average(losses, period, start_index=1)
    valid = numpy.isfinite(average_gain) & numpy.isfinite(average_loss)
    zero_loss = valid & (average_loss == 0)
    result[zero_loss] = 100.0
    regular = valid & (average_loss > 0)
    relative_strength = average_gain[regular] / average_loss[regular]
    result[regular] = 100.0 - 100.0 / (1.0 + relative_strength)
    return result


def adx(
    high: numpy.ndarray,
    low: numpy.ndarray,
    close: numpy.ndarray,
    period: int = 14,
) -> numpy.ndarray:
    result = numpy.full(close.shape, numpy.nan, dtype=float)
    if len(close) <= 2 * period:
        return result

    up_move = numpy.diff(high, prepend=high[0])
    down_move = -numpy.diff(low, prepend=low[0])
    plus_dm = numpy.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = numpy.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    true_range = numpy.full(close.shape, 0.0, dtype=float)
    true_range[0] = high[0] - low[0]
    true_range[1:] = numpy.maximum.reduce(
        (
            high[1:] - low[1:],
            numpy.abs(high[1:] - close[:-1]),
            numpy.abs(low[1:] - close[:-1]),
        )
    )

    tr_sum = float(numpy.sum(true_range[1 : period + 1]))
    plus_sum = float(numpy.sum(plus_dm[1 : period + 1]))
    minus_sum = float(numpy.sum(minus_dm[1 : period + 1]))
    dx = numpy.full(close.shape, numpy.nan, dtype=float)

    for index in range(period, len(close)):
        if index > period:
            tr_sum = tr_sum - tr_sum / period + true_range[index]
            plus_sum = plus_sum - plus_sum / period + plus_dm[index]
            minus_sum = minus_sum - minus_sum / period + minus_dm[index]
        if tr_sum <= 0:
            dx[index] = 0.0
            continue
        plus_di = 100.0 * plus_sum / tr_sum
        minus_di = 100.0 * minus_sum / tr_sum
        denominator = plus_di + minus_di
        dx[index] = 0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator

    first_adx_index = 2 * period - 1
    result[first_adx_index] = float(numpy.mean(dx[period : first_adx_index + 1]))
    for index in range(first_adx_index + 1, len(close)):
        result[index] = ((period - 1) * result[index - 1] + dx[index]) / period
    return result


def rolling_mean_std(values: numpy.ndarray, period: int) -> tuple:
    means = numpy.full(values.shape, numpy.nan, dtype=float)
    standard_deviations = numpy.full(values.shape, numpy.nan, dtype=float)
    if period < 1 or len(values) < period:
        return means, standard_deviations
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        means[index] = float(numpy.mean(window))
        standard_deviations[index] = float(numpy.std(window))
    return means, standard_deviations


def _wilder_average(
    values: numpy.ndarray,
    period: int,
    *,
    start_index: int = 0,
) -> numpy.ndarray:
    result = numpy.full(values.shape, numpy.nan, dtype=float)
    first_index = start_index + period - 1
    if period < 1 or first_index >= len(values):
        return result
    result[first_index] = float(numpy.mean(values[start_index : first_index + 1]))
    for index in range(first_index + 1, len(values)):
        result[index] = ((period - 1) * result[index - 1] + values[index]) / period
    return result


def compute_feature_arrays(candles: numpy.ndarray) -> dict:
    """Return point-in-time features whose value at i uses candles <= i only."""

    high = candles[:, 2]
    low = candles[:, 3]
    close = candles[:, 4]
    volume = candles[:, 5]

    fast_ema = ema(close, 20)
    slow_ema = ema(close, 50)
    atr_values = atr(high, low, close, 14)
    adx_values = adx(high, low, close, 14)
    rsi_values = rsi(close, 14)
    macd_line = ema(close, 12) - ema(close, 26)
    finite_macd = macd_line[numpy.isfinite(macd_line)]
    macd_signal = numpy.full(close.shape, numpy.nan, dtype=float)
    if len(finite_macd) >= 9:
        first_finite = int(numpy.flatnonzero(numpy.isfinite(macd_line))[0])
        signal_values = ema(macd_line[first_finite:], 9)
        macd_signal[first_finite:] = signal_values

    middle, standard_deviation = rolling_mean_std(close, 20)
    upper = middle + 2.0 * standard_deviation
    lower = middle - 2.0 * standard_deviation
    band_range = upper - lower
    bb_position = numpy.divide(
        close - lower,
        band_range,
        out=numpy.full(close.shape, numpy.nan, dtype=float),
        where=band_range != 0,
    )

    log_close = numpy.log(numpy.maximum(close, numpy.finfo(float).tiny))
    log_return_1 = _lag_difference(log_close, 1)
    log_return_4 = _lag_difference(log_close, 4)
    # rolling_mean_std returns (mean, std); only the std is a volatility feature.
    _, return_volatility = rolling_mean_std(log_return_1, 20)
    volume_mean, volume_std = rolling_mean_std(volume, 20)

    features = {
        "return_1": log_return_1,
        "return_4": log_return_4,
        "atr_pct": _safe_percentage(atr_values, close),
        "adx": adx_values / 100.0,
        "ema_spread_pct": _safe_percentage(fast_ema - slow_ema, slow_ema),
        "ema_slope_pct": _safe_percentage(fast_ema - _lag(fast_ema, 3), _lag(fast_ema, 3)),
        "bb_position": bb_position - 0.5,
        "bb_width_pct": _safe_percentage(band_range, middle),
        "rsi_centered": (rsi_values - 50.0) / 50.0,
        "macd_hist_pct": _safe_percentage(macd_line - macd_signal, close),
        "return_volatility": return_volatility,
        "volume_zscore": numpy.divide(
            volume - volume_mean,
            volume_std,
            out=numpy.full(close.shape, numpy.nan, dtype=float),
            where=volume_std > 0,
        ),
    }
    return features


def _lag(values: numpy.ndarray, periods: int) -> numpy.ndarray:
    result = numpy.full(values.shape, numpy.nan, dtype=float)
    if periods < len(values):
        result[periods:] = values[:-periods]
    return result


def _lag_difference(values: numpy.ndarray, periods: int) -> numpy.ndarray:
    lagged = _lag(values, periods)
    return values - lagged


def _safe_percentage(numerator: numpy.ndarray, denominator: numpy.ndarray) -> numpy.ndarray:
    result = numpy.divide(
        numerator,
        denominator,
        out=numpy.full(numerator.shape, numpy.nan, dtype=float),
        where=denominator != 0,
    )
    result[~numpy.isfinite(result)] = numpy.nan
    return result


def is_finite_feature_row(values: numpy.ndarray) -> bool:
    return bool(numpy.all(numpy.isfinite(values))) and not any(
        math.isinf(float(value)) for value in values
    )
