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
from src.monitoring.alerts import AlertManager, AlertThresholds

logger = logging.getLogger(__name__)
console = Console()


async def run_paper_trading(settings: Settings):
    """Run paper trading with live market data.

    Args:
        settings: Application settings
    """
    console.print(Panel.fit("Paper Trading Mode - Live Data + Local Simulation", style="bold green"))

    # Create clients
    public_client = BinancePublicClient()  # For market data only
    simulated_exchange = SimulatedExchangeClient(
        initial_equity=Decimal(str(settings.bot_equity_usdt))
    )

    try:
        # Test connection
        console.print("[cyan]Testing public API connection...[/cyan]")
        test_symbol = settings.symbols[0] if settings.symbols else "BTCUSDT"
        test_orderbook = await public_client.get_orderbook(test_symbol, limit=20)
        console.print(f"[green]Connected. Best bid: {test_orderbook.best_bid}, Best ask: {test_orderbook.best_ask}[/green]")

        # Create order book managers
        orderbook_managers = {}
        for symbol in settings.symbols:
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
        
        # Create metrics collector
        metrics_collector = MetricsCollector(Decimal(str(settings.bot_equity_usdt)))
        # Create alert manager for post-trade checks
        alert_manager = AlertManager(AlertThresholds())

        # Create market makers
        market_makers = []
        for symbol in settings.symbols:
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
            console.print(f"[green]Market maker ready for {symbol}[/green]")

        if not market_makers:
            console.print("[red]Error: No market makers could be initialized[/red]")
            return

        # Start all market makers
        console.print("[bold green]Starting market makers...[/bold green]")
        for mm in market_makers:
            await mm.start()

        # Subscribe to WebSocket streams
        console.print("[cyan]Subscribing to WebSocket streams...[/cyan]")
        streams = [f"{symbol.lower()}@depth20@100ms" for symbol in settings.symbols]
        # Binance multi-stream format: stream1/stream2 (no /ws/ prefix, handled in connect)
        stream_name = "/".join(streams)
        logger.info(f"Subscribing to streams: {stream_name}")

        def on_message(data: dict):
            """Handle WebSocket message."""
            try:
                # Binance WebSocket format for multi-stream: {"stream": "btcusdt@depth20@100ms", "data": {...}}
                # Single stream format: direct data dict
                if "stream" in data and "data" in data:
                    # Multi-stream format
                    stream = data["stream"]
                    ob_data = data["data"]
                elif "e" in data and data.get("e") == "depthUpdate":
                    # Single stream format (direct depthUpdate event)
                    stream = None  # Will extract from symbol
                    ob_data = data
                else:
                    logger.warning(f"Unknown WebSocket message format: {list(data.keys())}")
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
                        
                        # Feed to simulated exchange for order matching
                        asyncio.create_task(simulated_exchange.on_orderbook_update(symbol, snapshot))

                        # Trigger market maker update
                        for mm in market_makers:
                            if mm.symbol == symbol:
                                asyncio.create_task(mm.on_order_book_update(snapshot))
                else:
                    logger.warning(f"Symbol {symbol} not found in orderbook_managers. Available: {list(orderbook_managers.keys())}")
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}", exc_info=True)

        ws_client = BinanceWebSocketClient(
            ws_url="wss://stream.binance.com:9443",
            on_message=on_message,
        )

        # Connect to WebSocket
        try:
            await ws_client.connect(stream_name)
            console.print("[bold green]Paper trading is running! Press Ctrl+C to stop.[/bold green]")
        except Exception as e:
            console.print(f"[red]Error connecting to WebSocket: {e}[/red]")
            console.print("[yellow]Falling back to polling mode...[/yellow]")
            # Fallback to polling
            ws_client = None

        # Keep running
        last_status_print = datetime.utcnow()
        status_interval = timedelta(minutes=5)  # Print status every 5 minutes
        last_debug_log = datetime.utcnow()
        debug_interval = timedelta(seconds=10)  # Debug log every 10 seconds (for testing)
        
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
                        for symbol in settings.symbols:
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

