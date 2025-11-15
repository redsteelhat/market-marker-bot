"""Order management for market maker bot.

This module handles order submission, cancellation, and state synchronization.
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from src.core.models import Order, OrderSide, OrderType, OrderStatus
from src.data.binance_client import BinanceClient

logger = logging.getLogger(__name__)


class OrderManager:
    """Manages order lifecycle and synchronization."""

    def __init__(self, client: BinanceClient):
        """Initialize order manager.

        Args:
            client: Binance API client
        """
        self.client = client
        self.open_orders: Dict[str, Order] = {}  # order_id -> Order
        self.order_history: List[Order] = []
        self.sync_interval = 5  # seconds
        self.sync_task: Optional[asyncio.Task] = None

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        client_order_id: Optional[str] = None,
    ) -> Order:
        """Submit a limit order.

        Args:
            symbol: Trading symbol
            side: Order side
            quantity: Order quantity
            price: Order price
            client_order_id: Optional client order ID

        Returns:
            Order object
        """
        try:
            response = await self.client.place_limit_order(
                symbol=symbol,
                side=side,
                quantity=float(quantity),
                price=float(price),
                client_order_id=client_order_id,
            )

            order = self._parse_order_response(response)
            self.open_orders[order.order_id] = order
            logger.info(f"Order submitted: {order.order_id} {side.value} {quantity} @ {price}")

            return order
        except Exception as e:
            logger.error(f"Error submitting order: {e}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if successful, False otherwise
        """
        try:
            order = self.open_orders.get(order_id)
            if not order:
                logger.warning(f"Order not found: {order_id}")
                return False

            response = await self.client.cancel_order(
                symbol=order.symbol,
                order_id=order_id,
            )

            # Update order status
            order.status = OrderStatus.CANCELED
            order.update_time = datetime.utcnow()

            # Remove from open orders
            if order_id in self.open_orders:
                del self.open_orders[order_id]

            logger.info(f"Order canceled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
            return False

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            Number of orders canceled
        """
        try:
            if symbol:
                # Cancel all orders for a specific symbol
                response = await self.client.cancel_all_orders(symbol)
                # Remove from open orders
                canceled = [
                    order_id
                    for order_id, order in self.open_orders.items()
                    if order.symbol == symbol
                ]
                for order_id in canceled:
                    if order_id in self.open_orders:
                        order = self.open_orders[order_id]
                        order.status = OrderStatus.CANCELED
                        order.update_time = datetime.utcnow()
                        del self.open_orders[order_id]
                return len(canceled)
            else:
                # Cancel all orders for all symbols
                symbols = set(order.symbol for order in self.open_orders.values())
                total_canceled = 0
                for sym in symbols:
                    canceled = await self.cancel_all_orders(sym)
                    total_canceled += canceled
                return total_canceled
        except Exception as e:
            logger.error(f"Error canceling all orders: {e}")
            return 0

    async def sync_open_orders(self, symbol: Optional[str] = None) -> None:
        """Synchronize open orders with exchange.

        Args:
            symbol: Optional symbol filter
        """
        try:
            exchange_orders = await self.client.get_open_orders(symbol)
            exchange_order_ids = set()

            # Update existing orders and add new ones
            for ex_order_data in exchange_orders:
                order = self._parse_order_response(ex_order_data)
                exchange_order_ids.add(order.order_id)

                if order.order_id in self.open_orders:
                    # Update existing order
                    existing = self.open_orders[order.order_id]
                    existing.status = order.status
                    existing.filled_quantity = order.filled_quantity
                    existing.filled_price = order.filled_price
                    existing.update_time = order.update_time
                else:
                    # New order (shouldn't happen, but handle it)
                    self.open_orders[order.order_id] = order

            # Remove orders that are no longer open
            to_remove = [
                order_id
                for order_id, order in self.open_orders.items()
                if order_id not in exchange_order_ids
                and (symbol is None or order.symbol == symbol)
            ]
            for order_id in to_remove:
                order = self.open_orders[order_id]
                order.status = OrderStatus.FILLED  # Assume filled if not in exchange
                order.update_time = datetime.utcnow()
                del self.open_orders[order_id]

        except Exception as e:
            logger.error(f"Error syncing open orders: {e}")

    def _parse_order_response(self, data: dict) -> Order:
        """Parse Binance order response to Order model.

        Args:
            data: Order data from Binance API

        Returns:
            Order object
        """
        # Binance status mapping
        status_map = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }

        return Order(
            order_id=str(data.get("orderId", "")),
            client_order_id=data.get("clientOrderId"),
            symbol=data.get("symbol", ""),
            side=OrderSide.BUY if data.get("side") == "BUY" else OrderSide.SELL,
            order_type=OrderType.LIMIT if data.get("type") == "LIMIT" else OrderType.MARKET,
            quantity=Decimal(str(data.get("origQty", "0"))),
            price=Decimal(str(data.get("price", "0"))) if data.get("price") else None,
            status=status_map.get(data.get("status", "NEW"), OrderStatus.NEW),
            filled_quantity=Decimal(str(data.get("executedQty", "0"))),
            filled_price=Decimal(str(data.get("avgPrice", "0"))) if data.get("avgPrice") else None,
            timestamp=datetime.fromtimestamp(data.get("time", 0) / 1000),
            update_time=datetime.fromtimestamp(data.get("updateTime", 0) / 1000)
            if data.get("updateTime")
            else None,
        )

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open orders
        """
        if symbol:
            return [
                order for order in self.open_orders.values() if order.symbol == symbol and order.is_open
            ]
        return [order for order in self.open_orders.values() if order.is_open]

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order or None if not found
        """
        return self.open_orders.get(order_id)

    async def start_sync_loop(self) -> None:
        """Start periodic synchronization loop."""
        self.sync_task = asyncio.create_task(self._sync_loop())

    async def stop_sync_loop(self) -> None:
        """Stop periodic synchronization loop."""
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass

    async def _sync_loop(self) -> None:
        """Periodic synchronization loop."""
        while True:
            try:
                await asyncio.sleep(self.sync_interval)
                await self.sync_open_orders()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")

