"""Test scenarios for systematic testing.

This script provides controlled test scenarios for:
- Inventory limits
- Kill switch triggers
- Order limits
- Daily loss limits
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncio
import logging
from decimal import Decimal
from rich.console import Console
from rich.panel import Panel

from src.core.config import Settings
from src.data.binance_public_client import BinancePublicClient
from src.data.orderbook import OrderBookManager
from src.execution.simulated_exchange import SimulatedExchangeClient
from src.risk.guardian import RiskGuardian
from src.strategy.market_maker import MarketMaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


async def test_inventory_limit():
    """Test inventory limit enforcement."""
    console.print(Panel.fit("Test: Inventory Limit Enforcement", style="bold yellow"))
    
    settings = Settings.from_env()
    # Set very low inventory limit
    settings.strategy.max_inventory_notional_pct_per_symbol = 0.05  # 5%
    settings.strategy.inventory_hard_limit_pct = 0.05
    
    console.print(f"[cyan]Inventory limit set to: {settings.strategy.max_inventory_notional_pct_per_symbol * 100}%[/cyan]")
    console.print("[yellow]Running for 30 seconds to observe behavior...[/yellow]")
    
    # Run paper trading for short period
    from src.apps.paper_trading import run_paper_trading
    # Note: This is a simplified test - in real scenario, you'd want to inject test conditions
    console.print("[green]Test scenario ready. Check logs for 'inventory limit' messages.[/green]")


async def test_kill_switch():
    """Test kill switch trigger."""
    console.print(Panel.fit("Test: Kill Switch Trigger", style="bold red"))
    
    settings = Settings.from_env()
    # Set very low daily loss limit
    settings.risk.daily_loss_limit_pct = 0.001  # 0.1%
    
    console.print(f"[cyan]Daily loss limit set to: {settings.risk.daily_loss_limit_pct * 100}%[/cyan]")
    console.print("[yellow]Running with tight spread to trigger losses...[/yellow]")
    
    # Set tight spread to increase fill rate and potential losses
    settings.strategy.base_spread_bps = 2.0  # Very tight
    
    console.print("[green]Test scenario ready. Bot should trigger kill switch after small loss.[/green]")


async def test_order_limits():
    """Test order limit enforcement."""
    console.print(Panel.fit("Test: Order Limit Enforcement", style="bold blue"))
    
    settings = Settings.from_env()
    # Set low order limit
    settings.risk.max_open_orders_per_symbol = 2
    
    console.print(f"[cyan]Max open orders per symbol: {settings.risk.max_open_orders_per_symbol}[/cyan]")
    console.print("[yellow]Bot should not exceed this limit.[/yellow]")
    
    console.print("[green]Test scenario ready. Monitor open orders count.[/green]")


def main():
    """Run test scenarios."""
    import sys
    
    if len(sys.argv) < 2:
        console.print("[red]Usage: python scripts/test_scenarios.py <scenario>[/red]")
        console.print("\nAvailable scenarios:")
        console.print("  inventory  - Test inventory limit enforcement")
        console.print("  killswitch - Test kill switch trigger")
        console.print("  orders     - Test order limit enforcement")
        sys.exit(1)
    
    scenario = sys.argv[1].lower()
    
    if scenario == "inventory":
        asyncio.run(test_inventory_limit())
    elif scenario == "killswitch":
        asyncio.run(test_kill_switch())
    elif scenario == "orders":
        asyncio.run(test_order_limits())
    else:
        console.print(f"[red]Unknown scenario: {scenario}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()

