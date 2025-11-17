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

from src.core.config import Settings, TradingMode
from src.core.models import PnLState
from src.data.binance_client import BinanceClient
from src.data.binance_public_client import BinancePublicClient
from src.data.orderbook import OrderBookManager
from src.execution.order_manager import OrderManager
from src.execution.simulated_exchange import SimulatedExchangeClient
from src.risk.guardian import RiskGuardian
from src.strategy.market_maker import MarketMaker
from src.apps.paper_trading import run_paper_trading
from src.monitoring.metrics import collect_snapshot, MetricsCollector
from src.utils.logging import setup_logging

# Setup logging (rich handler with symbol-safe format)
setup_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

app = typer.Typer(help="Market Maker Bot CLI - run, monitor, and calibrate the market maker")
console = Console()


@app.command(help="Run the market maker. Examples:\n  python -m src.apps.main run --mode paper_exchange --symbols BTCUSDT,ETHUSDT\n  python -m src.apps.main run -m backtest -s BTCUSDT --spread-bps 6 --order-notional-pct 0.01\n  python -m src.apps.main run -m backtest -s BTCUSDT --start-date 2024-01-01 --end-date 2024-01-07")
def run(
    mode: str = typer.Option("paper_exchange", "--mode", "-m", help="Trading mode: live|paper_exchange|dry_run|backtest"),
    symbol: Optional[str] = typer.Option(None, "--symbol", "-s", help="Single trading symbol (e.g., BTCUSDT)"),
    symbols: Optional[str] = typer.Option(None, "--symbols", help="Comma-separated symbols, e.g., BTCUSDT,ETHUSDT"),
    spread_bps: Optional[float] = typer.Option(None, "--spread-bps", help="Override base spread (bps, full spread)"),
    order_notional_pct: Optional[float] = typer.Option(None, "--order-notional-pct", help="Override order notional pct of bot equity (e.g., 0.01)"),
    refresh_ms: Optional[int] = typer.Option(None, "--refresh-ms", help="Override quote refresh interval (ms)"),
    bot_equity: Optional[float] = typer.Option(None, "--bot-equity", help="Override bot equity in USDT (e.g., 100)"),
    log_level: str = typer.Option("INFO", "--log-level", help="Log level: DEBUG|INFO|WARNING|ERROR"),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="Backtest start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="Backtest end date (YYYY-MM-DD)"),
):
    """Run the market maker bot."""
    # Set log level early
    try:
        logging.getLogger().setLevel(getattr(logging, log_level.upper()))
    except Exception:
        logging.getLogger().setLevel(logging.INFO)

    console.print(Panel.fit("Starting Market Maker Bot", style="bold green"))
    
    try:
        # Load settings
        settings = Settings.from_env()
        
        # Override trading mode
        try:
            settings.trading_mode = TradingMode(mode)
        except ValueError:
            console.print(f"[red]Invalid mode: {mode}. Use: live, paper_exchange, dry_run, or backtest[/red]")
            sys.exit(1)
        
        # Symbols override
        if symbols:
            settings.symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        elif symbol:
            settings.symbols = [symbol.strip().upper()]

        # Strategy overrides
        if spread_bps is not None:
            settings.strategy.base_spread_bps = float(spread_bps)
        if order_notional_pct is not None:
            settings.strategy.order_notional_pct = float(order_notional_pct)
        if refresh_ms is not None:
            settings.strategy.refresh_interval_ms = int(refresh_ms)
        if bot_equity is not None:
            settings.bot_equity_usdt = float(bot_equity)
        
        if not settings.symbols:
            console.print("[red]Error: No symbols configured. Use --symbol or set in config.[/red]")
            sys.exit(1)
        
        # Run based on mode
        if settings.trading_mode == TradingMode.PAPER_EXCHANGE:
            console.print("[green]Mode: Paper Exchange (Live Data + Local Simulation)[/green]")
            asyncio.run(run_paper_trading(settings))
        elif settings.trading_mode == TradingMode.LIVE:
            console.print("[yellow]Mode: Live Trading (Real Orders)[/yellow]")
            # Check API credentials
            if not settings.exchange.api_key or not settings.exchange.api_secret:
                console.print("[red]Error: API credentials required for live trading[/red]")
                sys.exit(1)
            asyncio.run(_run_bot(settings))
        elif settings.trading_mode == TradingMode.DRY_RUN:
            console.print("[yellow]Mode: Dry Run (No Orders)[/yellow]")
            asyncio.run(_run_bot(settings, dry_run=True))
        elif settings.trading_mode == TradingMode.BACKTEST:
            console.print("[cyan]Mode: Backtest[/cyan]")
            from src.backtest.engine import BacktestEngine
            from datetime import datetime
            
            engine = BacktestEngine(settings)
            symbol = settings.symbols[0] if settings.symbols else "BTCUSDT"
            
            # Parse dates from CLI args, config, or use None (load all data)
            start_date_parsed = None
            end_date_parsed = None
            
            if start_date_arg := (start_date or settings.backtest_start_date):
                try:
                    start_date_parsed = datetime.strptime(start_date_arg, "%Y-%m-%d")
                except ValueError:
                    console.print(f"[yellow]Invalid start date format: {start_date_arg}. Use YYYY-MM-DD[/yellow]")
            
            if end_date_arg := (end_date or settings.backtest_end_date):
                try:
                    end_date_parsed = datetime.strptime(end_date_arg, "%Y-%m-%d")
                    # Add one day to include the full end date
                    from datetime import timedelta
                    end_date_parsed = end_date_parsed + timedelta(days=1)
                except ValueError:
                    console.print(f"[yellow]Invalid end date format: {end_date_arg}. Use YYYY-MM-DD[/yellow]")
            
            if start_date_parsed or end_date_parsed:
                console.print(f"[dim]Date range: {start_date_parsed.date() if start_date_parsed else 'start'} to {end_date_parsed.date() if end_date_parsed else 'end'}[/dim]")
            else:
                console.print("[dim]No date range specified, loading all available data[/dim]")
            
            try:
                results = asyncio.run(engine.run(symbol, start_date_parsed, end_date_parsed))
                
                # Display results
                results_table = Table(title="Backtest Results", show_header=True)
                results_table.add_column("Metric", style="cyan")
                results_table.add_column("Value", style="magenta")
                
                results_table.add_row("Symbol", results["symbol"])
                results_table.add_row("Snapshots Processed", str(results["snapshots_processed"]))
                results_table.add_row("Initial Equity", f"{results['initial_equity']:.2f} USDT")
                results_table.add_row("Final Equity", f"{results['final_equity']:.2f} USDT")
                results_table.add_row("Total PnL", f"{results['total_pnl']:+.2f} USDT")
                results_table.add_row("Realized PnL", f"{results['realized_pnl']:+.2f} USDT")
                results_table.add_row("Unrealized PnL", f"{results['unrealized_pnl']:+.2f} USDT")
                results_table.add_row("Total Trades", str(results["total_trades"]))
                
                if results["max_drawdown"] > 0:
                    results_table.add_row("Max Drawdown", f"{results['max_drawdown']:.2f} USDT ({results['max_drawdown_pct']:.2f}%)")
                
                if results["sharpe_ratio"]:
                    results_table.add_row("Sharpe Ratio", f"{results['sharpe_ratio']:.2f}")
                
                if results["kill_switch_triggered"]:
                    results_table.add_row("Kill Switch", "[red]TRIGGERED[/red]")
                
                console.print(results_table)
            except FileNotFoundError as e:
                console.print(f"[red]Backtest data not found: {e}[/red]")
                console.print("[yellow]Please provide historical data in data/backtest/ directory[/yellow]")
                console.print("[dim]Expected format: {SYMBOL}_orderbook.csv with columns: timestamp,bid_price,bid_size,ask_price,ask_size[/dim]")
            except Exception as e:
                console.print(f"[red]Backtest error: {e}[/red]")
                logger.exception("Backtest error")
        else:
            console.print(f"[red]Unknown mode: {settings.trading_mode}[/red]")
            sys.exit(1)
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Error running bot")
        sys.exit(1)


@app.command(help="Quickstart paper trading with sensible defaults.")
def quickstart(
    symbols: str = typer.Option("BTCUSDT,ETHUSDT", "--symbols", "-s", help="Comma-separated symbols"),
    spread_bps: int = typer.Option(6, "--spread-bps", help="Base spread (bps, full spread)"),
    order_notional_pct: float = typer.Option(0.01, "--order-notional-pct", help="Order notional pct of bot equity"),
    refresh_ms: int = typer.Option(1000, "--refresh-ms", help="Quote refresh interval (ms)"),
    log_level: str = typer.Option("INFO", "--log-level", help="Log level: DEBUG|INFO|WARNING|ERROR"),
):
    """Run paper trading mode with common overrides in one command."""
    run(
        mode="paper_exchange",
        symbol=None,
        symbols=symbols,
        spread_bps=float(spread_bps),
        order_notional_pct=float(order_notional_pct),
        refresh_ms=int(refresh_ms),
        log_level=log_level,
    )


@app.command()
def status():
    """Show bot status with detailed metrics."""
    console.print(Panel.fit("Market Maker Bot Status", style="bold blue"))
    
    try:
        settings = Settings.from_env()
        
        # Configuration table
        config_table = Table(title="Configuration", show_header=True)
        config_table.add_column("Setting", style="cyan")
        config_table.add_column("Value", style="magenta")
        
        config_table.add_row("Bot Equity", f"{settings.bot_equity_usdt} USDT")
        config_table.add_row("Trading Mode", settings.trading_mode.value)
        config_table.add_row("Environment", settings.environment)
        config_table.add_row("Testnet", "Yes" if settings.exchange.testnet else "No")
        config_table.add_row("Symbols", ", ".join(settings.symbols))
        config_table.add_row("Base Spread", f"{settings.strategy.base_spread_bps} bps")
        config_table.add_row("Refresh Interval", f"{settings.strategy.refresh_interval_ms} ms")
        config_table.add_row("Daily Loss Limit", f"{settings.risk.daily_loss_limit_pct * 100}%")
        config_table.add_row("Max Drawdown (Hard)", f"{settings.risk.max_drawdown_hard_pct * 100}%")
        
        console.print(config_table)
        
        # Try to get runtime status if bot is running
        console.print("\n[bold]Runtime Status:[/bold]")
        asyncio.run(_show_runtime_status(settings))
        
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


@app.command(help="Show effective configuration (after environment and CLI overrides).")
def config_show():
    try:
        settings = Settings.from_env()
        table = Table(title="Effective Configuration", show_header=True)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="magenta")
        table.add_row("Mode", settings.trading_mode.value)
        table.add_row("Symbols", ", ".join(settings.symbols))
        table.add_row("Bot Equity (USDT)", str(settings.bot_equity_usdt))
        table.add_row("Base Spread (bps)", str(settings.strategy.base_spread_bps))
        table.add_row("Order Notional Pct", str(settings.strategy.order_notional_pct))
        table.add_row("Refresh Interval (ms)", str(settings.strategy.refresh_interval_ms))
        console.print(table)
    except Exception as e:
        console.print(f"[red]Error showing config: {e}[/red]")
        logger.exception("Config show error")
        sys.exit(1)


@app.command(help="Run parameter sweep for calibration (grid search).")
def sweep(
    symbols: str = typer.Option("BTCUSDT", "--symbols", "-s", help="Comma-separated symbols"),
    spreads: str = typer.Option("4,6,8,10,12", "--spreads", help="Comma-separated base_spread_bps values"),
    sizes: str = typer.Option("0.005,0.01,0.015,0.02", "--sizes", help="Comma-separated order_notional_pct values"),
    max_runs: int = typer.Option(20, "--max-runs", help="Maximum combinations to run"),
):
    """Run grid search across spread and size to rank configurations."""
    try:
        from scripts.parameter_sweep import SweepConfig, sweep as run_sweep
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        spread_vals = [int(x.strip()) for x in spreads.split(",") if x.strip()]
        size_vals = [float(x.strip()) for x in sizes.split(",") if x.strip()]
        cfg = SweepConfig(symbols=syms, base_spread_bps_values=spread_vals, order_notional_pct_values=size_vals, max_runs=max_runs)
        asyncio.run(run_sweep(cfg))
    except Exception as e:
        console.print(f"[red]Sweep error: {e}[/red]")
        logger.exception("Sweep error")
        sys.exit(1)


@app.command(help="Start web dashboard for monitoring bot performance.")
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host", help="Dashboard server host"),
    port: int = typer.Option(8000, "--port", help="Dashboard server port"),
    mode: str = typer.Option("paper_exchange", "--mode", "-m", help="Trading mode (for data connection)"),
):
    """Start web dashboard server."""
    console.print(Panel.fit("Starting Dashboard Server", style="bold blue"))
    console.print(f"[cyan]Dashboard will be available at: http://{host}:{port}[/cyan]")
    
    try:
        from src.apps.dashboard import run_dashboard_server
        
        # Load settings
        settings = Settings.from_env()
        
        # Try to get exchange and risk guardian if bot is running
        exchange = None
        risk_guardian = None
        risk_scaling_engines = None
        
        if mode == "paper_exchange":
            try:
                from src.execution.simulated_exchange import SimulatedExchangeClient
                from src.risk.guardian import RiskGuardian
                from decimal import Decimal
                
                exchange = SimulatedExchangeClient(
                    initial_equity=Decimal(str(settings.bot_equity_usdt))
                )
                risk_guardian = RiskGuardian(
                    settings.risk, Decimal(str(settings.bot_equity_usdt))
                )
                # Risk scaling engines would be passed from running market makers
                # For now, we'll just start the dashboard
            except Exception as e:
                console.print(f"[yellow]Warning: Could not initialize exchange client: {e}[/yellow]")
                console.print("[dim]Dashboard will start but may not have live data[/dim]")
        
        asyncio.run(run_dashboard_server(
            host=host,
            port=port,
            exchange=exchange,
            risk_guardian=risk_guardian,
            settings=settings,
            risk_scaling_engines=risk_scaling_engines,
        ))
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Dashboard error: {e}[/red]")
        logger.exception("Dashboard error")
        sys.exit(1)

async def _run_bot(settings: Settings, dry_run: bool = False):
    """Run bot in live mode (for future Binance TR integration)."""
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
                exchange=client,
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


async def _show_runtime_status(settings: Settings):
    """Show runtime status with detailed metrics."""
    from decimal import Decimal
    from src.data.binance_public_client import BinancePublicClient
    from src.execution.simulated_exchange import SimulatedExchangeClient
    from src.risk.guardian import RiskGuardian
    
    try:
        # Try to get status from simulated exchange (if paper trading was active)
        public_client = BinancePublicClient()
        simulated_exchange = SimulatedExchangeClient(
            initial_equity=Decimal(str(settings.bot_equity_usdt))
        )
        risk_guardian = RiskGuardian(settings.risk, Decimal(str(settings.bot_equity_usdt)))
        
        # Get current state
        positions = await simulated_exchange.get_positions()
        open_orders = await simulated_exchange.get_open_orders()
        trades = await simulated_exchange.get_trades(limit=100)
        
        # Collect snapshot
        snapshot = await collect_snapshot(
            exchange=simulated_exchange,
            risk_guardian=risk_guardian,
            positions=positions,
            open_orders=open_orders,
            trades=trades,
            initial_equity=Decimal(str(settings.bot_equity_usdt)),
        )
        
        # Display metrics
        metrics_table = Table(title="Performance Metrics", show_header=True)
        metrics_table.add_column("Metric", style="cyan")
        metrics_table.add_column("Value", style="magenta")
        
        metrics_table.add_row("Equity", f"{snapshot.equity:.2f} USDT")
        metrics_table.add_row("Total PnL", f"{snapshot.total_pnl:.2f} USDT")
        metrics_table.add_row("Realized PnL", f"{snapshot.realized_pnl:.2f} USDT")
        metrics_table.add_row("Unrealized PnL", f"{snapshot.unrealized_pnl:.2f} USDT")
        metrics_table.add_row("Daily PnL", f"{snapshot.daily_pnl:.2f} USDT")
        
        if snapshot.max_drawdown_pct > 0:
            metrics_table.add_row("Max Drawdown", f"{snapshot.max_drawdown:.2f} USDT ({snapshot.max_drawdown_pct:.2f}%)")
        
        if snapshot.sharpe_ratio:
            metrics_table.add_row("Sharpe Ratio (24h)", f"{snapshot.sharpe_ratio:.2f}")
        
        console.print(metrics_table)
        
        # Positions
        if positions:
            pos_table = Table(title="Open Positions", show_header=True)
            pos_table.add_column("Symbol", style="cyan")
            pos_table.add_column("Quantity", style="magenta")
            pos_table.add_column("Entry Price", style="yellow")
            pos_table.add_column("Mark Price", style="yellow")
            pos_table.add_column("PnL", style="green" if snapshot.unrealized_pnl >= 0 else "red")
            
            for pos in positions:
                pos_table.add_row(
                    pos.symbol,
                    f"{pos.quantity:.6f}",
                    f"{pos.entry_price:.2f}" if pos.entry_price else "N/A",
                    f"{pos.mark_price:.2f}" if pos.mark_price else "N/A",
                    f"{pos.unrealized_pnl:.2f} USDT",
                )
            
            console.print(pos_table)
        
        # Orders
        if open_orders:
            orders_table = Table(title="Open Orders", show_header=True)
            orders_table.add_column("Symbol", style="cyan")
            orders_table.add_column("Side", style="magenta")
            orders_table.add_column("Quantity", style="yellow")
            orders_table.add_column("Price", style="yellow")
            orders_table.add_column("Status", style="green")
            
            for order in open_orders[:10]:  # Show first 10
                orders_table.add_row(
                    order.symbol,
                    order.side.value,
                    f"{order.quantity:.6f}",
                    f"{order.price:.2f}" if order.price else "N/A",
                    order.status.value,
                )
            
            if len(open_orders) > 10:
                orders_table.add_row("...", f"{len(open_orders) - 10} more orders", "", "", "")
            
            console.print(orders_table)
        
        # Trading stats
        stats_table = Table(title="Trading Statistics", show_header=True)
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="magenta")
        
        stats_table.add_row("Total Trades", str(snapshot.total_trades))
        stats_table.add_row("Trades Today", str(snapshot.trades_today))
        stats_table.add_row("Open Orders", str(snapshot.open_orders_count))
        
        if snapshot.cancel_to_trade_ratio:
            stats_table.add_row("Cancel/Trade Ratio", f"{snapshot.cancel_to_trade_ratio:.2f}")
        
        console.print(stats_table)
        
        # Kill switch status
        if snapshot.kill_switch_active:
            console.print(f"\n[bold red]KILL SWITCH ACTIVE: {snapshot.kill_switch_reason}[/bold red]")
        else:
            console.print("\n[bold green]System Status: OK[/bold green]")
        
        # Market data
        symbol = settings.symbols[0] if settings.symbols else "BTCUSDT"
        try:
            orderbook = await public_client.get_orderbook(symbol, limit=5)
            
            market_table = Table(title=f"Market Data - {symbol}", show_header=True)
            market_table.add_column("Metric", style="cyan")
            market_table.add_column("Value", style="magenta")
            
            market_table.add_row("Best Bid", f"{orderbook.best_bid}")
            market_table.add_row("Best Ask", f"{orderbook.best_ask}")
            market_table.add_row("Mid Price", f"{orderbook.mid_price}")
            market_table.add_row("Spread", f"{orderbook.spread_bps:.2f} bps")
            
            console.print(market_table)
        except Exception as e:
            console.print(f"[yellow]Could not fetch market data: {e}[/yellow]")
        
        await public_client.close()
        
    except Exception as e:
        console.print(f"[yellow]Bot not running or could not get status: {e}[/yellow]")
        console.print("[dim]Start the bot with 'python -m src.apps.main run' to see runtime metrics[/dim]")


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

