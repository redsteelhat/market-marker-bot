"""Core module for market maker bot.

This module contains domain models, configuration, and constants.
"""

from src.core.config import Settings, StrategyConfig, RiskConfig, ExchangeConfig
from src.core.models import (
    Order,
    Trade,
    Position,
    Quote,
    OrderBookSnapshot,
    PnLState,
    RiskLimits,
    SymbolConfig,
)
from src.core.constants import (
    DEFAULT_SPREAD_BPS,
    DEFAULT_MIN_SPREAD_BPS,
    DEFAULT_MAX_SPREAD_BPS,
    DEFAULT_MAKER_FEE_BPS,
    DEFAULT_TAKER_FEE_BPS,
    DEFAULT_REFRESH_INTERVAL_MS,
)

__all__ = [
    "Settings",
    "StrategyConfig",
    "RiskConfig",
    "ExchangeConfig",
    "Order",
    "Trade",
    "Position",
    "Quote",
    "OrderBookSnapshot",
    "PnLState",
    "RiskLimits",
    "SymbolConfig",
    "DEFAULT_SPREAD_BPS",
    "DEFAULT_MIN_SPREAD_BPS",
    "DEFAULT_MAX_SPREAD_BPS",
    "DEFAULT_MAKER_FEE_BPS",
    "DEFAULT_TAKER_FEE_BPS",
    "DEFAULT_REFRESH_INTERVAL_MS",
]

