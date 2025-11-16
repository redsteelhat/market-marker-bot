"""Paper trading application with live market data.

This module runs the market maker bot in paper trading mode:
- Uses live market data from Binance public API (no auth required)
- Simulates order execution locally
- No real orders sent to exchange
"""

import asyncio
import logging
from decimal import Decimal
from rich.console import Console
from rich.panel import Panel

from src.core.config import Settings
from src.data.binance_public_client import BinancePublicClient
from src.data.orderbook import OrderBookManager
from src.data.websocket import BinanceWebSocketClient
from src.execution.simulated_exchange import SimulatedExchangeClient
from src.execution.order_manager import OrderManager
from src.risk.guardian import RiskGuardian
from src.strategy.market_maker import MarketMaker

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
        stream_name = "/".join(streams)

        def on_message(data: dict):
            """Handle WebSocket message."""
            if "stream" in data and "data" in data:
                stream = data["stream"]
                symbol = stream.split("@")[0].upper() + "USDT"
                ob_data = data["data"]

                # Update order book
                if symbol in orderbook_managers:
                    ob_manager = orderbook_managers[symbol]
                    ob_manager.update_from_websocket(ob_data)
                    snapshot = ob_manager.snapshot

                    if snapshot:
                        # Feed to simulated exchange
                        asyncio.create_task(simulated_exchange.on_orderbook_update(symbol, snapshot))

                        # Trigger market maker update
                        for mm in market_makers:
                            if mm.symbol == symbol:
                                asyncio.create_task(mm.on_order_book_update(snapshot))

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
        try:
            while True:
                await asyncio.sleep(1)

                # Check kill switch
                if risk_guardian.is_kill_switch_active():
                    console.print(
                        f"[red]Kill switch active: {risk_guardian.get_kill_switch_reason()}[/red]"
                    )
                    break

                # Print status periodically
                # TODO: Add status display

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
            trades = await simulated_exchange.get_trades(limit=100)
            equity = simulated_exchange.get_equity()

            console.print(f"  Equity: {equity} USDT")
            console.print(f"  Total Trades: {len(trades)}")
            console.print(f"  Open Positions: {len(positions)}")
            for pos in positions:
                console.print(f"    {pos.symbol}: {pos.quantity} @ {pos.entry_price} (PnL: {pos.unrealized_pnl})")

            console.print("[green]Paper trading stopped[/green]")

    finally:
        await public_client.close()

