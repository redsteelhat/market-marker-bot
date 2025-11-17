"""Web dashboard for market maker bot.

This module provides a web-based dashboard for monitoring bot performance,
positions, risk metrics, and real-time updates.
"""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import Settings
from src.core.exchange import IExchangeClient
from src.core.models import Position, Trade
from src.monitoring.metrics import collect_snapshot
from src.risk.guardian import RiskGuardian

logger = logging.getLogger(__name__)

# Global state for dashboard
dashboard_state: Dict = {
    "bot_running": False,
    "symbols": [],
    "positions": {},
    "metrics": {},
    "risk_scaling": {},
    "trades": [],
    "last_update": None,
}

# WebSocket connections
active_connections: List[WebSocket] = []


async def broadcast_update(data: dict) -> None:
    """Broadcast update to all connected WebSocket clients."""
    if not active_connections:
        return

    message = json.dumps(data, default=str)
    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_text(message)
        except Exception as e:
            logger.debug(f"Error sending to WebSocket client: {e}")
            disconnected.append(connection)

    # Remove disconnected clients
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


async def update_dashboard_state(
    exchange: IExchangeClient,
    risk_guardian: RiskGuardian,
    settings: Settings,
    risk_scaling_engines: Optional[Dict[str, any]] = None,
) -> None:
    """Update dashboard state from exchange and risk guardian.

    Args:
        exchange: Exchange client
        risk_guardian: Risk guardian
        settings: Application settings
        risk_scaling_engines: Optional dict of risk scaling engines per symbol
    """
    try:
        # Get positions
        positions = await exchange.get_positions()
        positions_dict = {}
        for pos in positions:
            positions_dict[pos.symbol] = {
                "symbol": pos.symbol,
                "quantity": float(pos.quantity),
                "entry_price": float(pos.entry_price) if pos.entry_price else None,
                "mark_price": float(pos.mark_price) if pos.mark_price else None,
                "unrealized_pnl": float(pos.unrealized_pnl),
                "realized_pnl": float(pos.realized_pnl),
                "notional": float(pos.notional),
            }

        # Get recent trades
        trades = await exchange.get_trades(limit=50)
        trades_list = [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side.value,
                "quantity": float(t.quantity),
                "price": float(t.price),
                "timestamp": t.timestamp.isoformat(),
            }
            for t in trades
        ]

        # Collect metrics snapshot
        snapshot = await collect_snapshot(
            exchange=exchange,
            risk_guardian=risk_guardian,
            positions=positions,
            open_orders=await exchange.get_open_orders(),
            trades=trades,
            initial_equity=Decimal(str(settings.bot_equity_usdt)),
        )

        # Risk scaling data
        risk_scaling_data = {}
        if risk_scaling_engines:
            for symbol, engine in risk_scaling_engines.items():
                if engine:
                    risk_scaling_data[symbol] = {
                        "multiplier": float(engine.current_multiplier),
                        "is_risk_off": engine.is_risk_off(threshold=settings.risk.risk_off_threshold),
                    }

        # Update global state
        dashboard_state.update({
            "bot_running": True,
            "symbols": settings.symbols,
            "positions": positions_dict,
            "metrics": {
                "equity": float(snapshot.equity),
                "total_pnl": float(snapshot.total_pnl),
                "realized_pnl": float(snapshot.realized_pnl),
                "unrealized_pnl": float(snapshot.unrealized_pnl),
                "daily_pnl": float(snapshot.daily_pnl),
                "max_drawdown": float(snapshot.max_drawdown),
                "max_drawdown_pct": float(snapshot.max_drawdown_pct),
                "total_trades": snapshot.total_trades,
                "trades_today": snapshot.trades_today,
                "sharpe_ratio": float(snapshot.sharpe_ratio) if snapshot.sharpe_ratio else None,
                "kill_switch_active": snapshot.kill_switch_active,
                "kill_switch_reason": snapshot.kill_switch_reason,
            },
            "risk_scaling": risk_scaling_data,
            "trades": trades_list[-20:],  # Last 20 trades
            "last_update": datetime.utcnow().isoformat(),
        })

        # Broadcast update
        await broadcast_update({
            "type": "update",
            "data": dashboard_state,
        })

    except Exception as e:
        logger.error(f"Error updating dashboard state: {e}")


def create_app() -> FastAPI:
    """Create FastAPI application for dashboard."""
    app = FastAPI(title="Market Maker Bot Dashboard")

    # Get dashboard HTML path
    dashboard_html_path = Path(__file__).parent.parent.parent / "static" / "dashboard.html"
    
    # Fallback HTML if file doesn't exist
    fallback_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Dashboard</title></head>
    <body>
        <h1>Dashboard HTML file not found</h1>
        <p>Please ensure static/dashboard.html exists in the project root.</p>
    </body>
    </html>
    """

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard():
        """Serve dashboard HTML."""
        if dashboard_html_path.exists():
            with open(dashboard_html_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        else:
            return HTMLResponse(content=fallback_html, status_code=200)

    @app.get("/api/state")
    async def get_state():
        """Get current dashboard state."""
        return dashboard_state

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await websocket.accept()
        active_connections.append(websocket)

        try:
            # Send initial state
            await websocket.send_text(json.dumps({
                "type": "update",
                "data": dashboard_state,
            }, default=str))

            # Keep connection alive
            while True:
                await asyncio.sleep(1)
                # Client can send ping/pong messages here if needed
                try:
                    data = await websocket.receive_text()
                    # Echo back or handle client messages
                    if data == "ping":
                        await websocket.send_text('{"type": "pong"}')
                except Exception:
                    pass

        except WebSocketDisconnect:
            if websocket in active_connections:
                active_connections.remove(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            if websocket in active_connections:
                active_connections.remove(websocket)

    return app


async def run_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    exchange: Optional[IExchangeClient] = None,
    risk_guardian: Optional[RiskGuardian] = None,
    settings: Optional[Settings] = None,
    risk_scaling_engines: Optional[Dict[str, any]] = None,
    update_interval: float = 1.0,
):
    """Run dashboard server with periodic updates.

    Args:
        host: Server host
        port: Server port
        exchange: Exchange client for data
        risk_guardian: Risk guardian for metrics
        settings: Application settings
        risk_scaling_engines: Risk scaling engines per symbol
        update_interval: Update interval in seconds
    """
    import uvicorn

    app = create_app()

    # Start background task for periodic updates
    if exchange and risk_guardian and settings:
        async def update_loop():
            while True:
                try:
                    await update_dashboard_state(
                        exchange=exchange,
                        risk_guardian=risk_guardian,
                        settings=settings,
                        risk_scaling_engines=risk_scaling_engines,
                    )
                except Exception as e:
                    logger.error(f"Error in dashboard update loop: {e}")
                await asyncio.sleep(update_interval)

        asyncio.create_task(update_loop())

    # Run server
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

