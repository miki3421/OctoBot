"""Strictly simulated order bridge for the isolated Binance V5 account."""

import decimal
import enum
import json
import os
import pathlib
import sqlite3
import time

import octobot_services.interfaces.util as interfaces_util
import octobot_trading.api as trading_api
import octobot_trading.enums as trading_enums
import octobot_trading.personal_data as trading_personal_data


SYMBOL = "BTC/USDT:USDT"
EXCHANGE = "binance"
MAX_NOTIONAL_FRACTION = decimal.Decimal("0.10")
MAX_INITIAL_STOP_PCT = decimal.Decimal("1.00")
ENABLED_ENV = "V5_PAPER_BRIDGE_ENABLED"
TOKEN_PATH_ENV = "V5_PAPER_BRIDGE_TOKEN_PATH"
DATABASE_PATH_ENV = "V5_PAPER_BRIDGE_DATABASE_PATH"
DEFAULT_DATABASE_PATH = "/octobot/user/v5-paper-bridge.sqlite"
RECOVERY_WAIT_SECONDS = 90

_STARTED_AT_MONOTONIC = time.monotonic()
_POSITION_RECOVERY_FINALIZED = False


class V5PaperBridgeError(RuntimeError):
    """Raised when a paper-only invariant is not satisfied."""


class CommandStore:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=15)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS commands (
                event_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()
        integrity = self.connection.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise V5PaperBridgeError(
                f"V5 paper bridge database integrity={integrity}"
            )

    def existing_response(self, event_id):
        row = self.connection.execute(
            """
            SELECT status, response_json
            FROM commands
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != "completed" or not row[1]:
            raise V5PaperBridgeError(
                f"V5 paper command {event_id} is already processing"
            )
        return json.loads(row[1])

    def start(self, event_id, action, request):
        self.connection.execute(
            """
            INSERT INTO commands(
                event_id, action, status, request_json
            ) VALUES (?, ?, 'processing', ?)
            """,
            (event_id, action, _canonical_json(request)),
        )
        self.connection.commit()

    def complete(self, event_id, response):
        self.connection.execute(
            """
            UPDATE commands
            SET status = 'completed', response_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE event_id = ?
            """,
            (_canonical_json(response), event_id),
        )
        self.connection.commit()

    def fail(self, event_id, error):
        self.connection.execute(
            """
            UPDATE commands
            SET status = 'failed', response_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE event_id = ?
            """,
            (_canonical_json({"error": error}), event_id),
        )
        self.connection.commit()

    def active_open_response(self):
        """Return the last completed open not followed by a close."""
        active = None
        rows = self.connection.execute(
            """
            SELECT action, response_json
            FROM commands
            WHERE status = 'completed'
            ORDER BY rowid
            """
        ).fetchall()
        for action, response_json in rows:
            if action == "open":
                active = json.loads(response_json)
            elif action == "close":
                active = None
        return active

    def close(self):
        self.connection.close()


def is_enabled():
    return os.getenv(ENABLED_ENV, "").strip().lower() == "true"


def expected_token():
    token_path = os.getenv(TOKEN_PATH_ENV, "")
    if not token_path:
        raise V5PaperBridgeError("V5 paper bridge token is not configured")
    token = pathlib.Path(token_path).read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise V5PaperBridgeError("V5 paper bridge token is invalid")
    return token


def get_status():
    status = {
        "enabled": is_enabled(),
        "mode": "v5_isolated_octobot_paper",
        "symbol": SYMBOL,
        "exchange": EXCHANGE,
        "real_trader": False,
        "simulated_trader": False,
        "ready": False,
    }
    if not status["enabled"]:
        return status
    try:
        manager = _get_paper_exchange_manager()
        store = CommandStore(
            os.getenv(DATABASE_PATH_ENV, DEFAULT_DATABASE_PATH)
        )
        try:
            recovery = interfaces_util.run_in_bot_main_loop(
                _reconcile_position_after_restart(
                    manager, store.active_open_response()
                ),
                timeout=20,
            )
        finally:
            store.close()
        status.update(
            {
                "simulated_trader": True,
                "ready": recovery["state"] != "waiting_for_stop",
                "exchange_id": trading_api.get_exchange_manager_id(manager),
                "position_active": _active_position(manager) is not None,
                "position_recovery": recovery,
            }
        )
    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
    return status


async def _reconcile_position_after_restart(manager, open_response):
    """Rebuild a simulated futures position when its stop survived restart."""
    global _POSITION_RECOVERY_FINALIZED
    if _POSITION_RECOVERY_FINALIZED:
        return {
            "state": (
                "present"
                if _active_position(manager) is not None
                else "absent"
            ),
            "restored": False,
        }
    if _active_position(manager) is not None:
        _POSITION_RECOVERY_FINALIZED = True
        return {"state": "present", "restored": False}
    if not open_response:
        _POSITION_RECOVERY_FINALIZED = True
        return {"state": "absent", "restored": False}
    tagged_orders = _tagged_open_orders(manager)
    if not tagged_orders:
        if (
            time.monotonic() - _STARTED_AT_MONOTONIC
            < RECOVERY_WAIT_SECONDS
        ):
            return {"state": "waiting_for_stop", "restored": False}
        _POSITION_RECOVERY_FINALIZED = True
        return {"state": "absent", "restored": False}
    expected_tag = f"v5:{open_response.get('event_id', '')}"
    if any(order.tag != expected_tag for order in tagged_orders):
        raise V5PaperBridgeError(
            "V5 persisted stop does not match the paper entry"
        )
    raw_entry = open_response.get("entry_order")
    if not isinstance(raw_entry, dict):
        raise V5PaperBridgeError(
            "V5 persisted entry cannot restore its futures position"
        )
    entry = trading_personal_data.create_order_instance_from_raw(
        manager.trader, raw_entry
    )
    # OctoBot's generic raw-order parser intentionally ignores local tags.
    # Restore it explicitly because it binds this fill to its surviving stop.
    entry.tag = raw_entry.get("tag")
    if (
        entry.symbol != SYMBOL
        or entry.tag != expected_tag
        or entry.reduce_only
        or not entry.is_filled()
        or entry.filled_quantity <= 0
        or entry.filled_price <= 0
    ):
        raise V5PaperBridgeError(
            "V5 persisted entry failed position recovery validation"
        )
    await (
        manager.exchange_personal_data
        .handle_portfolio_and_position_update_from_order(
            entry,
            require_exchange_update=False,
            should_notify=True,
        )
    )
    position = _active_position(manager)
    if position is None:
        raise V5PaperBridgeError(
            "V5 simulated futures position recovery failed"
        )
    expected_quantity = decimal.Decimal(
        str(open_response["quantity"])
    )
    expected_price = decimal.Decimal(
        str(open_response["entry_price"])
    )
    if (
        position.quantity.copy_abs() != expected_quantity.copy_abs()
        or position.entry_price != expected_price
    ):
        raise V5PaperBridgeError(
            "V5 recovered futures position differs from persisted fill"
        )
    _POSITION_RECOVERY_FINALIZED = True
    return {
        "state": "restored",
        "restored": True,
        "entry_order_id": entry.order_id,
    }


def execute(request):
    if not is_enabled():
        raise V5PaperBridgeError("V5 paper bridge is disabled")
    event_id = _required_text(request, "event_id", maximum=160)
    action = _required_text(request, "action", maximum=20)
    if action not in {"open", "protect", "close"}:
        raise V5PaperBridgeError(f"unsupported V5 paper action: {action}")
    if request.get("symbol") != SYMBOL:
        raise V5PaperBridgeError("V5 bridge only accepts BTC futures")
    store = CommandStore(
        os.getenv(DATABASE_PATH_ENV, DEFAULT_DATABASE_PATH)
    )
    try:
        if response := store.existing_response(event_id):
            return {**response, "idempotent_replay": True}
        store.start(event_id, action, request)
        try:
            response = interfaces_util.run_in_bot_main_loop(
                _execute_async(action, request),
                timeout=20,
            )
        except Exception as error:
            store.fail(event_id, f"{type(error).__name__}: {error}")
            raise
        response = {
            **response,
            "event_id": event_id,
            "action": action,
            "paper_only": True,
            "exchange_order_authorized": False,
            "idempotent_replay": False,
        }
        store.complete(event_id, response)
        return response
    finally:
        store.close()


async def _execute_async(action, request):
    manager = _get_paper_exchange_manager()
    if action == "open":
        return await _open(manager, request)
    if action == "protect":
        return await _protect(manager, request)
    return await _close(manager)


def _get_paper_exchange_manager():
    managers = interfaces_util.get_exchange_managers()
    if len(managers) != 1:
        raise V5PaperBridgeError(
            "V5 broker requires exactly one exchange manager"
        )
    manager = managers[0]
    if trading_api.get_exchange_name(manager).lower() != EXCHANGE:
        raise V5PaperBridgeError("V5 broker exchange must be Binance")
    if not manager.is_future:
        raise V5PaperBridgeError("V5 broker requires futures")
    if trading_api.get_is_backtesting(manager):
        raise V5PaperBridgeError("V5 broker cannot run in backtesting")
    if not trading_api.is_trader_simulated(manager):
        raise V5PaperBridgeError(
            "V5 broker refuses every non-simulated trader"
        )
    return manager


def _active_position(manager):
    return next(
        (
            position
            for position in trading_api.get_positions(manager)
            if position.symbol == SYMBOL and not position.is_idle()
        ),
        None,
    )


async def _open(manager, request):
    if _active_position(manager) is not None:
        raise V5PaperBridgeError("V5 paper account already has a position")
    if _tagged_open_orders(manager):
        raise V5PaperBridgeError("V5 paper account already has an order")
    direction = _required_text(request, "direction", maximum=5)
    if direction not in {"LONG", "SHORT"}:
        raise V5PaperBridgeError("V5 direction must be LONG or SHORT")
    fraction = _decimal(
        request.get("notional_fraction"), "notional_fraction"
    )
    if fraction <= 0 or fraction > MAX_NOTIONAL_FRACTION:
        raise V5PaperBridgeError("V5 paper notional exceeds 10%")
    initial_stop_pct = _decimal(
        request.get("initial_stop_pct"), "initial_stop_pct"
    )
    if initial_stop_pct <= 0 or initial_stop_pct > MAX_INITIAL_STOP_PCT:
        raise V5PaperBridgeError("V5 initial stop exceeds 1%")
    _, _, _, mark_price, market = (
        await trading_personal_data.get_pre_order_data(
            manager, symbol=SYMBOL, timeout=10
        )
    )
    portfolio_value = decimal.Decimal(
        str(trading_api.get_current_portfolio_value(manager))
    )
    notional = portfolio_value * fraction
    details = list(
        trading_personal_data.decimal_check_and_adapt_order_details_if_necessary(
            notional / mark_price, mark_price, market
        )
    )
    if len(details) != 1:
        raise V5PaperBridgeError("V5 quantity could not be adapted")
    quantity, adapted_price = details[0]
    is_long = direction == "LONG"
    entry_type = (
        trading_enums.TraderOrderType.BUY_MARKET
        if is_long
        else trading_enums.TraderOrderType.SELL_MARKET
    )
    exit_side = (
        trading_enums.TradeOrderSide.SELL
        if is_long
        else trading_enums.TradeOrderSide.BUY
    )
    tag = f"v5:{request['event_id']}"
    entry = trading_personal_data.create_order_instance(
        trader=manager.trader,
        order_type=entry_type,
        symbol=SYMBOL,
        current_price=adapted_price,
        quantity=quantity,
        price=adapted_price,
        tag=tag,
    )
    created_entry = await manager.trader.create_order(entry)
    if created_entry is None:
        raise V5PaperBridgeError("V5 paper entry was not created")
    position = _active_position(manager)
    entry_price = (
        decimal.Decimal(str(position.entry_price))
        if position is not None
        else decimal.Decimal(str(created_entry.filled_price))
    )
    stop_factor = initial_stop_pct / decimal.Decimal("100")
    stop_price = entry_price * (
        decimal.Decimal("1") - stop_factor
        if is_long
        else decimal.Decimal("1") + stop_factor
    )
    stop_price = trading_personal_data.decimal_adapt_price(
        market, stop_price
    )
    stop = trading_personal_data.create_order_instance(
        trader=manager.trader,
        order_type=trading_enums.TraderOrderType.STOP_LOSS,
        symbol=SYMBOL,
        current_price=adapted_price,
        quantity=quantity,
        price=stop_price,
        side=exit_side,
        reduce_only=True,
        tag=tag,
    )
    try:
        created_stop = await manager.trader.create_order(stop)
    except Exception:
        await _close_position_if_open(manager)
        raise
    if created_stop is None:
        await _close_position_if_open(manager)
        raise V5PaperBridgeError("V5 protective stop was not created")
    return {
        "status": "opened",
        "direction": direction,
        "entry_order_id": created_entry.order_id,
        "stop_order_id": created_stop.order_id,
        "entry_price": float(entry_price),
        "stop_price": float(stop_price),
        "quantity": float(quantity),
        "notional": float(quantity * entry_price),
        "portfolio_value": float(portfolio_value),
        "entry_order": _json_safe(created_entry.to_dict()),
    }


async def _protect(manager, request):
    if _active_position(manager) is None:
        return {"status": "already_closed"}
    stop_order_id = _required_text(
        request, "stop_order_id", maximum=160
    )
    locked_stop_price = _decimal(
        request.get("locked_stop_price"), "locked_stop_price"
    )
    stop_order = next(
        (
            order
            for order in trading_api.get_open_orders(manager, symbol=SYMBOL)
            if order.order_id == stop_order_id
        ),
        None,
    )
    if stop_order is None:
        raise V5PaperBridgeError("V5 protective stop is missing")
    mark_price = (
        await manager.exchange_symbols_data.get_exchange_symbol_data(SYMBOL)
        .prices_manager.get_mark_price(timeout=10)
    )
    market = await manager.exchange.get_market_status_including_lazy_load(
        SYMBOL, with_fixer=False
    )
    locked_stop_price = trading_personal_data.decimal_adapt_price(
        market, locked_stop_price
    )
    edited = await manager.trader.edit_order(
        stop_order,
        edited_price=locked_stop_price,
        edited_stop_price=locked_stop_price,
        edited_current_price=decimal.Decimal(str(mark_price)),
    )
    if not edited:
        raise V5PaperBridgeError("V5 stop could not be protected")
    return {
        "status": "protected",
        "stop_order_id": stop_order.order_id,
        "locked_stop_price": float(locked_stop_price),
    }


async def _close(manager):
    position = _active_position(manager)
    if position is None:
        await _cancel_tagged_open_orders(manager)
        return {"status": "already_closed"}
    created = await manager.trader.close_position(
        position,
        emit_trading_signals=False,
    )
    if not created:
        raise V5PaperBridgeError("V5 position could not be closed")
    await _cancel_tagged_open_orders(manager)
    return {
        "status": "closed",
        "close_order_ids": [
            order.order_id for order in created if order is not None
        ],
    }


async def _close_position_if_open(manager):
    if position := _active_position(manager):
        await manager.trader.close_position(
            position,
            emit_trading_signals=False,
        )


def _tagged_open_orders(manager):
    return [
        order
        for order in trading_api.get_open_orders(manager, symbol=SYMBOL)
        if (order.tag or "").startswith("v5:")
    ]


async def _cancel_tagged_open_orders(manager):
    for order in _tagged_open_orders(manager):
        await manager.trader.cancel_order(
            order,
            emit_trading_signals=False,
        )


def _required_text(request, key, maximum):
    value = request.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise V5PaperBridgeError(f"invalid V5 field: {key}")
    return value


def _decimal(value, key):
    try:
        parsed = decimal.Decimal(str(value))
    except (decimal.InvalidOperation, TypeError, ValueError) as error:
        raise V5PaperBridgeError(f"invalid V5 decimal: {key}") from error
    if not parsed.is_finite():
        raise V5PaperBridgeError(f"invalid V5 decimal: {key}")
    return parsed


def _canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return _json_safe(value.value)
    return value
