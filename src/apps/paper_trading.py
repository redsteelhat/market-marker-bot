"""Paper trading application with live market data.

This module runs the market maker bot in paper trading mode:
- Uses live market data from Binance public API (no auth required)
- Simulates order execution locally
- No real orders sent to exchange
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.core.config import Settings
from src.data.binance_public_client import BinancePublicClient
from src.data.orderbook import OrderBookManager
from src.data.websocket import BinanceWebSocketClient
from src.execution.simulated_exchange import SimulatedExchangeClient
from src.execution.order_manager import OrderManager
from src.risk.guardian import RiskGuardian
from src.strategy.market_maker import MarketMaker
from src.monitoring.metrics import MetricsCollector, collect_snapshot
from src.monitoring.journal import TradeJournal, JournalConfig
from src.monitoring.alerts import AlertManager, AlertThresholds

logger = logging.getLogger(__name__)
console = Console()


async def run_paper_trading(settings: Settings, enable_dashboard: bool = False, dashboard_port: int = 8000):
    """Run paper trading with live market data.

    Args:
        settings: Application settings
        enable_dashboard: If True, start dashboard server in the same process
        dashboard_port: Dashboard server port (if enable_dashboard is True)
    """
    console.print(Panel.fit("Paper Trading Mode - Live Data + Local Simulation", style="bold green"))

    # Import dashboard module to access bot_runtime_state
    from src.apps.dashboard import bot_runtime_state, dashboard_state
    
    # Initialize bot runtime state
    bot_runtime_state["bot_running"] = True
    
    # Create clients
    public_client = BinancePublicClient()  # For market data only
    simulated_exchange = SimulatedExchangeClient(
        initial_equity=Decimal(str(settings.bot_equity_usdt))
    )
    
    # Store references in bot runtime state for dynamic symbol management
    bot_runtime_state["public_client"] = public_client
    bot_runtime_state["simulated_exchange"] = simulated_exchange

    try:
        # Prepare run directory for journaling
        run_dir_ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_dir = f"runs/{run_dir_ts}"
        journal = TradeJournal(JournalConfig(run_dir=run_dir), initial_equity=Decimal(str(settings.bot_equity_usdt)))
        
        # Test connection with a default symbol (for connection test only)
        console.print("[cyan]Testing public API connection...[/cyan]")
        test_symbol = "BTCUSDT"  # Always use BTCUSDT for connection test
        test_orderbook = await public_client.get_orderbook(test_symbol, limit=20)
        console.print(f"[green]Connected. Best bid: {test_orderbook.best_bid}, Best ask: {test_orderbook.best_ask}[/green]")
        
        # Get active symbols from dashboard (selected coins) or start with empty list
        # Bot will wait for user to select coins from dashboard
        active_symbols = bot_runtime_state.get("active_symbols", [])
        if not active_symbols:
            # Check dashboard state for selected coins
            active_symbols = dashboard_state.get("selected_coins", [])
        
        console.print(f"[yellow]Starting with {len(active_symbols)} active symbols: {active_symbols if active_symbols else 'None (select coins from dashboard)'}[/yellow]")
        console.print("[dim]Note: Select coins from dashboard to start trading[/dim]")

        # Create order book managers (initially empty, will be populated when coins are selected)
        orderbook_managers = {}
        for symbol in active_symbols:
            ob_manager = OrderBookManager(symbol)
            # Get initial snapshot
            snapshot = await public_client.get_orderbook(symbol, limit=20)
            ob_manager.update_from_binance({
                "bids": [[float(level.price), float(level.quantity)] for level in snapshot.bids],
                "asks": [[float(level.price), float(level.quantity)] for level in snapshot.asks],
            })
            # Feed to simulated exchange
            await simulated_exchange.on_orderbook_update(symbol, snapshot)
            orderbook_managers[symbol] = ob_manager
            console.print(f"[green]Order book loaded for {symbol}[/green]")

        # Create risk guardian
        risk_guardian = RiskGuardian(
            settings.risk, Decimal(str(settings.bot_equity_usdt))
        )
        
        # Store in bot runtime state
        bot_runtime_state["risk_guardian"] = risk_guardian
        bot_runtime_state["settings"] = settings
        
        # Config summary
        console.print("[dim]\n[CONFIG] Mode: paper_exchange[/dim]")
        console.print(f"[dim][CONFIG] Active Symbols: {', '.join(active_symbols) if active_symbols else 'None (select from dashboard)'}[/dim]")
        try:
            console.print(f"[dim][CONFIG] Base spread (bps): {settings.strategy.base_spread_bps}[/dim]")
        except Exception:
            pass
        try:
            console.print(f"[dim][CONFIG] Order notional %: {settings.strategy.order_notional_pct}[/dim]")
        except Exception:
            pass
        console.print("[dim][CONFIG] Toxicity thresholds: soft=0.70, hard=0.90[/dim]\n")
        
        # Create metrics collector
        metrics_collector = MetricsCollector(Decimal(str(settings.bot_equity_usdt)))
        # Create alert manager for post-trade checks
        alert_manager = AlertManager(AlertThresholds())

        # Create market makers (only for active symbols)
        market_makers = []
        risk_scaling_engines = {}
        for symbol in active_symbols:
            if symbol not in orderbook_managers:
                continue

            mm = MarketMaker(
                settings=settings,
                exchange=simulated_exchange,
                risk_guardian=risk_guardian,
                symbol=symbol,
                orderbook_manager=orderbook_managers[symbol],
            )
            market_makers.append(mm)
            # Collect risk scaling engines if available
            if hasattr(mm, 'risk_scaling') and mm.risk_scaling:
                risk_scaling_engines[symbol] = mm.risk_scaling
            console.print(f"[green]Market maker ready for {symbol}[/green]")

        # Store in bot runtime state
        bot_runtime_state["orderbook_managers"] = orderbook_managers
        bot_runtime_state["market_makers"] = market_makers
        bot_runtime_state["risk_scaling_engines"] = risk_scaling_engines

        # Start all market makers (if any)
        if market_makers:
            console.print("[bold green]Starting market makers...[/bold green]")
            for mm in market_makers:
                await mm.start()
        else:
            console.print("[yellow]No market makers to start. Select coins from dashboard to begin trading.[/yellow]")

        # Start dashboard server if enabled (BEFORE WebSocket to ensure it starts)
        dashboard_server_task = None
        dashboard_update_task = None
        dashboard_thread = None
        
        # Debug: Log enable_dashboard value
        logger.info(f"DEBUG: enable_dashboard={enable_dashboard}, type={type(enable_dashboard)}, dashboard_port={dashboard_port}")
        console.print(f"[dim]DEBUG: enable_dashboard={enable_dashboard}, dashboard_port={dashboard_port}[/dim]")
        
        if enable_dashboard:
            logger.info(f"Dashboard enabled: enable_dashboard={enable_dashboard}, port={dashboard_port}")
            try:
                import threading
                from src.apps.dashboard import create_app, update_dashboard_state, setup_dashboard_log_handler
                import uvicorn
                
                logger.info("Importing dashboard modules successful")
                
                # Setup dashboard log handler
                setup_dashboard_log_handler()
                logger.info("Dashboard log handler setup complete")
                
                console.print(f"[bold cyan]Starting dashboard server on port {dashboard_port}...[/bold cyan]")
                logger.info(f"Starting dashboard server on port {dashboard_port}")
                
                # Create FastAPI app
                app = create_app()
                
                # Start dashboard update loop (isolated from bot operations)
                async def dashboard_update_loop():
                    """Dashboard update loop - isolated from bot trading operations."""
                    update_interval = 2.0  # Update every 2 seconds (less frequent to reduce load)
                    consecutive_errors = 0
                    max_consecutive_errors = 5
                    
                    while True:
                        try:
                           # Get current active symbols from bot runtime state (atomic read)
                           current_active_symbols = bot_runtime_state.get("active_symbols", active_symbols)
                           # Get current orderbook managers (may have changed)
                           current_orderbook_managers = bot_runtime_state.get("orderbook_managers", orderbook_managers)
                           
                           # Update dashboard state (with timeout protection)
                           await update_dashboard_state(
                               exchange=simulated_exchange,
                               risk_guardian=risk_guardian,
                               settings=settings,
                               risk_scaling_engines=risk_scaling_engines,
                               orderbook_managers=current_orderbook_managers,  # Pass orderbook managers for prices
                               selected_coins=current_active_symbols,
                           )
                           
                           # Reset error counter on success
                           consecutive_errors = 0
                           
                        except Exception as e:
                            consecutive_errors += 1
                            if consecutive_errors >= max_consecutive_errors:
                                logger.error(f"Dashboard update loop has {consecutive_errors} consecutive errors, pausing for 10 seconds")
                                await asyncio.sleep(10.0)  # Pause longer on repeated errors
                                consecutive_errors = 0
                            else:
                                logger.warning(f"Error in dashboard update loop (attempt {consecutive_errors}/{max_consecutive_errors}): {e}")
                        
                        # Sleep with interval (allows bot operations to proceed)
                        await asyncio.sleep(update_interval)
                
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
                        console.print(f"[red]Dashboard server failed: {e}[/red]")
                        import traceback
                        traceback.print_exc()
                
                dashboard_thread = threading.Thread(target=run_server, daemon=True)
                dashboard_thread.start()
                
                # Wait for server to start (or error)
                import time
                if server_started.wait(timeout=3):
                    if server_error[0]:
                        console.print(f"[red]✗ Dashboard server failed to start: {server_error[0]}[/red]")
                    else:
                        console.print(f"[green]✓ Dashboard available at: http://127.0.0.1:{dashboard_port}[/green]")
                else:
                    console.print(f"[yellow]⚠ Dashboard server may still be starting...[/yellow]")
                    console.print(f"[dim]Check http://127.0.0.1:{dashboard_port} in a few seconds[/dim]")
            except Exception as e:
                console.print(f"[red]Error: Could not start dashboard server: {e}[/red]")
                logger.exception("Dashboard server start error")
                import traceback
                traceback.print_exc()

        # Subscribe to WebSocket streams (only for active symbols)
        console.print("[cyan]Subscribing to WebSocket streams...[/cyan]")
        streams = [f"{symbol.lower()}@depth20@100ms" for symbol in active_symbols]
        # Binance multi-stream format: stream1/stream2 (no /ws/ prefix, handled in connect)
        stream_name = "/".join(streams) if streams else None
        if stream_name:
            logger.info(f"Subscribing to streams: {stream_name}")
        else:
            logger.info("No active symbols, skipping WebSocket subscription (will subscribe when coins are selected)")

        def on_message(data: dict):
            """Handle WebSocket message - isolated from dashboard updates."""
            try:
                # Process WebSocket message in background task to avoid blocking
                # This ensures bot operations are not delayed by dashboard updates
                # Binance WebSocket format for multi-stream: {"stream": "btcusdt@depth20@100ms", "data": {...}}
                # Single stream format: direct data dict
                # Snapshot format: {"lastUpdateId": ..., "bids": ..., "asks": ...} - ignore these
                if "stream" in data and "data" in data:
                    # Multi-stream format
                    stream = data["stream"]
                    ob_data = data["data"]
                elif "e" in data and data.get("e") == "depthUpdate":
                    # Single stream format (direct depthUpdate event)
                    stream = None  # Will extract from symbol
                    ob_data = data
                elif "lastUpdateId" in data and "bids" in data and "asks" in data:
                    # This is a snapshot format, not an update - ignore it
                    logger.debug(f"Ignoring snapshot format message (not an update)")
                    return
                else:
                    # Only log at debug level to reduce spam
                    logger.debug(f"Unknown WebSocket message format: {list(data.keys())}")
                    return

                # Extract symbol from stream name or data
                if stream:
                    # Extract symbol: "btcusdt@depth20@100ms" -> "BTCUSDT"
                    symbol_part = stream.split("@")[0].upper()
                    symbol = symbol_part
                elif "s" in ob_data:
                    # Extract from data
                    symbol = ob_data["s"]
                else:
                    logger.warning(f"Cannot extract symbol from message: {list(ob_data.keys())}")
                    return

                logger.debug(f"WebSocket update received for {symbol}")

                # Update order book
                if symbol in orderbook_managers:
                    ob_manager = orderbook_managers[symbol]
                    ob_manager.update_from_websocket(ob_data)
                    snapshot = ob_manager.snapshot

                    if snapshot:
                        logger.debug(f"Order book updated for {symbol}: bid={snapshot.best_bid}, ask={snapshot.best_ask}")
                        
                        # Feed to simulated exchange for order matching (high priority)
                        # Use create_task to ensure non-blocking execution
                        exchange_task = asyncio.create_task(
                            simulated_exchange.on_orderbook_update(symbol, snapshot)
                        )
                        
                        # Trigger market maker update (high priority - bot trading logic)
                        for mm in market_makers:
                            if mm.symbol == symbol:
                                # Market maker updates are critical - execute immediately
                                mm_task = asyncio.create_task(mm.on_order_book_update(snapshot))
                                # Don't await - let it run in background
                                # Bot operations should not wait for dashboard
                else:
                    logger.warning(f"Symbol {symbol} not found in orderbook_managers. Available: {list(orderbook_managers.keys())}")
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}", exc_info=True)

        ws_client = BinanceWebSocketClient(
            ws_url="wss://stream.binance.com:9443",
            on_message=on_message,
        )
        
        # Store in bot runtime state
        bot_runtime_state["ws_client"] = ws_client

        # Connect to WebSocket (only if we have active symbols)
        if stream_name:
            try:
                await ws_client.connect(stream_name)
                console.print("[bold green]Paper trading is running! Press Ctrl+C to stop.[/bold green]")
            except Exception as e:
                console.print(f"[red]Error connecting to WebSocket: {e}[/red]")
                console.print("[yellow]Falling back to polling mode...[/yellow]")
                # Fallback to polling
                ws_client = None
        else:
            console.print("[bold yellow]Paper trading is running! Select coins from dashboard to start trading. Press Ctrl+C to stop.[/bold yellow]")
            ws_client = None

        # Dashboard is already started before WebSocket (see above)
        # No need to start it again here
        if not enable_dashboard:
            # Start dashboard update task if dashboard is enabled (for external dashboard server)
            try:
                dashboard_update_task = asyncio.create_task(
                    _dashboard_update_loop(
                        simulated_exchange, risk_guardian, settings, risk_scaling_engines
                    )
                )
                console.print("[dim]Dashboard updates enabled (if dashboard server is running)[/dim]")
            except Exception as e:
                logger.debug(f"Dashboard update task not started: {e}")
        
        # Keep running
        last_status_print = datetime.utcnow()
        status_interval = timedelta(minutes=5)  # Print status every 5 minutes
        last_debug_log = datetime.utcnow()
        debug_interval = timedelta(seconds=10)  # Debug log every 10 seconds (for testing)
        last_journal_append = datetime.utcnow()
        journal_interval = timedelta(seconds=10)  # append new trades every 10s
        
        try:
            while True:
                await asyncio.sleep(1)
                
                # Debug logging every 30 seconds
                now = datetime.utcnow()
                if now - last_debug_log >= debug_interval:
                    try:
                        positions = await simulated_exchange.get_positions()
                        open_orders = await simulated_exchange.get_open_orders()
                        # get_open_orders returns List[Order]
                        total_orders = len(open_orders) if isinstance(open_orders, list) else 0
                        
                        console.print(f"\n[cyan]Status Update ({now.strftime('%H:%M:%S')}):[/cyan]")
                        console.print(f"  Open Orders: {total_orders}")
                        console.print(f"  Positions: {len(positions)}")
                        # Get active symbols from bot runtime state (may have changed)
                        current_active_symbols = bot_runtime_state.get("active_symbols", active_symbols)
                        for symbol in current_active_symbols:
                            if symbol in orderbook_managers:
                                ob = orderbook_managers[symbol]
                                if ob.snapshot:
                                    # Get open orders for this symbol
                                    symbol_orders = [o for o in open_orders if o.symbol == symbol] if isinstance(open_orders, list) else []
                                    console.print(f"  {symbol}: Bid={ob.snapshot.best_bid}, Ask={ob.snapshot.best_ask}, Mid={ob.snapshot.mid_price}, Open Orders={len(symbol_orders)}")
                                    if symbol_orders:
                                        for order in symbol_orders[:2]:  # Show first 2 orders
                                            console.print(f"    {order.side.value} {order.quantity} @ {order.price}")
                        if positions:
                            for pos in positions:
                                console.print(f"  Position {pos.symbol}: {pos.quantity:.6f} @ {pos.entry_price} (PnL: {pos.unrealized_pnl:+.2f} USDT)")
                    except Exception as e:
                        logger.error(f"Error in debug logging: {e}")
                    last_debug_log = now

                # Append new trades to journal periodically
                now = datetime.utcnow()
                if now - last_journal_append >= journal_interval:
                    try:
                        latest_trades = await simulated_exchange.get_trades(limit=1000)
                        journal.append_new_trades(latest_trades)
                    except Exception as e:
                        logger.error(f"Journal append error: {e}")
                    last_journal_append = now

                # Check kill switch
                if risk_guardian.is_kill_switch_active():
                    console.print(
                        f"[red]Kill switch active: {risk_guardian.get_kill_switch_reason()}[/red]"
                    )
                    break

                # Print status periodically
                now = datetime.utcnow()
                if now - last_status_print >= status_interval:
                    try:
                        positions = await simulated_exchange.get_positions()
                        open_orders = await simulated_exchange.get_open_orders()
                        trades = await simulated_exchange.get_trades(limit=1000)
                        
                        snapshot = await collect_snapshot(
                            exchange=simulated_exchange,
                            risk_guardian=risk_guardian,
                            positions=positions,
                            open_orders=open_orders,
                            trades=trades,
                            initial_equity=Decimal(str(settings.bot_equity_usdt)),
                            metrics_collector=metrics_collector,
                        )

                        # Post-trade checks & alerts
                        try:
                            alert_manager.evaluate(snapshot)
                        except Exception as e:
                            logger.error(f"Alert evaluation error: {e}")
                        
                        console.print(f"\n[bold cyan]Status Update ({now.strftime('%H:%M:%S')}):[/bold cyan]")
                        console.print(f"  Equity: {snapshot.equity:.2f} USDT | PnL: {snapshot.total_pnl:+.2f} USDT")
                        console.print(f"  Trades: {snapshot.total_trades} | Open Orders: {snapshot.open_orders_count}")
                        if snapshot.sharpe_ratio:
                            console.print(f"  Sharpe (24h): {snapshot.sharpe_ratio:.2f}")
                        if snapshot.kill_switch_active:
                            console.print(f"  [red]KILL SWITCH: {snapshot.kill_switch_reason}[/red]")
                        
                        last_status_print = now
                    except Exception as e:
                        logger.error(f"Error printing status: {e}")

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping paper trading...[/yellow]")
        finally:
            # Stop dashboard update task if running
            try:
                if 'dashboard_update_task' in locals() and dashboard_update_task:
                    dashboard_update_task.cancel()
                    try:
                        await dashboard_update_task
                    except asyncio.CancelledError:
                        pass
            except Exception:
                pass
            
            # Dashboard server thread will be stopped automatically when main thread exits (daemon=True)
            
            # Stop all market makers
            for mm in market_makers:
                try:
                    await mm.stop()
                except Exception as e:
                    logger.error(f"Error stopping market maker: {e}")

            # Disconnect WebSocket
            if ws_client:
                try:
                    await ws_client.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting WebSocket: {e}")

            # Print final stats
            console.print("\n[bold]Final Statistics:[/bold]")
            positions = await simulated_exchange.get_positions()
            open_orders = await simulated_exchange.get_open_orders()
            trades = await simulated_exchange.get_trades(limit=1000)
            
            snapshot = await collect_snapshot(
                exchange=simulated_exchange,
                risk_guardian=risk_guardian,
                positions=positions,
                open_orders=open_orders,
                trades=trades,
                initial_equity=Decimal(str(settings.bot_equity_usdt)),
                metrics_collector=metrics_collector,
            )

            # Write session summary to journal
            try:
                journal.write_summary(
                    positions=positions,
                    trades=trades,
                    equity=snapshot.equity,
                    realized_pnl=snapshot.realized_pnl,
                    unrealized_pnl=snapshot.unrealized_pnl,
                )
                console.print(f"[green]Session journal saved to: {run_dir}[/green]")
                console.print(f"[dim]- trades.csv (all trades)\n- summary.md (session report)[/dim]")
            except Exception as e:
                logger.error(f"Error writing session summary: {e}")
            
            final_table = Table(title="Final Performance", show_header=True)
            final_table.add_column("Metric", style="cyan")
            final_table.add_column("Value", style="magenta")
            
            final_table.add_row("Initial Equity", f"{settings.bot_equity_usdt} USDT")
            final_table.add_row("Final Equity", f"{snapshot.equity:.2f} USDT")
            final_table.add_row("Total PnL", f"{snapshot.total_pnl:+.2f} USDT")
            final_table.add_row("Realized PnL", f"{snapshot.realized_pnl:+.2f} USDT")
            final_table.add_row("Unrealized PnL", f"{snapshot.unrealized_pnl:+.2f} USDT")
            final_table.add_row("Total Trades", str(snapshot.total_trades))
            final_table.add_row("Trades Today", str(snapshot.trades_today))
            
            if snapshot.max_drawdown_pct > 0:
                final_table.add_row("Max Drawdown", f"{snapshot.max_drawdown:.2f} USDT ({snapshot.max_drawdown_pct:.2f}%)")
            
            if snapshot.sharpe_ratio:
                final_table.add_row("Sharpe Ratio (24h)", f"{snapshot.sharpe_ratio:.2f}")
            
            console.print(final_table)
            
            if positions:
                console.print("\n[bold]Final Positions:[/bold]")
                for pos in positions:
                    console.print(f"  {pos.symbol}: {pos.quantity:.6f} @ {pos.entry_price} (PnL: {pos.unrealized_pnl:+.2f} USDT)")

            console.print("[green]Paper trading stopped[/green]")

    finally:
        await public_client.close()


async def _dashboard_update_loop(
    exchange: SimulatedExchangeClient,
    risk_guardian: RiskGuardian,
    settings: Settings,
    risk_scaling_engines: dict,
    update_interval: float = 2.0,  # Increased to 2 seconds to reduce load
):
    """Background task to update dashboard state periodically.
    
    This loop is isolated from bot trading operations and uses timeouts
    to prevent blocking the main event loop.
    """
    from src.apps.dashboard import update_dashboard_state, bot_runtime_state
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            # Get current active symbols and orderbook managers from bot runtime state (atomic read)
            current_active_symbols = bot_runtime_state.get("active_symbols", [])
            orderbook_managers = bot_runtime_state.get("orderbook_managers", {})
            
            # Update dashboard state (with timeout protection in update_dashboard_state)
            await update_dashboard_state(
                exchange=exchange,
                risk_guardian=risk_guardian,
                settings=settings,
                risk_scaling_engines=risk_scaling_engines,
                orderbook_managers=orderbook_managers,
                selected_coins=current_active_symbols,
            )
            
            # Reset error counter on success
            consecutive_errors = 0
            
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"Dashboard update loop has {consecutive_errors} consecutive errors, pausing for 10 seconds")
                await asyncio.sleep(10.0)  # Pause longer on repeated errors
                consecutive_errors = 0
            else:
                logger.debug(f"Error in dashboard update loop (attempt {consecutive_errors}/{max_consecutive_errors}): {e}")
        
        # Sleep with interval (allows bot operations to proceed)
        await asyncio.sleep(update_interval)

