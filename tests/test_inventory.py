"""Tests for inventory manager."""

import pytest
from decimal import Decimal
from src.core.config import StrategyConfig
from src.core.models import Position
from src.strategy.inventory import InventoryManager


@pytest.fixture
def strategy_config():
    """Create strategy config for testing."""
    return StrategyConfig(
        target_inventory=0.0,
        inventory_soft_band_pct=0.20,
        inventory_hard_limit_pct=0.30,
    )


@pytest.fixture
def inventory_manager(strategy_config):
    """Create inventory manager for testing."""
    return InventoryManager(strategy_config, Decimal("200"))


def test_inventory_within_soft_band(inventory_manager):
    """Test soft band check."""
    # Small position within soft band (0.01 * 50000 = 500 USDT, but bot equity is 200)
    # Soft band is 20% = 40 USDT, so we need a smaller position
    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("0.0008"),  # 0.0008 * 50000 = 40 USDT (exactly at soft band)
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
    )
    assert inventory_manager.is_within_soft_band(position) is True

    # Large position outside soft band
    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("0.01"),  # 0.01 * 50000 = 500 USDT > 40 USDT soft band
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
    )
    assert inventory_manager.is_within_soft_band(position) is False


def test_inventory_within_hard_limit(inventory_manager):
    """Test hard limit check."""
    # Position within hard limit (30% of 200 = 60 USDT)
    # 0.0012 * 50000 = 60 USDT (exactly at hard limit)
    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("0.001"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
    )
    assert inventory_manager.is_within_hard_limit(position) is True

    # Position outside hard limit
    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("0.002"),  # 0.002 * 50000 = 100 USDT > 60 USDT hard limit
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
    )
    assert inventory_manager.is_within_hard_limit(position) is False


def test_should_quote_bid(inventory_manager):
    """Test bid quote decision."""
    # Short position should quote bid
    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("-0.1"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
    )
    assert inventory_manager.should_quote_bid(position) is True

    # Flat position should quote bid
    assert inventory_manager.should_quote_bid(None) is True


def test_should_quote_ask(inventory_manager):
    """Test ask quote decision."""
    # Long position should quote ask
    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("0.1"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
    )
    assert inventory_manager.should_quote_ask(position) is True

    # Flat position should quote ask
    assert inventory_manager.should_quote_ask(None) is True

