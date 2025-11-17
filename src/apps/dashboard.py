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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

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
    "logs": [],  # Recent logs (last 100)
    "last_update": None,
    "balance": None,  # Binance balance info
    "selected_coins": [],  # User-selected coins to track
    "signals": [],  # Recent trading signals
}

# Global bot state for dynamic coin management
# This is shared between dashboard and bot runtime
bot_runtime_state: Dict = {
    "active_symbols": [],  # Symbols that bot is actively trading
    "orderbook_managers": {},  # Will be set by paper_trading
    "market_makers": [],  # Will be set by paper_trading
    "ws_client": None,  # Will be set by paper_trading
    "public_client": None,  # Will be set by paper_trading
    "simulated_exchange": None,  # Will be set by paper_trading
    "risk_guardian": None,  # Will be set by paper_trading
    "settings": None,  # Will be set by paper_trading
    "risk_scaling_engines": {},  # Will be set by paper_trading
}

# Log buffer for dashboard
log_buffer: List[Dict] = []
MAX_LOG_BUFFER = 100


class DashboardLogHandler(logging.Handler):
    """Custom log handler that captures logs for dashboard."""
    
    def __init__(self):
        super().__init__()
        # Don't set a formatter - we'll format manually
    
    def emit(self, record: logging.LogRecord):
        """Capture log record and add to buffer."""
        try:
            # Ensure symbol attribute exists (for SymbolFilter compatibility)
            if not hasattr(record, "symbol"):
                record.symbol = "-"
            
            # Get the raw message (without formatting)
            message = record.getMessage()
            
            # If there's extra context, add it
            if hasattr(record, "symbol") and record.symbol != "-":
                message = f"[{record.symbol}] {message}"
            
            # Check if this is a signal log
            is_signal = "[SIGNAL]" in message or "SIGNAL" in message.upper()
            signal_type = None
            if is_signal:
                # Extract signal type from message
                if "ENTER_LONG" in message or "LONG" in message.upper():
                    signal_type = "ENTER_LONG"
                elif "ENTER_SHORT" in message or "SHORT" in message.upper():
                    signal_type = "ENTER_SHORT"
                elif "EXIT_LONG" in message:
                    signal_type = "EXIT_LONG"
                elif "EXIT_SHORT" in message:
                    signal_type = "EXIT_SHORT"
            
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name.split('.')[-1],  # Just module name
                "message": message,
                "is_signal": is_signal,
                "signal_type": signal_type,
            }
            
            # Add to buffer
            log_buffer.append(log_entry)
            
            # If it's a signal, also add to signals list in dashboard state
            if is_signal and signal_type:
                # Extract symbol from message if available
                symbol = record.symbol if hasattr(record, "symbol") and record.symbol != "-" else None
                if not symbol and "[" in message and "]" in message:
                    # Try to extract from message like "[BTCUSDT] SIGNAL..."
                    parts = message.split("]")
                    if len(parts) > 0:
                        symbol = parts[0].replace("[", "").strip()
                
                signal_entry = {
                    "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                    "symbol": symbol,
                    "signal_type": signal_type,
                    "message": message,
                }
                
                # Add to signals list (keep last 20)
                if "signals" not in dashboard_state:
                    dashboard_state["signals"] = []
                dashboard_state["signals"].append(signal_entry)
                if len(dashboard_state["signals"]) > 20:
                    dashboard_state["signals"].pop(0)
            
            # Keep only last N logs
            if len(log_buffer) > MAX_LOG_BUFFER:
                log_buffer.pop(0)
                
        except Exception as e:
            # Log to stderr if handler fails (but don't break main logging)
            import sys
            print(f"DashboardLogHandler error: {e}", file=sys.stderr)


# Setup dashboard log handler (only if not already added)
# We'll add this handler to the root logger, but we need to make sure
# it's added after setup_logging is called (which happens in main.py)
def setup_dashboard_log_handler():
    """Setup dashboard log handler. Call this after setup_logging."""
    root_logger = logging.getLogger()
    
    # Check if handler already exists
    if any(isinstance(h, DashboardLogHandler) for h in root_logger.handlers):
        return
    
    dashboard_log_handler = DashboardLogHandler()
    dashboard_log_handler.setLevel(logging.DEBUG)  # Capture all levels
    root_logger.addHandler(dashboard_log_handler)
    # Don't change root logger level - respect existing level
    
    # Also add SymbolFilter to ensure symbol attribute exists
    from src.utils.logging import SymbolFilter
    dashboard_log_handler.addFilter(SymbolFilter())
    
    # Test log to verify handler is working
    test_logger = logging.getLogger(__name__)
    test_logger.info("Dashboard log handler initialized successfully")

# Try to setup immediately (will work if logging is already configured)
try:
    setup_dashboard_log_handler()
except Exception:
    pass  # Will be called later when logging is properly set up

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
    orderbook_managers: Optional[Dict[str, any]] = None,
    selected_coins: Optional[List[str]] = None,
) -> None:
    """Update dashboard state from exchange and risk guardian.
    
    This function is designed to be non-blocking and isolated from bot trading operations.
    It uses timeouts to prevent blocking the main event loop.

    Args:
        exchange: Exchange client
        risk_guardian: Risk guardian
        settings: Application settings
        risk_scaling_engines: Optional dict of risk scaling engines per symbol
    """
    try:
        # Use asyncio.wait_for to prevent blocking operations
        # This ensures dashboard updates don't interfere with bot trading
        async def _safe_update():
            return await _update_dashboard_state_internal(
                exchange, risk_guardian, settings, risk_scaling_engines, orderbook_managers, selected_coins
            )
        
        # Timeout of 2 seconds - if dashboard update takes longer, skip it
        await asyncio.wait_for(_safe_update(), timeout=2.0)
    except asyncio.TimeoutError:
        logger.warning("Dashboard update timed out, skipping this cycle")
    except Exception as e:
        logger.error(f"Error updating dashboard state: {e}", exc_info=True)


async def _update_dashboard_state_internal(
    exchange: IExchangeClient,
    risk_guardian: RiskGuardian,
    settings: Settings,
    risk_scaling_engines: Optional[Dict[str, any]] = None,
    orderbook_managers: Optional[Dict[str, any]] = None,
    selected_coins: Optional[List[str]] = None,
) -> None:
    """Internal dashboard state update (without timeout wrapper)."""
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

        # Get Binance balance if exchange supports it
        balance_info = None
        try:
            if hasattr(exchange, 'get_account_balance'):
                balance_info = await exchange.get_account_balance()
        except Exception as e:
            logger.debug(f"Could not fetch balance: {e}")

        # Get current prices from orderbook managers
        prices = {}
        # First, get prices for bot's active symbols
        if orderbook_managers:
            for symbol, ob_manager in orderbook_managers.items():
                if ob_manager and ob_manager.snapshot:
                    ob_snapshot = ob_manager.snapshot
                    prices[symbol] = {
                        "best_bid": float(ob_snapshot.best_bid) if ob_snapshot.best_bid else None,
                        "best_ask": float(ob_snapshot.best_ask) if ob_snapshot.best_ask else None,
                        "mid_price": float(ob_snapshot.mid_price) if ob_snapshot.mid_price else None,
                        "spread": float(ob_snapshot.spread) if ob_snapshot.spread else None,
                        "spread_bps": float(ob_snapshot.spread_bps) if ob_snapshot.spread_bps else None,
                        "timestamp": ob_snapshot.timestamp.isoformat() if ob_snapshot.timestamp else None,
                    }
        else:
            # Fallback: try to get from exchange for bot's symbols
            for symbol in settings.symbols:
                try:
                    orderbook = await exchange.get_orderbook(symbol, limit=1)
                    if orderbook:
                        prices[symbol] = {
                            "best_bid": float(orderbook.best_bid) if orderbook.best_bid else None,
                            "best_ask": float(orderbook.best_ask) if orderbook.best_ask else None,
                            "mid_price": float(orderbook.mid_price) if orderbook.mid_price else None,
                            "spread": float(orderbook.spread) if orderbook.spread else None,
                            "spread_bps": float(orderbook.spread_bps) if orderbook.spread_bps else None,
                            "timestamp": orderbook.timestamp.isoformat() if orderbook.timestamp else None,
                        }
                except Exception:
                    pass
        
        # Get prices for selected coins (if any) from Binance public API
        # Also update prices for bot's active symbols to ensure they're fresh
        selected_coins_list = selected_coins if selected_coins else dashboard_state.get("selected_coins", [])
        # Combine selected coins with bot's active symbols to ensure all are updated
        all_symbols_to_update = list(set(selected_coins_list + settings.symbols))
        
        if all_symbols_to_update:
            try:
                from src.data.binance_public_client import BinancePublicClient
                public_client = BinancePublicClient(base_url="https://fapi.binance.com")  # Futures API
                
                for symbol in all_symbols_to_update:
                    # Always fetch from ticker for selected coins and bot's active symbols
                    # This ensures fresh prices even if orderbook manager has stale data
                    try:
                        # Get ticker for quick price info
                        ticker = await public_client.get_ticker(symbol)
                        if ticker:
                            bid_price = float(ticker.get("bidPrice", 0))
                            ask_price = float(ticker.get("askPrice", 0))
                            mid_price = (bid_price + ask_price) / 2 if bid_price > 0 and ask_price > 0 else float(ticker.get("lastPrice", 0))
                            spread = ask_price - bid_price if bid_price > 0 and ask_price > 0 else 0
                            spread_bps = (spread / mid_price * 10000) if mid_price > 0 else 0
                            
                            # Always update price entry from ticker (overrides orderbook manager data)
                            prices[symbol] = {
                                "best_bid": bid_price if bid_price > 0 else None,
                                "best_ask": ask_price if ask_price > 0 else None,
                                "mid_price": mid_price if mid_price > 0 else None,
                                "spread": spread if spread > 0 else None,
                                "spread_bps": spread_bps if spread_bps > 0 else None,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                            logger.debug(f"Updated price for {symbol} from ticker: mid={mid_price}, bid={bid_price}, ask={ask_price}")
                    except Exception as e:
                        logger.debug(f"Could not fetch price for {symbol} from ticker: {e}")
                        # If ticker fails, keep existing price from orderbook manager if available
                        pass
                
                await public_client.close()
            except Exception as e:
                logger.debug(f"Could not create public client for price updates: {e}")
                pass

        # Update global state
        # Use active_symbols from bot runtime state instead of settings.symbols
        active_symbols_from_bot = bot_runtime_state.get("active_symbols", [])
        dashboard_state.update({
            "bot_running": True,
            "symbols": active_symbols_from_bot,  # Use active symbols from bot runtime state
            "positions": positions_dict,
            "prices": prices,  # Add price data
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
            "logs": log_buffer[-50:],  # Last 50 logs
            "balance": balance_info,  # Binance balance
            "selected_coins": selected_coins if selected_coins else dashboard_state.get("selected_coins", []),  # Selected coins
            "signals": dashboard_state.get("signals", []),  # Recent signals
            "last_update": datetime.utcnow().isoformat(),
        })

        # Broadcast update
        await broadcast_update({
            "type": "update",
            "data": dashboard_state,
        })
        
        logger.debug(
            f"Dashboard state updated: equity={dashboard_state.get('metrics', {}).get('equity')}, "
            f"trades={len(dashboard_state.get('trades', []))}, "
            f"prices={len(prices)}, selected_coins={len(selected_coins_list) if selected_coins_list else 0}"
        )

    except Exception as e:
        logger.error(f"Error updating dashboard state: {e}", exc_info=True)


def create_app() -> FastAPI:
    """Create FastAPI application for dashboard."""
    app = FastAPI(title="Market Maker Bot Dashboard")
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify actual origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    @app.post("/api/select-coins")
    async def select_coins(request: Request):
        """Update selected coins to track AND activate them in bot.
        
        Expected request body:
        {
            "coins": ["BTCUSDT", "ETHUSDT", ...]
        }
        """
        try:
            data = await request.json()
            coins = data.get("coins", [])
            
            # Update dashboard state
            dashboard_state["selected_coins"] = coins
            
            # Update bot runtime state - these are the coins bot will trade
            bot_runtime_state["active_symbols"] = coins
            
            # If bot is running, dynamically update symbols (non-blocking)
            if bot_runtime_state.get("bot_running", False):
                # Run symbol update in background to avoid blocking API response
                asyncio.create_task(_update_bot_symbols(coins))
            
            logger.info(f"Selected coins updated: {coins}")
            return JSONResponse({"status": "ok", "selected_coins": coins, "active_symbols": bot_runtime_state["active_symbols"]})
        except Exception as e:
            logger.error(f"Error updating selected coins: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)
    
    async def _update_bot_symbols(new_symbols: List[str]):
        """Dynamically update bot symbols during runtime.
        
        This function is isolated from dashboard updates and uses timeouts
        to prevent blocking bot operations.
        
        Args:
            new_symbols: List of symbols to activate
        """
        try:
            # Use timeout to prevent blocking
            async def _safe_update():
                return await _update_bot_symbols_internal(new_symbols)
            
            # Timeout of 10 seconds for symbol updates
            await asyncio.wait_for(_safe_update(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("Symbol update timed out - bot may continue with previous symbols")
        except Exception as e:
            logger.error(f"Error updating bot symbols: {e}", exc_info=True)
    
    async def _update_bot_symbols_internal(new_symbols: List[str]):
        """Internal symbol update (without timeout wrapper)."""
        try:
            import asyncio
            from src.data.orderbook import OrderBookManager
            from src.strategy.market_maker import MarketMaker
            
            current_symbols = set(bot_runtime_state.get("active_symbols", []))
            new_symbols_set = set(new_symbols)
            
            # Symbols to remove
            to_remove = current_symbols - new_symbols_set
            # Symbols to add
            to_add = new_symbols_set - current_symbols
            
            orderbook_managers = bot_runtime_state.get("orderbook_managers", {})
            market_makers = bot_runtime_state.get("market_makers", [])
            public_client = bot_runtime_state.get("public_client")
            simulated_exchange = bot_runtime_state.get("simulated_exchange")
            risk_guardian = bot_runtime_state.get("risk_guardian")
            settings = bot_runtime_state.get("settings")
            ws_client = bot_runtime_state.get("ws_client")
            
            if not all([public_client, simulated_exchange, risk_guardian, settings]):
                logger.warning("Bot runtime state not fully initialized, cannot update symbols")
                return
            
            # Remove symbols
            for symbol in to_remove:
                logger.info(f"Removing symbol {symbol} from bot")
                
                # Stop market maker
                for mm in market_makers[:]:
                    if mm.symbol == symbol:
                        await mm.stop()
                        market_makers.remove(mm)
                        logger.info(f"Stopped market maker for {symbol}")
                
                # Remove orderbook manager
                if symbol in orderbook_managers:
                    del orderbook_managers[symbol]
                
                # Cancel all orders for this symbol
                if simulated_exchange:
                    try:
                        await simulated_exchange.cancel_all_orders(symbol)
                    except Exception as e:
                        logger.error(f"Error canceling orders for {symbol}: {e}")
            
            # Add symbols
            for symbol in to_add:
                logger.info(f"Adding symbol {symbol} to bot")
                
                try:
                    # Create orderbook manager
                    ob_manager = OrderBookManager(symbol)
                    
                    # Get initial snapshot
                    snapshot = await public_client.get_orderbook(symbol, limit=20)
                    ob_manager.update_from_binance({
                        "bids": [[float(level.price), float(level.quantity)] for level in snapshot.bids],
                        "asks": [[float(level.price), float(level.quantity)] for level in snapshot.asks],
                    })
                    
                    # Feed to simulated exchange
                    await simulated_exchange.on_orderbook_update(symbol, snapshot)
                    orderbook_managers[symbol] = ob_manager
                    
                    # Create market maker
                    mm = MarketMaker(
                        settings=settings,
                        exchange=simulated_exchange,
                        risk_guardian=risk_guardian,
                        symbol=symbol,
                        orderbook_manager=ob_manager,
                    )
                    market_makers.append(mm)
                    await mm.start()
                    
                    logger.info(f"Added and started market maker for {symbol}")
                    
                except Exception as e:
                    logger.error(f"Error adding symbol {symbol}: {e}", exc_info=True)
            
            # Update WebSocket subscription if needed
            if ws_client and (to_add or to_remove):
                # Re-subscribe to streams
                all_symbols = list(new_symbols_set)
                streams = [f"{symbol.lower()}@depth20@100ms" for symbol in all_symbols]
                stream_name = "/".join(streams)
                try:
                    # Note: Binance WebSocket doesn't support dynamic subscription changes easily
                    # We may need to reconnect. For now, log a warning.
                    logger.warning(f"WebSocket subscription should be updated for new symbols: {all_symbols}")
                    logger.warning("Note: Full WebSocket reconnection may be required for symbol changes")
                except Exception as e:
                    logger.error(f"Error updating WebSocket subscription: {e}")
            
            # Update bot runtime state
            bot_runtime_state["active_symbols"] = new_symbols
            bot_runtime_state["orderbook_managers"] = orderbook_managers
            bot_runtime_state["market_makers"] = market_makers
            
            logger.info(f"Bot symbols updated. Active: {bot_runtime_state['active_symbols']}")
            
        except Exception as e:
            logger.error(f"Error updating bot symbols: {e}", exc_info=True)

    @app.get("/api/routes")
    async def get_routes():
        """Debug endpoint to list all available routes."""
        routes = []
        for route in app.routes:
            if hasattr(route, 'methods') and hasattr(route, 'path'):
                routes.append({
                    "path": route.path,
                    "methods": list(route.methods) if route.methods else ["GET"]
                })
        return JSONResponse({"routes": routes})

    @app.get("/api/backtest/test")
    async def test_backtest():
        """Test endpoint to verify backtest route is accessible."""
        return JSONResponse({"status": "ok", "message": "Backtest endpoint is accessible"})

    @app.post("/api/backtest")
    async def run_backtest(request: Request):
        """Run backtest from dashboard.
        
        Expected request body:
        {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
            "spread_bps": 8.0,
            "order_notional_pct": 0.01
        }
        """
        try:
            logger.info("Backtest request received")
            from src.backtest.engine import BacktestEngine
            from src.core.config import Settings
            from datetime import datetime
            import asyncio
            
            # Get request data
            data = await request.json()
            logger.info(f"Backtest request data: {data}")
            
            symbol = data.get("symbol", "BTCUSDT")
            start_date_str = data.get("start_date")
            end_date_str = data.get("end_date")
            spread_bps = data.get("spread_bps", 8.0)
            order_notional_pct = data.get("order_notional_pct", 0.01)
            
            # Parse dates
            start_date = None
            end_date = None
            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
                except ValueError as e:
                    logger.error(f"Invalid start_date format: {start_date_str}")
                    return JSONResponse({"error": f"Invalid start_date format: {start_date_str}"}, status_code=400)
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
                    # Add one day to include the full end date
                    from datetime import timedelta
                    end_date = end_date + timedelta(days=1)
                except ValueError as e:
                    logger.error(f"Invalid end_date format: {end_date_str}")
                    return JSONResponse({"error": f"Invalid end_date format: {end_date_str}"}, status_code=400)
            
            logger.info(f"Running backtest: symbol={symbol}, start={start_date}, end={end_date}, spread={spread_bps}, notional={order_notional_pct}")
            
            # Load settings and override with backtest parameters
            settings = Settings.from_env()
            if spread_bps:
                settings.strategy.base_spread_bps = spread_bps
            if order_notional_pct:
                settings.strategy.order_notional_pct = order_notional_pct
            
            # Run backtest
            engine = BacktestEngine(settings)
            logger.info("Backtest engine created, starting run...")
            results = await engine.run(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                enable_dashboard=False,  # Don't start dashboard for backtest
            )
            logger.info(f"Backtest completed: {results}")
            
            # Format results
            snapshots_processed = results.get("snapshots_processed", 0)
            if snapshots_processed == 0:
                logger.warning(f"No historical data found for {symbol} in date range {start_date_str} to {end_date_str}")
                # Check if data file exists
                from pathlib import Path
                data_file = Path(f"data/backtest/{symbol}_orderbook.csv")
                if not data_file.exists():
                    error_msg = f"No backtest data file found for {symbol}. Please download data first using: python scripts/download_backtest_data.py --symbol {symbol} --start-date 2024-01-01 --end-date 2024-01-07"
                else:
                    error_msg = f"No data found in the selected date range ({start_date_str} to {end_date_str}). Available data is typically from 2024. Please select dates within 2024 range (e.g., 2024-01-01 to 2024-01-07)."
                
                return JSONResponse({
                    "error": error_msg,
                    "symbol": symbol,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "snapshots_processed": 0,
                    "data_file_exists": data_file.exists() if 'data_file' in locals() else False,
                }, status_code=400)
            
            response_data = {
                "symbol": symbol,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "snapshots_processed": snapshots_processed,
                "total_pnl": float(results.get("total_pnl", 0)),
                "total_trades": results.get("total_trades", 0),
                "max_drawdown": float(results.get("max_drawdown", 0)),
                "max_drawdown_pct": float(results.get("max_drawdown_pct", 0)),
                "sharpe_ratio": float(results.get("sharpe_ratio", 0)) if results.get("sharpe_ratio") else None,
                "equity_final": float(results.get("final_equity", results.get("equity_final", 0))),  # Use final_equity from results
                "initial_equity": float(results.get("initial_equity", 0)),
            }
            logger.info(f"Backtest response: {response_data}")
            return JSONResponse(response_data)
        except Exception as e:
            logger.error(f"Backtest error: {e}", exc_info=True)
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Backtest error details: {error_details}")
            return JSONResponse({"error": str(e), "details": error_details}, status_code=500)

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

