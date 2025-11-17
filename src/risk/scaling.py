"""Risk scaling engine for dynamic position sizing.

This module implements volatility-based and drawdown-based risk scaling
to dynamically adjust position sizes, spreads, and quote frequencies
based on market conditions.
"""

import logging
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Deque, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RiskScalingEngine:
    """Risk scaling engine that computes risk multipliers based on ATR and drawdown."""

    def __init__(
        self,
        atr_length: int = 14,
        dd_lookback_hours: int = 240,
        vol_low: float = 0.5,
        vol_high: float = 2.0,
        dd_soft: float = 0.05,
        dd_hard: float = 0.15,
        risk_min: float = 0.1,
        risk_max: float = 2.0,
        initial_equity: Decimal = Decimal("200.0"),
    ):
        """Initialize risk scaling engine.

        Args:
            atr_length: ATR calculation period
            dd_lookback_hours: Drawdown lookback window in hours
            vol_low: Low volatility threshold (ATR multiplier)
            vol_high: High volatility threshold (ATR multiplier)
            dd_soft: Soft drawdown threshold (5% = 0.05)
            dd_hard: Hard drawdown threshold (15% = 0.15)
            risk_min: Minimum risk multiplier
            risk_max: Maximum risk multiplier
            initial_equity: Initial equity for drawdown calculation
        """
        self.atr_length = atr_length
        self.dd_lookback_hours = dd_lookback_hours
        self.vol_low = vol_low
        self.vol_high = vol_high
        self.dd_soft = dd_soft
        self.dd_hard = dd_hard
        self.risk_min = risk_min
        self.risk_max = risk_max

        # Price series for ATR calculation
        # Each element: {"high": Decimal, "low": Decimal, "close": Decimal, "timestamp": datetime}
        self.price_series: Deque[dict] = deque(maxlen=atr_length * 3)

        # Equity series for drawdown calculation
        # Each element: (timestamp, equity)
        self.equity_series: Deque[Tuple[datetime, Decimal]] = deque()

        # Track peak equity
        self.equity_peak: Optional[Decimal] = None
        self.initial_equity = initial_equity

        # Current risk multiplier
        self.current_multiplier: float = 1.0

    def update_price(self, high: Decimal, low: Decimal, close: Decimal, timestamp: Optional[datetime] = None) -> None:
        """Update price series for ATR calculation.

        Args:
            high: High price
            low: Low price
            close: Close price
            timestamp: Optional timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        self.price_series.append({
            "high": high,
            "low": low,
            "close": close,
            "timestamp": timestamp,
        })

    def update_equity(self, equity: Decimal, timestamp: Optional[datetime] = None) -> None:
        """Update equity series for drawdown calculation.

        Args:
            equity: Current equity
            timestamp: Optional timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        self.equity_series.append((timestamp, equity))

        # Update peak
        if self.equity_peak is None or equity > self.equity_peak:
            self.equity_peak = equity

        # Prune old equity data
        cutoff_time = timestamp - timedelta(hours=self.dd_lookback_hours)
        while self.equity_series and self.equity_series[0][0] < cutoff_time:
            self.equity_series.popleft()

    def compute_atr(self) -> Optional[Decimal]:
        """Compute Average True Range (ATR).

        Returns:
            ATR value or None if insufficient data
        """
        if len(self.price_series) < self.atr_length + 1:
            return None

        trs: List[Decimal] = []
        prev_close: Optional[Decimal] = None

        # Get last (atr_length + 1) bars
        bars = list(self.price_series)[-(self.atr_length + 1):]

        for bar in bars:
            if prev_close is None:
                prev_close = bar["close"]
                continue

            high = bar["high"]
            low = bar["low"]
            close = bar["close"]

            # True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            trs.append(tr)
            prev_close = close

        if not trs:
            return None

        # Use EMA for ATR (TradingView compatible)
        # First value is simple average, then EMA
        if len(trs) == 1:
            return trs[0]
        
        # Initial value: simple average of first period
        initial_period = min(self.atr_length, len(trs))
        atr = sum(trs[:initial_period]) / Decimal(initial_period)
        
        # EMA smoothing factor
        alpha = Decimal("2") / Decimal(str(self.atr_length + 1))
        
        # Apply EMA to remaining TRs
        for tr in trs[initial_period:]:
            atr = alpha * tr + (Decimal("1") - alpha) * atr
        
        return atr

    def compute_drawdown(self) -> float:
        """Compute maximum drawdown in lookback window.

        Returns:
            Maximum drawdown as fraction (e.g., 0.12 = 12%)
        """
        if not self.equity_series:
            return 0.0

        # Use peak from lookback window
        peak = self.equity_series[0][1]
        max_dd = 0.0

        for _, equity in self.equity_series:
            if equity > peak:
                peak = equity

            if peak > 0:
                dd = float((peak - equity) / peak)
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    def vol_multiplier(self, atr: Decimal, current_price: Decimal) -> float:
        """Compute volatility-based multiplier.

        Args:
            atr: ATR value
            current_price: Current price for normalization

        Returns:
            Multiplier (0.5 to 1.5 range typically)
        """
        if atr is None or current_price == 0:
            return 1.0

        # Normalize ATR by price to get percentage
        atr_pct = float(atr / current_price) * 100.0  # Convert to percentage

        # Use ATR percentage thresholds
        # vol_low and vol_high are already in percentage terms (e.g., 0.5% = 0.5)
        if atr_pct < self.vol_low:
            return 1.5  # Low volatility - be more aggressive
        elif atr_pct > self.vol_high:
            return 0.5  # High volatility - be defensive
        else:
            # Linear interpolation between thresholds
            if self.vol_high == self.vol_low:
                return 1.0
            t = (atr_pct - self.vol_low) / (self.vol_high - self.vol_low)
            return 1.5 - t * 1.0  # Interpolate from 1.5 to 0.5

    def dd_multiplier(self, dd: float) -> float:
        """Compute drawdown-based multiplier.

        Args:
            dd: Drawdown as fraction (e.g., 0.12 = 12%)

        Returns:
            Multiplier (0.1 to 1.0 range)
        """
        if dd <= self.dd_soft:
            return 1.0

        if dd >= self.dd_hard:
            return 0.1  # Almost stop - only reduce risk

        # Linear interpolation between soft and hard thresholds
        t = (dd - self.dd_soft) / (self.dd_hard - self.dd_soft)
        return 1.0 - t * 0.9  # From 1.0 to 0.1

    def compute_risk_multiplier(self, current_price: Decimal) -> float:
        """Compute overall risk multiplier.

        Args:
            current_price: Current price for ATR normalization

        Returns:
            Risk multiplier (clamped between risk_min and risk_max)
        """
        # Compute ATR
        atr = self.compute_atr()

        # Compute drawdown
        dd = self.compute_drawdown()

        # Compute multipliers
        m_vol = self.vol_multiplier(atr, current_price) if atr else 1.0
        m_dd = self.dd_multiplier(dd)

        # Combine multipliers
        risk = m_vol * m_dd

        # Clamp
        risk = max(self.risk_min, min(self.risk_max, risk))

        self.current_multiplier = risk

        # Log periodically
        if len(self.equity_series) % 100 == 0:  # Every 100 updates
            logger.debug(
                f"Risk multiplier: {risk:.3f} (ATR: {atr}, DD: {dd:.2%}, vol_mult: {m_vol:.2f}, dd_mult: {m_dd:.2f})"
            )

        return risk

    def is_risk_off(self, threshold: float = 0.3) -> bool:
        """Check if we're in risk-off mode.

        Args:
            threshold: Risk multiplier threshold below which we enter risk-off mode

        Returns:
            True if in risk-off mode
        """
        return self.current_multiplier < threshold

    def get_spread_multiplier(self) -> float:
        """Get spread multiplier based on risk.

        When risk is low, widen spread to reduce exposure.

        Returns:
            Spread multiplier (1.0 = normal, higher = wider spread)
        """
        # Inverse relationship: low risk_mult → wider spread
        # risk_mult = 1.0 → spread_mult = 1.0
        # risk_mult = 0.1 → spread_mult = 2.0 (example)
        if self.current_multiplier <= 0:
            return 2.0

        # Linear: spread_mult = 1 + (1 - risk_mult)
        spread_mult = 1.0 + (1.0 - self.current_multiplier)
        return max(1.0, min(3.0, spread_mult))  # Clamp between 1.0 and 3.0

