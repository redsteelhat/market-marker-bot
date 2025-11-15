"""Risk limits checking functions.

This module provides functions to check various risk limits:
- Daily loss limits
- Maximum drawdown
- Symbol-based position limits
"""

from decimal import Decimal
from typing import Optional
from src.core.models import Position, PnLState, RiskLimits
from src.core.config import RiskConfig


class RiskLimitsChecker:
    """Checks risk limits for positions and PnL."""

    def __init__(self, config: RiskConfig, bot_equity: Decimal):
        """Initialize risk limits checker.

        Args:
            config: Risk configuration
            bot_equity: Bot equity in USDT
        """
        self.config = config
        self.bot_equity = bot_equity

    def check_daily_loss_limit(self, pnl_state: PnLState) -> tuple[bool, Optional[str]]:
        """Check if daily loss limit is exceeded.

        Args:
            pnl_state: Current PnL state

        Returns:
            Tuple of (is_violated, reason)
        """
        daily_loss_limit = self.bot_equity * Decimal(str(self.config.daily_loss_limit_pct))
        if pnl_state.daily_realized_pnl <= -daily_loss_limit:
            return (
                True,
                f"Daily loss limit exceeded: {pnl_state.daily_realized_pnl} <= -{daily_loss_limit}",
            )
        return (False, None)

    def check_drawdown_limit(self, pnl_state: PnLState) -> tuple[bool, Optional[str], bool]:
        """Check if drawdown limit is exceeded.

        Args:
            pnl_state: Current PnL state

        Returns:
            Tuple of (is_violated, reason, is_hard_limit)
        """
        soft_limit = self.bot_equity * Decimal(str(self.config.max_drawdown_soft_pct))
        hard_limit = self.bot_equity * Decimal(str(self.config.max_drawdown_hard_pct))

        if pnl_state.drawdown >= hard_limit:
            return (
                True,
                f"Hard drawdown limit exceeded: {pnl_state.drawdown} >= {hard_limit}",
                True,
            )
        elif pnl_state.drawdown >= soft_limit:
            return (
                True,
                f"Soft drawdown limit exceeded: {pnl_state.drawdown} >= {soft_limit}",
                False,
            )
        return (False, None, False)

    def check_position_limits(
        self, position: Position, risk_limits: RiskLimits
    ) -> tuple[bool, Optional[str]]:
        """Check if position exceeds limits.

        Args:
            position: Current position
            risk_limits: Risk limits for the symbol

        Returns:
            Tuple of (is_violated, reason)
        """
        # Check net notional limit
        net_notional = abs(position.notional)
        if net_notional > risk_limits.max_net_notional:
            return (
                True,
                f"Net notional limit exceeded: {net_notional} > {risk_limits.max_net_notional}",
            )

        # Check gross notional limit (if we track both long and short separately)
        # For now, we'll use net notional as proxy
        return (False, None)

    def check_inventory_limit(
        self, position: Position, inventory_hard_limit_pct: Decimal
    ) -> tuple[bool, Optional[str]]:
        """Check if inventory exceeds hard limit.

        Args:
            position: Current position
            inventory_hard_limit_pct: Inventory hard limit as percentage

        Returns:
            Tuple of (is_violated, reason)
        """
        inventory_limit = self.bot_equity * inventory_hard_limit_pct
        if abs(position.notional) > inventory_limit:
            return (
                True,
                f"Inventory hard limit exceeded: {abs(position.notional)} > {inventory_limit}",
            )
        return (False, None)

    def check_order_size_limit(
        self, order_notional: Decimal, max_order_notional: Decimal
    ) -> tuple[bool, Optional[str]]:
        """Check if order size exceeds limit.

        Args:
            order_notional: Order notional value
            max_order_notional: Maximum order notional

        Returns:
            Tuple of (is_violated, reason)
        """
        if order_notional > max_order_notional:
            return (
                True,
                f"Order size limit exceeded: {order_notional} > {max_order_notional}",
            )
        return (False, None)

    def check_price_band(
        self, price: Decimal, best_bid: Decimal, best_ask: Decimal
    ) -> tuple[bool, Optional[str]]:
        """Check if price is within allowed band from best bid/ask.

        Args:
            price: Order price
            best_bid: Best bid price
            best_ask: Best ask price

        Returns:
            Tuple of (is_violated, reason)
        """
        max_distance_pct = Decimal(str(self.config.max_price_distance_from_best_pct))
        mid = (best_bid + best_ask) / 2
        max_distance = mid * max_distance_pct

        # Check if price is too far from best bid/ask
        if price < best_bid - max_distance or price > best_ask + max_distance:
            return (
                True,
                f"Price outside allowed band: {price} not within {max_distance} of best bid/ask",
            )
        return (False, None)

    def calculate_max_net_notional(self, symbol: str) -> Decimal:
        """Calculate maximum net notional for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Maximum net notional
        """
        return self.bot_equity * Decimal(str(self.config.max_net_notional_pct_per_symbol))

    def calculate_max_gross_notional(self, symbol: str) -> Decimal:
        """Calculate maximum gross notional for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Maximum gross notional
        """
        return self.bot_equity * Decimal(str(self.config.max_gross_notional_pct_per_symbol))

    def calculate_max_order_notional(self) -> Decimal:
        """Calculate maximum order notional.

        Returns:
            Maximum order notional
        """
        # This should come from strategy config, but we'll use a default here
        # In practice, this should be passed from strategy config
        return self.bot_equity * Decimal("0.025")  # 2.5% default

