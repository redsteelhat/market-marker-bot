"""Script to check environment configuration."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import Settings
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def main():
    """Check and display environment configuration."""
    console.print(Panel.fit("Environment Configuration Check", style="bold blue"))
    
    try:
        settings = Settings.from_env()
        
        # Main config table
        table = Table(title="Main Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="magenta")
        
        table.add_row("Environment", settings.environment)
        table.add_row("Trading Mode", settings.trading_mode)
        table.add_row("Bot Equity", f"{settings.bot_equity_usdt} USDT")
        table.add_row("Symbols", ", ".join(settings.symbols))
        
        console.print(table)
        
        # Exchange config table
        exchange_table = Table(title="Exchange Configuration")
        exchange_table.add_column("Setting", style="cyan")
        exchange_table.add_column("Value", style="magenta")
        exchange_table.add_column("Status", style="yellow")
        
        exchange = settings.exchange
        exchange_table.add_row("Testnet", "Yes" if exchange.testnet else "No", "OK" if exchange.testnet else "WARN")
        exchange_table.add_row("Base URL", exchange.base_url, "OK" if exchange.base_url else "FAIL")
        exchange_table.add_row("WS URL", exchange.ws_url or "Not set", "OK" if exchange.ws_url else "WARN")
        exchange_table.add_row("API Key", "Set" if exchange.api_key else "Not set", "OK" if exchange.api_key else "WARN")
        exchange_table.add_row("API Secret", "Set" if exchange.api_secret else "Not set", "OK" if exchange.api_secret else "WARN")
        
        console.print(exchange_table)
        
        # Strategy config
        strategy_table = Table(title="Strategy Configuration")
        strategy_table.add_column("Parameter", style="cyan")
        strategy_table.add_column("Value", style="magenta")
        
        strategy = settings.strategy
        strategy_table.add_row("Base Spread", f"{strategy.base_spread_bps} bps")
        strategy_table.add_row("Min Spread", f"{strategy.min_spread_bps} bps")
        strategy_table.add_row("Max Spread", f"{strategy.max_spread_bps} bps")
        strategy_table.add_row("Refresh Interval", f"{strategy.refresh_interval_ms} ms")
        strategy_table.add_row("Order Notional %", f"{strategy.order_notional_pct * 100}%")
        
        console.print(strategy_table)
        
        # Risk config
        risk_table = Table(title="Risk Configuration")
        risk_table.add_column("Parameter", style="cyan")
        risk_table.add_column("Value", style="magenta")
        
        risk = settings.risk
        risk_table.add_row("Daily Loss Limit", f"{risk.daily_loss_limit_pct * 100}%")
        risk_table.add_row("Max Drawdown (Soft)", f"{risk.max_drawdown_soft_pct * 100}%")
        risk_table.add_row("Max Drawdown (Hard)", f"{risk.max_drawdown_hard_pct * 100}%")
        risk_table.add_row("Max Net Notional/Symbol", f"{risk.max_net_notional_pct_per_symbol * 100}%")
        
        console.print(risk_table)
        
        # Warnings
        warnings = []
        if not exchange.api_key:
            warnings.append("WARNING: API Key not set - bot cannot connect to exchange")
        if not exchange.api_secret:
            warnings.append("WARNING: API Secret not set - bot cannot connect to exchange")
        if not exchange.testnet and exchange.api_key:
            warnings.append("WARNING: Using MAINNET - be careful with real funds!")
        
        if warnings:
            console.print("\n[bold yellow]Warnings:[/bold yellow]")
            for warning in warnings:
                console.print(f"  {warning}")
        else:
            console.print("\n[bold green]Configuration looks good![/bold green]")
        
        # Recommendations
        console.print("\n[bold cyan]Recommendations:[/bold cyan]")
        if not exchange.api_key:
            console.print("  1. Copy .env.example to .env: cp .env.example .env")
            console.print("  2. Add your Binance testnet API credentials")
            console.print("  3. Set BINANCE_FUTURES_USE_TESTNET=true for testing")
        
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())


if __name__ == "__main__":
    main()

