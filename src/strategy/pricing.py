"""Pricing engine for market making.

This module calculates bid/ask prices based on:
- Mid price
- Spread parameters
- Inventory skew
- Volatility adjustments
"""

from decimal import Decimal
from typing import Optional
from src.core.models import OrderBookSnapshot, Quote
from src.core.config import StrategyConfig


class PricingEngine:
    """Calculates bid/ask quotes for market making."""

    def __init__(self, config: StrategyConfig):
        """Initialize pricing engine.

        Args:
            config: Strategy configuration
        """
        self.config = config

    def compute_quote(
        self,
        orderbook: OrderBookSnapshot,
        current_inventory: Decimal,
        volatility_estimate: Optional[Decimal] = None,
    ) -> Quote:
        """Compute bid/ask quote.

        Args:
            orderbook: Current order book snapshot
            current_inventory: Current inventory (positive=long, negative=short)
            volatility_estimate: Optional volatility estimate (for spread adjustment)

        Returns:
            Quote with bid/ask prices and sizes
        """
        # Get mid price
        mid = orderbook.mid_price
        if not mid:
            raise ValueError("Cannot compute quote: no mid price available")

        # Calculate base spread
        spread_bps = self._calculate_spread(volatility_estimate)

        # Apply inventory skew to mid price
        skewed_mid = self._apply_inventory_skew(mid, current_inventory)

        # Calculate half spread
        half_spread = skewed_mid * (spread_bps / Decimal("20000"))  # Divide by 2 and convert bps to decimal

        # Calculate bid and ask prices
        bid_price = skewed_mid - half_spread
        ask_price = skewed_mid + half_spread

        # Round to appropriate precision (this should come from symbol config)
        # For now, we'll use a simple rounding
        bid_price = self._round_price(bid_price)
        ask_price = self._round_price(ask_price)

        # Calculate order sizes (this should come from strategy config)
        # For now, we'll use a simple fixed size
        bid_size = Decimal("0.001")  # This should be calculated based on order_notional_pct
        ask_size = Decimal("0.001")

        return Quote(
            symbol=orderbook.symbol,
            bid_price=bid_price,
            bid_size=bid_size,
            ask_price=ask_price,
            ask_size=ask_size,
        )

    def _calculate_spread(self, volatility_estimate: Optional[Decimal] = None) -> Decimal:
        """Calculate spread in basis points.

        Args:
            volatility_estimate: Optional volatility estimate

        Returns:
            Spread in basis points
        """
        base_spread = Decimal(str(self.config.base_spread_bps))

        # Adjust for volatility if provided
        if volatility_estimate and self.config.vol_spread_factor > 0:
            # Normalize volatility (assuming 1.0 is normal)
            # In practice, you'd calculate this from historical data
            vol_adjustment = volatility_estimate * Decimal(str(self.config.vol_spread_factor))
            adjusted_spread = base_spread + vol_adjustment
        else:
            adjusted_spread = base_spread

        # Clamp to min/max spread
        min_spread = Decimal(str(self.config.min_spread_bps))
        max_spread = Decimal(str(self.config.max_spread_bps))

        if adjusted_spread < min_spread:
            adjusted_spread = min_spread
        elif adjusted_spread > max_spread:
            adjusted_spread = max_spread

        return adjusted_spread

    def _apply_inventory_skew(self, mid: Decimal, inventory: Decimal) -> Decimal:
        """Apply inventory skew to mid price.

        Args:
            mid: Mid price
            inventory: Current inventory (positive=long, negative=short)

        Returns:
            Skewed mid price
        """
        if inventory == 0:
            return mid

        # Calculate skew based on inventory
        # The skew should push the mid price away from the inventory direction
        # If we're long (positive inventory), we want to sell, so skew mid down
        # If we're short (negative inventory), we want to buy, so skew mid up

        # Normalize inventory (this should be relative to max inventory)
        # For now, we'll use a simple linear skew
        skew_strength = Decimal(str(self.config.inventory_skew_strength))
        max_inventory_pct = Decimal(str(self.config.max_inventory_notional_pct_per_symbol))

        # Calculate skew amount (as percentage of mid)
        # Negative inventory (short) -> positive skew (higher mid)
        # Positive inventory (long) -> negative skew (lower mid)
        inventory_ratio = inventory / (Decimal("100") * max_inventory_pct)  # Simplified normalization
        skew_pct = -inventory_ratio * skew_strength * Decimal("0.01")  # Convert to percentage

        skewed_mid = mid * (Decimal("1") + skew_pct)
        return skewed_mid

    def _round_price(self, price: Decimal, tick_size: Decimal = Decimal("0.01")) -> Decimal:
        """Round price to tick size.

        Args:
            price: Price to round
            tick_size: Tick size

        Returns:
            Rounded price
        """
        # Round down to nearest tick
        return (price / tick_size).quantize(Decimal("1")) * tick_size

    def calculate_order_size(
        self, price: Decimal, bot_equity: Decimal, volatility_estimate: Optional[Decimal] = None
    ) -> Decimal:
        """Calculate order size based on notional percentage.

        Args:
            price: Order price
            bot_equity: Bot equity in USDT
            volatility_estimate: Optional volatility estimate

        Returns:
            Order size
        """
        # Calculate notional based on percentage
        notional_pct = Decimal(str(self.config.order_notional_pct))

        # Adjust for volatility if enabled
        if self.config.dynamic_size_by_vol and volatility_estimate:
            # Higher volatility -> smaller size
            # This is a simplified adjustment
            vol_factor = Decimal("1.0") / (Decimal("1.0") + volatility_estimate)
            notional_pct = notional_pct * vol_factor

        notional = bot_equity * notional_pct

        # Clamp to min/max
        min_notional = Decimal(str(self.config.min_order_notional))
        max_notional = bot_equity * Decimal(str(self.config.max_order_notional_pct))

        # Ensure min_notional doesn't exceed max_notional
        if min_notional > max_notional:
            min_notional = max_notional * Decimal("0.5")  # Fallback: use 50% of max

        if notional < min_notional:
            notional = min_notional
        elif notional > max_notional:
            notional = max_notional

        # Calculate size
        size = notional / price
        
        # Round to reasonable precision (8 decimal places for BTC)
        size = size.quantize(Decimal("0.00000001"))
        
        return size

