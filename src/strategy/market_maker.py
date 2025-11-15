"""Market maker strategy engine.

This module implements the main market making logic with event-driven loop.
"""

import asyncio
import logging
from decimal import Decimal
from typing import Callable, Optional
from src.core.models import Order, OrderBookSnapshot, Position, Quote
from src.core.config import Settings
from src.data.orderbook import OrderBookManager
from src.execution.order_manager import OrderManager
from src.risk.guardian import RiskGuardian
from src.strategy.pricing import PricingEngine
from src.strategy.inventory import InventoryManager

logger = logging.getLogger(__name__)


class MarketMaker:
    """Main market maker strategy engine."""

    def __init__(
        self,
        settings: Settings,
        order_manager: OrderManager,
        risk_guardian: RiskGuardian,
        symbol: str,
        orderbook_manager: OrderBookManager,
    ):
        """Initialize market maker.

        Args:
            settings: Application settings
            order_manager: Order manager
            risk_guardian: Risk guardian
            symbol: Trading symbol
            orderbook_manager: Order book manager
        """
        self.settings = settings
        self.order_manager = order_manager
        self.risk_guardian = risk_guardian
        self.symbol = symbol
        self.orderbook_manager = orderbook_manager

        self.pricing_engine = PricingEngine(settings.strategy)
        self.inventory_manager = InventoryManager(
            settings.strategy, Decimal(str(settings.bot_equity_usdt))
        )

        self.running = False
        self.quote_task: Optional[asyncio.Task] = None
        self.current_position: Optional[Position] = None
        self.current_quote: Optional[Quote] = None
        self.open_orders: dict[str, Order] = {}  # client_order_id -> Order

    async def start(self) -> None:
        """Start market maker."""
        if self.running:
            logger.warning("Market maker already running")
            return

        self.running = True
        logger.info(f"Starting market maker for {self.symbol}")

        # Start quote refresh loop
        self.quote_task = asyncio.create_task(self._quote_loop())

    async def stop(self) -> None:
        """Stop market maker."""
        if not self.running:
            return

        logger.info(f"Stopping market maker for {self.symbol}")
        self.running = False

        # Cancel quote task
        if self.quote_task:
            self.quote_task.cancel()
            try:
                await self.quote_task
            except asyncio.CancelledError:
                pass

        # Cancel all open orders
        await self.order_manager.cancel_all_orders(self.symbol)

    async def on_order_book_update(self, snapshot: OrderBookSnapshot) -> None:
        """Handle order book update.

        Args:
            snapshot: Order book snapshot
        """
        self.orderbook_manager.update_from_binance(
            {
                "bids": [[float(level.price), float(level.quantity)] for level in snapshot.bids],
                "asks": [[float(level.price), float(level.quantity)] for level in snapshot.asks],
            }
        )

        # Trigger immediate re-quote if price changed significantly
        if self._should_requote_immediately(snapshot):
            await self._update_quotes()

    async def on_fill(self, trade: dict) -> None:
        """Handle trade fill.

        Args:
            trade: Trade data
        """
        logger.info(f"Fill received: {trade}")

        # Update position (this should be done by a position manager)
        # For now, we'll just log it

        # Update quotes if needed
        await self._update_quotes()

    async def _quote_loop(self) -> None:
        """Periodic quote update loop."""
        refresh_interval = self.settings.strategy.refresh_interval_ms / 1000.0

        while self.running:
            try:
                await asyncio.sleep(refresh_interval)
                await self._update_quotes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in quote loop: {e}")

    async def _update_quotes(self) -> None:
        """Update quotes and manage orders."""
        if not self.running:
            return

        # Check kill switch
        if self.risk_guardian.is_kill_switch_active():
            logger.warning("Kill switch active, skipping quote update")
            return

        # Get current order book
        snapshot = self.orderbook_manager.snapshot
        if not snapshot or not snapshot.mid_price:
            logger.warning("No order book snapshot available")
            return

        # Get current inventory
        inventory_qty = self.inventory_manager.get_inventory_quantity(self.current_position)

        # Calculate volatility estimate (simplified - should come from volatility calculator)
        volatility_estimate = None

        # Compute new quote
        try:
            quote = self.pricing_engine.compute_quote(snapshot, inventory_qty, volatility_estimate)
        except Exception as e:
            logger.error(f"Error computing quote: {e}")
            return

        # Check if we should quote each side
        should_quote_bid = self.inventory_manager.should_quote_bid(self.current_position)
        should_quote_ask = self.inventory_manager.should_quote_ask(self.current_position)

        # Update orders
        await self._update_orders(quote, should_quote_bid, should_quote_ask)

        self.current_quote = quote

    async def _update_orders(
        self, quote: Quote, should_quote_bid: bool, should_quote_ask: bool
    ) -> None:
        """Update orders based on new quote.

        Args:
            quote: New quote
            should_quote_bid: Whether to quote bid side
            should_quote_ask: Whether to quote ask side
        """
        # Get current open orders
        open_orders = self.order_manager.get_open_orders(self.symbol)

        # Cancel orders that are no longer needed or have wrong prices
        for order in open_orders:
            should_cancel = False

            if order.side.value == "BUY" and not should_quote_bid:
                should_cancel = True
            elif order.side.value == "SELL" and not should_quote_ask:
                should_cancel = True
            elif order.price:
                # Check if price changed significantly
                if order.side.value == "BUY" and abs(order.price - quote.bid_price) > Decimal("0.01"):
                    should_cancel = True
                elif order.side.value == "SELL" and abs(order.price - quote.ask_price) > Decimal("0.01"):
                    should_cancel = True

            if should_cancel and order.order_id:
                await self.order_manager.cancel_order(order.order_id)

        # Submit new orders if needed
        if should_quote_bid:
            await self._submit_bid_order(quote)
        if should_quote_ask:
            await self._submit_ask_order(quote)

    async def _submit_bid_order(self, quote: Quote) -> None:
        """Submit bid order.

        Args:
            quote: Quote with bid price and size
        """
        # Check if we already have a bid order at this price
        open_orders = self.order_manager.get_open_orders(self.symbol)
        for order in open_orders:
            if order.side.value == "BUY" and order.price and abs(order.price - quote.bid_price) < Decimal("0.01"):
                return  # Already have order at this price

        # Calculate order size
        bot_equity = Decimal(str(self.settings.bot_equity_usdt))
        size = self.pricing_engine.calculate_order_size(quote.bid_price, bot_equity)

        # Create order
        from src.core.models import OrderSide

        order = Order(
            symbol=self.symbol,
            side=OrderSide.BUY,
            quantity=size,
            price=quote.bid_price,
        )

        # Check risk limits
        snapshot = self.orderbook_manager.snapshot
        if snapshot:
            max_order_notional = bot_equity * Decimal(
                str(self.settings.strategy.max_order_notional_pct)
            )
            is_allowed, reason = self.risk_guardian.check_order_limits(
                order,
                self.current_position,
                snapshot.best_bid,
                snapshot.best_ask,
                max_order_notional,
            )

            if not is_allowed:
                logger.warning(f"Bid order rejected by risk guardian: {reason}")
                return

        # Submit order
        try:
            submitted_order = await self.order_manager.submit_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=size,
                price=quote.bid_price,
            )
            logger.info(f"Bid order submitted: {submitted_order.order_id} @ {quote.bid_price}")
        except Exception as e:
            logger.error(f"Error submitting bid order: {e}")

    async def _submit_ask_order(self, quote: Quote) -> None:
        """Submit ask order.

        Args:
            quote: Quote with ask price and size
        """
        # Check if we already have an ask order at this price
        open_orders = self.order_manager.get_open_orders(self.symbol)
        for order in open_orders:
            if order.side.value == "SELL" and order.price and abs(order.price - quote.ask_price) < Decimal("0.01"):
                return  # Already have order at this price

        # Calculate order size
        bot_equity = Decimal(str(self.settings.bot_equity_usdt))
        size = self.pricing_engine.calculate_order_size(quote.ask_price, bot_equity)

        # Create order
        from src.core.models import OrderSide

        order = Order(
            symbol=self.symbol,
            side=OrderSide.SELL,
            quantity=size,
            price=quote.ask_price,
        )

        # Check risk limits
        snapshot = self.orderbook_manager.snapshot
        if snapshot:
            max_order_notional = bot_equity * Decimal(
                str(self.settings.strategy.max_order_notional_pct)
            )
            is_allowed, reason = self.risk_guardian.check_order_limits(
                order,
                self.current_position,
                snapshot.best_bid,
                snapshot.best_ask,
                max_order_notional,
            )

            if not is_allowed:
                logger.warning(f"Ask order rejected by risk guardian: {reason}")
                return

        # Submit order
        try:
            submitted_order = await self.order_manager.submit_order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                quantity=size,
                price=quote.ask_price,
            )
            logger.info(f"Ask order submitted: {submitted_order.order_id} @ {quote.ask_price}")
        except Exception as e:
            logger.error(f"Error submitting ask order: {e}")

    def _should_requote_immediately(self, snapshot: OrderBookSnapshot) -> bool:
        """Check if we should re-quote immediately based on price change.

        Args:
            snapshot: New order book snapshot

        Returns:
            True if should re-quote immediately
        """
        if not self.current_quote or not snapshot.mid_price:
            return True

        old_mid = self.current_quote.mid_price
        new_mid = snapshot.mid_price

        if old_mid == 0:
            return True

        price_change_pct = abs((new_mid - old_mid) / old_mid) * Decimal("10000")  # Convert to bps
        trigger_bps = Decimal(str(self.settings.strategy.price_change_trigger_bps))

        return price_change_pct >= trigger_bps

    def update_position(self, position: Position) -> None:
        """Update current position.

        Args:
            position: New position
        """
        self.current_position = position

