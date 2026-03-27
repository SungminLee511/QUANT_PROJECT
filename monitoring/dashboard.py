"""Dashboard router — positions, P&L, orders, equity history, kill switch.

All API endpoints accept an optional ?session_id= query parameter.
When provided, data is scoped to that session via namespaced Redis keys and DB filtering.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import get_current_user, require_auth
from risk.kill_switch import KillSwitch
from session.manager import SessionManager
from shared.redis_client import RedisClient, session_channel

logger = logging.getLogger(__name__)


def _portfolio_key(session_id: Optional[str]) -> str:
    """Return the Redis key for portfolio state, scoped to session if provided."""
    if session_id:
        return session_channel(session_id, "portfolio:state")
    return "portfolio:state"


def _kill_switch_key(session_id: Optional[str], default_key: str) -> str:
    """Return the Redis key for kill switch, scoped to session if provided."""
    if session_id:
        return session_channel(session_id, "risk:kill_switch")
    return default_key


def create_dashboard_router(
    config: dict, redis: RedisClient, templates: Jinja2Templates,
    session_manager: SessionManager,
) -> APIRouter:
    router = APIRouter()
    default_ks_key = config.get("risk", {}).get("kill_switch_key", "risk:kill_switch")

    # ── Pages ────────────────────────────────────────────────────────

    @router.get("/overview")
    async def overview(request: Request):
        redirect = require_auth(request)
        if redirect:
            return redirect
        sessions = await session_manager.get_all_sessions()
        for s in sessions:
            s["is_running"] = session_manager.is_running(s["id"])
        session_ids = [s["id"] for s in sessions]
        return templates.TemplateResponse(request, "overview.html", {
            "user": get_current_user(request),
            "sessions": sessions,
            "active_page": "overview",
            "selected_session": None,
            "session_ids_json": json.dumps(session_ids),
        })

    @router.get("/")
    async def index(request: Request, session_id: Optional[str] = Query(None)):
        redirect = require_auth(request)
        if redirect:
            return redirect
        if not session_id:
            return RedirectResponse(url="/overview", status_code=302)
        # Fetch all sessions for the sidebar
        sessions = await session_manager.get_all_sessions()
        for s in sessions:
            s["is_running"] = session_manager.is_running(s["id"])
        return templates.TemplateResponse(request, "dashboard.html", {
            "user": get_current_user(request),
            "sessions": sessions,
            "active_page": "dashboard",
            "selected_session": session_id,
        })

    # ── API ──────────────────────────────────────────────────────────

    @router.get("/api/positions")
    async def api_positions(request: Request, session_id: Optional[str] = Query(None)):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        key = _portfolio_key(session_id)
        state = await redis.get_flag(key)
        if not state:
            return JSONResponse({"positions": [], "cash": 0, "total_equity": 0})
        return JSONResponse({
            "positions": state.get("positions", [
                {"symbol": s} for s in state.get("position_symbols", [])
            ]),
            "cash": state.get("cash", 0),
            "total_equity": state.get("total_equity", 0),
        })

    @router.get("/api/pnl")
    async def api_pnl(request: Request, session_id: Optional[str] = Query(None)):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        key = _portfolio_key(session_id)
        state = await redis.get_flag(key)
        if not state:
            return JSONResponse({"daily_pnl": 0, "total_equity": 0})
        return JSONResponse({
            "daily_pnl": state.get("daily_pnl", 0),
            "total_equity": state.get("total_equity", 0),
            "peak_equity": state.get("peak_equity", 0),
        })

    @router.get("/api/orders")
    async def api_orders(request: Request, session_id: Optional[str] = Query(None)):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            from db.session import get_session
            from db.models import Order
            from sqlalchemy import select

            async with get_session() as session:
                stmt = select(Order).order_by(Order.created_at.desc()).limit(100)
                if session_id:
                    stmt = stmt.where(Order.session_id == session_id)
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
    async def api_equity_history(request: Request, session_id: Optional[str] = Query(None)):
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
                if session_id:
                    stmt = stmt.where(EquitySnapshot.session_id == session_id)
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
    async def api_status(request: Request, session_id: Optional[str] = Query(None)):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        key = _portfolio_key(session_id)
        ks_key = _kill_switch_key(session_id, default_ks_key)
        state = await redis.get_flag(key)
        kill_switch = KillSwitch(redis, ks_key, session_id=session_id or "")
        ks = await kill_switch.get_state()
        return JSONResponse({
            "kill_switch": ks,
            "total_equity": state.get("total_equity", 0) if state else 0,
            "open_positions": state.get("open_positions", 0) if state else 0,
        })

    @router.post("/api/kill-switch")
    async def api_kill_switch(request: Request, session_id: Optional[str] = Query(None)):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        ks_key = _kill_switch_key(session_id, default_ks_key)
        kill_switch = KillSwitch(redis, ks_key, session_id=session_id or "")
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
