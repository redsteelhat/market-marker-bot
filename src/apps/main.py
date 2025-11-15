"""Main CLI application for market maker bot.

Usage:
    python -m src.apps.main run [--config CONFIG] [--dry-run]
    python -m src.apps.main status
    python -m src.apps.main stop
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.core.config import Settings
from src.core.models import PnLState
from src.data.binance_client import BinanceClient
from src.data.orderbook import OrderBookManager
from src.execution.order_manager import OrderManager
from src.risk.guardian import RiskGuardian
from src.strategy.market_maker import MarketMaker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="Market Maker Bot CLI")
console = Console()


@app.command()
def run(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run mode (no real orders)"),
    symbol: Optional[str] = typer.Option(None, "--symbol", "-s", help="Trading symbol (e.g., BTCUSDT)"),
):
    """Run the market maker bot."""
    console.print(Panel.fit("🚀 Starting Market Maker Bot", style="bold green"))
    
    try:
        # Load settings
        settings = Settings.from_env()
        
        if symbol:
            settings.symbols = [symbol]
        
        if not settings.symbols:
            console.print("[red]Error: No symbols configured. Use --symbol or set in config.[/red]")
            sys.exit(1)
        
        # Check API credentials
        if not settings.exchange_api_key or not settings.exchange_api_secret:
            console.print("[yellow]Warning: API credentials not found. Using testnet mode.[/yellow]")
            settings.exchange_testnet = True
        
        if dry_run:
            console.print("[yellow]⚠️  DRY RUN MODE: No real orders will be sent[/yellow]")
        
        # Run bot
        asyncio.run(_run_bot(settings, dry_run))
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Error running bot")
        sys.exit(1)


@app.command()
def status():
    """Show bot status."""
    console.print(Panel.fit("📊 Market Maker Bot Status", style="bold blue"))
    
    try:
        settings = Settings.from_env()
        
        # Create table
        table = Table(title="Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="magenta")
        
        table.add_row("Bot Equity", f"{settings.bot_equity_usdt} USDT")
        table.add_row("Environment", settings.environment)
        table.add_row("Testnet", "Yes" if settings.exchange_testnet else "No")
        table.add_row("Symbols", ", ".join(settings.symbols))
        table.add_row("Base Spread", f"{settings.strategy.base_spread_bps} bps")
        table.add_row("Refresh Interval", f"{settings.strategy.refresh_interval_ms} ms")
        table.add_row("Daily Loss Limit", f"{settings.risk.daily_loss_limit_pct * 100}%")
        table.add_row("Max Drawdown (Hard)", f"{settings.risk.max_drawdown_hard_pct * 100}%")
        
        console.print(table)
        
        # Try to connect and show market data
        console.print("\n[bold]Market Data:[/bold]")
        asyncio.run(_show_market_status(settings))
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Error getting status")
        sys.exit(1)


@app.command()
def stop():
    """Stop the bot (if running)."""
    console.print("[yellow]Stopping bot...[/yellow]")
    # TODO: Implement graceful shutdown
    console.print("[green]Bot stopped[/green]")


async def _run_bot(settings: Settings, dry_run: bool = False):
    """Run the market maker bot."""
    from decimal import Decimal
    
    console.print(f"[green]Initializing bot for symbols: {', '.join(settings.symbols)}[/green]")
    
    # Create clients
    exchange_config = settings.exchange
    client = BinanceClient(exchange_config)
    
    try:
        # Test connection
        console.print("[cyan]Testing connection...[/cyan]")
        exchange_info = await client.get_exchange_info()
        console.print(f"[green]✓ Connected. Found {len(exchange_info.get('symbols', []))} symbols[/green]")
        
        # Create order manager
        order_manager = OrderManager(client)
        
        # Create risk guardian
        risk_guardian = RiskGuardian(
            settings.risk, Decimal(str(settings.bot_equity_usdt))
        )
        
        # Create market makers for each symbol
        market_makers = []
        for symbol in settings.symbols:
            console.print(f"[cyan]Setting up market maker for {symbol}...[/cyan]")
            
            # Get symbol config
            symbol_config = await client.get_symbol_config(symbol)
            if not symbol_config:
                console.print(f"[yellow]Warning: Could not get config for {symbol}, skipping[/yellow]")
                continue
            
            # Create order book manager
            ob_manager = OrderBookManager(symbol)
            
            # Get initial order book
            try:
                orderbook_data = await client.get_orderbook(symbol, limit=20)
                ob_manager.update_from_binance(orderbook_data)
                console.print(f"[green]✓ Order book loaded for {symbol}[/green]")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not load order book for {symbol}: {e}[/yellow]")
                continue
            
            # Create market maker
            mm = MarketMaker(
                settings=settings,
                order_manager=order_manager,
                risk_guardian=risk_guardian,
                symbol=symbol,
                orderbook_manager=ob_manager,
            )
            
            market_makers.append(mm)
            console.print(f"[green]✓ Market maker ready for {symbol}[/green]")
        
        if not market_makers:
            console.print("[red]Error: No market makers could be initialized[/red]")
            return
        
        # Start all market makers
        console.print("[bold green]Starting market makers...[/bold green]")
        for mm in market_makers:
            await mm.start()
        
        console.print("[bold green]✓ Bot is running! Press Ctrl+C to stop.[/bold green]")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
                
                # Check kill switch
                if risk_guardian.is_kill_switch_active():
                    console.print(f"[red]⚠️  Kill switch active: {risk_guardian.get_kill_switch_reason()}[/red]")
                    break
                    
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping market makers...[/yellow]")
        finally:
            # Stop all market makers
            for mm in market_makers:
                await mm.stop()
            
            console.print("[green]✓ Bot stopped[/green]")
    
    finally:
        await client.close()


async def _show_market_status(settings: Settings):
    """Show market status."""
    exchange_config = settings.exchange
    client = BinanceClient(exchange_config)
    
    try:
        # Get order book for first symbol
        if settings.symbols:
            symbol = settings.symbols[0]
            try:
                orderbook_data = await client.get_orderbook(symbol, limit=5)
                ob_manager = OrderBookManager(symbol)
                ob_manager.update_from_binance(orderbook_data)
                snapshot = ob_manager.snapshot
                
                if snapshot:
                    table = Table(title=f"{symbol} Order Book")
                    table.add_column("Side", style="cyan")
                    table.add_column("Price", style="green")
                    table.add_column("Quantity", style="yellow")
                    
                    # Show best levels
                    for i, bid in enumerate(snapshot.bids[:3]):
                        table.add_row("BID", str(bid.price), str(bid.quantity))
                    table.add_row("", f"MID: {snapshot.mid_price}", "")
                    for i, ask in enumerate(snapshot.asks[:3]):
                        table.add_row("ASK", str(ask.price), str(ask.quantity))
                    
                    console.print(table)
                    console.print(f"Spread: {snapshot.spread} ({snapshot.spread_bps} bps)")
            except Exception as e:
                console.print(f"[yellow]Could not fetch market data: {e}[/yellow]")
    
    finally:
        await client.close()


if __name__ == "__main__":
    app()

