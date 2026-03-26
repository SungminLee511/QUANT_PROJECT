"""Session management API router — create, list, start, stop, delete sessions."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from monitoring.auth import get_current_user
from session.manager import SessionManager
from session.schemas import SessionCreate, SessionUpdate
from shared.enums import SessionType

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

    return router
