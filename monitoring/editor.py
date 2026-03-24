"""Strategy editor router — load, save, validate, and deploy user strategies.

When session_id is provided, strategy code is stored in the DB (TradingSession.strategy_code)
rather than the filesystem, enabling per-session strategies.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import get_current_user, require_auth
from session.manager import SessionManager
from shared.redis_client import RedisClient
from strategy.validator import validate_strategy_code

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STRATEGY = PROJECT_ROOT / "strategy" / "examples" / "momentum.py"
USER_STRATEGIES_DIR = PROJECT_ROOT / "strategy" / "user_strategies"
ACTIVE_STRATEGY_FILE = USER_STRATEGIES_DIR / "active_strategy.py"


def create_editor_router(
    config: dict, redis: RedisClient, templates: Jinja2Templates,
    session_manager: SessionManager,
) -> APIRouter:
    router = APIRouter(prefix="/editor")

    # ── Page ─────────────────────────────────────────────────────────

    @router.get("")
    async def editor_page(request: Request, session_id: Optional[str] = Query(None)):
        redirect = require_auth(request)
        if redirect:
            return redirect
        sessions = await session_manager.get_all_sessions()
        for s in sessions:
            s["is_running"] = session_manager.is_running(s["id"])
        return templates.TemplateResponse(request, "editor.html", {
            "user": get_current_user(request),
            "sessions": sessions,
            "active_page": "editor",
            "selected_session": session_id,
        })

    # ── API ──────────────────────────────────────────────────────────

    @router.get("/api/load")
    async def load_strategy(request: Request, session_id: Optional[str] = Query(None)):
        """Load strategy code. If session_id provided, loads from DB; else from filesystem."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if session_id:
            # Load from DB
            info = await session_manager.get_session_info(session_id)
            if info and info.get("strategy_code"):
                return JSONResponse({
                    "code": info["strategy_code"],
                    "source": "session",
                    "session_id": session_id,
                })

        # Fallback: try active user strategy, then default
        if ACTIVE_STRATEGY_FILE.exists():
            code = ACTIVE_STRATEGY_FILE.read_text()
            source = "user"
        else:
            code = DEFAULT_STRATEGY.read_text()
            source = "default"

        return JSONResponse({"code": code, "source": source})

    @router.post("/api/validate")
    async def validate_strategy(request: Request):
        """Validate strategy code without saving."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        code = body.get("code", "")

        if not code.strip():
            return JSONResponse({
                "valid": False,
                "errors": ["Code is empty"],
                "warnings": [],
                "class_name": "",
            })

        result = validate_strategy_code(code)
        return JSONResponse({
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "class_name": result.class_name,
        })

    @router.post("/api/deploy")
    async def deploy_strategy(request: Request, session_id: Optional[str] = Query(None)):
        """Validate, save, and hot-reload the strategy.

        If session_id is provided, saves to DB and signals that session's strategy engine.
        Otherwise saves to filesystem (legacy single-session mode).
        """
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        code = body.get("code", "")
        # Allow session_id in body too (from frontend)
        session_id = session_id or body.get("session_id")

        if not code.strip():
            return JSONResponse({
                "deployed": False,
                "errors": ["Code is empty"],
            })

        # Validate first
        result = validate_strategy_code(code)
        if not result.valid:
            return JSONResponse({
                "deployed": False,
                "errors": result.errors,
            })

        if session_id:
            # Save to DB
            from sqlalchemy import select
            from db.session import get_session as get_db_session
            from db.models import TradingSession

            try:
                async with get_db_session() as db:
                    stmt = select(TradingSession).where(TradingSession.id == session_id)
                    res = await db.execute(stmt)
                    ts = res.scalar_one_or_none()
                    if ts is None:
                        return JSONResponse({"deployed": False, "errors": ["Session not found"]})
                    ts.strategy_code = code
                    ts.strategy_class = result.class_name

                logger.info(
                    "Strategy deployed to session %s: class=%s",
                    session_id, result.class_name,
                )

                # Signal session's strategy engine to reload
                from shared.redis_client import session_channel
                reload_key = session_channel(session_id, "strategy:reload")
                await redis.set_flag(reload_key, {
                    "class_name": result.class_name,
                    "source": "session_db",
                })
                await redis.redis.publish(reload_key, "reload")

                return JSONResponse({
                    "deployed": True,
                    "class_name": result.class_name,
                    "message": f"Strategy '{result.class_name}' deployed to session.",
                })
            except Exception as e:
                logger.exception("Failed to deploy strategy to session %s", session_id)
                return JSONResponse({"deployed": False, "errors": [str(e)]})
        else:
            # Legacy: save to filesystem
            USER_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
            ACTIVE_STRATEGY_FILE.write_text(code)
            logger.info(
                "Strategy deployed: class=%s, saved to %s",
                result.class_name, ACTIVE_STRATEGY_FILE,
            )

            try:
                await redis.set_flag("strategy:reload", {
                    "module": "strategy.user_strategies.active_strategy",
                    "class_name": result.class_name,
                })
                await redis.redis.publish("strategy:reload", "reload")
            except Exception:
                logger.exception("Failed to signal strategy reload")

            return JSONResponse({
                "deployed": True,
                "class_name": result.class_name,
                "message": f"Strategy '{result.class_name}' deployed successfully.",
            })

    @router.post("/api/reset")
    async def reset_to_default(request: Request):
        """Reset to the default momentum strategy."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        code = DEFAULT_STRATEGY.read_text()
        return JSONResponse({"code": code, "source": "default"})

    return router
