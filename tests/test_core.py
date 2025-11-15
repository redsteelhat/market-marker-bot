"""Tests for core module."""

import pytest
from decimal import Decimal
from src.core.config import Settings, StrategyConfig, RiskConfig, ExchangeConfig
from src.core.models import Order, OrderSide, OrderType, OrderStatus, Position, Quote, OrderBookSnapshot, OrderBookLevel
from src.core.constants import DEFAULT_SPREAD_BPS, DEFAULT_MAKER_FEE_BPS


def test_settings_creation():
    """Test Settings creation."""
    settings = Settings.from_env()
    assert settings.bot_equity_usdt > 0
    assert settings.strategy is not None
    assert settings.risk is not None


def test_strategy_config_defaults():
    """Test StrategyConfig defaults."""
    config = StrategyConfig()
    assert config.base_spread_bps == 8.0
    assert config.min_spread_bps == 4.0
    assert config.max_spread_bps == 30.0
    assert config.refresh_interval_ms == 1000


def test_risk_config_defaults():
    """Test RiskConfig defaults."""
    config = RiskConfig()
    assert config.daily_loss_limit_pct == 0.01
    assert config.max_drawdown_soft_pct == 0.10
    assert config.max_drawdown_hard_pct == 0.15


def test_order_model():
    """Test Order model."""
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("0.001"),
        price=Decimal("50000"),
    )
    assert order.symbol == "BTCUSDT"
    assert order.side == OrderSide.BUY
    assert order.notional == Decimal("50")
    assert order.is_open is True


def test_position_model():
    """Test Position model."""
    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("0.1"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("51000"),
        unrealized_pnl=Decimal("100"),  # (51000 - 50000) * 0.1
    )
    assert position.is_long is True
    assert position.notional == Decimal("5100")  # 0.1 * 51000
    assert position.unrealized_pnl == Decimal("100")


def test_quote_model():
    """Test Quote model."""
    quote = Quote(
        symbol="BTCUSDT",
        bid_price=Decimal("49900"),
        bid_size=Decimal("0.001"),
        ask_price=Decimal("50100"),
        ask_size=Decimal("0.001"),
    )
    assert quote.mid_price == Decimal("50000")
    assert quote.spread == Decimal("200")
    # 200/50000 * 10000 = 40 bps (not 4 bps - the calculation was wrong in comment)
    assert quote.spread_bps == Decimal("40")


def test_orderbook_snapshot():
    """Test OrderBookSnapshot model."""
    snapshot = OrderBookSnapshot(
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
    assert snapshot.best_bid == Decimal("49900")
    assert snapshot.best_ask == Decimal("50100")
    assert snapshot.mid_price == Decimal("50000")
    assert snapshot.spread == Decimal("200")

