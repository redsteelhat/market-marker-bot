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
        enable_dashboard: bool = False,
        dashboard_port: int = 8000,
    ) -> dict:
        """Run backtest.

        Args:
            symbol: Trading symbol
            start_date: Start date for backtest
            end_date: End date for backtest
            enable_dashboard: If True, start dashboard server during backtest
            dashboard_port: Dashboard server port (if enable_dashboard is True)

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

        # Start dashboard if enabled
        dashboard_thread = None
        dashboard_update_task = None
        if enable_dashboard:
            try:
                import threading
                from src.apps.dashboard import create_app, update_dashboard_state, setup_dashboard_log_handler
                import uvicorn
                
                # Setup dashboard log handler
                setup_dashboard_log_handler()
                
                logger.info(f"Starting dashboard server on port {dashboard_port}...")
                
                # Create FastAPI app
                app = create_app()
                
                # Start dashboard update loop
                async def dashboard_update_loop():
                    while True:
                        try:
                            await update_dashboard_state(
                                exchange=simulated_exchange,
                                risk_guardian=risk_guardian,
                                settings=self.settings,
                                risk_scaling_engines=None,  # Backtest doesn't use risk scaling
                            )
                        except Exception as e:
                            logger.error(f"Error in dashboard update loop: {e}")
                        await asyncio.sleep(1.0)
                
                # Start update loop as background task
                dashboard_update_task = asyncio.create_task(dashboard_update_loop())
                
                # Start uvicorn server in a separate thread (blocking)
                server_started = threading.Event()
                server_error = [None]  # Use list to allow modification in nested function
                
                def run_server():
                    try:
                        import uvicorn
                        # Create new event loop for this thread
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        config = uvicorn.Config(
                            app, 
                            host="127.0.0.1", 
                            port=dashboard_port, 
                            log_level="info",
                            access_log=False  # Reduce noise
                        )
                        server = uvicorn.Server(config)
                        
                        # Signal that server is starting
                        server_started.set()
                        
                        # Run server
                        loop.run_until_complete(server.serve())
                    except Exception as e:
                        server_error[0] = e
                        logger.error(f"Dashboard server error: {e}", exc_info=True)
                        import traceback
                        traceback.print_exc()
                
                dashboard_thread = threading.Thread(target=run_server, daemon=True)
                dashboard_thread.start()
                
                # Wait for server to start (or error)
                import time
                if server_started.wait(timeout=3):
                    if server_error[0]:
                        logger.error(f"Dashboard server failed to start: {server_error[0]}")
                    else:
                        logger.info(f"Dashboard available at: http://127.0.0.1:{dashboard_port}")
                else:
                    logger.warning(f"Dashboard server may still be starting... Check http://127.0.0.1:{dashboard_port} in a few seconds")
            except Exception as e:
                logger.error(f"Could not start dashboard server: {e}")

        # Process historical data
        snapshot_count = 0
        last_dashboard_update = 0
        dashboard_update_interval = 100  # Update dashboard every 100 snapshots
        try:
            for snapshot in self.data_loader.load_orderbook_snapshots(symbol, start_date, end_date):
                # Update order book
                orderbook_manager.update_from_snapshot(snapshot)
                
                # Feed to simulated exchange
                await simulated_exchange.on_orderbook_update(symbol, snapshot)
                
                # Trigger market maker
                await market_maker.on_order_book_update(snapshot)
                
                snapshot_count += 1
                
                # Update dashboard periodically (more frequent than status logs)
                if enable_dashboard and snapshot_count - last_dashboard_update >= dashboard_update_interval:
                    last_dashboard_update = snapshot_count
                    # Dashboard update loop will handle this automatically
                
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
            # Stop dashboard update task if running
            if dashboard_update_task:
                dashboard_update_task.cancel()
                try:
                    await dashboard_update_task
                except asyncio.CancelledError:
                    pass
            
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

