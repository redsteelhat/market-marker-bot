"""Inventory management for market making.

This module handles inventory tracking, band management, and skew adjustments.
"""

from decimal import Decimal
from typing import Optional
from src.core.models import Position
from src.core.config import StrategyConfig


class InventoryManager:
    """Manages inventory and applies skew adjustments."""

    def __init__(self, config: StrategyConfig, bot_equity: Decimal):
        """Initialize inventory manager.

        Args:
            config: Strategy configuration
            bot_equity: Bot equity in USDT
        """
        self.config = config
        self.bot_equity = bot_equity
        self.target_inventory = Decimal(str(config.target_inventory))

    def get_inventory_notional(self, position: Optional[Position]) -> Decimal:
        """Get current inventory notional value.

        Args:
            position: Current position

        Returns:
            Inventory notional value
        """
        if not position:
            return Decimal("0")
        return position.notional

    def get_inventory_quantity(self, position: Optional[Position]) -> Decimal:
        """Get current inventory quantity.

        Args:
            position: Current position

        Returns:
            Inventory quantity (positive=long, negative=short)
        """
        if not position:
            return Decimal("0")
        return position.quantity

    def is_within_soft_band(self, position: Optional[Position]) -> bool:
        """Check if inventory is within soft band.

        Args:
            position: Current position

        Returns:
            True if within soft band, False otherwise
        """
        inventory_notional = abs(self.get_inventory_notional(position))
        soft_band_limit = self.bot_equity * Decimal(str(self.config.inventory_soft_band_pct))
        return inventory_notional <= soft_band_limit

    def is_within_hard_limit(self, position: Optional[Position]) -> bool:
        """Check if inventory is within hard limit.

        Args:
            position: Current position

        Returns:
            True if within hard limit, False otherwise
        """
        inventory_notional = abs(self.get_inventory_notional(position))
        hard_limit = self.bot_equity * Decimal(str(self.config.inventory_hard_limit_pct))
        return inventory_notional <= hard_limit

    def get_inventory_skew_factor(self, position: Optional[Position]) -> Decimal:
        """Get inventory skew factor (0-1).

        Args:
            position: Current position

        Returns:
            Skew factor (0 = no skew, 1 = maximum skew)
        """
        if not position or position.quantity == 0:
            return Decimal("0")

        inventory_notional = abs(self.get_inventory_notional(position))
        hard_limit = self.bot_equity * Decimal(str(self.config.inventory_hard_limit_pct))

        if hard_limit == 0:
            return Decimal("0")

        # Calculate skew factor based on how close we are to hard limit
        skew_factor = inventory_notional / hard_limit

        # Clamp to 0-1
        if skew_factor > Decimal("1"):
            skew_factor = Decimal("1")
        elif skew_factor < Decimal("0"):
            skew_factor = Decimal("0")

        return skew_factor

    def should_quote_bid(self, position: Optional[Position]) -> bool:
        """Determine if we should quote bid (buy side).

        Args:
            position: Current position

        Returns:
            True if should quote bid, False otherwise
        """
        # If we're short (negative inventory), we want to buy
        if position and position.quantity < 0:
            return True

        # If we're at hard limit on long side, don't quote bid
        if position and position.quantity > 0:
            if not self.is_within_hard_limit(position):
                return False

        # If we're within soft band, quote both sides
        if self.is_within_soft_band(position):
            return True

        # If we're outside soft band but within hard limit, still quote but with skew
        if self.is_within_hard_limit(position):
            return True

        return False

    def should_quote_ask(self, position: Optional[Position]) -> bool:
        """Determine if we should quote ask (sell side).

        Args:
            position: Current position

        Returns:
            True if should quote ask, False otherwise
        """
        # If we're long (positive inventory), we want to sell
        if position and position.quantity > 0:
            return True

        # If we're at hard limit on short side, don't quote ask
        if position and position.quantity < 0:
            if not self.is_within_hard_limit(position):
                return False

        # If we're within soft band, quote both sides
        if self.is_within_soft_band(position):
            return True

        # If we're outside soft band but within hard limit, still quote but with skew
        if self.is_within_hard_limit(position):
            return True

        return False

    def get_target_inventory(self) -> Decimal:
        """Get target inventory.

        Returns:
            Target inventory (usually 0 for delta-neutral)
        """
        return self.target_inventory

    def get_inventory_deviation(self, position: Optional[Position]) -> Decimal:
        """Deviation from target inventory (quote asset quantity)."""
        current = self.get_inventory_quantity(position)
        return current - self.target_inventory

    def calculate_inventory_drift(self, position: Optional[Position]) -> Decimal:
        """Calculate how far inventory is from target.

        Args:
            position: Current position

        Returns:
            Inventory drift (positive = above target, negative = below target)
        """
        current = self.get_inventory_quantity(position)
        return current - self.target_inventory

