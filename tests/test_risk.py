"""Tests for risk module."""

import pytest
from decimal import Decimal
from src.core.config import RiskConfig
from src.core.models import Position, PnLState, Order, OrderSide
from src.risk.limits import RiskLimitsChecker
from src.risk.guardian import RiskGuardian
from src.risk.metrics import RiskMetrics


@pytest.fixture
def risk_config():
    """Create risk config for testing."""
    return RiskConfig(
        daily_loss_limit_pct=0.01,
        max_drawdown_soft_pct=0.10,
        max_drawdown_hard_pct=0.15,
        max_net_notional_pct_per_symbol=0.30,
    )


@pytest.fixture
def limits_checker(risk_config):
    """Create limits checker for testing."""
    return RiskLimitsChecker(risk_config, Decimal("200"))


def test_daily_loss_limit(limits_checker):
    """Test daily loss limit check."""
    pnl_state = PnLState(
        initial_equity=Decimal("200"),
        current_equity=Decimal("198"),
        peak_equity=Decimal("200"),
        daily_realized_pnl=Decimal("-2.1"),  # Exceeds 1% limit (2 USDT)
    )
    is_violated, reason = limits_checker.check_daily_loss_limit(pnl_state)
    assert is_violated is True
    assert reason is not None


def test_drawdown_limit(limits_checker):
    """Test drawdown limit check."""
    pnl_state = PnLState(
        initial_equity=Decimal("200"),
        current_equity=Decimal("170"),
        peak_equity=Decimal("200"),
    )
    pnl_state.update_equity(Decimal("170"))
    is_violated, reason, is_hard = limits_checker.check_drawdown_limit(pnl_state)
    assert is_violated is True
    assert is_hard is True  # 15% drawdown


def test_position_limits(limits_checker):
    """Test position limits check."""
    from src.core.models import RiskLimits

    position = Position(
        symbol="BTCUSDT",
        quantity=Decimal("1.0"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
    )
    risk_limits = RiskLimits(
        symbol="BTCUSDT",
        max_net_notional=Decimal("60"),  # 30% of 200
        max_gross_notional=Decimal("120"),
        current_net_notional=Decimal("50000"),  # Exceeds limit
        current_gross_notional=Decimal("50000"),
    )
    is_violated, reason = limits_checker.check_position_limits(position, risk_limits)
    assert is_violated is True


def test_risk_guardian_kill_switch(risk_config):
    """Test kill switch."""
    guardian = RiskGuardian(risk_config, Decimal("200"))
    assert guardian.is_kill_switch_active() is False

    guardian.trigger_kill_switch("Test reason")
    assert guardian.is_kill_switch_active() is True
    assert guardian.get_kill_switch_reason() == "Test reason"

    guardian.reset_kill_switch()
    assert guardian.is_kill_switch_active() is False


def test_sharpe_ratio():
    """Test Sharpe ratio calculation."""
    returns = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"), Decimal("0.015")]
    sharpe = RiskMetrics.calculate_sharpe_ratio(returns)
    assert sharpe is not None
    assert sharpe > 0


def test_max_drawdown():
    """Test max drawdown calculation."""
    equity_series = [
        Decimal("200"),
        Decimal("210"),
        Decimal("205"),
        Decimal("190"),
        Decimal("195"),
    ]
    max_dd, max_dd_pct = RiskMetrics.calculate_max_drawdown(equity_series)
    assert max_dd > 0
    assert max_dd_pct > 0

