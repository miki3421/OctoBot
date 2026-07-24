# pylint: disable=E0611
#  Drakkar-Software OctoBot-Trading
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

import octobot_commons.enums as commons_enums
import octobot_commons.tree as commons_tree

import octobot_trading.exchange_channel as exchange_channel
import octobot_trading.constants as constants
import octobot_trading.personal_data.orders.channel.orders_updater as orders_updater
import octobot_trading.personal_data.orders.orders_storage_operations as orders_storage_operations


class OrdersUpdaterSimulator(orders_updater.OrdersUpdater):
    async def start(self):
        await self.wait_for_dependencies(
            [
                commons_tree.get_exchange_path(
                    self.channel.exchange_manager.exchange_name,
                    commons_enums.InitializationEventExchangeTopics.CONTRACTS.value,
                ),
                commons_tree.get_exchange_path(
                    self.channel.exchange_manager.exchange_name,
                    commons_enums.InitializationEventExchangeTopics.POSITIONS.value,
                ),
            ],
            self.DEPENDENCIES_TIMEOUT,
        )
        await self._restore_required_virtual_orders()
        # on simulator, orders are fetched from the start
        self.channel.exchange_manager.exchange_personal_data.on_completed_orders_fetch()
        await exchange_channel.get_chan(constants.RECENT_TRADES_CHANNEL, self.channel.exchange_manager.id) \
            .new_consumer(self.ignore_recent_trades_update)
        for symbol in self.channel.exchange_manager.exchange_config.traded_symbol_pairs:
            self._set_initialized_event(symbol)

    async def ignore_recent_trades_update(self, exchange: str, exchange_id: str,
                                          cryptocurrency: str, symbol: str, recent_trades: list):
        """
        Used to subscribe at least one recent trades consumer during backtesting
        """

    async def _restore_required_virtual_orders(self):
        storage = self.channel.exchange_manager.storage_manager.orders_storage
        if storage is None or not storage.should_store_data():
            return
        pending_groups = {}
        orders_manager = (
            self.channel.exchange_manager.exchange_personal_data.orders_manager
        )
        restored_count = 0
        for order_details in storage.get_all_simulated_startup_orders():
            try:
                raw_order = order_details[constants.STORAGE_ORIGIN_VALUE]
                order_id = raw_order.get("id")
                if order_id is not None and orders_manager.has_order(order_id):
                    continue
                await orders_storage_operations.create_order_from_storage_data(
                    order_details,
                    self.channel.exchange_manager,
                    pending_groups,
                )
                restored_count += 1
            except Exception as err:
                self.logger.exception(
                    err,
                    True,
                    f"Error when restoring a simulated order from storage: {err}",
                )
        if pending_groups:
            await (
                orders_storage_operations
                .create_missing_virtual_orders_from_storage_order_groups(
                    pending_groups,
                    self.channel.exchange_manager,
                )
            )
        if restored_count:
            self.logger.info(
                f"Restored {restored_count} simulated order(s) from storage."
            )
