"""Market maker strategy engine.

This module implements the main market making logic with event-driven loop.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional
from src.core.models import Order, OrderBookSnapshot, Position, Quote
from src.core.config import Settings
from src.core.exchange import IExchangeClient
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
        exchange: IExchangeClient,
        risk_guardian: RiskGuardian,
        symbol: str,
        orderbook_manager: OrderBookManager,
    ):
        """Initialize market maker.

        Args:
            settings: Application settings
            exchange: Exchange client (real or simulated)
            risk_guardian: Risk guardian
            symbol: Trading symbol
            orderbook_manager: Order book manager
        """
        self.settings = settings
        self.exchange = exchange
        self.order_manager = OrderManager(exchange)
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
        
        # Log throttling for risk warnings
        self._last_risk_warning_at: dict[str, datetime] = {}
        self._risk_warning_throttle_seconds = 10

        # Refresh control
        self._last_refresh_at: Optional[datetime] = None
        self._last_mid: Optional[Decimal] = None

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
        loop_count = 0

        while self.running:
            try:
                await asyncio.sleep(refresh_interval)
                loop_count += 1
                
                # Log every 10 loops (every ~10 seconds)
                if loop_count % 10 == 0:
                    logger.info(f"Quote loop running for {self.symbol} (loop #{loop_count})")

                # Time-based and price-drift-based refresh (cancel/replace)
                now = datetime.utcnow()
                snapshot = self.orderbook_manager.snapshot
                mid = snapshot.mid_price if snapshot else None

                force_refresh = False
                # Time-based: every 5 seconds
                if not self._last_refresh_at or (now - self._last_refresh_at).total_seconds() >= 5:
                    force_refresh = True
                # Price-drift based: 5 bps
                if mid and self._last_mid:
                    drift_bps = abs(mid - self._last_mid) / self._last_mid * Decimal("10000")
                    if drift_bps >= Decimal("5"):
                        force_refresh = True

                if force_refresh:
                    try:
                        await self.order_manager.cancel_all_orders(self.symbol)
                        self._last_refresh_at = now
                        if mid:
                            self._last_mid = mid
                        logger.debug(f"Refreshed orders for {self.symbol} (force_refresh={force_refresh})")
                    except Exception as e:
                        logger.error(f"Error refreshing orders for {self.symbol}: {e}")

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
            logger.debug(f"No order book snapshot available for {self.symbol}")
            return

        # Get current inventory
        inventory_qty = self.inventory_manager.get_inventory_quantity(self.current_position)

        # Calculate volatility estimate (simplified - should come from volatility calculator)
        volatility_estimate = None

        # Compute new quote
        try:
            quote = self.pricing_engine.compute_quote(snapshot, inventory_qty, volatility_estimate)
            logger.debug(f"Computed quote for {self.symbol}: bid={quote.bid_price}, ask={quote.ask_price}, mid={snapshot.mid_price}")
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
        
        # Calculate price change threshold (5 bps of mid price)
        snapshot = self.orderbook_manager.snapshot
        if snapshot and snapshot.mid_price:
            price_threshold = snapshot.mid_price * Decimal("0.0005")  # 5 bps
        else:
            price_threshold = Decimal("1.0")  # Fallback

        # Cancel orders that are no longer needed or have wrong prices
        cancelled_count = 0
        for order in open_orders:
            should_cancel = False

            if order.side.value == "BUY" and not should_quote_bid:
                should_cancel = True
            elif order.side.value == "SELL" and not should_quote_ask:
                should_cancel = True
            elif order.price:
                # Check if price changed significantly (use dynamic threshold)
                if order.side.value == "BUY" and abs(order.price - quote.bid_price) > price_threshold:
                    should_cancel = True
                elif order.side.value == "SELL" and abs(order.price - quote.ask_price) > price_threshold:
                    should_cancel = True

            if should_cancel and order.order_id:
                await self.order_manager.cancel_order(order.order_id)
                cancelled_count += 1

        if cancelled_count > 0:
            logger.debug(f"Cancelled {cancelled_count} order(s) for {self.symbol}")

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
        # Calculate price tolerance (5 bps of mid price)
        snapshot = self.orderbook_manager.snapshot
        if snapshot and snapshot.mid_price:
            price_tolerance = snapshot.mid_price * Decimal("0.0005")  # 5 bps
        else:
            price_tolerance = Decimal("1.0")  # Fallback
        
        # Check if we already have a bid order at this price
        open_orders = self.order_manager.get_open_orders(self.symbol)
        for order in open_orders:
            if order.side.value == "BUY" and order.price and abs(order.price - quote.bid_price) < price_tolerance:
                logger.debug(f"Already have BUY order at {quote.bid_price} for {self.symbol}, skipping")
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
                self._log_risk_warning("bid-order-rejected", f"Bid order rejected by risk guardian: {reason}")
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
        # Calculate price tolerance (5 bps of mid price)
        snapshot = self.orderbook_manager.snapshot
        if snapshot and snapshot.mid_price:
            price_tolerance = snapshot.mid_price * Decimal("0.0005")  # 5 bps
        else:
            price_tolerance = Decimal("1.0")  # Fallback
        
        # Check if we already have an ask order at this price
        open_orders = self.order_manager.get_open_orders(self.symbol)
        for order in open_orders:
            if order.side.value == "SELL" and order.price and abs(order.price - quote.ask_price) < price_tolerance:
                logger.debug(f"Already have SELL order at {quote.ask_price} for {self.symbol}, skipping")
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
                self._log_risk_warning("ask-order-rejected", f"Ask order rejected by risk guardian: {reason}")
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

    def _log_risk_warning(self, key: str, message: str) -> None:
        """Log risk warning with throttling to avoid spam.

        Args:
            key: Unique key for this warning type
            message: Warning message
        """
        now = datetime.utcnow()
        last = self._last_risk_warning_at.get(key)
        
        if not last or (now - last) > timedelta(seconds=self._risk_warning_throttle_seconds):
            logger.warning(message)
            self._last_risk_warning_at[key] = now

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

