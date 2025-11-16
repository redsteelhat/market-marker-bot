"""Order book management and snapshot handling.

This module provides order book snapshot management, mid price calculation,
and spread computation.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from src.core.models import OrderBookSnapshot, OrderBookLevel


class OrderBookManager:
    """Manages order book snapshots and provides utility methods."""

    def __init__(self, symbol: str):
        """Initialize order book manager.

        Args:
            symbol: Trading symbol
        """
        self.symbol = symbol
        self.snapshot: Optional[OrderBookSnapshot] = None
        self.last_update: Optional[datetime] = None

    def update_from_binance(self, data: dict) -> None:
        """Update order book from Binance API response.

        Args:
            data: Order book data from Binance API
        """
        bids = [
            OrderBookLevel(price=Decimal(str(level[0])), quantity=Decimal(str(level[1])))
            for level in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=Decimal(str(level[0])), quantity=Decimal(str(level[1])))
            for level in data.get("asks", [])
        ]

        self.snapshot = OrderBookSnapshot(
            symbol=self.symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.utcnow(),
        )
        self.last_update = datetime.utcnow()

    def update_from_websocket(self, update: dict) -> None:
        """Update order book from WebSocket stream.

        Args:
            update: WebSocket update data
        """
        if not self.snapshot:
            # Need initial snapshot first
            return

        # Handle partial book depth update
        bids = update.get("b", [])  # Binance uses 'b' for bids
        asks = update.get("a", [])  # Binance uses 'a' for asks

        # Update bid levels
        for level in bids:
            price = Decimal(str(level[0]))
            quantity = Decimal(str(level[1]))
            if quantity == 0:
                # Remove level
                self.snapshot.bids = [b for b in self.snapshot.bids if b.price != price]
            else:
                # Update or add level
                existing = next((b for b in self.snapshot.bids if b.price == price), None)
                if existing:
                    existing.quantity = quantity
                else:
                    self.snapshot.bids.append(OrderBookLevel(price=price, quantity=quantity))
                    # Sort bids descending
                    self.snapshot.bids.sort(key=lambda x: x.price, reverse=True)

        # Update ask levels
        for level in asks:
            price = Decimal(str(level[0]))
            quantity = Decimal(str(level[1]))
            if quantity == 0:
                # Remove level
                self.snapshot.asks = [a for a in self.snapshot.asks if a.price != price]
            else:
                # Update or add level
                existing = next((a for a in self.snapshot.asks if a.price == price), None)
                if existing:
                    existing.quantity = quantity
                else:
                    self.snapshot.asks.append(OrderBookLevel(price=price, quantity=quantity))
                    # Sort asks ascending
                    self.snapshot.asks.sort(key=lambda x: x.price)

        self.snapshot.timestamp = datetime.utcnow()
        self.last_update = datetime.utcnow()

    def update_from_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """Update order book from snapshot.

        Args:
            snapshot: Order book snapshot
        """
        self.snapshot = snapshot
        self.last_update = snapshot.timestamp

    def get_best_bid(self) -> Optional[Decimal]:
        """Get best bid price.

        Returns:
            Best bid price or None
        """
        if self.snapshot and self.snapshot.best_bid:
            return self.snapshot.best_bid
        return None

    def get_best_ask(self) -> Optional[Decimal]:
        """Get best ask price.

        Returns:
            Best ask price or None
        """
        if self.snapshot and self.snapshot.best_ask:
            return self.snapshot.best_ask
        return None

    def get_mid_price(self) -> Optional[Decimal]:
        """Get mid price.

        Returns:
            Mid price or None
        """
        if self.snapshot:
            return self.snapshot.mid_price
        return None

    def get_spread(self) -> Optional[Decimal]:
        """Get absolute spread.

        Returns:
            Spread or None
        """
        if self.snapshot:
            return self.snapshot.spread
        return None

    def get_spread_bps(self) -> Optional[Decimal]:
        """Get spread in basis points.

        Returns:
            Spread in bps or None
        """
        if self.snapshot:
            return self.snapshot.spread_bps
        return None

    def get_depth(self, side: str, levels: int = 5) -> list[OrderBookLevel]:
        """Get order book depth for a side.

        Args:
            side: 'bid' or 'ask'
            levels: Number of levels to return

        Returns:
            List of order book levels
        """
        if not self.snapshot:
            return []

        if side.lower() == "bid":
            return self.snapshot.bids[:levels]
        elif side.lower() == "ask":
            return self.snapshot.asks[:levels]
        return []

    def get_total_liquidity(self, side: str, price_range_pct: Decimal = Decimal("0.01")) -> Decimal:
        """Get total liquidity within price range.

        Args:
            side: 'bid' or 'ask'
            price_range_pct: Price range as percentage (e.g., 0.01 for 1%)

        Returns:
            Total liquidity in quote asset
        """
        if not self.snapshot:
            return Decimal("0")

        mid = self.get_mid_price()
        if not mid:
            return Decimal("0")

        if side.lower() == "bid":
            levels = self.snapshot.bids
            price_limit = mid * (Decimal("1") - price_range_pct)
        else:
            levels = self.snapshot.asks
            price_limit = mid * (Decimal("1") + price_range_pct)

        total = Decimal("0")
        for level in levels:
            if side.lower() == "bid" and level.price < price_limit:
                break
            if side.lower() == "ask" and level.price > price_limit:
                break
            total += level.quantity * level.price

        return total

    def is_stale(self, max_age_seconds: int = 5) -> bool:
        """Check if order book snapshot is stale.

        Args:
            max_age_seconds: Maximum age in seconds

        Returns:
            True if stale, False otherwise
        """
        if not self.last_update:
            return True

        age = (datetime.utcnow() - self.last_update).total_seconds()
        return age > max_age_seconds

