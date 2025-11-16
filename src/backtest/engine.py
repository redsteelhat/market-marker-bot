"""Backtest engine for historical data simulation.

This module runs the market maker strategy against historical data
to evaluate performance and optimize parameters.
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.core.config import Settings
from src.backtest.data_loader import HistoricalDataLoader
from src.execution.simulated_exchange import SimulatedExchangeClient
from src.data.orderbook import OrderBookManager
from src.risk.guardian import RiskGuardian
from src.strategy.market_maker import MarketMaker
from src.monitoring.metrics import MetricsCollector, collect_snapshot

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Backtest engine for market maker strategy."""

    def __init__(self, settings: Settings):
        """Initialize backtest engine.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.data_loader = HistoricalDataLoader(settings.backtest_data_path if hasattr(settings, 'backtest_data_path') else "data/backtest")

    async def run(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        """Run backtest.

        Args:
            symbol: Trading symbol
            start_date: Start date for backtest
            end_date: End date for backtest

        Returns:
            Backtest results dictionary
        """
        logger.info(f"Starting backtest for {symbol} from {start_date} to {end_date}")

        # Initialize components
        simulated_exchange = SimulatedExchangeClient(
            initial_equity=Decimal(str(self.settings.bot_equity_usdt))
        )
        risk_guardian = RiskGuardian(
            self.settings.risk, Decimal(str(self.settings.bot_equity_usdt))
        )
        metrics_collector = MetricsCollector(Decimal(str(self.settings.bot_equity_usdt)))
        orderbook_manager = OrderBookManager(symbol)

        # Create market maker
        market_maker = MarketMaker(
            settings=self.settings,
            exchange=simulated_exchange,
            risk_guardian=risk_guardian,
            symbol=symbol,
            orderbook_manager=orderbook_manager,
        )

        await market_maker.start()

        # Process historical data
        snapshot_count = 0
        try:
            for snapshot in self.data_loader.load_orderbook_snapshots(symbol, start_date, end_date):
                # Update order book
                orderbook_manager.update_from_snapshot(snapshot)
                
                # Feed to simulated exchange
                await simulated_exchange.on_orderbook_update(symbol, snapshot)
                
                # Trigger market maker
                await market_maker.on_order_book_update(snapshot)
                
                snapshot_count += 1
                
                # Periodic status
                if snapshot_count % 1000 == 0:
                    positions = await simulated_exchange.get_positions()
                    open_orders = await simulated_exchange.get_open_orders()
                    trades = await simulated_exchange.get_trades(limit=1000)
                    
                    snapshot_metrics = await collect_snapshot(
                        exchange=simulated_exchange,
                        risk_guardian=risk_guardian,
                        positions=positions,
                        open_orders=open_orders,
                        trades=trades,
                        initial_equity=Decimal(str(self.settings.bot_equity_usdt)),
                        metrics_collector=metrics_collector,
                    )
                    
                    logger.info(
                        f"Processed {snapshot_count} snapshots | "
                        f"Equity: {snapshot_metrics.equity:.2f} | "
                        f"PnL: {snapshot_metrics.total_pnl:+.2f} | "
                        f"Trades: {snapshot_metrics.total_trades}"
                    )
                    
                    # Check kill switch
                    if snapshot_metrics.kill_switch_active:
                        logger.warning(f"Kill switch triggered: {snapshot_metrics.kill_switch_reason}")
                        break

        finally:
            await market_maker.stop()

        # Collect final results
        positions = await simulated_exchange.get_positions()
        open_orders = await simulated_exchange.get_open_orders()
        trades = await simulated_exchange.get_trades(limit=10000)

        final_snapshot = await collect_snapshot(
            exchange=simulated_exchange,
            risk_guardian=risk_guardian,
            positions=positions,
            open_orders=open_orders,
            trades=trades,
            initial_equity=Decimal(str(self.settings.bot_equity_usdt)),
            metrics_collector=metrics_collector,
        )

        return {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "snapshots_processed": snapshot_count,
            "initial_equity": float(self.settings.bot_equity_usdt),
            "final_equity": float(final_snapshot.equity),
            "total_pnl": float(final_snapshot.total_pnl),
            "realized_pnl": float(final_snapshot.realized_pnl),
            "unrealized_pnl": float(final_snapshot.unrealized_pnl),
            "total_trades": final_snapshot.total_trades,
            "max_drawdown": float(final_snapshot.max_drawdown),
            "max_drawdown_pct": float(final_snapshot.max_drawdown_pct),
            "sharpe_ratio": float(final_snapshot.sharpe_ratio) if final_snapshot.sharpe_ratio else None,
            "kill_switch_triggered": final_snapshot.kill_switch_active,
        }

