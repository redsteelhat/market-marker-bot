"""Comprehensive system test script."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from decimal import Decimal

print("=" * 70)
print("COMPREHENSIVE SYSTEM TEST")
print("=" * 70)

# Test results
results = {
    "passed": [],
    "failed": [],
    "warnings": []
}

def test(name, func):
    """Run a test and record result."""
    try:
        func()
        results["passed"].append(name)
        print(f"[PASS] {name}")
        return True
    except Exception as e:
        results["failed"].append((name, str(e)))
        print(f"[FAIL] {name}: {e}")
        return False

# 1. Module Import Tests
print("\n1. MODULE IMPORT TESTS")
print("-" * 70)

test("Core imports", lambda: __import__("src.core"))
test("Data imports", lambda: __import__("src.data"))
test("Execution imports", lambda: __import__("src.execution"))
test("Risk imports", lambda: __import__("src.risk"))
test("Strategy imports", lambda: __import__("src.strategy"))
test("Apps imports", lambda: __import__("src.apps"))

# 2. Config Loading Tests
print("\n2. CONFIG LOADING TESTS")
print("-" * 70)

from src.core.config import Settings

def test_config():
    s = Settings.from_env()
    assert s.environment == "dev"
    assert s.bot_equity_usdt > 0
    assert len(s.symbols) > 0
    assert s.exchange.base_url
    assert s.strategy.base_spread_bps > 0
    assert s.risk.daily_loss_limit_pct > 0

test("Config loading", test_config)

# 3. Model Tests
print("\n3. MODEL TESTS")
print("-" * 70)

from src.core.models import Order, OrderSide, Position, Quote, OrderBookSnapshot, OrderBookLevel

def test_order_model():
    o = Order(symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.001"), price=Decimal("50000"))
    assert o.notional == Decimal("50")
    assert o.is_open is True

def test_position_model():
    p = Position(symbol="BTCUSDT", quantity=Decimal("0.1"), entry_price=Decimal("50000"), mark_price=Decimal("51000"), unrealized_pnl=Decimal("100"))
    assert p.notional == Decimal("5100")
    assert p.is_long is True

def test_quote_model():
    q = Quote(symbol="BTCUSDT", bid_price=Decimal("49900"), bid_size=Decimal("0.001"), ask_price=Decimal("50100"), ask_size=Decimal("0.001"))
    assert q.mid_price == Decimal("50000")
    assert q.spread_bps == Decimal("40")

test("Order model", test_order_model)
test("Position model", test_position_model)
test("Quote model", test_quote_model)

# 4. Pricing Engine Tests
print("\n4. PRICING ENGINE TESTS")
print("-" * 70)

from src.strategy.pricing import PricingEngine
from src.core.config import StrategyConfig

def test_pricing_engine():
    config = StrategyConfig()
    engine = PricingEngine(config)
    snapshot = OrderBookSnapshot(
        symbol="BTCUSDT",
        bids=[OrderBookLevel(price=Decimal("49900"), quantity=Decimal("0.1"))],
        asks=[OrderBookLevel(price=Decimal("50100"), quantity=Decimal("0.1"))],
    )
    quote = engine.compute_quote(snapshot, Decimal("0"))
    assert quote.bid_price < quote.ask_price
    assert quote.bid_price < snapshot.mid_price
    assert quote.ask_price > snapshot.mid_price

test("Pricing engine", test_pricing_engine)

# 5. Inventory Manager Tests
print("\n5. INVENTORY MANAGER TESTS")
print("-" * 70)

from src.strategy.inventory import InventoryManager

def test_inventory_manager():
    config = StrategyConfig()
    mgr = InventoryManager(config, Decimal("200"))
    pos = Position(symbol="BTCUSDT", quantity=Decimal("0.01"), entry_price=Decimal("50000"), mark_price=Decimal("50000"))
    # Just test that methods don't crash
    mgr.is_within_soft_band(pos)
    mgr.is_within_hard_limit(pos)
    mgr.should_quote_bid(pos)
    mgr.should_quote_ask(pos)

test("Inventory manager", test_inventory_manager)

# 6. Risk Module Tests
print("\n6. RISK MODULE TESTS")
print("-" * 70)

from src.risk.guardian import RiskGuardian
from src.risk.limits import RiskLimitsChecker
from src.risk.metrics import RiskMetrics
from src.core.config import RiskConfig

def test_risk_guardian():
    config = RiskConfig()
    guardian = RiskGuardian(config, Decimal("200"))
    assert guardian.is_kill_switch_active() is False
    guardian.trigger_kill_switch("Test")
    assert guardian.is_kill_switch_active() is True
    guardian.reset_kill_switch()
    assert guardian.is_kill_switch_active() is False

def test_risk_limits():
    config = RiskConfig()
    checker = RiskLimitsChecker(config, Decimal("200"))
    from src.core.models import PnLState
    pnl = PnLState(initial_equity=Decimal("200"), current_equity=Decimal("198"), peak_equity=Decimal("200"), daily_realized_pnl=Decimal("-2.1"))
    is_violated, reason = checker.check_daily_loss_limit(pnl)
    assert is_violated is True

def test_risk_metrics():
    returns = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01")]
    sharpe = RiskMetrics.calculate_sharpe_ratio(returns)
    assert sharpe is not None
    equity = [Decimal("200"), Decimal("210"), Decimal("190")]
    dd, dd_pct = RiskMetrics.calculate_max_drawdown(equity)
    assert dd > 0

test("Risk guardian", test_risk_guardian)
test("Risk limits", test_risk_limits)
test("Risk metrics", test_risk_metrics)

# 7. Data Module Tests
print("\n7. DATA MODULE TESTS")
print("-" * 70)

from src.data.orderbook import OrderBookManager

def test_orderbook_manager():
    mgr = OrderBookManager("BTCUSDT")
    data = {
        "bids": [["49900", "0.1"], ["49800", "0.2"]],
        "asks": [["50100", "0.1"], ["50200", "0.2"]],
    }
    mgr.update_from_binance(data)
    assert mgr.snapshot is not None
    assert mgr.get_best_bid() == Decimal("49900")
    assert mgr.get_best_ask() == Decimal("50100")
    assert mgr.get_mid_price() == Decimal("50000")

test("Orderbook manager", test_orderbook_manager)

# 8. Execution Module Tests
print("\n8. EXECUTION MODULE TESTS")
print("-" * 70)

from src.execution.routing import OrderRouter

def test_order_router():
    router = OrderRouter()
    # Just test that it can be instantiated
    assert router is not None

test("Order router", test_order_router)

# 9. Project Structure Tests
print("\n9. PROJECT STRUCTURE TESTS")
print("-" * 70)

def test_project_structure():
    required_dirs = [
        "src/core",
        "src/data",
        "src/strategy",
        "src/risk",
        "src/execution",
        "src/apps",
        "tests",
        "docs",
    ]
    for dir_path in required_dirs:
        assert Path(dir_path).exists(), f"Directory {dir_path} not found"

test("Project structure", test_project_structure)

# 10. Dependency Tests
print("\n10. DEPENDENCY TESTS")
print("-" * 70)

def test_dependencies():
    from importlib import import_module
    modules = ["httpx", "websockets", "pandas", "numpy", "pydantic", "pydantic_settings", "pytest", "typer", "rich"]
    for m in modules:
        try:
            import_module(m)
        except ImportError:
            raise ImportError(f"Module {m} not installed")

test("Dependencies", test_dependencies)

# Summary
print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)
print(f"Passed: {len(results['passed'])}")
print(f"Failed: {len(results['failed'])}")
print(f"Warnings: {len(results['warnings'])}")

if results["failed"]:
    print("\nFailed Tests:")
    for name, error in results["failed"]:
        print(f"  - {name}: {error}")
    sys.exit(1)
else:
    print("\nALL TESTS PASSED!")
    sys.exit(0)

