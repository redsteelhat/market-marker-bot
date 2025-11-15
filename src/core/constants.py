"""Constants and default values for market maker bot."""

from decimal import Decimal

# Spread defaults (in basis points)
DEFAULT_SPREAD_BPS = Decimal("8.0")  # 0.08% full spread
DEFAULT_MIN_SPREAD_BPS = Decimal("4.0")  # 0.04% minimum spread
DEFAULT_MAX_SPREAD_BPS = Decimal("30.0")  # 0.30% maximum spread

# Fee defaults (in basis points)
DEFAULT_MAKER_FEE_BPS = Decimal("2.0")  # 0.02% maker fee
DEFAULT_TAKER_FEE_BPS = Decimal("5.0")  # 0.05% taker fee
DEFAULT_FEE_DISCOUNT_FACTOR = Decimal("1.0")  # No discount by default

# Quote refresh defaults
DEFAULT_REFRESH_INTERVAL_MS = 1000  # 1 second
DEFAULT_MAX_QUOTE_AGE_MS = 2000  # 2 seconds
DEFAULT_PRICE_CHANGE_TRIGGER_BPS = Decimal("5.0")  # 0.05%

# Order size defaults
DEFAULT_ORDER_NOTIONAL_PCT = Decimal("0.0075")  # 0.75% of bot equity
DEFAULT_MIN_ORDER_NOTIONAL = Decimal("10.0")  # 10 USDT
DEFAULT_MAX_ORDER_NOTIONAL_PCT = Decimal("0.025")  # 2.5% of bot equity

# Inventory defaults
DEFAULT_TARGET_INVENTORY = Decimal("0.0")  # Delta-neutral
DEFAULT_INVENTORY_SOFT_BAND_PCT = Decimal("0.20")  # ±20% of bot equity
DEFAULT_INVENTORY_HARD_LIMIT_PCT = Decimal("0.30")  # ±30% of bot equity
DEFAULT_INVENTORY_SKEW_STRENGTH = Decimal("1.2")  # Skew strength

# Risk limits defaults
DEFAULT_MAX_NET_NOTIONAL_PCT_PER_SYMBOL = Decimal("0.30")  # 30% of bot equity
DEFAULT_MAX_GROSS_NOTIONAL_PCT_PER_SYMBOL = Decimal("0.60")  # 60% of bot equity
DEFAULT_MAX_TOTAL_NET_NOTIONAL_PCT = Decimal("0.50")  # 50% of bot equity

# Loss limits defaults
DEFAULT_DAILY_LOSS_LIMIT_PCT = Decimal("0.01")  # 1% of bot equity
DEFAULT_MAX_DRAWDOWN_SOFT_PCT = Decimal("0.10")  # 10% soft limit
DEFAULT_MAX_DRAWDOWN_HARD_PCT = Decimal("0.15")  # 15% hard limit

# Order limits defaults
DEFAULT_MAX_OPEN_ORDERS_PER_SYMBOL = 4
DEFAULT_MAX_NEW_ORDERS_PER_SECOND = 10
DEFAULT_MAX_CANCELS_PER_SECOND = 10
DEFAULT_MAX_CANCEL_TO_TRADE_RATIO = Decimal("50.0")  # 50:1

# Price band defaults
DEFAULT_MAX_PRICE_DISTANCE_FROM_BEST_PCT = Decimal("0.005")  # 0.5%

# Volatility defaults
DEFAULT_VOL_SPREAD_FACTOR = Decimal("1.0")
DEFAULT_VOLATILITY_WINDOW_MINUTES = 30  # 30-minute realized volatility

# Slippage defaults (in ticks)
DEFAULT_MAKER_SLIPPAGE_TICKS = Decimal("0.5")  # 0-1 tick for maker
DEFAULT_TAKER_SLIPPAGE_TICKS = Decimal("2.0")  # 1-3 ticks for taker

# Performance metric thresholds
SHARPE_TARGET_MIN = Decimal("1.0")  # Minimum Sharpe ratio target
SHARPE_TARGET_GOOD = Decimal("1.5")  # Good Sharpe ratio
SHARPE_ALARM_THRESHOLD = Decimal("0.5")  # Alarm if Sharpe < 0.5

# Fill ratio thresholds
MIN_FILL_RATIO = Decimal("0.05")  # Minimum acceptable fill ratio (5%)
MAX_FILL_RATIO = Decimal("0.95")  # Maximum fill ratio (too aggressive)

# TCA thresholds
MAX_SLIPPAGE_BPS = Decimal("3.0")  # 3 bps max acceptable slippage
MAX_EFFECTIVE_SPREAD_BPS = Decimal("10.0")  # 10 bps max effective spread

# Binance-specific defaults
BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
BINANCE_FUTURES_WS_URL = "wss://fstream.binance.com"
BINANCE_SPOT_BASE_URL = "https://api.binance.com"
BINANCE_SPOT_WS_URL = "wss://stream.binance.com:9443"

# Default symbols
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# Logging defaults
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

