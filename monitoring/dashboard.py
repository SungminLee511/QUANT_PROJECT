"""FastAPI web dashboard — real-time positions, P&L, orders, kill switch."""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from risk.kill_switch import KillSwitch
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(config: dict, redis: RedisClient) -> FastAPI:
    """Create and return the FastAPI dashboard application."""
    app = FastAPI(title="Quant Trader Dashboard")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    kill_switch = KillSwitch(
        redis, config.get("risk", {}).get("kill_switch_key", "risk:kill_switch")
    )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

    @app.get("/api/positions")
    async def api_positions():
        state = await redis.get_flag("portfolio:state")
        if not state:
            return JSONResponse({"positions": [], "cash": 0, "total_equity": 0})
        return JSONResponse({
            "positions": [
                {"symbol": s} for s in state.get("position_symbols", [])
            ],
            "cash": state.get("cash", 0),
            "total_equity": state.get("total_equity", 0),
        })

    @app.get("/api/pnl")
    async def api_pnl():
        state = await redis.get_flag("portfolio:state")
        if not state:
            return JSONResponse({"daily_pnl": 0, "total_equity": 0})
        return JSONResponse({
            "daily_pnl": state.get("daily_pnl", 0),
            "total_equity": state.get("total_equity", 0),
            "peak_equity": state.get("peak_equity", 0),
        })

    @app.get("/api/orders")
    async def api_orders():
        try:
            from db.session import get_session
            from db.models import Order
            from sqlalchemy import select

            async with get_session() as session:
                stmt = select(Order).order_by(Order.created_at.desc()).limit(100)
                result = await session.execute(stmt)
                orders = result.scalars().all()
                return JSONResponse({
                    "orders": [
                        {
                            "id": o.id,
                            "symbol": o.symbol,
                            "side": o.side,
                            "quantity": o.quantity,
                            "filled_quantity": o.filled_quantity,
                            "status": o.status,
                            "exchange": o.exchange,
                            "created_at": o.created_at.isoformat() if o.created_at else "",
                        }
                        for o in orders
                    ]
                })
        except Exception as e:
            logger.exception("Error fetching orders")
            return JSONResponse({"orders": [], "error": str(e)})

    @app.get("/api/equity-history")
    async def api_equity_history():
        try:
            from db.session import get_session
            from db.models import EquitySnapshot
            from sqlalchemy import select

            async with get_session() as session:
                stmt = (
                    select(EquitySnapshot)
                    .order_by(EquitySnapshot.timestamp.desc())
                    .limit(500)
                )
                result = await session.execute(stmt)
                snapshots = result.scalars().all()
                return JSONResponse({
                    "snapshots": [
                        {
                            "timestamp": s.timestamp.isoformat(),
                            "total_equity": s.total_equity,
                            "cash": s.cash,
                            "positions_value": s.positions_value,
                        }
                        for s in reversed(snapshots)
                    ]
                })
        except Exception as e:
            logger.exception("Error fetching equity history")
            return JSONResponse({"snapshots": [], "error": str(e)})

    @app.get("/api/status")
    async def api_status():
        state = await redis.get_flag("portfolio:state")
        ks = await kill_switch.get_state()
        return JSONResponse({
            "kill_switch": ks,
            "total_equity": state.get("total_equity", 0) if state else 0,
            "open_positions": state.get("open_positions", 0) if state else 0,
        })

    @app.post("/api/kill-switch")
    async def api_kill_switch(request: Request):
        body = await request.json()
        action = body.get("action", "toggle")
        if action == "activate":
            await kill_switch.activate(reason="Dashboard manual activation")
            return JSONResponse({"status": "activated"})
        elif action == "deactivate":
            await kill_switch.deactivate()
            return JSONResponse({"status": "deactivated"})
        else:
            # Toggle
            if await kill_switch.is_active():
                await kill_switch.deactivate()
                return JSONResponse({"status": "deactivated"})
            else:
                await kill_switch.activate(reason="Dashboard toggle")
                return JSONResponse({"status": "activated"})

    return app


async def run_dashboard(config: dict, redis: RedisClient) -> None:
    """Start the dashboard server."""
    app = create_app(config, redis)
    dash_cfg = config.get("monitoring", {}).get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 8080)

    server_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(server_config)
    logger.info("Dashboard starting on %s:%s", host, port)
    await server.serve()
