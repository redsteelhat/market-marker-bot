"""
Parameter sweep / grid search for strategy calibration.

Runs backtests across a grid of (base_spread_bps, order_notional_pct) and ranks results.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from typing import Iterable, List, Tuple

from src.core.config import Settings
from src.backtest.engine import BacktestEngine


@dataclass
class SweepConfig:
    symbols: List[str]
    base_spread_bps_values: List[int]
    order_notional_pct_values: List[float]
    max_runs: int = 50


async def run_one(symbol: str, base_spread_bps: int, order_notional_pct: float) -> Tuple[dict, dict]:
    # Build settings override
    settings = Settings()
    settings.symbols = [symbol]
    settings.strategy.base_spread_bps = base_spread_bps
    settings.strategy.order_notional_pct = order_notional_pct

    engine = BacktestEngine(settings=settings)
    results = await engine.run(symbol)  # assumes returns dict with metrics
    return ({
        "symbol": symbol,
        "base_spread_bps": base_spread_bps,
        "order_notional_pct": order_notional_pct,
    }, results)


async def sweep(cfg: SweepConfig) -> None:
    runs = list(product(cfg.symbols, cfg.base_spread_bps_values, cfg.order_notional_pct_values))
    if len(runs) > cfg.max_runs:
        runs = runs[: cfg.max_runs]

    results: List[Tuple[dict, dict]] = []
    for symbol, spread, size_pct in runs:
        params, res = await run_one(symbol, spread, size_pct)
        results.append((params, res))

    # Rank by Net PnL, then Sharpe, then Max Drawdown (ascending)
    def score(item: Tuple[dict, dict]) -> Tuple[Decimal, Decimal, Decimal]:
        params, res = item
        net_pnl = Decimal(str(res.get("net_pnl", "0")))
        sharpe = Decimal(str(res.get("sharpe", "0")))
        mdd = Decimal(str(res.get("max_drawdown_pct", "0")))
        return (net_pnl, sharpe, -mdd)

    ranked = sorted(results, key=score, reverse=True)

    print("\nTop 5 configurations:")
    for i, (params, res) in enumerate(ranked[:5], start=1):
        print(f"{i}. {params} -> net_pnl={res.get('net_pnl')}, sharpe={res.get('sharpe')}, mdd%={res.get('max_drawdown_pct')}")


if __name__ == "__main__":
    cfg = SweepConfig(
        symbols=["BTCUSDT"],
        base_spread_bps_values=[4, 6, 8, 10, 12],
        order_notional_pct_values=[0.005, 0.01, 0.015, 0.02],
        max_runs=20,
    )
    asyncio.run(sweep(cfg))


