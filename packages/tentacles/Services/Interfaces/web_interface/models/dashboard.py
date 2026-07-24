#  Drakkar-Software OctoBot-Interfaces
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library.
import functools
import json
import math
import os
import pathlib
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

import numpy as np

import octobot_backtesting.api as backtesting_api
import octobot_services.interfaces.util as interfaces_util
import octobot_trading.api as trading_api
import octobot_trading.enums as trading_enums
import octobot_trading.constants as trading_constants
import tentacles.Services.Interfaces.web_interface.models.interface_settings as interface_settings
import tentacles.Services.Interfaces.web_interface.enums as enums
import octobot_commons.timestamp_util as timestamp_util
import octobot_commons.enums as commons_enums
import octobot_commons.symbols as commons_symbols
import octobot.ai_strategy_lab.percentage_engine as percentage_engine
import octobot.ai_strategy_lab.percentage_probability_engine as percentage_probability_engine
import octobot.ai_strategy_lab.percentage_signal_engine as percentage_signal_engine

GET_SYMBOL_SEPARATOR = "|"
DISPLAY_CANCELLED_TRADES = False
PERCENTAGE_RESEARCH_5M_COLLECTOR = pathlib.Path(
    os.environ.get(
        "PERCENTAGE_RESEARCH_5M_COLLECTOR",
        (
            "/octobot/backtesting/research/"
            "kucoin_futures_5m_BTC_20250722_20260721.data"
        ),
    )
)
KUCOIN_FUTURES_KLINES_URL = "https://api-futures.kucoin.com/api/v1/kline/query"
PERCENTAGE_RESEARCH_5M_HISTORY_LIMIT = 5000
PERCENTAGE_RESEARCH_5M_CACHE_SECONDS = 60
_percentage_research_5m_live_cache = {}
_percentage_research_5m_live_lock = threading.Lock()


def parse_get_symbol(get_symbol):
    return get_symbol.replace(GET_SYMBOL_SEPARATOR, "/")


def get_value_from_dict_or_string(data):
    if isinstance(data, dict):
        return data["value"]
    else:
        return data


def format_trades(dict_trade_history):
    trade_time_key = "time"
    trade_price_key = "price"
    trade_description_key = "trade_description"
    trade_order_side_key = "order_side"
    trades = {
        trade_time_key: [],
        trade_price_key: [],
        trade_description_key: [],
        trade_order_side_key: []
    }
    if not dict_trade_history:
        return trades
    for dict_trade in dict_trade_history:
        status = dict_trade.get(trading_enums.ExchangeConstantsOrderColumns.STATUS.value,
                                trading_enums.OrderStatus.UNKNOWN.value)
        trade_side = trading_enums.TradeOrderSide(dict_trade[trading_enums.ExchangeConstantsOrderColumns.SIDE.value])
        trade_type = trading_api.parse_trade_type(dict_trade)
        if trade_type in (trading_enums.TraderOrderType.UNSUPPORTED, trading_enums.TraderOrderType.UNKNOWN):
            trade_type = trade_side
        if status is not trading_enums.OrderStatus.CANCELED.value or DISPLAY_CANCELLED_TRADES:
            trade_time = dict_trade[trading_enums.ExchangeConstantsOrderColumns.TIMESTAMP.value]
            if trade_time > trading_constants.MINIMUM_VAL_TRADE_TIME:
                trades[trade_time_key].append(
                    timestamp_util.convert_timestamp_to_datetime(
                        trade_time, time_format="%y-%m-%d %H:%M:%S", local_timezone=True
                    )
                )
                trades[trade_price_key].append(
                    float(dict_trade[trading_enums.ExchangeConstantsOrderColumns.PRICE.value]))
                trades[trade_description_key].append(
                    f"{trade_type.name.replace('_', ' ')}: "
                    f"{dict_trade[trading_enums.ExchangeConstantsOrderColumns.AMOUNT.value]} "
                    f"{dict_trade[trading_enums.ExchangeConstantsOrderColumns.QUANTITY_CURRENCY.value]} "
                    f"at {dict_trade[trading_enums.ExchangeConstantsOrderColumns.PRICE.value]} "
                    f"{dict_trade[trading_enums.ExchangeConstantsOrderColumns.MARKET.value]}")
                trades[trade_order_side_key].append(trade_side.value)

    return trades


def format_orders(order, min_order_time):
    time_key = "time"
    price_key = "price"
    description_key = "description"
    order_side_key = "order_side"
    formatted_orders = {
        time_key: [],
        price_key: [],
        description_key: [],
        order_side_key: []
    }
    for order in order:
        if order.creation_time > trading_constants.MINIMUM_VAL_TRADE_TIME:
            formatted_orders[time_key].append(
                timestamp_util.convert_timestamp_to_datetime(
                    max(min_order_time, order.creation_time),
                    time_format="%y-%m-%d %H:%M:%S", local_timezone=True
                )
            )
            formatted_orders[price_key].append(float(order.origin_price))
            formatted_orders[description_key].append(
                f"{order.order_type.name.replace('_', ' ')}: {order.origin_quantity} {order.quantity_currency} "
                f"at {order.origin_price}"
            )
            formatted_orders[order_side_key].append(order.side.value)
    return formatted_orders


def _remove_invalid_chars(string):
    return string.split("[")[0]


def _get_candles_reply(exchange, exchange_id, symbol, time_frame):
    return {
        "exchange_name": _remove_invalid_chars(exchange),
        "exchange_id": exchange_id,
        "symbol": symbol,
        "time_frame": time_frame.value
    }


def _get_first_exchange_identifiers(exchange_name=None, trading_exchange_only=False):
    for exchange_manager in interfaces_util.get_exchange_managers():
        if trading_exchange_only and not trading_api.is_trader_existing_and_enabled(exchange_manager):
            continue
        name = trading_api.get_exchange_name(exchange_manager)
        if exchange_name is None or name == exchange_name:
            return exchange_manager, name, trading_api.get_exchange_manager_id(exchange_manager)
    raise KeyError("No exchange to be found")


def get_first_exchange_data(exchange_name=None, trading_exchange_only=False):
    return _get_first_exchange_identifiers(exchange_name, trading_exchange_only=trading_exchange_only)


def get_watched_symbol_data(symbol):
    symbol_object = commons_symbols.parse_symbol(parse_get_symbol(symbol))
    try:
        last_possibility = {}
        for exchange_manager in interfaces_util.get_exchange_managers():
            exchange_id = trading_api.get_exchange_manager_id(exchange_manager)
            exchange_name = trading_api.get_exchange_name(exchange_manager)
            last_possibility = _get_candles_reply(
                exchange_name,
                exchange_id,
                symbol,
                _get_default_time_frame(exchange_name, exchange_id)
            )
            if symbol_object in trading_api.get_trading_symbols(exchange_manager):
                return last_possibility
        # symbol has not been found in exchange, still return the last exchange
        # in case it becomes available
        return last_possibility
    except KeyError:
        return {}


def _get_default_time_frame(exchange_name, exchange_id):
    available_time_frames = trading_api.get_watched_timeframes(
        trading_api.get_exchange_manager_from_exchange_name_and_id(exchange_name, exchange_id)
    )
    display_time_frame = commons_enums.TimeFrames(interface_settings.get_display_timeframe())
    if display_time_frame in available_time_frames:
        return display_time_frame
    return available_time_frames[0]


def _is_symbol_data_available(exchange_manager, symbol):
    return symbol in trading_api.get_trading_pairs(exchange_manager)


def get_startup_messages():
    return interfaces_util.get_bot_api().get_startup_messages()


def get_first_symbol_data():
    try:
        exchange, exchange_name, exchange_id = _get_first_exchange_identifiers()
        symbol = trading_api.get_trading_pairs(exchange)[0]
        time_frame = _get_default_time_frame(exchange_name, exchange_id)
        return _get_candles_reply(exchange_name, exchange_id, symbol, time_frame)
    except (KeyError, IndexError):
        return {}


def _create_candles_data(exchange_manager, symbol, time_frame, historical_candles, kline,
                         bot_api, list_arrays, in_backtesting, ignore_trades, ignore_orders):
    candles_key = "candles"
    trades_key = "trades"
    orders_key = "orders"
    symbol_key = "symbol"
    simulated_key = "simulated"
    exchange_id_key = "exchange_id"
    result_dict = {
        candles_key: {},
        trades_key: {},
        orders_key: {},
        simulated_key: trading_api.is_trader_simulated(exchange_manager),
        symbol_key: symbol,
        exchange_id_key: trading_api.get_exchange_manager_id(exchange_manager),
    }
    try:
        data = historical_candles

        # add kline as the last (current) candle that is not yet in history
        if math.nan not in kline and data[commons_enums.PriceIndexes.IND_PRICE_TIME.value][-1] != kline[
            commons_enums.PriceIndexes.IND_PRICE_TIME.value]:
            data[commons_enums.PriceIndexes.IND_PRICE_TIME.value] = np.append(
                data[commons_enums.PriceIndexes.IND_PRICE_TIME.value],
                kline[commons_enums.PriceIndexes.IND_PRICE_TIME.value])
            data[commons_enums.PriceIndexes.IND_PRICE_CLOSE.value] = np.append(
                data[commons_enums.PriceIndexes.IND_PRICE_CLOSE.value],
                kline[commons_enums.PriceIndexes.IND_PRICE_CLOSE.value])
            data[commons_enums.PriceIndexes.IND_PRICE_LOW.value] = np.append(
                data[commons_enums.PriceIndexes.IND_PRICE_LOW.value],
                kline[commons_enums.PriceIndexes.IND_PRICE_LOW.value])
            data[commons_enums.PriceIndexes.IND_PRICE_OPEN.value] = np.append(
                data[commons_enums.PriceIndexes.IND_PRICE_OPEN.value],
                kline[commons_enums.PriceIndexes.IND_PRICE_OPEN.value])
            data[commons_enums.PriceIndexes.IND_PRICE_HIGH.value] = np.append(
                data[commons_enums.PriceIndexes.IND_PRICE_HIGH.value],
                kline[commons_enums.PriceIndexes.IND_PRICE_HIGH.value])
            data[commons_enums.PriceIndexes.IND_PRICE_VOL.value] = np.append(
                data[commons_enums.PriceIndexes.IND_PRICE_VOL.value],
                kline[commons_enums.PriceIndexes.IND_PRICE_VOL.value])
        data_x = timestamp_util.convert_timestamps_to_datetime(data[commons_enums.PriceIndexes.IND_PRICE_TIME.value],
                                                               time_format="%y-%m-%d %H:%M:%S",
                                                               local_timezone=True)
        if not ignore_trades:
            # handle trades after the 1st displayed candle start time for dashboard
            first_time_to_handle_in_board = data[commons_enums.PriceIndexes.IND_PRICE_TIME.value][0]
            trades_history = []
            if trading_api.is_trader_existing_and_enabled(exchange_manager):
                trades_history += trading_api.get_trade_history(exchange_manager, None, symbol,
                                                                first_time_to_handle_in_board, True)

            result_dict[trades_key] = format_trades(trades_history)

        if not ignore_orders:
            if trading_api.is_trader_existing_and_enabled(exchange_manager):
                result_dict[orders_key] = format_orders(
                    trading_api.get_open_orders(exchange_manager, symbol=symbol),
                    # align time for historical candles only
                    data[commons_enums.PriceIndexes.IND_PRICE_TIME.value][0]
                    if len(data[commons_enums.PriceIndexes.IND_PRICE_TIME.value]) > 2 else 0
                )

        if list_arrays:
            result_dict[candles_key] = {
                enums.PriceStrings.STR_PRICE_TIME.value: data_x,
                enums.PriceStrings.STR_PRICE_CLOSE.value: data[
                    commons_enums.PriceIndexes.IND_PRICE_CLOSE.value].tolist(),
                enums.PriceStrings.STR_PRICE_LOW.value: data[commons_enums.PriceIndexes.IND_PRICE_LOW.value].tolist(),
                enums.PriceStrings.STR_PRICE_OPEN.value: data[commons_enums.PriceIndexes.IND_PRICE_OPEN.value].tolist(),
                enums.PriceStrings.STR_PRICE_HIGH.value: data[commons_enums.PriceIndexes.IND_PRICE_HIGH.value].tolist(),
                enums.PriceStrings.STR_PRICE_VOL.value: data[commons_enums.PriceIndexes.IND_PRICE_VOL.value].tolist()
            }
            if len(data_x) >= 3:
                try:
                    result_dict["percentage_research"] = (
                        percentage_engine.analyze_percentage_opportunities(
                            times=data_x,
                            opens=data[commons_enums.PriceIndexes.IND_PRICE_OPEN.value],
                            highs=data[commons_enums.PriceIndexes.IND_PRICE_HIGH.value],
                            lows=data[commons_enums.PriceIndexes.IND_PRICE_LOW.value],
                            closes=data[commons_enums.PriceIndexes.IND_PRICE_CLOSE.value],
                        )
                    )
                except (TypeError, ValueError) as error:
                    result_dict["percentage_research"] = {
                        "schema_version": 1,
                        "mode": "hindsight_percentage_research_only",
                        "research_only": True,
                        "orders_authorized": False,
                        "error": str(error),
                    }
                time_frame_value = (
                    time_frame.value
                    if hasattr(time_frame, "value")
                    else str(time_frame)
                )
                if time_frame_value == "1h":
                    try:
                        result_dict["percentage_causal"] = (
                            percentage_signal_engine.analyze_causal_percentage_signals(
                                times=data_x,
                                opens=data[commons_enums.PriceIndexes.IND_PRICE_OPEN.value],
                                highs=data[commons_enums.PriceIndexes.IND_PRICE_HIGH.value],
                                lows=data[commons_enums.PriceIndexes.IND_PRICE_LOW.value],
                                closes=data[commons_enums.PriceIndexes.IND_PRICE_CLOSE.value],
                                volumes=data[commons_enums.PriceIndexes.IND_PRICE_VOL.value],
                            )
                        )
                    except (TypeError, ValueError) as error:
                        result_dict["percentage_causal"] = {
                            "schema_version": 1,
                            "mode": "causal_percentage_candidate_v1",
                            "research_only": True,
                            "signal_uses_future_outcomes": False,
                            "orders_authorized": False,
                            "automatic_promotion": False,
                            "error": str(error),
                        }
                if time_frame_value in {"5m", "15m"}:
                    try:
                        result_dict["percentage_probability"] = (
                            percentage_probability_engine.analyze_chart_probabilities(
                                times=data[
                                    commons_enums.PriceIndexes.IND_PRICE_TIME.value
                                ],
                                display_times=data_x,
                                opens=data[
                                    commons_enums.PriceIndexes.IND_PRICE_OPEN.value
                                ],
                                highs=data[
                                    commons_enums.PriceIndexes.IND_PRICE_HIGH.value
                                ],
                                lows=data[
                                    commons_enums.PriceIndexes.IND_PRICE_LOW.value
                                ],
                                closes=data[
                                    commons_enums.PriceIndexes.IND_PRICE_CLOSE.value
                                ],
                                volumes=data[
                                    commons_enums.PriceIndexes.IND_PRICE_VOL.value
                                ],
                                time_frame=time_frame_value,
                            )
                        )
                    except (OSError, TypeError, ValueError) as error:
                        result_dict["percentage_probability"] = {
                            "schema_version": 1,
                            "mode": "causal_calibrated_percentage_probability_v1",
                            "research_only": True,
                            "signal_uses_future_outcomes": False,
                            "orders_authorized": False,
                            "automatic_promotion": False,
                            "time_frame": time_frame_value,
                            "error": str(error),
                        }
                if time_frame_value == "15m":
                    try:
                        result_dict["percentage_long_hypothesis"] = (
                            percentage_probability_engine.analyze_long_15m_hypothesis(
                                times=data[
                                    commons_enums.PriceIndexes.IND_PRICE_TIME.value
                                ],
                                display_times=data_x,
                                opens=data[
                                    commons_enums.PriceIndexes.IND_PRICE_OPEN.value
                                ],
                                highs=data[
                                    commons_enums.PriceIndexes.IND_PRICE_HIGH.value
                                ],
                                lows=data[
                                    commons_enums.PriceIndexes.IND_PRICE_LOW.value
                                ],
                                closes=data[
                                    commons_enums.PriceIndexes.IND_PRICE_CLOSE.value
                                ],
                                volumes=data[
                                    commons_enums.PriceIndexes.IND_PRICE_VOL.value
                                ],
                            )
                        )
                    except (OSError, TypeError, ValueError) as error:
                        result_dict["percentage_long_hypothesis"] = {
                            "schema_version": 1,
                            "mode": "diagnostic_long_15m_hypothesis_h1",
                            "research_only": True,
                            "orders_authorized": False,
                            "automatic_promotion": False,
                            "short_enabled": False,
                            "time_frame": "15m",
                            "error": str(error),
                        }
                    try:
                        result_dict["percentage_long_hypothesis_h2"] = (
                            percentage_probability_engine.analyze_long_15m_hypothesis_h2(
                                times=data[
                                    commons_enums.PriceIndexes.IND_PRICE_TIME.value
                                ],
                                display_times=data_x,
                                opens=data[
                                    commons_enums.PriceIndexes.IND_PRICE_OPEN.value
                                ],
                                highs=data[
                                    commons_enums.PriceIndexes.IND_PRICE_HIGH.value
                                ],
                                lows=data[
                                    commons_enums.PriceIndexes.IND_PRICE_LOW.value
                                ],
                                closes=data[
                                    commons_enums.PriceIndexes.IND_PRICE_CLOSE.value
                                ],
                                volumes=data[
                                    commons_enums.PriceIndexes.IND_PRICE_VOL.value
                                ],
                            )
                        )
                    except (OSError, TypeError, ValueError) as error:
                        result_dict["percentage_long_hypothesis_h2"] = {
                            "schema_version": 1,
                            "mode": "diagnostic_bidirectional_15m_hypothesis_h2",
                            "research_only": True,
                            "diagnostic_reuse": True,
                            "orders_authorized": False,
                            "automatic_promotion": False,
                            "short_enabled": True,
                            "alternating_directions": True,
                            "time_frame": "15m",
                            "error": str(error),
                        }
        else:
            result_dict[candles_key] = {
                enums.PriceStrings.STR_PRICE_TIME.value: data_x,
                enums.PriceStrings.STR_PRICE_CLOSE.value: data[commons_enums.PriceIndexes.IND_PRICE_CLOSE.value],
                enums.PriceStrings.STR_PRICE_LOW.value: data[commons_enums.PriceIndexes.IND_PRICE_LOW.value],
                enums.PriceStrings.STR_PRICE_OPEN.value: data[commons_enums.PriceIndexes.IND_PRICE_OPEN.value],
                enums.PriceStrings.STR_PRICE_HIGH.value: data[commons_enums.PriceIndexes.IND_PRICE_HIGH.value]
            }
    except IndexError:
        pass
    return result_dict


def _ensure_time_frame(time_frame: str):
    try:
        commons_enums.TimeFrames(time_frame)
        return time_frame
    except ValueError:
        # if timeframe is invalid, use display timefrmae
        return interface_settings.get_display_timeframe()


@functools.lru_cache(maxsize=1)
def _load_percentage_research_5m_snapshot() -> list[np.ndarray]:
    path = PERCENTAGE_RESEARCH_5M_COLLECTOR
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("5m research collector failed SQLite integrity check")
        rows = connection.execute(
            """
            SELECT candle
            FROM ohlcv
            WHERE symbol = ? AND time_frame = '5m'
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            ("BTC/USDT:USDT", PERCENTAGE_RESEARCH_5M_HISTORY_LIMIT),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) < 150:
        raise ValueError("5m research collector has insufficient candles")
    values = np.asarray(
        [json.loads(row[0])[:6] for row in reversed(rows)],
        dtype=float,
    )
    return [values[:, index] for index in range(6)]


def _fetch_public_kucoin_5m(start_timestamp: int, end_timestamp: int) -> list[list[float]]:
    candles = {}
    interval_seconds = 300
    chunk_start = start_timestamp * 1000
    end = end_timestamp * 1000
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + 199 * interval_seconds * 1000)
        query = urllib.parse.urlencode(
            {
                "symbol": "XBTUSDTM",
                "granularity": 5,
                "from": chunk_start,
                "to": chunk_end,
            }
        )
        request = urllib.request.Request(
            f"{KUCOIN_FUTURES_KLINES_URL}?{query}",
            headers={"User-Agent": "OctoBot-dashboard-research/1"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if payload.get("code") != "200000":
            raise RuntimeError(f"KuCoin public 5m request failed: {payload}")
        for row in payload.get("data", []):
            timestamp = int(row[0]) // 1000
            if start_timestamp <= timestamp <= end_timestamp:
                candles[timestamp] = [
                    timestamp,
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                ]
        if chunk_end >= end:
            break
        chunk_start = chunk_end
    return [candles[key] for key in sorted(candles)]


def _load_percentage_research_5m_live() -> tuple[list[np.ndarray], dict]:
    with _percentage_research_5m_live_lock:
        now = time.time()
        if (
            _percentage_research_5m_live_cache
            and now - _percentage_research_5m_live_cache["loaded_at"]
            < PERCENTAGE_RESEARCH_5M_CACHE_SECONDS
        ):
            return (
                _percentage_research_5m_live_cache["candles"],
                _percentage_research_5m_live_cache["metadata"],
            )
        frozen = _load_percentage_research_5m_snapshot()
        frozen_rows = np.column_stack(frozen).tolist()
        frozen_last = int(frozen_rows[-1][0])
        metadata = {
            "live": False,
            "offline": True,
            "orders_authorized": False,
            "source": "storico locale KuCoin Futures 5m",
            "warning": "Aggiornamento pubblico KuCoin non disponibile.",
        }
        try:
            public_rows = _fetch_public_kucoin_5m(
                frozen_last + 300,
                int(now // 300 * 300),
            )
            merged = {int(row[0]): row for row in frozen_rows}
            merged.update({int(row[0]): row for row in public_rows})
            rows = [merged[key] for key in sorted(merged)]
            metadata.update(
                {
                    "live": True,
                    "offline": False,
                    "source": "storico locale + aggiornamento pubblico KuCoin 5m",
                    "warning": (
                        "Feed pubblico research-only; non è sottoscritto dal "
                        "decisore operativo e non autorizza ordini."
                    ),
                }
            )
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            rows = frozen_rows
            metadata["error"] = str(error)
        values = np.asarray(rows, dtype=float)
        candles = [values[:, index] for index in range(6)]
        metadata["last_candle_timestamp"] = int(values[-1, 0])
        _percentage_research_5m_live_cache.update(
            {"loaded_at": now, "candles": candles, "metadata": metadata}
        )
        return candles, metadata


def get_currency_price_graph_update(exchange_id, symbol, time_frame, list_arrays=True, backtesting=False,
                                    minimal_candles=False, ignore_trades=False, ignore_orders=False):
    bot_api = interfaces_util.get_bot_api()
    parsed_symbol = commons_symbols.parse_symbol(parse_get_symbol(symbol))
    in_backtesting = backtesting_api.is_backtesting_enabled(interfaces_util.get_global_config()) or backtesting
    exchange_manager = trading_api.get_exchange_manager_from_exchange_id(exchange_id)
    symbol_id = str(parsed_symbol)
    if time_frame is not None:
        try:
            time_frame = _ensure_time_frame(time_frame)
            if (
                time_frame == "5m"
                and symbol_id == "BTC/USDT:USDT"
                and not in_backtesting
            ):
                research_candles, research_metadata = (
                    _load_percentage_research_5m_live()
                )
                if minimal_candles:
                    research_candles = [
                        column[-2:] for column in research_candles
                    ]
                result = _create_candles_data(
                    exchange_manager,
                    symbol_id,
                    time_frame,
                    research_candles,
                    [math.nan],
                    bot_api,
                    list_arrays,
                    in_backtesting,
                    True,
                    True,
                )
                result["research_snapshot"] = {
                    **research_metadata,
                    "last_candle": result["candles"][
                        enums.PriceStrings.STR_PRICE_TIME.value
                    ][-1],
                }
                if "percentage_probability" in result:
                    result["percentage_probability"]["data_source"] = (
                        research_metadata["source"]
                    )
                    result["percentage_probability"]["snapshot_last_candle"] = (
                        result["candles"][
                            enums.PriceStrings.STR_PRICE_TIME.value
                        ][-1]
                    )
                return result
            symbol_data = trading_api.get_symbol_data(exchange_manager, symbol_id, allow_creation=False)
            limit = 1 if minimal_candles else -1
            historical_candles = trading_api.get_symbol_historical_candles(symbol_data, time_frame, limit=limit)
            kline = [math.nan]
            if trading_api.has_symbol_klines(symbol_data, time_frame):
                kline = trading_api.get_symbol_klines(symbol_data, time_frame)
            if historical_candles is not None:
                return _create_candles_data(exchange_manager, symbol_id, time_frame, historical_candles,
                                            kline, bot_api, list_arrays, in_backtesting, ignore_trades, ignore_orders)
        except KeyError:
            traded_pairs = trading_api.get_trading_pairs(exchange_manager)
            if not traded_pairs or symbol_id in traded_pairs:
                # not started yet
                return None
            else:
                return {"error": f"no data for {parsed_symbol}"}
    return None
