import decimal
import pathlib
import tempfile
import types
import unittest
from unittest import mock

import octobot_trading.enums as trading_enums

import tentacles.Services.Interfaces.web_interface.models.v5_paper_bridge as bridge


class TestCommandStore(unittest.TestCase):
    def test_completed_command_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "bridge.sqlite"
            store = bridge.CommandStore(path)
            store.start("open:1", "open", {"value": 1})
            store.complete("open:1", {"status": "opened"})
            store.close()

            restored = bridge.CommandStore(path)
            self.assertEqual(
                restored.existing_response("open:1"),
                {"status": "opened"},
            )
            restored.close()

    def test_active_open_response_is_cleared_by_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "bridge.sqlite"
            store = bridge.CommandStore(path)
            store.start("open:1", "open", {})
            store.complete(
                "open:1",
                {"event_id": "open:1", "status": "opened"},
            )
            self.assertEqual(
                store.active_open_response()["event_id"], "open:1"
            )
            store.start("close:1", "close", {})
            store.complete("close:1", {"status": "closed"})
            self.assertIsNone(store.active_open_response())
            store.close()

    def test_real_trader_is_rejected(self):
        manager = types.SimpleNamespace(is_future=True)
        with (
            mock.patch.object(
                bridge.interfaces_util,
                "get_exchange_managers",
                return_value=[manager],
            ),
            mock.patch.object(
                bridge.trading_api,
                "get_exchange_name",
                return_value="binance",
            ),
            mock.patch.object(
                bridge.trading_api,
                "get_is_backtesting",
                return_value=False,
            ),
            mock.patch.object(
                bridge.trading_api,
                "is_trader_simulated",
                return_value=False,
            ),
        ):
            with self.assertRaisesRegex(
                bridge.V5PaperBridgeError, "non-simulated"
            ):
                bridge._get_paper_exchange_manager()


class TestPaperOpen(unittest.IsolatedAsyncioTestCase):
    async def test_open_creates_market_entry_and_reduce_only_stop(self):
        trader = types.SimpleNamespace(
            create_order=mock.AsyncMock()
        )
        manager = types.SimpleNamespace(trader=trader)
        position = types.SimpleNamespace(
            entry_price=decimal.Decimal("100000")
        )
        created_entry = types.SimpleNamespace(
            order_id="entry-1",
            filled_price=decimal.Decimal("100000"),
            to_dict=lambda: {
                "id": "entry-1",
                "price": decimal.Decimal("100000"),
            },
        )
        created_stop = types.SimpleNamespace(order_id="stop-1")
        trader.create_order.side_effect = [created_entry, created_stop]
        entry_order = object()
        stop_order = object()

        with (
            mock.patch.object(
                bridge,
                "_active_position",
                side_effect=[None, position],
            ),
            mock.patch.object(
                bridge, "_tagged_open_orders", return_value=[]
            ),
            mock.patch.object(
                bridge.trading_personal_data,
                "get_pre_order_data",
                new=mock.AsyncMock(
                    return_value=(
                        decimal.Decimal("0"),
                        decimal.Decimal("0"),
                        decimal.Decimal("0"),
                        decimal.Decimal("100000"),
                        object(),
                    )
                ),
            ),
            mock.patch.object(
                bridge.trading_api,
                "get_current_portfolio_value",
                return_value=decimal.Decimal("10000"),
            ),
            mock.patch.object(
                bridge.trading_personal_data,
                "decimal_check_and_adapt_order_details_if_necessary",
                return_value=[
                    (
                        decimal.Decimal("0.01"),
                        decimal.Decimal("100000"),
                    )
                ],
            ),
            mock.patch.object(
                bridge.trading_personal_data,
                "decimal_adapt_price",
                return_value=decimal.Decimal("99000"),
            ),
            mock.patch.object(
                bridge.trading_personal_data,
                "create_order_instance",
                side_effect=[entry_order, stop_order],
            ) as factory,
        ):
            result = await bridge._open(
                manager,
                {
                    "event_id": "open:1",
                    "direction": "LONG",
                    "notional_fraction": 0.10,
                    "initial_stop_pct": 1.0,
                },
            )

        self.assertEqual(result["status"], "opened")
        self.assertEqual(result["entry_order_id"], "entry-1")
        self.assertEqual(result["stop_order_id"], "stop-1")
        self.assertEqual(result["quantity"], 0.01)
        self.assertEqual(trader.create_order.await_count, 2)
        entry_call, stop_call = factory.call_args_list
        self.assertEqual(
            entry_call.kwargs["order_type"],
            trading_enums.TraderOrderType.BUY_MARKET,
        )
        self.assertEqual(
            stop_call.kwargs["order_type"],
            trading_enums.TraderOrderType.STOP_LOSS,
        )
        self.assertTrue(stop_call.kwargs["reduce_only"])
        self.assertEqual(
            stop_call.kwargs["side"],
            trading_enums.TradeOrderSide.SELL,
        )
        self.assertEqual(
            result["entry_order"],
            {"id": "entry-1", "price": "100000"},
        )


class TestPositionRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_replays_persisted_fill_when_stop_was_restored(self):
        position = types.SimpleNamespace(
            quantity=decimal.Decimal("0.01"),
            entry_price=decimal.Decimal("100000"),
        )
        manager = types.SimpleNamespace(
            trader=object(),
            exchange_personal_data=types.SimpleNamespace(
                handle_portfolio_and_position_update_from_order=(
                    mock.AsyncMock()
                )
            ),
        )
        stop = types.SimpleNamespace(tag="v5:open:1")
        entry = types.SimpleNamespace(
            symbol=bridge.SYMBOL,
            tag="v5:open:1",
            reduce_only=False,
            filled_quantity=decimal.Decimal("0.01"),
            filled_price=decimal.Decimal("100000"),
            order_id="entry-1",
            is_filled=lambda: True,
        )
        with (
            mock.patch.object(
                bridge,
                "_active_position",
                side_effect=[None, position],
            ),
            mock.patch.object(
                bridge, "_tagged_open_orders", return_value=[stop]
            ),
            mock.patch.object(
                bridge.trading_personal_data,
                "create_order_instance_from_raw",
                return_value=entry,
            ),
        ):
            result = await bridge._reconcile_position_after_restart(
                manager,
                {
                    "event_id": "open:1",
                    "entry_order": {"id": "entry-1"},
                    "quantity": 0.01,
                    "entry_price": 100000,
                },
            )
        self.assertTrue(result["restored"])
        (
            manager.exchange_personal_data
            .handle_portfolio_and_position_update_from_order
            .assert_awaited_once_with(
                entry,
                require_exchange_update=False,
                should_notify=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
