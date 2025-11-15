"""WebSocket client for Binance Futures streams.

This module provides WebSocket connections for market data (order book, trades)
and private streams (order updates, account updates).
"""

import asyncio
import json
import logging
from typing import Callable, Optional
import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    """WebSocket client for Binance Futures streams."""

    def __init__(
        self,
        ws_url: str,
        on_message: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        reconnect_interval: int = 5,
        heartbeat_interval: int = 30,
    ):
        """Initialize WebSocket client.

        Args:
            ws_url: WebSocket URL
            on_message: Callback for received messages
            on_error: Callback for errors
            reconnect_interval: Reconnect interval in seconds
            heartbeat_interval: Heartbeat interval in seconds
        """
        self.ws_url = ws_url
        self.on_message = on_message
        self.on_error = on_error
        self.reconnect_interval = reconnect_interval
        self.heartbeat_interval = heartbeat_interval

        self.ws: Optional[WebSocketClientProtocol] = None
        self.running = False
        self.reconnect_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None

    async def connect(self, stream: str) -> None:
        """Connect to WebSocket stream.

        Args:
            stream: Stream name (e.g., 'btcusdt@depth20@100ms')
        """
        url = f"{self.ws_url}/ws/{stream}"
        logger.info(f"Connecting to WebSocket: {url}")

        try:
            self.ws = await websockets.connect(url)
            self.running = True
            logger.info("WebSocket connected successfully")

            # Start heartbeat task
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Start receive loop
            await self._receive_loop()
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            if self.on_error:
                self.on_error(e)
            raise

    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket."""
        while self.running and self.ws:
            try:
                message = await self.ws.recv()
                data = json.loads(message)
                if self.on_message:
                    self.on_message(data)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                if self.running:
                    await self._reconnect()
                break
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                if self.on_error:
                    self.on_error(e)
                if self.running:
                    await self._reconnect()
                break

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat/ping."""
        while self.running and self.ws:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self.ws and self.running:
                    await self.ws.ping()
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                break

    async def _reconnect(self) -> None:
        """Reconnect to WebSocket."""
        logger.info(f"Reconnecting in {self.reconnect_interval} seconds...")
        await asyncio.sleep(self.reconnect_interval)
        # Reconnection logic should be handled by the caller
        # or by implementing a reconnect method that knows the stream

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self.running = False
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.ws:
            await self.ws.close()
        logger.info("WebSocket disconnected")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


class BinancePrivateWebSocketClient:
    """Private WebSocket client for authenticated streams."""

    def __init__(
        self,
        ws_url: str,
        api_key: str,
        listen_key: str,
        on_message: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        """Initialize private WebSocket client.

        Args:
            ws_url: WebSocket URL
            api_key: API key
            listen_key: User data stream listen key
            on_message: Callback for received messages
            on_error: Callback for errors
        """
        self.ws_url = ws_url
        self.api_key = api_key
        self.listen_key = listen_key
        self.on_message = on_message
        self.on_error = on_error

        self.ws: Optional[WebSocketClientProtocol] = None
        self.running = False

    async def connect(self) -> None:
        """Connect to private WebSocket stream."""
        url = f"{self.ws_url}/ws/{self.listen_key}"
        logger.info("Connecting to private WebSocket stream")

        try:
            self.ws = await websockets.connect(url)
            self.running = True
            logger.info("Private WebSocket connected successfully")

            await self._receive_loop()
        except Exception as e:
            logger.error(f"Private WebSocket connection error: {e}")
            if self.on_error:
                self.on_error(e)
            raise

    async def _receive_loop(self) -> None:
        """Receive messages from private WebSocket."""
        while self.running and self.ws:
            try:
                message = await self.ws.recv()
                data = json.loads(message)
                if self.on_message:
                    self.on_message(data)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Private WebSocket connection closed")
                break
            except Exception as e:
                logger.error(f"Error receiving private message: {e}")
                if self.on_error:
                    self.on_error(e)
                break

    async def disconnect(self) -> None:
        """Disconnect from private WebSocket."""
        self.running = False
        if self.ws:
            await self.ws.close()
        logger.info("Private WebSocket disconnected")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

