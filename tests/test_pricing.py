"""Tests for pricing engine."""

import pytest
from decimal import Decimal
from src.core.config import StrategyConfig
from src.core.models import OrderBookSnapshot, OrderBookLevel
from src.strategy.pricing import PricingEngine


@pytest.fixture
def strategy_config():
    """Create strategy config for testing."""
    return StrategyConfig(
        base_spread_bps=8.0,
        min_spread_bps=4.0,
        max_spread_bps=30.0,
        inventory_skew_strength=1.2,
        order_notional_pct=0.0075,
        min_order_notional=10.0,
        max_order_notional_pct=0.025,
    )


@pytest.fixture
def orderbook():
    """Create order book snapshot for testing."""
    return OrderBookSnapshot(
        symbol="BTCUSDT",
        bids=[
            OrderBookLevel(price=Decimal("49900"), quantity=Decimal("0.1")),
            OrderBookLevel(price=Decimal("49800"), quantity=Decimal("0.2")),
        ],
        asks=[
            OrderBookLevel(price=Decimal("50100"), quantity=Decimal("0.1")),
            OrderBookLevel(price=Decimal("50200"), quantity=Decimal("0.2")),
        ],
    )


def test_pricing_engine_compute_quote(strategy_config, orderbook):
    """Test quote computation."""
    engine = PricingEngine(strategy_config)
    quote = engine.compute_quote(orderbook, Decimal("0"))

    assert quote.symbol == "BTCUSDT"
    assert quote.bid_price < quote.ask_price
    assert quote.bid_price < orderbook.mid_price
    assert quote.ask_price > orderbook.mid_price


def test_pricing_engine_inventory_skew(strategy_config, orderbook):
    """Test inventory skew."""
    engine = PricingEngine(strategy_config)

    # Long inventory should skew mid down
    quote_long = engine.compute_quote(orderbook, Decimal("0.1"))
    quote_neutral = engine.compute_quote(orderbook, Decimal("0"))

    # Short inventory should skew mid up
    quote_short = engine.compute_quote(orderbook, Decimal("-0.1"))

    # Long inventory: bid should be lower (we want to sell)
    assert quote_long.bid_price <= quote_neutral.bid_price

    # Short inventory: ask should be higher (we want to buy)
    assert quote_short.ask_price >= quote_neutral.ask_price


def test_pricing_engine_order_size(strategy_config):
    """Test order size calculation."""
    engine = PricingEngine(strategy_config)
    bot_equity = Decimal("200")

    size = engine.calculate_order_size(Decimal("50000"), bot_equity)
    assert size > 0
    assert size * Decimal("50000") >= Decimal("10")  # Min notional


def test_pricing_engine_spread_limits(strategy_config, orderbook):
    """Test spread min/max limits."""
    engine = PricingEngine(strategy_config)

    # Very high volatility should hit max spread
    quote = engine.compute_quote(orderbook, Decimal("0"), Decimal("10"))
    spread_bps = quote.spread_bps
    assert spread_bps <= Decimal(str(strategy_config.max_spread_bps))

    # Very low volatility should hit min spread
    quote = engine.compute_quote(orderbook, Decimal("0"), Decimal("0"))
    spread_bps = quote.spread_bps
    assert spread_bps >= Decimal(str(strategy_config.min_spread_bps))

