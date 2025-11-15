"""Configuration management using Pydantic Settings.

This module handles loading configuration from environment variables
and provides type-safe configuration objects.
"""

from typing import Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    order_notional_pct: float = Field(0.0075, description="Order notional as % of bot equity (0.5-1.0%)")
    min_order_notional: float = Field(10.0, description="Minimum order notional in USDT")
    max_order_notional_pct: float = Field(0.025, description="Max order notional as % of bot equity (2-3%)")
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
    exchange_api_key: str = Field("", description="Exchange API key")
    exchange_api_secret: str = Field("", description="Exchange API secret")
    exchange_api_passphrase: Optional[str] = Field(None, description="Exchange API passphrase")
    exchange_base_url: str = Field("https://fapi.binance.com", description="Exchange base URL")
    exchange_ws_url: Optional[str] = Field("wss://fstream.binance.com", description="WebSocket URL")
    exchange_testnet: bool = Field(False, description="Use testnet environment")

    @property
    def exchange(self) -> ExchangeConfig:
        """Get exchange configuration."""
        return ExchangeConfig(
            api_key=self.exchange_api_key,
            api_secret=self.exchange_api_secret,
            api_passphrase=self.exchange_api_passphrase,
            base_url=self.exchange_base_url,
            ws_url=self.exchange_ws_url,
            testnet=self.exchange_testnet,
        )

    # Strategy configuration
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)

    # Risk configuration
    risk: RiskConfig = Field(default_factory=RiskConfig)

    # Trading symbols
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])

    # Logging
    log_level: str = Field("INFO", description="Logging level")
    log_file: Optional[str] = Field(None, description="Log file path")

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        return cls()

