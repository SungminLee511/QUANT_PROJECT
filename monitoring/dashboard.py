"""Dashboard router — positions, P&L, orders, equity history, kill switch."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import get_current_user, require_auth
from risk.kill_switch import KillSwitch
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


def create_dashboard_router(
    config: dict, redis: RedisClient, templates: Jinja2Templates
) -> APIRouter:
    router = APIRouter()
    kill_switch = KillSwitch(
        redis, config.get("risk", {}).get("kill_switch_key", "risk:kill_switch")
    )

    # ── Pages ────────────────────────────────────────────────────────

    @router.get("/")
    async def index(request: Request):
        redirect = require_auth(request)
        if redirect:
            return redirect
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": get_current_user(request),
        })

    # ── API ──────────────────────────────────────────────────────────

    @router.get("/api/positions")
    async def api_positions(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
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

    @router.get("/api/pnl")
    async def api_pnl(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        state = await redis.get_flag("portfolio:state")
        if not state:
            return JSONResponse({"daily_pnl": 0, "total_equity": 0})
        return JSONResponse({
            "daily_pnl": state.get("daily_pnl", 0),
            "total_equity": state.get("total_equity", 0),
            "peak_equity": state.get("peak_equity", 0),
        })

    @router.get("/api/orders")
    async def api_orders(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
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

    @router.get("/api/equity-history")
    async def api_equity_history(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
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

    @router.get("/api/status")
    async def api_status(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        state = await redis.get_flag("portfolio:state")
        ks = await kill_switch.get_state()
        return JSONResponse({
            "kill_switch": ks,
            "total_equity": state.get("total_equity", 0) if state else 0,
            "open_positions": state.get("open_positions", 0) if state else 0,
        })

    @router.post("/api/kill-switch")
    async def api_kill_switch(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        action = body.get("action", "toggle")
        if action == "activate":
            await kill_switch.activate(reason="Dashboard manual activation")
            return JSONResponse({"status": "activated"})
        elif action == "deactivate":
            await kill_switch.deactivate()
            return JSONResponse({"status": "deactivated"})
        else:
            if await kill_switch.is_active():
                await kill_switch.deactivate()
                return JSONResponse({"status": "deactivated"})
            else:
                await kill_switch.activate(reason="Dashboard toggle")
                return JSONResponse({"status": "activated"})

    return router
