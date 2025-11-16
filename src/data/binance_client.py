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
from src.core.exchange import IExchangeClient
from src.core.models import Order, OrderSide, OrderType, OrderStatus, Position, SymbolConfig, Trade, OrderBookSnapshot


class BinanceClient(IExchangeClient):
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

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[Order]:
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
        data = response.json()

        # Parse using order manager's parser
        from src.execution.order_manager import OrderManager
        temp_manager = OrderManager(self)
        orders = [temp_manager._parse_order_response(order_data) for order_data in data]
        return [o for o in orders if o.is_open]

    async def submit_order(self, order: Order) -> Order:
        """Submit an order (implements IExchangeClient).

        Args:
            order: Order to submit

        Returns:
            Submitted order with order_id
        """
        params = {
            "symbol": order.symbol,
            "side": order.side.value,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": float(order.quantity),
            "price": float(order.price) if order.price else None,
        }
        if order.client_order_id:
            params["newClientOrderId"] = order.client_order_id

        auth_params = self._get_auth_params(params)
        response = await self.client.post(
            "/fapi/v1/order",
            params=auth_params,
        )
        response.raise_for_status()
        data = response.json()

        # Update order with response
        from src.execution.order_manager import OrderManager
        temp_manager = OrderManager(self)
        submitted_order = temp_manager._parse_order_response(data)
        return submitted_order

    async def place_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        time_in_force: str = "GTC",
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Place a limit order (legacy method, use submit_order instead).

        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            quantity: Order quantity
            price: Order price
            time_in_force: Time in force (GTC, IOC, FOK)
            client_order_id: Optional client order ID

        Returns:
            Order response dict
        """
        from src.core.models import Order
        from decimal import Decimal

        order = Order(
            symbol=symbol,
            side=side,
            quantity=Decimal(str(quantity)),
            price=Decimal(str(price)),
            client_order_id=client_order_id,
        )
        submitted = await self.submit_order(order)
        
        # Return dict format for backward compatibility
        return {
            "orderId": int(submitted.order_id) if submitted.order_id and submitted.order_id.isdigit() else 0,
            "clientOrderId": submitted.client_order_id or "",
            "symbol": submitted.symbol,
            "side": submitted.side.value,
            "type": "LIMIT",
            "status": submitted.status.value,
            "origQty": str(submitted.quantity),
            "price": str(submitted.price) if submitted.price else "0",
            "executedQty": str(submitted.filled_quantity) if submitted.filled_quantity else "0",
            "time": int(submitted.timestamp.timestamp() * 1000) if submitted.timestamp else 0,
        }

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order (implements IExchangeClient).

        Args:
            order_id: Order ID to cancel
            symbol: Trading symbol

        Returns:
            True if successful, False otherwise
        """
        params = {"symbol": symbol, "orderId": order_id}
        auth_params = self._get_auth_params(params)
        
        try:
            response = await self.client.delete(
                "/fapi/v1/order",
                params=auth_params,
            )
            response.raise_for_status()
            return True
        except Exception:
            return False

    async def cancel_order_legacy(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Cancel an order (legacy method).

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

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders (implements IExchangeClient).

        Args:
            symbol: Optional symbol filter

        Returns:
            Number of orders canceled
        """
        if not symbol:
            # Cancel all orders for all symbols (not supported by Binance, return 0)
            return 0

        params = {"symbol": symbol}
        auth_params = self._get_auth_params(params)
        
        try:
            response = await self.client.delete(
                "/fapi/v1/allOpenOrders",
                params=auth_params,
            )
            response.raise_for_status()
            # Binance doesn't return count, so we need to check open orders before/after
            # For now, return 1 to indicate success
            return 1
        except Exception:
            return 0

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

