"""Session management API router — create, list, start, stop, delete sessions."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from monitoring.auth import get_current_user
from session.manager import SessionManager
from session.schemas import SessionCreate, SessionUpdate
from shared.enums import Exchange, SessionType
from shared.market_calendar import MarketCalendar

logger = logging.getLogger(__name__)


def create_sessions_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter(prefix="/api/sessions")

    @router.get("")
    async def list_sessions(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        sessions = await session_manager.get_all_sessions()
        # Enrich with runtime status
        for s in sessions:
            s["is_running"] = session_manager.is_running(s["id"])
        return JSONResponse({"sessions": sessions})

    @router.post("")
    async def create_session(request: Request):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        try:
            session_type = SessionType(body.get("session_type", "binance_sim"))
            session_id = await session_manager.create_session(
                name=body.get("name", "Untitled"),
                session_type=session_type,
                symbols=body.get("symbols", ["BTCUSDT"]),
                api_key=body.get("api_key", ""),
                api_secret=body.get("api_secret", ""),
                testnet=body.get("testnet", True),
                starting_budget=float(body.get("starting_budget", 10000.0)),
            )
            return JSONResponse({"id": session_id, "created": True})
        except Exception as e:
            logger.exception("Failed to create session")
            return JSONResponse({"error": str(e)}, status_code=400)

    @router.get("/{session_id}")
    async def get_session(request: Request, session_id: str):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        info = await session_manager.get_session_info(session_id)
        if info is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        info["is_running"] = session_manager.is_running(session_id)
        return JSONResponse(info)

    @router.put("/{session_id}")
    async def update_session(request: Request, session_id: str):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        # Whitelist allowed update fields to prevent overriding internal fields
        _ALLOWED_UPDATE_FIELDS = {
            "name", "symbols", "api_key", "api_secret", "testnet",
            "starting_budget", "strategy_code", "data_config", "custom_data_code",
        }
        filtered = {k: v for k, v in body.items() if k in _ALLOWED_UPDATE_FIELDS}
        success = await session_manager.update_session(session_id, **filtered)
        if not success:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"updated": True})

    @router.delete("/{session_id}")
    async def delete_session(request: Request, session_id: str):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        await session_manager.delete_session(session_id)
        return JSONResponse({"deleted": True})

    @router.post("/{session_id}/start")
    async def start_session(request: Request, session_id: str):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        success = await session_manager.start_session(session_id)
        return JSONResponse({"started": success})

    @router.post("/{session_id}/stop")
    async def stop_session(request: Request, session_id: str):
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        success = await session_manager.stop_session(session_id)
        return JSONResponse({"stopped": success})

    @router.get("/{session_id}/equity")
    async def session_equity(request: Request, session_id: str):
        """Return equity info for a session.

        For sim sessions: returns sim adapter equity + total fees.
        For real sessions: returns broker equity (from API), computed equity
        (from portfolio tracker), and the difference (= estimated commission).
        """
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        pipeline = session_manager.get_pipeline(session_id)
        if pipeline is None:
            return JSONResponse({"error": "session not running"}, status_code=404)

        result: dict = {"session_id": session_id, "is_simulation": pipeline.session_type.is_simulation}

        if pipeline.sim_adapter is not None:
            # Sim session — equity from SimAdapter
            balances = await pipeline.sim_adapter.get_balances()
            result.update({
                "equity": balances.get("total_equity", 0),
                "cash": balances.get("cash", 0),
                "positions_value": balances.get("positions_value", 0),
                "total_fees": balances.get("total_fees", 0),
            })
        else:
            # Real session — get broker equity via adapter + computed equity via tracker
            from shared.redis_client import session_channel
            broker_equity = None
            computed_equity = None

            # Broker equity from exchange adapter
            if pipeline.order_router:
                try:
                    adapter = pipeline.order_router._get_adapter(pipeline.session_type.exchange)
                    broker_balances = await adapter.get_balances()
                    # Alpaca returns {"USD": {"total": equity}}
                    # Binance returns per-asset balances
                    if "USD" in broker_balances:
                        broker_equity = broker_balances["USD"].get("total", 0)
                    else:
                        # Binance: sum all asset values (requires price lookup)
                        broker_equity = sum(
                            (info.get("free", 0) + info.get("locked", 0))
                            for info in broker_balances.values()
                        )
                except Exception as e:
                    logger.warning("Failed to fetch broker equity for session %s: %s", session_id, e)

            # Computed equity from portfolio tracker (Redis state)
            portfolio_key = session_channel(session_id, "portfolio:state")
            state = await session_manager.redis.get_flag(portfolio_key)
            if state:
                computed_equity = state.get("total_equity")

            result.update({
                "broker_equity": broker_equity,
                "computed_equity": computed_equity,
                "estimated_fees": round(computed_equity - broker_equity, 2) if (computed_equity is not None and broker_equity is not None) else None,
            })

        return JSONResponse(result)

    @router.get("/{session_id}/market-status")
    async def market_status(request: Request, session_id: str):
        """Return current market status for a session's exchange."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        info = await session_manager.get_session_info(session_id)
        if info is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        session_type = SessionType(info["session_type"])
        cal = MarketCalendar(session_type.exchange)
        schedule_mode = (info.get("data_config") or {}).get("schedule_mode", "always_on")

        return JSONResponse({
            "exchange": session_type.exchange.value,
            "schedule_mode": schedule_mode,
            "is_open": cal.is_market_open(),
            "next_open": cal.next_open().isoformat(),
            "next_close": cal.next_close().isoformat(),
            "minutes_to_close": cal.minutes_until_close(),
        })

    return router
