"""Risk guardian for pre-trade checks and kill switch.

This module provides pre-trade risk checks and kill switch functionality.
"""

import logging
from decimal import Decimal
from typing import Optional
from src.core.models import Order, Position, PnLState, RiskLimits
from src.core.config import RiskConfig
from src.risk.limits import RiskLimitsChecker

logger = logging.getLogger(__name__)


class RiskGuardian:
    """Pre-trade risk guardian and kill switch manager."""

    def __init__(self, config: RiskConfig, bot_equity: Decimal):
        """Initialize risk guardian.

        Args:
            config: Risk configuration
            bot_equity: Bot equity in USDT
        """
        self.config = config
        self.bot_equity = bot_equity
        self.limits_checker = RiskLimitsChecker(config, bot_equity)
        self.kill_switch_active = False
        self.kill_switch_reason: Optional[str] = None

    def check_order_limits(
        self,
        order: Order,
        position: Optional[Position],
        best_bid: Optional[Decimal],
        best_ask: Optional[Decimal],
        max_order_notional: Decimal,
    ) -> tuple[bool, Optional[str]]:
        """Check if order passes pre-trade risk checks.

        Args:
            order: Order to check
            position: Current position for the symbol
            best_bid: Best bid price
            best_ask: Best ask price
            max_order_notional: Maximum order notional

        Returns:
            Tuple of (is_allowed, reason_if_rejected)
        """
        # Check if kill switch is active
        if self.kill_switch_active:
            return (False, f"Kill switch active: {self.kill_switch_reason}")

        # Check order size limit
        order_notional = order.notional
        is_violated, reason = self.limits_checker.check_order_size_limit(
            order_notional, max_order_notional
        )
        if is_violated:
            return (False, reason)

        # Check price band (if we have best bid/ask)
        if best_bid and best_ask and order.price:
            is_violated, reason = self.limits_checker.check_price_band(
                order.price, best_bid, best_ask
            )
            if is_violated:
                return (False, reason)

        # Check position limits (if we have position)
        if position:
            # Calculate what position would be after this order
            # For simplicity, we'll check current position
            # In practice, you'd want to check projected position
            risk_limits = RiskLimits(
                symbol=order.symbol,
                max_net_notional=self.limits_checker.calculate_max_net_notional(order.symbol),
                max_gross_notional=self.limits_checker.calculate_max_gross_notional(order.symbol),
                current_net_notional=position.notional,
                current_gross_notional=abs(position.notional),
            )
            is_violated, reason = self.limits_checker.check_position_limits(position, risk_limits)
            if is_violated:
                return (False, reason)

        return (True, None)

    def check_inventory_limits(
        self, position: Position, inventory_hard_limit_pct: Decimal
    ) -> tuple[bool, Optional[str]]:
        """Check if inventory is within limits.

        Args:
            position: Current position
            inventory_hard_limit_pct: Inventory hard limit as percentage

        Returns:
            Tuple of (is_within_limits, reason_if_violated)
        """
        is_violated, reason = self.limits_checker.check_inventory_limit(
            position, inventory_hard_limit_pct
        )
        if is_violated:
            return (False, reason)
        return (True, None)

    def check_daily_loss(self, pnl_state: PnLState) -> tuple[bool, Optional[str]]:
        """Check if daily loss limit is exceeded.

        Args:
            pnl_state: Current PnL state

        Returns:
            Tuple of (is_within_limits, reason_if_violated)
        """
        is_violated, reason = self.limits_checker.check_daily_loss_limit(pnl_state)
        if is_violated:
            return (False, reason)
        return (True, None)

    def check_drawdown(self, pnl_state: PnLState) -> tuple[bool, Optional[str], bool]:
        """Check if drawdown limit is exceeded.

        Args:
            pnl_state: Current PnL state

        Returns:
            Tuple of (is_within_limits, reason_if_violated, is_hard_limit)
        """
        is_violated, reason, is_hard = self.limits_checker.check_drawdown_limit(pnl_state)
        if is_violated:
            return (False, reason, is_hard)
        return (True, None, False)

    def trigger_kill_switch(self, reason: str) -> None:
        """Trigger kill switch.

        Args:
            reason: Reason for kill switch
        """
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        logger.critical(f"KILL SWITCH TRIGGERED: {reason}")

    def reset_kill_switch(self) -> None:
        """Reset kill switch (manual intervention required)."""
        self.kill_switch_active = False
        self.kill_switch_reason = None
        logger.info("Kill switch reset")

    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is active.

        Returns:
            True if kill switch is active, False otherwise
        """
        return self.kill_switch_active

    def get_kill_switch_reason(self) -> Optional[str]:
        """Get kill switch reason.

        Returns:
            Kill switch reason or None
        """
        return self.kill_switch_reason

    def check_all_limits(
        self,
        order: Optional[Order],
        position: Optional[Position],
        pnl_state: PnLState,
        inventory_hard_limit_pct: Decimal,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None,
        max_order_notional: Optional[Decimal] = None,
    ) -> tuple[bool, Optional[str]]:
        """Check all risk limits (comprehensive check).

        Args:
            order: Optional order to check
            position: Optional current position
            pnl_state: Current PnL state
            inventory_hard_limit_pct: Inventory hard limit as percentage
            best_bid: Optional best bid price
            best_ask: Optional best ask price
            max_order_notional: Optional maximum order notional

        Returns:
            Tuple of (is_allowed, reason_if_rejected)
        """
        # Check kill switch
        if self.kill_switch_active:
            return (False, f"Kill switch active: {self.kill_switch_reason}")

        # Check daily loss
        is_ok, reason = self.check_daily_loss(pnl_state)
        if not is_ok:
            self.trigger_kill_switch(reason)
            return (False, reason)

        # Check drawdown
        is_ok, reason, is_hard = self.check_drawdown(pnl_state)
        if not is_ok:
            if is_hard:
                self.trigger_kill_switch(reason)
            return (False, reason)

        # Check inventory limits
        if position:
            is_ok, reason = self.check_inventory_limits(position, inventory_hard_limit_pct)
            if not is_ok:
                self.trigger_kill_switch(reason)
                return (False, reason)

        # Check order limits
        if order and max_order_notional and best_bid and best_ask:
            is_ok, reason = self.check_order_limits(
                order, position, best_bid, best_ask, max_order_notional
            )
            if not is_ok:
                return (False, reason)

        return (True, None)

