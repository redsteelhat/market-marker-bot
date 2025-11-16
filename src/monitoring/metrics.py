"""Metrics collection and snapshot management.

This module provides functions to collect system metrics and create snapshots
for monitoring and analysis.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
from dataclasses import dataclass

from src.core.models import Position, Order, Trade, PnLState
from src.risk.metrics import RiskMetrics


@dataclass
class SystemSnapshot:
    """System snapshot with all key metrics."""

    timestamp: datetime
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    
    # Positions
    positions: List[Position]
    total_positions_value: Decimal
    
    # Orders
    open_orders: List[Order]
    open_orders_count: int
    open_orders_per_symbol: Dict[str, int]
    
    # Trades
    total_trades: int
    trades_today: int
    cancel_to_trade_ratio: Optional[Decimal]
    
    # Risk metrics
    daily_pnl: Decimal
    peak_equity: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Optional[Decimal]
    
    # Strategy metrics
    avg_spread_bps: Optional[Decimal]
    fill_rate: Optional[Decimal]
    
    # System health
    kill_switch_active: bool
    kill_switch_reason: Optional[str]


class MetricsCollector:
    """Collects and aggregates system metrics."""

    def __init__(self, initial_equity: Decimal):
        """Initialize metrics collector.

        Args:
            initial_equity: Initial equity in USDT
        """
        self.initial_equity = initial_equity
        self.peak_equity = initial_equity
        self.equity_history: List[Decimal] = [initial_equity]
        self.pnl_history: List[Decimal] = []
        self.trade_timestamps: List[datetime] = []
        self.daily_pnl_history: List[Decimal] = []
        self.current_day = datetime.utcnow().date()
        self.daily_trades: int = 0
        self.total_cancels: int = 0
        self.total_trades: int = 0

    def record_trade(self, timestamp: datetime, pnl: Decimal) -> None:
        """Record a trade.

        Args:
            timestamp: Trade timestamp
            pnl: Trade PnL
        """
        self.trade_timestamps.append(timestamp)
        self.pnl_history.append(pnl)
        
        # Check if new day
        if timestamp.date() != self.current_day:
            self.current_day = timestamp.date()
            self.daily_trades = 0
        
        self.daily_trades += 1
        self.total_trades += 1

    def record_cancel(self) -> None:
        """Record an order cancellation."""
        self.total_cancels += 1

    def update_equity(self, equity: Decimal) -> None:
        """Update equity and track peak.

        Args:
            equity: Current equity
        """
        self.equity_history.append(equity)
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        # Keep only last 1000 points to prevent memory leak
        if len(self.equity_history) > 1000:
            self.equity_history = self.equity_history[-1000:]

    def calculate_sharpe_ratio(self, window_hours: int = 24) -> Optional[Decimal]:
        """Calculate Sharpe ratio for recent period.

        Args:
            window_hours: Time window in hours

        Returns:
            Sharpe ratio or None if insufficient data
        """
        if len(self.pnl_history) < 2:
            return None

        cutoff_time = datetime.utcnow() - timedelta(hours=window_hours)
        recent_returns = [
            pnl for ts, pnl in zip(self.trade_timestamps, self.pnl_history)
            if ts >= cutoff_time
        ]

        if len(recent_returns) < 2:
            return None

        return RiskMetrics.calculate_sharpe_ratio(recent_returns)

    def calculate_max_drawdown(self) -> tuple[Decimal, Decimal]:
        """Calculate max drawdown.

        Returns:
            Tuple of (max drawdown, max drawdown %)
        """
        if len(self.equity_history) < 2:
            return Decimal("0"), Decimal("0")

        return RiskMetrics.calculate_max_drawdown(self.equity_history)

    def get_cancel_to_trade_ratio(self) -> Optional[Decimal]:
        """Get cancel-to-trade ratio.

        Returns:
            Ratio or None if no trades
        """
        if self.total_trades == 0:
            return None
        return Decimal(str(self.total_cancels)) / Decimal(str(self.total_trades))

    def get_daily_pnl(self, positions: List[Position]) -> Decimal:
        """Calculate daily PnL.

        Args:
            positions: Current positions

        Returns:
            Daily PnL
        """
        realized = sum(p.realized_pnl for p in positions)
        unrealized = sum(p.unrealized_pnl for p in positions)
        return realized + unrealized


async def collect_snapshot(
    exchange,
    risk_guardian,
    positions: List[Position],
    open_orders: List[Order],
    trades: List[Trade],
    initial_equity: Decimal,
    metrics_collector: Optional[MetricsCollector] = None,
) -> SystemSnapshot:
    """Collect system snapshot.

    Args:
        exchange: Exchange client (for equity if available)
        risk_guardian: Risk guardian (for kill switch status)
        positions: Current positions
        open_orders: Open orders
        trades: All trades
        initial_equity: Initial equity
        metrics_collector: Optional metrics collector

    Returns:
        System snapshot
    """
    # Calculate equity
    if hasattr(exchange, "get_equity"):
        equity = exchange.get_equity()
    else:
        realized_pnl = sum(p.realized_pnl for p in positions)
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        equity = initial_equity + realized_pnl + unrealized_pnl

    # Update metrics collector
    if metrics_collector:
        metrics_collector.update_equity(equity)

    # Calculate PnL
    realized_pnl = sum(p.realized_pnl for p in positions)
    unrealized_pnl = sum(p.unrealized_pnl for p in positions)
    total_pnl = realized_pnl + unrealized_pnl

    # Positions
    total_positions_value = sum(
        abs(p.quantity * (p.mark_price or Decimal("0"))) for p in positions
    )

    # Orders per symbol
    orders_per_symbol: Dict[str, int] = {}
    for order in open_orders:
        orders_per_symbol[order.symbol] = orders_per_symbol.get(order.symbol, 0) + 1

    # Trades today
    today = datetime.utcnow().date()
    trades_today = sum(1 for t in trades if t.timestamp.date() == today)

    # Cancel-to-trade ratio
    cancel_to_trade_ratio = None
    if metrics_collector:
        cancel_to_trade_ratio = metrics_collector.get_cancel_to_trade_ratio()

    # Risk metrics
    daily_pnl = total_pnl  # Simplified - could track per day
    peak_equity = metrics_collector.peak_equity if metrics_collector else equity
    max_drawdown, max_drawdown_pct = (
        metrics_collector.calculate_max_drawdown()
        if metrics_collector
        else (Decimal("0"), Decimal("0"))
    )
    sharpe_ratio = (
        metrics_collector.calculate_sharpe_ratio()
        if metrics_collector
        else None
    )

    # Strategy metrics (simplified)
    avg_spread_bps = None  # TODO: Calculate from quotes
    fill_rate = None  # TODO: Calculate from orders/trades

    # Kill switch
    kill_switch_active = risk_guardian.is_kill_switch_active()
    kill_switch_reason = (
        risk_guardian.get_kill_switch_reason() if kill_switch_active else None
    )

    return SystemSnapshot(
        timestamp=datetime.utcnow(),
        equity=equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        positions=positions,
        total_positions_value=total_positions_value,
        open_orders=open_orders,
        open_orders_count=len(open_orders),
        open_orders_per_symbol=orders_per_symbol,
        total_trades=len(trades),
        trades_today=trades_today,
        cancel_to_trade_ratio=cancel_to_trade_ratio,
        daily_pnl=daily_pnl,
        peak_equity=peak_equity,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        avg_spread_bps=avg_spread_bps,
        fill_rate=fill_rate,
        kill_switch_active=kill_switch_active,
        kill_switch_reason=kill_switch_reason,
    )

