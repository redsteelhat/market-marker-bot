"""Simulated exchange for paper trading.

This module implements a local exchange that simulates order matching
and position tracking without sending real orders to any exchange.
"""

import uuid
import logging
from typing import Dict, List, Optional
from datetime import datetime
from decimal import Decimal
from src.core.exchange import IExchangeClient
from src.core.models import Order, OrderSide, OrderStatus, Position, Trade, OrderBookSnapshot

logger = logging.getLogger(__name__)


class SimulatedExchangeClient(IExchangeClient):
    """Simulated exchange client for paper trading."""

    def __init__(self, initial_equity: Decimal = Decimal("200.0")):
        """Initialize simulated exchange.

        Args:
            initial_equity: Initial equity in USDT
        """
        # symbol -> list of open orders
        self.open_orders: Dict[str, List[Order]] = {}

        # symbol -> position
        self.positions: Dict[str, Position] = {}

        # All trades
        self.trades: List[Trade] = []

        # Last order book snapshot per symbol
        self.last_orderbook: Dict[str, OrderBookSnapshot] = {}

        # Initial equity
        self.initial_equity = initial_equity
        self.current_equity = initial_equity

    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBookSnapshot:
        """Get last order book snapshot.

        Args:
            symbol: Trading symbol
            limit: Number of levels (ignored, returns cached snapshot)

        Returns:
            Last order book snapshot
        """
        if symbol not in self.last_orderbook:
            raise ValueError(f"No order book data available for {symbol}")
        return self.last_orderbook[symbol]

    async def submit_order(self, order: Order) -> Order:
        """Submit an order to simulated exchange.

        Args:
            order: Order to submit

        Returns:
            Order with assigned order_id
        """
        if not order.order_id:
            order.order_id = str(uuid.uuid4())

        order.status = OrderStatus.NEW
        order.timestamp = datetime.utcnow()

        self.open_orders.setdefault(order.symbol, []).append(order)
        logger.info(f"Simulated order submitted: {order.order_id} {order.side.value} {order.quantity} @ {order.price}")

        # Try to match immediately
        if order.symbol in self.last_orderbook:
            await self._match_orders(order.symbol, self.last_orderbook[order.symbol])

        return order

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel
            symbol: Trading symbol

        Returns:
            True if canceled, False if not found
        """
        if symbol not in self.open_orders:
            return False

        original_count = len(self.open_orders[symbol])
        self.open_orders[symbol] = [
            o for o in self.open_orders[symbol] if o.order_id != order_id
        ]

        canceled = len(self.open_orders[symbol]) < original_count
        if canceled:
            logger.info(f"Simulated order canceled: {order_id}")
        return canceled

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            Number of orders canceled
        """
        if symbol:
            count = len(self.open_orders.get(symbol, []))
            self.open_orders[symbol] = []
            return count
        else:
            total = sum(len(orders) for orders in self.open_orders.values())
            self.open_orders.clear()
            return total

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open orders
        """
        if symbol:
            return [o for o in self.open_orders.get(symbol, []) if o.is_open]
        else:
            all_orders = []
            for orders in self.open_orders.values():
                all_orders.extend([o for o in orders if o.is_open])
            return all_orders

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Get current positions.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of positions
        """
        if symbol:
            if symbol in self.positions:
                return [self.positions[symbol]]
            return []
        return list(self.positions.values())

    async def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> List[Trade]:
        """Get recent trades.

        Args:
            symbol: Optional symbol filter
            limit: Maximum number of trades

        Returns:
            List of trades
        """
        trades = self.trades
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        return trades[-limit:] if limit > 0 else trades

    async def on_orderbook_update(self, symbol: str, snapshot: OrderBookSnapshot) -> None:
        """Update order book and try to match orders.

        This should be called whenever new order book data arrives.

        Args:
            symbol: Trading symbol
            snapshot: New order book snapshot
        """
        self.last_orderbook[symbol] = snapshot
        await self._match_orders(symbol, snapshot)

    async def _match_orders(self, symbol: str, snapshot: OrderBookSnapshot) -> None:
        """Match open orders against order book.

        Args:
            symbol: Trading symbol
            snapshot: Current order book snapshot
        """
        if symbol not in self.open_orders:
            return

        if not snapshot.best_bid or not snapshot.best_ask:
            return

        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask

        new_open_orders = []

        for order in self.open_orders[symbol]:
            if not order.is_open:
                continue

            filled = False
            fill_price: Optional[Decimal] = None

            # Simple matching logic:
            # BUY limit order: fill if price >= best_ask
            # SELL limit order: fill if price <= best_bid
            if order.side == OrderSide.BUY and order.price and order.price >= best_ask:
                fill_price = best_ask
                filled = True
            elif order.side == OrderSide.SELL and order.price and order.price <= best_bid:
                fill_price = best_bid
                filled = True

            if filled and fill_price:
                await self._apply_fill(order, fill_price, snapshot)
            else:
                new_open_orders.append(order)

        self.open_orders[symbol] = new_open_orders

    async def _apply_fill(self, order: Order, fill_price: Decimal, snapshot: OrderBookSnapshot) -> None:
        """Apply a fill to an order and update position.

        Args:
            order: Order that was filled
            fill_price: Fill price
            snapshot: Order book snapshot at fill time
        """
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.update_time = datetime.utcnow()

        # Create trade
        trade = Trade(
            trade_id=str(uuid.uuid4()),
            order_id=order.order_id or "",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fee=Decimal("0"),  # Simulated - no fees for now
            timestamp=datetime.utcnow(),
            is_maker=True,  # Limit orders are maker
        )

        self.trades.append(trade)
        logger.info(f"Simulated fill: {trade.trade_id} {trade.side.value} {trade.quantity} @ {trade.price}")

        # Update position
        await self._update_position(trade, snapshot)

    async def _update_position(self, trade: Trade, snapshot: OrderBookSnapshot) -> None:
        """Update position based on trade.

        Args:
            trade: Trade that occurred
            snapshot: Order book snapshot for mark price
        """
        symbol = trade.symbol
        mark_price = snapshot.mid_price or trade.price

        if symbol not in self.positions:
            # Create new position
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=Decimal("0"),
                entry_price=None,
                mark_price=mark_price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
            )

        position = self.positions[symbol]

        # Update quantity
        if trade.side == OrderSide.BUY:
            new_quantity = position.quantity + trade.quantity
        else:
            new_quantity = position.quantity - trade.quantity

        # Update entry price (weighted average)
        if new_quantity != 0:
            if position.entry_price is None:
                new_entry_price = trade.price
            else:
                # Weighted average entry price
                if trade.side == OrderSide.BUY:
                    total_cost = (position.quantity * (position.entry_price or Decimal("0"))) + (trade.quantity * trade.price)
                    new_entry_price = total_cost / new_quantity
                else:
                    # Selling - entry price stays same if we're reducing position
                    new_entry_price = position.entry_price
        else:
            new_entry_price = None

        # Calculate realized PnL if position flipped or closed
        realized_pnl = Decimal("0")
        if position.quantity != 0 and new_quantity == 0:
            # Position closed
            if position.entry_price:
                if position.quantity > 0:
                    realized_pnl = (trade.price - position.entry_price) * abs(position.quantity)
                else:
                    realized_pnl = (position.entry_price - trade.price) * abs(position.quantity)
        elif (position.quantity > 0 and new_quantity < 0) or (position.quantity < 0 and new_quantity > 0):
            # Position flipped
            if position.entry_price:
                closed_qty = abs(position.quantity)
                if position.quantity > 0:
                    realized_pnl = (trade.price - position.entry_price) * closed_qty
                else:
                    realized_pnl = (position.entry_price - trade.price) * closed_qty

        # Update position
        position.quantity = new_quantity
        position.entry_price = new_entry_price
        position.mark_price = mark_price
        position.realized_pnl += realized_pnl
        position.timestamp = datetime.utcnow()

        # Calculate unrealized PnL
        if position.quantity != 0 and position.entry_price:
            position.unrealized_pnl = (mark_price - position.entry_price) * position.quantity
        else:
            position.unrealized_pnl = Decimal("0")

        # Update equity
        self.current_equity = self.initial_equity + sum(
            p.realized_pnl + p.unrealized_pnl for p in self.positions.values()
        )

    def get_equity(self) -> Decimal:
        """Get current equity.

        Returns:
            Current equity in USDT
        """
        return self.current_equity

    async def close(self) -> None:
        """Close simulated exchange (no-op)."""
        pass

