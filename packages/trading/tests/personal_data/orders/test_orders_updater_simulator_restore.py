from unittest import mock

import pytest

import octobot_trading.constants as constants
import octobot_trading.personal_data.orders.channel.orders_updater_simulator as updater_simulator


pytestmark = pytest.mark.asyncio


async def test_restore_simulated_orders_is_idempotent_for_active_order_ids():
    first = {constants.STORAGE_ORIGIN_VALUE: {"id": "already-active"}}
    second = {constants.STORAGE_ORIGIN_VALUE: {"id": "to-restore"}}
    storage = mock.Mock()
    storage.should_store_data.return_value = True
    storage.get_all_simulated_startup_orders.return_value = [first, second]

    orders_manager = mock.Mock()
    orders_manager.has_order.side_effect = lambda order_id: (
        order_id == "already-active"
    )
    exchange_manager = mock.Mock()
    exchange_manager.storage_manager.orders_storage = storage
    exchange_manager.exchange_personal_data.orders_manager = orders_manager

    updater = object.__new__(updater_simulator.OrdersUpdaterSimulator)
    updater.channel = mock.Mock()
    updater.channel.exchange_manager = exchange_manager
    updater.logger = mock.Mock()

    with mock.patch.object(
        updater_simulator.orders_storage_operations,
        "create_order_from_storage_data",
        new=mock.AsyncMock(),
    ) as create_order:
        await updater._restore_required_virtual_orders()

    create_order.assert_awaited_once_with(second, exchange_manager, {})
