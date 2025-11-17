"""Configuration management using Pydantic Settings.

This module handles loading configuration from environment variables
and provides type-safe configuration objects.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    """Trading mode enumeration."""

    LIVE = "live"  # Real orders, real exchange
    PAPER_EXCHANGE = "paper_exchange"  # Local paper trading with live data
    DRY_RUN = "dry_run"  # No orders sent, logging only
    BACKTEST = "backtest"  # Offline backtest only


class ExchangeConfig(BaseModel):
    """Exchange API configuration."""

    api_key: str = Field(..., description="Exchange API key")
    api_secret: str = Field(..., description="Exchange API secret")
    api_passphrase: Optional[str] = Field(None, description="Exchange API passphrase (if required)")
    base_url: str = Field(..., description="Exchange base URL")
    ws_url: Optional[str] = Field(None, description="WebSocket URL")
    testnet: bool = Field(False, description="Use testnet environment")


class StrategyConfig(BaseModel):
    """Strategy parameters for market making."""

    # Spread parameters
    base_spread_bps: float = Field(8.0, description="Base spread in basis points (full spread)")
    min_spread_bps: float = Field(4.0, description="Minimum spread in basis points")
    max_spread_bps: float = Field(30.0, description="Maximum spread in basis points")
    vol_spread_factor: float = Field(1.0, description="Volatility spread adjustment factor")
    inventory_skew_strength: float = Field(1.2, description="Inventory skew strength (1.0-1.5)")

    # Order size parameters
    order_notional_pct: float = Field(0.01, description="Order notional as % of bot equity (1.0%)")
    min_order_notional: float = Field(2.0, description="Minimum order notional in USDT")
    max_order_notional_pct: float = Field(0.03, description="Max order notional as % of bot equity (3%)")
    dynamic_size_by_vol: bool = Field(True, description="Adjust order size by volatility")

    # Quote refresh parameters
    refresh_interval_ms: int = Field(1000, description="Quote refresh interval in milliseconds")
    max_quote_age_ms: int = Field(2000, description="Maximum quote age before re-quote")
    price_change_trigger_bps: float = Field(5.0, description="Price change trigger for immediate re-quote (bps)")

    # Inventory parameters
    target_inventory: float = Field(0.0, description="Target inventory (delta-neutral)")
    max_inventory_notional_pct_per_symbol: float = Field(
        0.30, description="Max inventory notional as % of bot equity per symbol"
    )
    inventory_soft_band_pct: float = Field(0.20, description="Inventory soft band as % of bot equity (±)")
    inventory_hard_limit_pct: float = Field(0.30, description="Inventory hard limit as % of bot equity (±)")

    # Trading horizon
    trading_horizon: str = Field("continuous", description="Trading horizon (continuous/daily)")
    daily_maintenance_window_minutes: int = Field(30, description="Daily maintenance window in minutes")
    flatten_on_shutdown: bool = Field(True, description="Flatten inventory on shutdown")
    flatten_on_hard_risk_event: bool = Field(True, description="Flatten inventory on hard risk event")


class RiskConfig(BaseModel):
    """Risk management parameters."""

    # Position limits
    max_net_notional_pct_per_symbol: float = Field(
        0.30, description="Max net notional as % of bot equity per symbol"
    )
    max_gross_notional_pct_per_symbol: float = Field(
        0.60, description="Max gross notional as % of bot equity per symbol"
    )
    max_total_net_notional_pct: float = Field(
        0.50, description="Max total net notional across all symbols as % of bot equity"
    )

    # Loss limits
    daily_loss_limit_pct: float = Field(0.01, description="Daily max loss as % of bot equity (1%)")
    max_drawdown_soft_pct: float = Field(0.10, description="Soft drawdown limit as % of bot equity (10%)")
    max_drawdown_hard_pct: float = Field(0.15, description="Hard drawdown limit as % of bot equity (15%)")

    # Order limits
    max_open_orders_per_symbol: int = Field(4, description="Max open orders per symbol")
    max_new_orders_per_second: int = Field(10, description="Max new orders per second (all symbols)")
    max_cancels_per_second: int = Field(10, description="Max cancels per second")
    max_cancel_to_trade_ratio: float = Field(50.0, description="Max cancel-to-trade ratio")

    # Price band
    max_price_distance_from_best_pct: float = Field(
        0.005, description="Max price distance from best bid/ask as % (0.5%)"
    )

    # Kill switch
    enable_kill_switch: bool = Field(True, description="Enable kill switch mechanism")
    kill_switch_on_api_errors: bool = Field(True, description="Trigger kill switch on persistent API errors")

    # Risk scaling (volatility and drawdown-based)
    enable_risk_scaling: bool = Field(True, description="Enable risk scaling based on ATR and drawdown")
    risk_scaling_atr_length: int = Field(14, description="ATR calculation period")
    risk_scaling_dd_lookback_hours: int = Field(240, description="Drawdown lookback window in hours")
    risk_scaling_vol_low: float = Field(0.5, description="Low volatility threshold (ATR multiplier)")
    risk_scaling_vol_high: float = Field(2.0, description="High volatility threshold (ATR multiplier)")
    risk_scaling_dd_soft: float = Field(0.05, description="Soft drawdown threshold (5% = 0.05)")
    risk_scaling_dd_hard: float = Field(0.15, description="Hard drawdown threshold (15% = 0.15)")
    risk_scaling_min: float = Field(0.1, description="Minimum risk multiplier")
    risk_scaling_max: float = Field(2.0, description="Maximum risk multiplier")
    risk_off_threshold: float = Field(0.3, description="Risk multiplier threshold for risk-off mode")


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    environment: str = Field("dev", description="Environment (dev/staging/prod)")

    # Bot equity
    bot_equity_usdt: float = Field(200.0, description="Bot equity in USDT")

    # Exchange configuration (loaded from env vars)
    # Support both old format and new BINANCE_FUTURES_* format
    exchange_api_key: str = Field("", description="Exchange API key (BINANCE_FUTURES_API_KEY_*)")
    exchange_api_secret: str = Field("", description="Exchange API secret (BINANCE_FUTURES_API_SECRET_*)")
    exchange_api_passphrase: Optional[str] = Field(None, description="Exchange API passphrase")
    exchange_base_url: str = Field("https://fapi.binance.com", description="Exchange base URL (BINANCE_FUTURES_*_BASE_URL)")
    exchange_ws_url: Optional[str] = Field("wss://fstream.binance.com", description="WebSocket URL (BINANCE_FUTURES_WS_*)")
    exchange_testnet: bool = Field(False, description="Use testnet environment (BINANCE_FUTURES_USE_TESTNET)")
    
    # New format env vars (will be mapped in property)
    binance_futures_use_testnet: bool = Field(False, description="Use Binance Futures testnet")
    binance_futures_api_key_testnet: str = Field("", description="Binance Futures testnet API key")
    binance_futures_api_secret_testnet: str = Field("", description="Binance Futures testnet API secret")
    binance_futures_api_key_mainnet: str = Field("", description="Binance Futures mainnet API key")
    binance_futures_api_secret_mainnet: str = Field("", description="Binance Futures mainnet API secret")
    binance_futures_mainnet_base_url: str = Field("https://fapi.binance.com", description="Binance Futures mainnet base URL")
    binance_futures_testnet_base_url: str = Field("https://demo-fapi.binance.com", description="Binance Futures testnet base URL")
    binance_futures_ws_market_mainnet: str = Field("wss://fstream.binance.com", description="Binance Futures mainnet WS market URL")
    binance_futures_ws_market_testnet: str = Field("wss://fstream.binancefuture.com", description="Binance Futures testnet WS market URL")
    
    # Trading mode
    trading_mode: TradingMode = Field(
        TradingMode.PAPER_EXCHANGE, description="Trading mode: live|paper_exchange|dry_run|backtest"
    )
    
    @field_validator("trading_mode", mode="before")
    @classmethod
    def normalize_trading_mode(cls, v):
        """Normalize trading mode (handle legacy 'paper' -> 'paper_exchange')."""
        if isinstance(v, str):
            if v == "paper":
                return TradingMode.PAPER_EXCHANGE
            try:
                return TradingMode(v)
            except ValueError:
                return TradingMode.PAPER_EXCHANGE
        return v
    
    # Default symbols
    default_symbols: str = Field("BTCUSDT,ETHUSDT", description="Default symbols (comma-separated)")

    @property
    def exchange(self) -> ExchangeConfig:
        """Get exchange configuration.
        
        Supports both old format (exchange_*) and new format (BINANCE_FUTURES_*).
        New format takes precedence.
        """
        # Use new format if available, otherwise fall back to old format
        use_testnet = self.binance_futures_use_testnet if self.binance_futures_use_testnet else self.exchange_testnet
        
        if use_testnet:
            api_key = self.binance_futures_api_key_testnet or self.exchange_api_key
            api_secret = self.binance_futures_api_secret_testnet or self.exchange_api_secret
            base_url = self.binance_futures_testnet_base_url or self.exchange_base_url
            ws_url = self.binance_futures_ws_market_testnet or self.exchange_ws_url
        else:
            api_key = self.binance_futures_api_key_mainnet or self.exchange_api_key
            api_secret = self.binance_futures_api_secret_mainnet or self.exchange_api_secret
            base_url = self.binance_futures_mainnet_base_url or self.exchange_base_url
            ws_url = self.binance_futures_ws_market_mainnet or self.exchange_ws_url
        
        return ExchangeConfig(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=self.exchange_api_passphrase,
            base_url=base_url,
            ws_url=ws_url,
            testnet=use_testnet,
        )

    # Strategy configuration
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)

    # Risk configuration
    risk: RiskConfig = Field(default_factory=RiskConfig)

    # Trading symbols (from DEFAULT_SYMBOLS env var or default)
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    
    @field_validator("symbols", mode="before")
    @classmethod
    def parse_symbols(cls, v):
        """Parse symbols from string or list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v
    
    @field_validator("default_symbols", mode="after")
    @classmethod
    def set_symbols_from_default(cls, v):
        """Return default_symbols value."""
        return v

    # Logging
    log_level: str = Field("INFO", description="Logging level")
    log_file: Optional[str] = Field(None, description="Log file path")
    
    # Backtest
    backtest_data_path: str = Field("data/backtest", description="Path to backtest data directory")
    backtest_start_date: Optional[str] = Field(None, description="Backtest start date (YYYY-MM-DD)")
    backtest_end_date: Optional[str] = Field(None, description="Backtest end date (YYYY-MM-DD)")

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        settings = cls()
        # Parse DEFAULT_SYMBOLS if provided and symbols not explicitly set
        if settings.default_symbols and (not settings.symbols or settings.symbols == ["BTCUSDT", "ETHUSDT"]):
            settings.symbols = [s.strip() for s in settings.default_symbols.split(",") if s.strip()]
        return settings

