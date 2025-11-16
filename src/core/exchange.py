"""Exchange client interface for abstraction.

This module defines the exchange client interface that can be implemented
by real exchanges (Binance) or simulated exchanges (paper trading).
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from src.core.models import Order, Trade, Position, OrderBookSnapshot


class IExchangeClient(ABC):
    """Interface for exchange clients (real or simulated)."""

    @abstractmethod
    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBookSnapshot:
        """Get order book snapshot.

        Args:
            symbol: Trading symbol
            limit: Number of levels

        Returns:
            Order book snapshot
        """
        pass

    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit an order.

        Args:
            order: Order to submit

        Returns:
            Submitted order with order_id
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel
            symbol: Trading symbol

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            Number of orders canceled
        """
        pass

    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open orders
        """
        pass

    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Get current positions.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of positions
        """
        pass

    @abstractmethod
    async def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> List[Trade]:
        """Get recent trades.

        Args:
            symbol: Optional symbol filter
            limit: Maximum number of trades

        Returns:
            List of trades
        """
        pass

    async def close(self) -> None:
        """Close client connection (if needed)."""
        pass

