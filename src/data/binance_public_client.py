"""Binance public data client (no authentication required).

This client only uses public endpoints for market data.
No API key or KYC required.
"""

import httpx
from typing import Optional
from src.core.exchange import IExchangeClient
from src.core.models import Order, Trade, Position, OrderBookSnapshot, OrderBookLevel
from datetime import datetime
from decimal import Decimal


class BinancePublicClient(IExchangeClient):
    """Binance public data client - only market data, no trading."""

    def __init__(self, base_url: str = "https://api.binance.com"):
        """Initialize public client.

        Args:
            base_url: Binance API base URL (default: spot API)
        """
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10.0))

    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBookSnapshot:
        """Get order book snapshot from public endpoint.

        Args:
            symbol: Trading symbol
            limit: Number of levels (5, 10, 20, 50, 100, 500, 1000)

        Returns:
            Order book snapshot
        """
        response = await self.client.get(
            "/api/v3/depth",
            params={"symbol": symbol, "limit": limit},
        )
        response.raise_for_status()
        data = response.json()

        bids = [
            OrderBookLevel(price=Decimal(str(level[0])), quantity=Decimal(str(level[1])))
            for level in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=Decimal(str(level[0])), quantity=Decimal(str(level[1])))
            for level in data.get("asks", [])
        ]

        return OrderBookSnapshot(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.utcnow(),
        )

    async def get_ticker(self, symbol: str) -> dict:
        """Get 24h ticker price statistics.

        Args:
            symbol: Trading symbol

        Returns:
            Ticker data
        """
        response = await self.client.get(
            "/api/v3/ticker/24hr",
            params={"symbol": symbol},
        )
        response.raise_for_status()
        return response.json()

    async def submit_order(self, order: Order) -> Order:
        """Public client does not support order submission.

        Raises:
            NotImplementedError: Always raised
        """
        raise NotImplementedError("Public client does not support order submission. Use SimulatedExchangeClient for paper trading.")

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Public client does not support order cancellation.

        Raises:
            NotImplementedError: Always raised
        """
        raise NotImplementedError("Public client does not support order cancellation. Use SimulatedExchangeClient for paper trading.")

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Public client does not support order cancellation.

        Raises:
            NotImplementedError: Always raised
        """
        raise NotImplementedError("Public client does not support order cancellation. Use SimulatedExchangeClient for paper trading.")

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[Order]:
        """Public client has no open orders.

        Returns:
            Empty list
        """
        return []

    async def get_positions(self, symbol: Optional[str] = None) -> list[Position]:
        """Public client has no positions.

        Returns:
            Empty list
        """
        return []

    async def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> list[Trade]:
        """Get recent trades from public endpoint.

        Args:
            symbol: Trading symbol
            limit: Maximum number of trades

        Returns:
            List of trades
        """
        if not symbol:
            return []

        response = await self.client.get(
            "/api/v3/trades",
            params={"symbol": symbol, "limit": limit},
        )
        response.raise_for_status()
        data = response.json()

        from src.core.models import OrderSide

        trades = []
        for trade_data in data:
            trade = Trade(
                trade_id=str(trade_data["id"]),
                order_id="",  # Public trades don't have order_id
                symbol=symbol,
                side=OrderSide.BUY if trade_data["isBuyerMaker"] else OrderSide.SELL,
                quantity=Decimal(str(trade_data["qty"])),
                price=Decimal(str(trade_data["price"])),
                fee=Decimal("0"),  # Public data doesn't include fees
                timestamp=datetime.fromtimestamp(trade_data["time"] / 1000),
                is_maker=trade_data.get("isBuyerMaker", False),
            )
            trades.append(trade)

        return trades

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

