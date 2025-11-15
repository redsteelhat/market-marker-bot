"""Domain models for market maker bot.

All models are exchange-agnostic and use Pydantic for validation.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    """Order side enumeration."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type enumeration."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderStatus(str, Enum):
    """Order status enumeration."""

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Order(BaseModel):
    """Order model - exchange agnostic."""

    order_id: Optional[str] = Field(None, description="Exchange order ID")
    client_order_id: Optional[str] = Field(None, description="Client order ID")
    symbol: str = Field(..., description="Trading symbol (e.g., BTCUSDT)")
    side: OrderSide = Field(..., description="Order side (BUY/SELL)")
    order_type: OrderType = Field(OrderType.LIMIT, description="Order type")
    quantity: Decimal = Field(..., description="Order quantity")
    price: Optional[Decimal] = Field(None, description="Order price (for limit orders)")
    status: OrderStatus = Field(OrderStatus.NEW, description="Order status")
    filled_quantity: Decimal = Field(Decimal("0"), description="Filled quantity")
    filled_price: Optional[Decimal] = Field(None, description="Average fill price")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Order timestamp")
    update_time: Optional[datetime] = Field(None, description="Last update timestamp")

    @property
    def notional(self) -> Decimal:
        """Calculate order notional value."""
        if self.price:
            return self.quantity * self.price
        return Decimal("0")

    @property
    def filled_notional(self) -> Decimal:
        """Calculate filled notional value."""
        if self.filled_price:
            return self.filled_quantity * self.filled_price
        return Decimal("0")

    @property
    def is_open(self) -> bool:
        """Check if order is still open."""
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)


class Trade(BaseModel):
    """Trade (fill) model."""

    trade_id: str = Field(..., description="Trade ID")
    order_id: str = Field(..., description="Related order ID")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(..., description="Trade side")
    quantity: Decimal = Field(..., description="Trade quantity")
    price: Decimal = Field(..., description="Trade price")
    fee: Decimal = Field(Decimal("0"), description="Trade fee")
    fee_asset: str = Field("USDT", description="Fee asset")
    timestamp: datetime = Field(..., description="Trade timestamp")
    is_maker: bool = Field(False, description="Whether trade was maker or taker")

    @property
    def notional(self) -> Decimal:
        """Calculate trade notional value."""
        return self.quantity * self.price


class Position(BaseModel):
    """Position model for a symbol."""

    symbol: str = Field(..., description="Trading symbol")
    quantity: Decimal = Field(Decimal("0"), description="Position quantity (positive=long, negative=short)")
    entry_price: Optional[Decimal] = Field(None, description="Average entry price")
    mark_price: Optional[Decimal] = Field(None, description="Current mark price")
    unrealized_pnl: Decimal = Field(Decimal("0"), description="Unrealized PnL")
    realized_pnl: Decimal = Field(Decimal("0"), description="Realized PnL")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    @property
    def notional(self) -> Decimal:
        """Calculate position notional value."""
        if self.mark_price:
            return abs(self.quantity) * self.mark_price
        elif self.entry_price:
            return abs(self.quantity) * self.entry_price
        return Decimal("0")

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        """Check if position is flat."""
        return self.quantity == 0


class Quote(BaseModel):
    """Quote model for bid/ask prices and sizes."""

    symbol: str = Field(..., description="Trading symbol")
    bid_price: Decimal = Field(..., description="Bid price")
    bid_size: Decimal = Field(..., description="Bid size")
    ask_price: Decimal = Field(..., description="Ask price")
    ask_size: Decimal = Field(..., description="Ask size")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Quote timestamp")

    @property
    def mid_price(self) -> Decimal:
        """Calculate mid price."""
        return (self.bid_price + self.ask_price) / 2

    @property
    def spread(self) -> Decimal:
        """Calculate absolute spread."""
        return self.ask_price - self.bid_price

    @property
    def spread_bps(self) -> Decimal:
        """Calculate spread in basis points."""
        if self.mid_price and self.mid_price > 0:
            return (self.spread / self.mid_price) * Decimal("10000")
        return Decimal("0")


class OrderBookLevel(BaseModel):
    """Single level in order book."""

    price: Decimal = Field(..., description="Price level")
    quantity: Decimal = Field(..., description="Quantity at this level")


class OrderBookSnapshot(BaseModel):
    """Order book snapshot model."""

    symbol: str = Field(..., description="Trading symbol")
    bids: list[OrderBookLevel] = Field(default_factory=list, description="Bid levels")
    asks: list[OrderBookLevel] = Field(default_factory=list, description="Ask levels")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Snapshot timestamp")

    @property
    def best_bid(self) -> Optional[Decimal]:
        """Get best bid price."""
        if self.bids:
            return self.bids[0].price
        return None

    @property
    def best_ask(self) -> Optional[Decimal]:
        """Get best ask price."""
        if self.asks:
            return self.asks[0].price
        return None

    @property
    def mid_price(self) -> Optional[Decimal]:
        """Calculate mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[Decimal]:
        """Calculate absolute spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_bps(self) -> Optional[Decimal]:
        """Calculate spread in basis points."""
        if self.mid_price and self.mid_price > 0 and self.spread:
            return (self.spread / self.mid_price) * Decimal("10000")
        return None


class PnLState(BaseModel):
    """PnL state model for tracking performance."""

    # Spread PnL
    spread_pnl: Decimal = Field(Decimal("0"), description="Spread PnL (gross)")
    spread_pnl_net: Decimal = Field(Decimal("0"), description="Net spread PnL (after fees)")

    # Inventory PnL
    inventory_pnl: Decimal = Field(Decimal("0"), description="Inventory PnL (mark-to-market)")

    # Commission costs
    maker_commission: Decimal = Field(Decimal("0"), description="Total maker commission")
    taker_commission: Decimal = Field(Decimal("0"), description="Total taker commission")

    # Slippage cost
    slippage_cost: Decimal = Field(Decimal("0"), description="Total slippage cost")

    # Funding PnL (for perpetuals)
    funding_pnl: Decimal = Field(Decimal("0"), description="Funding PnL")

    # Net PnL
    net_pnl: Decimal = Field(Decimal("0"), description="Net PnL")

    # Equity tracking
    initial_equity: Decimal = Field(..., description="Initial equity")
    current_equity: Decimal = Field(..., description="Current equity")
    peak_equity: Decimal = Field(..., description="Peak equity")
    drawdown: Decimal = Field(Decimal("0"), description="Current drawdown")
    drawdown_pct: Decimal = Field(Decimal("0"), description="Current drawdown percentage")

    # Daily tracking
    daily_realized_pnl: Decimal = Field(Decimal("0"), description="Daily realized PnL")
    daily_trades: int = Field(0, description="Daily trade count")
    daily_volume: Decimal = Field(Decimal("0"), description="Daily trading volume")

    # Timestamps
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")
    daily_reset_time: Optional[datetime] = Field(None, description="Daily reset timestamp")

    def update_equity(self, new_equity: Decimal) -> None:
        """Update equity and recalculate drawdown."""
        self.current_equity = new_equity
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity
        self.drawdown = self.peak_equity - self.current_equity
        if self.peak_equity > 0:
            self.drawdown_pct = (self.drawdown / self.peak_equity) * Decimal("100")


class RiskLimits(BaseModel):
    """Risk limits model for a symbol."""

    symbol: str = Field(..., description="Trading symbol")
    max_net_notional: Decimal = Field(..., description="Max net notional limit")
    max_gross_notional: Decimal = Field(..., description="Max gross notional limit")
    current_net_notional: Decimal = Field(Decimal("0"), description="Current net notional")
    current_gross_notional: Decimal = Field(Decimal("0"), description="Current gross notional")

    @property
    def net_notional_utilization(self) -> Decimal:
        """Calculate net notional utilization percentage."""
        if self.max_net_notional > 0:
            return (abs(self.current_net_notional) / self.max_net_notional) * Decimal("100")
        return Decimal("0")

    @property
    def gross_notional_utilization(self) -> Decimal:
        """Calculate gross notional utilization percentage."""
        if self.max_gross_notional > 0:
            return (self.current_gross_notional / self.max_gross_notional) * Decimal("100")
        return Decimal("0")


class SymbolConfig(BaseModel):
    """Symbol-specific configuration."""

    symbol: str = Field(..., description="Trading symbol")
    tick_size: Decimal = Field(..., description="Price tick size")
    min_quantity: Decimal = Field(..., description="Minimum order quantity")
    min_notional: Decimal = Field(..., description="Minimum order notional")
    base_asset: str = Field(..., description="Base asset (e.g., BTC)")
    quote_asset: str = Field(..., description="Quote asset (e.g., USDT)")
    contract_type: str = Field("PERPETUAL", description="Contract type (SPOT/PERPETUAL)")

