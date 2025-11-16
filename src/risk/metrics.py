"""Risk metrics calculation.

This module provides functions to calculate performance metrics:
- Sharpe ratio
- Maximum drawdown
- Spread PnL
- Cancel-to-trade ratio
"""

import math
from decimal import Decimal
from typing import List, Optional
from src.core.models import PnLState, Trade, Order


class RiskMetrics:
    """Calculate risk and performance metrics."""

    @staticmethod
    def calculate_sharpe_ratio(
        returns: List[Decimal], risk_free_rate: Decimal = Decimal("0.0"), periods_per_year: int = 365
    ) -> Optional[Decimal]:
        """Calculate Sharpe ratio.

        Args:
            returns: List of period returns
            risk_free_rate: Risk-free rate (annual)
            periods_per_year: Number of periods per year (e.g., 365 for daily)

        Returns:
            Sharpe ratio or None if insufficient data
        """
        if len(returns) < 2:
            return None

        # Calculate mean return
        mean_return = sum(returns) / Decimal(len(returns))

        # Calculate standard deviation
        variance = sum((r - mean_return) ** 2 for r in returns) / Decimal(len(returns) - 1)
        std_dev = variance.sqrt()

        if std_dev == 0:
            return None

        # Annualize
        annualized_return = mean_return * Decimal(periods_per_year)
        annualized_std = std_dev * Decimal(math.sqrt(periods_per_year))

        # Sharpe ratio
        sharpe = (annualized_return - risk_free_rate) / annualized_std
        return sharpe

    @staticmethod
    def calculate_max_drawdown(equity_series: List[Decimal]) -> tuple[Decimal, Decimal]:
        """Calculate maximum drawdown.

        Args:
            equity_series: Series of equity values over time

        Returns:
            Tuple of (max_drawdown, max_drawdown_pct)
        """
        if not equity_series:
            return (Decimal("0"), Decimal("0"))

        peak = equity_series[0]
        max_dd = Decimal("0")
        max_dd_pct = Decimal("0")

        for equity in equity_series:
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            drawdown_pct = (drawdown / peak * Decimal("100")) if peak > 0 else Decimal("0")

            if drawdown > max_dd:
                max_dd = drawdown
                max_dd_pct = drawdown_pct

        return (max_dd, max_dd_pct)

    @staticmethod
    def calculate_spread_pnl(trades: List[Trade]) -> tuple[Decimal, Decimal]:
        """Calculate spread PnL (gross and net).

        Args:
            trades: List of trades

        Returns:
            Tuple of (gross_spread_pnl, net_spread_pnl)
        """
        if not trades:
            return (Decimal("0"), Decimal("0"))

        # Group trades by symbol and calculate spread PnL
        buy_trades = {}
        sell_trades = {}

        for trade in trades:
            if trade.side == "BUY":
                if trade.symbol not in buy_trades:
                    buy_trades[trade.symbol] = []
                buy_trades[trade.symbol].append(trade)
            else:
                if trade.symbol not in sell_trades:
                    sell_trades[trade.symbol] = []
                sell_trades[trade.symbol].append(trade)

        gross_pnl = Decimal("0")
        total_fees = Decimal("0")

        # Calculate spread PnL for each symbol
        for symbol in set(list(buy_trades.keys()) + list(sell_trades.keys())):
            buys = buy_trades.get(symbol, [])
            sells = sell_trades.get(symbol, [])

            # Match buys and sells
            buy_qty = sum(t.quantity for t in buys)
            sell_qty = sum(t.quantity for t in sells)
            matched_qty = min(buy_qty, sell_qty)

            if matched_qty > 0:
                avg_buy_price = sum(t.price * t.quantity for t in buys) / buy_qty
                avg_sell_price = sum(t.price * t.quantity for t in sells) / sell_qty
                spread = avg_sell_price - avg_buy_price
                gross_pnl += spread * matched_qty

            # Calculate fees
            total_fees += sum(t.fee for t in buys + sells)

        net_pnl = gross_pnl - total_fees
        return (gross_pnl, net_pnl)

    @staticmethod
    def calculate_cancel_to_trade_ratio(
        total_cancels: int, total_fills: int
    ) -> Optional[Decimal]:
        """Calculate cancel-to-trade ratio.

        Args:
            total_cancels: Total number of canceled orders
            total_fills: Total number of filled orders

        Returns:
            Cancel-to-trade ratio or None if no fills
        """
        if total_fills == 0:
            return None
        return Decimal(total_cancels) / Decimal(total_fills)

    @staticmethod
    def calculate_fill_ratio(orders: List[Order]) -> Decimal:
        """Calculate fill ratio.

        Args:
            orders: List of orders

        Returns:
            Fill ratio (0-1)
        """
        if not orders:
            return Decimal("0")

        total_qty = sum(order.quantity for order in orders)
        filled_qty = sum(order.filled_quantity for order in orders)

        if total_qty == 0:
            return Decimal("0")

        return filled_qty / total_qty

    @staticmethod
    def is_too_volatile(volatility_bps: Optional[Decimal], threshold_bps: Decimal = Decimal("50")) -> bool:
        """Return True if short-term volatility (bps) exceeds threshold."""
        if volatility_bps is None:
            return False
        return volatility_bps >= threshold_bps

    @staticmethod
    def orderbook_imbalance(bid_notional: Decimal, ask_notional: Decimal) -> Optional[Decimal]:
        """Compute order book imbalance in [-1,1]."""
        total = bid_notional + ask_notional
        if total == 0:
            return None
        return (bid_notional - ask_notional) / total

    @staticmethod
    def calculate_realized_pnl(trades: List[Trade]) -> Decimal:
        """Calculate realized PnL from trades.

        Args:
            trades: List of trades

        Returns:
            Realized PnL
        """
        if not trades:
            return Decimal("0")

        # Simple calculation: sum of (sell_price - buy_price) * quantity for matched trades
        # This is a simplified version; in practice, you'd need to match trades properly
        pnl = Decimal("0")
        for trade in trades:
            if trade.side == "SELL":
                pnl += trade.notional
            else:
                pnl -= trade.notional
            pnl -= trade.fee  # Subtract fees

        return pnl

    @staticmethod
    def calculate_inventory_pnl(
        position: Optional[object], mark_price: Decimal
    ) -> Decimal:
        """Calculate inventory PnL (mark-to-market).

        Args:
            position: Position object with quantity and entry_price
            mark_price: Current mark price

        Returns:
            Inventory PnL
        """
        if not position or position.quantity == 0:
            return Decimal("0")

        if not position.entry_price:
            return Decimal("0")

        pnl = (mark_price - position.entry_price) * position.quantity
        return pnl

