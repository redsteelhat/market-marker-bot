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
from src.risk.scaling import RiskScalingEngine
from src.strategy.pricing import PricingEngine
from src.strategy.inventory import InventoryManager
from src.strategy.signals import TradeSignal

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

        # Risk scaling engine
        if settings.risk.enable_risk_scaling:
            self.risk_scaling = RiskScalingEngine(
                atr_length=settings.risk.risk_scaling_atr_length,
                dd_lookback_hours=settings.risk.risk_scaling_dd_lookback_hours,
                vol_low=settings.risk.risk_scaling_vol_low,
                vol_high=settings.risk.risk_scaling_vol_high,
                dd_soft=settings.risk.risk_scaling_dd_soft,
                dd_hard=settings.risk.risk_scaling_dd_hard,
                risk_min=settings.risk.risk_scaling_min,
                risk_max=settings.risk.risk_scaling_max,
                initial_equity=Decimal(str(settings.bot_equity_usdt)),
            )
        else:
            self.risk_scaling = None

        self.running = False
        self.quote_task: Optional[asyncio.Task] = None
        self.current_position: Optional[Position] = None
        self.current_quote: Optional[Quote] = None
        self.open_orders: dict[str, Order] = {}  # client_order_id -> Order
        
        # Log throttling for risk warnings
        self._last_risk_warning_at: dict[str, datetime] = {}
        self._risk_warning_throttle_seconds = 10
        
        # Quote pause state to prevent log spam
        self._is_paused: bool = False
        self._last_pause_reason: Optional[str] = None
        self._last_pause_log_at: Optional[datetime] = None
        self._pause_log_cooldown_seconds: int = 2

        # Refresh control
        self._last_refresh_at: Optional[datetime] = None
        self._last_mid: Optional[Decimal] = None
        
        # Degraded quoting state
        self._degraded_active: bool = False
        self._degraded_last_reason: Optional[str] = None
        self._degrade_size_multiplier: Optional[Decimal] = None
        self._last_logged_signal: Optional[TradeSignal] = None

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
        """Periodic quote update loop with risk-based frequency scaling."""
        base_refresh_interval = self.settings.strategy.refresh_interval_ms / 1000.0
        loop_count = 0

        while self.running:
            try:
                # Calculate dynamic refresh interval based on risk multiplier
                refresh_interval = base_refresh_interval
                if self.risk_scaling:
                    # When risk is low (risk_mult < 1), quote less frequently
                    # risk_mult = 1.0 → normal frequency
                    # risk_mult = 0.1 → 3x slower (less frequent quotes)
                    risk_mult = self.risk_scaling.current_multiplier
                    if risk_mult < 1.0:
                        # Inverse relationship: lower risk_mult → slower quotes
                        frequency_multiplier = 1.0 + (1.0 - risk_mult) * 2.0  # 1.0 to 3.0 range
                        refresh_interval = base_refresh_interval * frequency_multiplier
                        logger.debug(f"Risk-based quote frequency: risk_mult={risk_mult:.3f}, frequency_mult={frequency_multiplier:.2f}, interval={refresh_interval:.2f}s")
                
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
                # Time-based: every 5 seconds (or longer if risk is low)
                time_threshold = 5.0
                if self.risk_scaling and self.risk_scaling.current_multiplier < 1.0:
                    # Scale time threshold with risk multiplier
                    time_threshold = 5.0 * (1.0 + (1.0 - self.risk_scaling.current_multiplier) * 2.0)
                
                if not self._last_refresh_at or (now - self._last_refresh_at).total_seconds() >= time_threshold:
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

        # Update risk scaling engine with price and equity data
        risk_multiplier = Decimal("1.0")
        spread_multiplier = Decimal("1.0")
        is_risk_off = False

        if self.risk_scaling:
            mid_price = snapshot.mid_price
            best_bid = snapshot.best_bid
            best_ask = snapshot.best_ask

            # Update price series for ATR calculation
            if best_bid and best_ask:
                high = max(best_bid, best_ask, mid_price)
                low = min(best_bid, best_ask, mid_price)
                self.risk_scaling.update_price(high, low, mid_price)

            # Update equity from exchange
            try:
                positions = await self.exchange.get_positions()
                total_unrealized_pnl = sum(p.unrealized_pnl for p in positions if p.symbol == self.symbol)
                current_equity = Decimal(str(self.settings.bot_equity_usdt)) + total_unrealized_pnl
                # Also add realized PnL if available
                if positions:
                    for p in positions:
                        if p.symbol == self.symbol:
                            current_equity += p.realized_pnl
                            break
                self.risk_scaling.update_equity(current_equity)
            except Exception as e:
                logger.debug(f"Could not update equity for risk scaling: {e}")

            # Compute risk multiplier
            risk_mult = self.risk_scaling.compute_risk_multiplier(mid_price)
            risk_multiplier = Decimal(str(risk_mult))
            spread_multiplier = Decimal(str(self.risk_scaling.get_spread_multiplier()))
            is_risk_off = self.risk_scaling.is_risk_off(threshold=self.settings.risk.risk_off_threshold)

            # Log periodically (every 50 quote updates)
            if not hasattr(self, '_risk_scaling_log_counter'):
                self._risk_scaling_log_counter = 0
            self._risk_scaling_log_counter += 1
            if self._risk_scaling_log_counter % 50 == 0:
                logger.info(
                    f"Risk scaling for {self.symbol}: multiplier={risk_multiplier:.3f}, "
                    f"spread_mult={spread_multiplier:.3f}, risk_off={is_risk_off}"
                )

        # Calculate short-term volatility (bps) and depth metrics
        volatility_estimate = self.orderbook_manager.get_realized_volatility(n=30)
        depth_bid = self.orderbook_manager.get_depth_volume_bps("bid", Decimal("10"))  # within 10 bps
        depth_ask = self.orderbook_manager.get_depth_volume_bps("ask", Decimal("10"))

        # Risk: evaluate toxicity with soft/hard behavior
        action, tox_reason, imbalance = self.risk_guardian.evaluate_toxicity(
            volatility_bps=volatility_estimate,
            bid_depth_notional=depth_bid,
            ask_depth_notional=depth_ask,
        )
        if action == "pause":
            # Enter/maintain paused state with throttled logging
            await self.order_manager.cancel_all_orders(self.symbol)
            now = datetime.utcnow()
            should_log = False
            if not self._is_paused:
                should_log = True
            elif tox_reason != self._last_pause_reason:
                should_log = True
            elif not self._last_pause_log_at or (now - self._last_pause_log_at).total_seconds() >= self._pause_log_cooldown_seconds:
                should_log = True

            if should_log:
                logger.info(f"QUOTE_PAUSED for {self.symbol}: {tox_reason}")
                self._last_pause_log_at = now

            self._is_paused = True
            self._last_pause_reason = tox_reason
            # Leaving degraded mode if any
            if self._degraded_active:
                logger.info(f"QUOTE_NORMALIZED for {self.symbol} (leaving degraded due to PAUSE)")
            self._degraded_active = False
            self._degraded_last_reason = None
            self._degrade_size_multiplier = None
            return
        else:
            # If previously paused, log a single resume event
            if self._is_paused:
                logger.info(f"QUOTE_RESUMED for {self.symbol}")
            self._is_paused = False
            self._last_pause_reason = None

        # Handle degraded mode (wider spreads, smaller size, possibly one-sided quoting)
        degraded_this_cycle = (action == "degrade")
        if degraded_this_cycle and not self._degraded_active:
            logger.info(f"QUOTE_DEGRADED for {self.symbol}: {tox_reason}")
        if not degraded_this_cycle and self._degraded_active:
            logger.info(f"QUOTE_NORMALIZED for {self.symbol}")
        self._degraded_active = degraded_this_cycle
        self._degraded_last_reason = tox_reason if degraded_this_cycle else None
        self._degrade_size_multiplier = Decimal("0.5") if degraded_this_cycle else None

        # Compute new quote
        try:
            quote = self.pricing_engine.compute_quote(
                snapshot,
                inventory_qty,
                volatility_estimate=volatility_estimate,
                depth_bid_notional=depth_bid,
                depth_ask_notional=depth_ask,
            )
            logger.debug(f"Computed quote for {self.symbol}: bid={quote.bid_price}, ask={quote.ask_price}, mid={snapshot.mid_price}")
        except Exception as e:
            logger.error(f"Error computing quote: {e}")
            return

        # Apply risk scaling to quote sizes (base_notional_per_side * risk_multiplier)
        if self.risk_scaling:
            # Calculate base size from base_notional_per_side
            base_notional = Decimal(str(self.settings.risk.base_notional_per_side))
            if snapshot.mid_price and snapshot.mid_price > 0:
                base_size = base_notional / snapshot.mid_price
                # Apply risk multiplier to base size
                quote.bid_size = base_size * risk_multiplier
                quote.ask_size = base_size * risk_multiplier
                logger.debug(
                    f"Applied risk scaling: base_notional={base_notional}, base_size={base_size}, "
                    f"risk_mult={risk_multiplier}, final_bid_size={quote.bid_size}, final_ask_size={quote.ask_size}"
                )
            else:
                # Fallback: scale existing sizes
                quote.bid_size = quote.bid_size * risk_multiplier
                quote.ask_size = quote.ask_size * risk_multiplier
                logger.debug(f"Applied risk scaling (fallback): bid_size={quote.bid_size}, ask_size={quote.ask_size}, multiplier={risk_multiplier}")

        # Apply risk scaling to spread (widen when risk is low)
        if self.risk_scaling and spread_multiplier != Decimal("1.0") and snapshot.mid_price:
            mid_price = snapshot.mid_price
            current_spread = quote.ask_price - quote.bid_price
            target_spread = current_spread * spread_multiplier
            spread_adjustment = (target_spread - current_spread) / Decimal("2")
            quote.bid_price = quote.bid_price - spread_adjustment
            quote.ask_price = quote.ask_price + spread_adjustment
            logger.debug(f"Applied spread scaling: spread_mult={spread_multiplier}, new_bid={quote.bid_price}, new_ask={quote.ask_price}")

        # Determine which sides to quote (inventory-based)
        should_quote_bid = self.inventory_manager.should_quote_bid(self.current_position)
        should_quote_ask = self.inventory_manager.should_quote_ask(self.current_position)

        # Risk-off mode: only reduce position, don't open new ones
        if is_risk_off:
            # In risk-off mode, we only quote to reduce existing positions
            # Use more aggressive pricing to ensure fills (wider spread, better prices)
            if inventory_qty > 0:
                # Long position: only quote ask (sell to reduce)
                should_quote_bid = False
                should_quote_ask = True
                # Make ask price more attractive (lower) to encourage selling
                quote.ask_price = quote.ask_price * Decimal("0.999")  # 0.1% more attractive
                logger.info(f"Risk-off mode: only quoting ask to reduce long position (qty={inventory_qty}, price={quote.ask_price})")
            elif inventory_qty < 0:
                # Short position: only quote bid (buy to reduce)
                should_quote_bid = True
                should_quote_ask = False
                # Make bid price more attractive (higher) to encourage buying
                quote.bid_price = quote.bid_price * Decimal("1.001")  # 0.1% more attractive
                logger.info(f"Risk-off mode: only quoting bid to reduce short position (qty={inventory_qty}, price={quote.bid_price})")
            else:
                # Flat position: don't quote at all
                should_quote_bid = False
                should_quote_ask = False
                logger.info(f"Risk-off mode: flat position, not quoting (risk_mult={risk_multiplier:.3f})")

        # If degraded, widen spreads around mid and possibly one-side quote
        if self._degraded_active and snapshot and snapshot.mid_price:
            widen_bps = Decimal("5")  # 5 bps widen on each side
            mid_price = snapshot.mid_price
            widen_amount = (mid_price * widen_bps) / Decimal("10000")
            try:
                # Adjust prices outward
                if getattr(quote, "bid_price", None):
                    quote.bid_price = quote.bid_price - widen_amount
                if getattr(quote, "ask_price", None):
                    quote.ask_price = quote.ask_price + widen_amount
                # Asymmetric quoting depending on imbalance direction if available
                if imbalance is not None:
                    if imbalance > 0:
                        # More bid-side depth; avoid placing additional bids
                        should_quote_bid = False
                    elif imbalance < 0:
                        # More ask-side depth; avoid placing additional asks
                        should_quote_ask = False
            except Exception as e:
                logger.error(f"Error applying degraded adjustments: {e}")

        # Compute and log trade signal (visibility layer; does not alter execution directly)
        try:
            toxicity_state = "PAUSED" if self._is_paused else ("DEGRADED" if self._degraded_active else "NORMAL")
            spread_bps = getattr(snapshot, "spread_bps", None)
            signal = self._compute_trade_signal(
                mid_price=snapshot.mid_price,
                imbalance=imbalance if imbalance is not None else Decimal("0"),
                spread_bps=Decimal(str(spread_bps)) if spread_bps is not None else None,
                toxicity_state=toxicity_state,
                inventory_qty=inventory_qty or Decimal("0"),
            )
            self._log_trade_signal(signal, snapshot.mid_price, imbalance, spread_bps, toxicity_state, inventory_qty)
        except Exception as e:
            logger.error(f"Error computing/logging trade signal: {e}")

        # Check if we should quote each side (post-adjustment)

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

        # Use quote size (already scaled by risk multiplier)
        # This ensures risk scaling is properly applied
        size = quote.bid_size
        if self._degrade_size_multiplier:
            size = (size * self._degrade_size_multiplier).quantize(Decimal("0.00000001"))
        
        # Ensure minimum size
        if size <= 0:
            logger.debug(f"Bid size too small ({size}), skipping order")
            return

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

        # Use quote size (already scaled by risk multiplier)
        # This ensures risk scaling is properly applied
        size = quote.ask_size
        if self._degrade_size_multiplier:
            size = (size * self._degrade_size_multiplier).quantize(Decimal("0.00000001"))
        
        # Ensure minimum size
        if size <= 0:
            logger.debug(f"Ask size too small ({size}), skipping order")
            return

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

    def _compute_trade_signal(
        self,
        mid_price: Decimal,
        imbalance: Decimal,
        spread_bps: Optional[Decimal],
        toxicity_state: str,
        inventory_qty: Decimal,
    ) -> TradeSignal:
        # 1) Never signal in hard toxic conditions
        if toxicity_state == "PAUSED":
            return TradeSignal.NONE

        # 2) Require minimum spread
        if spread_bps is not None and spread_bps < Decimal("3.0"):
            return TradeSignal.NONE

        # Entry/Exit thresholds (simple defaults, can be moved to config)
        IMB_ENTRY = Decimal("0.75")
        IMB_EXIT = Decimal("0.40")

        # No position: directional entry based on imbalance
        if abs(inventory_qty) < Decimal("0.00000001"):
            if imbalance >= IMB_ENTRY:
                return TradeSignal.ENTER_LONG
            if imbalance <= -IMB_ENTRY:
                return TradeSignal.ENTER_SHORT
            return TradeSignal.NONE

        # With position: exit if imbalance normalizes
        if inventory_qty > 0:
            if abs(imbalance) < IMB_EXIT:
                return TradeSignal.EXIT_LONG
        elif inventory_qty < 0:
            if abs(imbalance) < IMB_EXIT:
                return TradeSignal.EXIT_SHORT

        return TradeSignal.NONE

    def _log_trade_signal(
        self,
        signal: TradeSignal,
        mid_price: Decimal,
        imbalance: Optional[Decimal],
        spread_bps: Optional[Decimal],
        toxicity_state: str,
        inventory_qty: Decimal,
    ) -> None:
        if signal == TradeSignal.NONE:
            return

        # Only log when signal changes to reduce noise
        if signal == self._last_logged_signal:
            return

        tag = ""
        if signal in (TradeSignal.ENTER_LONG, TradeSignal.EXIT_SHORT):
            tag = "[bold green]LONG[/bold green]"
        elif signal in (TradeSignal.ENTER_SHORT, TradeSignal.EXIT_LONG):
            tag = "[bold red]SHORT[/bold red]"
        else:
            tag = "[bold yellow]FLAT[/bold yellow]"

        logger.info(
            (
                "[SIGNAL] [cyan]%s[/cyan] %s | mid=%.2f spread=%sbps | imb=%s tox=%s inv=%.6f"
            ),
            self.symbol,
            tag,
            float(mid_price),
            f"{spread_bps:.2f}" if spread_bps is not None else "N/A",
            f"{imbalance:.2f}" if imbalance is not None else "N/A",
            toxicity_state,
            float(inventory_qty),
            extra={"symbol": self.symbol},
        )
        self._last_logged_signal = signal

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

