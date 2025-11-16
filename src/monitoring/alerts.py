"""Alerting and post-trade checks.

This module evaluates snapshots/metrics and triggers alerts on anomalies:
- Excessive cancel-to-trade ratio
- Low fill ratio
- Abnormal slippage (placeholder)
- Daily loss and drawdown soft alerts (kill switch remains in RiskGuardian)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from src.monitoring.metrics import SystemSnapshot


logger = logging.getLogger(__name__)


@dataclass
class AlertThresholds:
    min_fill_ratio: Decimal = Decimal("0.05")          # 5%
    max_cancel_to_trade: Decimal = Decimal("50")       # 50:1
    max_slippage_ticks: int = 3                        # placeholder
    soft_daily_loss_pct: Decimal = Decimal("0.005")    # 0.5% soft alert
    soft_drawdown_pct: Decimal = Decimal("0.10")       # 10% soft alert


class AlertManager:
    """Evaluates post-trade metrics and raises alerts."""

    def __init__(
        self,
        thresholds: Optional[AlertThresholds] = None,
        notify: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.thresholds = thresholds or AlertThresholds()
        # notify is a callback to route alerts (e.g., console, webhook)
        self.notify = notify or (lambda msg: logger.warning(msg))

    def _alert(self, message: str) -> None:
        try:
            self.notify(message)
        except Exception as e:
            logger.error(f"Alert notify failed: {e}")

    def evaluate(self, snapshot: SystemSnapshot) -> None:
        """Evaluate a snapshot and emit alerts if needed."""
        # Fill ratio
        if snapshot.fill_ratio is not None:
            try:
                if snapshot.fill_ratio < self.thresholds.min_fill_ratio:
                    self._alert(
                        f"Low fill ratio: {snapshot.fill_ratio:.3f} < {self.thresholds.min_fill_ratio}"
                    )
            except Exception:
                pass

        # Cancel-to-trade ratio
        if snapshot.cancel_to_trade_ratio is not None:
            try:
                if snapshot.cancel_to_trade_ratio > self.thresholds.max_cancel_to_trade:
                    self._alert(
                        f"High cancel-to-trade ratio: {snapshot.cancel_to_trade_ratio:.1f} > {self.thresholds.max_cancel_to_trade}"
                    )
            except Exception:
                pass

        # Soft daily loss alert (RiskGuardian still enforces hard)
        try:
            if snapshot.daily_pnl is not None and snapshot.initial_equity is not None:
                loss_pct = (snapshot.daily_pnl / snapshot.initial_equity) if snapshot.initial_equity != 0 else Decimal("0")
                if loss_pct < Decimal("0") and abs(loss_pct) >= self.thresholds.soft_daily_loss_pct:
                    self._alert(
                        f"Soft daily loss alert: {loss_pct * Decimal('100'):.2f}% (threshold {self.thresholds.soft_daily_loss_pct * Decimal('100'):.2f}%)"
                    )
        except Exception:
            pass

        # Soft drawdown alert
        try:
            if snapshot.max_drawdown_pct is not None:
                if snapshot.max_drawdown_pct >= self.thresholds.soft_drawdown_pct:
                    self._alert(
                        f"Soft drawdown alert: {snapshot.max_drawdown_pct * Decimal('100'):.2f}% ≥ {self.thresholds.soft_drawdown_pct * Decimal('100'):.2f}%"
                    )
        except Exception:
            pass

        # Slippage placeholder (needs slippage calculation in snapshot for real use)
        # if snapshot.avg_slippage_ticks and snapshot.avg_slippage_ticks > self.thresholds.max_slippage_ticks:
        #     self._alert(f"Abnormal slippage: {snapshot.avg_slippage_ticks} ticks > {self.thresholds.max_slippage_ticks}")


