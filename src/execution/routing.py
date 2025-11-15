"""Order routing for market maker bot.

This module handles routing orders to the appropriate exchange/client.
"""

from typing import Dict, Optional
from src.core.models import Order
from src.data.binance_client import BinanceClient


class OrderRouter:
    """Routes orders to appropriate exchange clients."""

    def __init__(self):
        """Initialize order router."""
        self.clients: Dict[str, BinanceClient] = {}  # symbol -> client

    def register_client(self, symbol: str, client: BinanceClient) -> None:
        """Register a client for a symbol.

        Args:
            symbol: Trading symbol
            client: Binance client
        """
        self.clients[symbol] = client

    def get_client(self, symbol: str) -> Optional[BinanceClient]:
        """Get client for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Binance client or None if not found
        """
        return self.clients.get(symbol)

    def route_order(self, order: Order) -> Optional[BinanceClient]:
        """Route an order to appropriate client.

        Args:
            order: Order to route

        Returns:
            Binance client or None if not found
        """
        return self.get_client(order.symbol)

    def has_client(self, symbol: str) -> bool:
        """Check if client exists for symbol.

        Args:
            symbol: Trading symbol

        Returns:
            True if client exists, False otherwise
        """
        return symbol in self.clients

