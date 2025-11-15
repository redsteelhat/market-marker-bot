"""Binance Futures API client for REST API calls.

This module provides HTTP client functionality for Binance Futures API,
including authentication, rate limiting, and error handling.
"""

import hashlib
import hmac
import time
from typing import Optional
import httpx
from src.core.config import ExchangeConfig
from src.core.models import Order, OrderSide, OrderType, OrderStatus, Position, SymbolConfig


class BinanceClient:
    """Binance Futures API client."""

    def __init__(self, config: ExchangeConfig):
        """Initialize Binance client.

        Args:
            config: Exchange configuration with API credentials
        """
        self.config = config
        self.base_url = config.base_url
        self.api_key = config.api_key
        self.api_secret = config.api_secret
        self.testnet = config.testnet

        # Create HTTP client with timeout
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(10.0),
            headers={"X-MBX-APIKEY": self.api_key} if self.api_key else {},
        )

    def _generate_signature(self, params: dict) -> str:
        """Generate HMAC SHA256 signature for authenticated requests.

        Args:
            params: Request parameters

        Returns:
            Signature string
        """
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _get_auth_params(self, params: Optional[dict] = None) -> dict:
        """Add authentication parameters to request.

        Args:
            params: Existing parameters

        Returns:
            Parameters with timestamp and signature
        """
        if params is None:
            params = {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._generate_signature(params)
        return params

    async def get_orderbook(self, symbol: str, limit: int = 20) -> dict:
        """Get order book snapshot.

        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            limit: Number of levels (5, 10, 20, 50, 100, 500, 1000)

        Returns:
            Order book data
        """
        response = await self.client.get(
            "/fapi/v1/depth",
            params={"symbol": symbol, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    async def get_ticker(self, symbol: str) -> dict:
        """Get 24h ticker price statistics.

        Args:
            symbol: Trading symbol

        Returns:
            Ticker data
        """
        response = await self.client.get(
            "/fapi/v1/ticker/24hr",
            params={"symbol": symbol},
        )
        response.raise_for_status()
        return response.json()

    async def get_positions(self, symbol: Optional[str] = None) -> list[dict]:
        """Get current positions.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of positions
        """
        params = {}
        if symbol:
            params["symbol"] = symbol

        auth_params = self._get_auth_params(params)
        response = await self.client.get(
            "/fapi/v2/positionRisk",
            params=auth_params,
        )
        response.raise_for_status()
        return response.json()

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """Get all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open orders
        """
        params = {}
        if symbol:
            params["symbol"] = symbol

        auth_params = self._get_auth_params(params)
        response = await self.client.get(
            "/fapi/v1/openOrders",
            params=auth_params,
        )
        response.raise_for_status()
        return response.json()

    async def place_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        time_in_force: str = "GTC",
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Place a limit order.

        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            quantity: Order quantity
            price: Order price
            time_in_force: Time in force (GTC, IOC, FOK)
            client_order_id: Optional client order ID

        Returns:
            Order response
        """
        params = {
            "symbol": symbol,
            "side": side.value,
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": time_in_force,
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        auth_params = self._get_auth_params(params)
        response = await self.client.post(
            "/fapi/v1/order",
            params=auth_params,
        )
        response.raise_for_status()
        return response.json()

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Cancel an order.

        Args:
            symbol: Trading symbol
            order_id: Exchange order ID
            client_order_id: Client order ID

        Returns:
            Cancel response
        """
        params = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["origClientOrderId"] = client_order_id

        auth_params = self._get_auth_params(params)
        response = await self.client.delete(
            "/fapi/v1/order",
            params=auth_params,
        )
        response.raise_for_status()
        return response.json()

    async def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Cancel response
        """
        params = {"symbol": symbol}
        auth_params = self._get_auth_params(params)
        response = await self.client.delete(
            "/fapi/v1/allOpenOrders",
            params=auth_params,
        )
        response.raise_for_status()
        return response.json()

    async def get_order_status(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Get order status.

        Args:
            symbol: Trading symbol
            order_id: Exchange order ID
            client_order_id: Client order ID

        Returns:
            Order status
        """
        params = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["origClientOrderId"] = client_order_id

        auth_params = self._get_auth_params(params)
        response = await self.client.get(
            "/fapi/v1/order",
            params=auth_params,
        )
        response.raise_for_status()
        return response.json()

    async def get_exchange_info(self) -> dict:
        """Get exchange information (symbols, filters, etc.).

        Returns:
            Exchange information
        """
        response = await self.client.get("/fapi/v1/exchangeInfo")
        response.raise_for_status()
        return response.json()

    async def get_symbol_config(self, symbol: str) -> Optional[SymbolConfig]:
        """Get symbol configuration.

        Args:
            symbol: Trading symbol

        Returns:
            Symbol configuration or None if not found
        """
        exchange_info = await self.get_exchange_info()
        for symbol_info in exchange_info.get("symbols", []):
            if symbol_info["symbol"] == symbol:
                filters = {f["filterType"]: f for f in symbol_info.get("filters", [])}
                price_filter = filters.get("PRICE_FILTER", {})
                lot_size_filter = filters.get("LOT_SIZE_FILTER", {})
                min_notional_filter = filters.get("MIN_NOTIONAL", {})

                return SymbolConfig(
                    symbol=symbol,
                    tick_size=float(price_filter.get("tickSize", "0.01")),
                    min_quantity=float(lot_size_filter.get("minQty", "0.001")),
                    min_notional=float(min_notional_filter.get("minNotional", "5.0")),
                    base_asset=symbol_info.get("baseAsset", ""),
                    quote_asset=symbol_info.get("quoteAsset", ""),
                    contract_type=symbol_info.get("contractType", "PERPETUAL"),
                )
        return None

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

