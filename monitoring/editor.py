"""Strategy editor router (V2) — tabbed UI for data config, custom data, and strategy code.

Three tabs:
1. Data Config — resolution, fields, lookbacks, strategy execution multiplier
2. Custom Data Functions — user-provided fetch() functions for extra data
3. Strategy Code — main(data) function
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import get_current_user, require_auth
from session.manager import SessionManager, DEFAULT_DATA_CONFIG
from shared.redis_client import RedisClient
from strategy.validator_v2 import validate_strategy_code
from strategy.custom_validator import validate_custom_data_function

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STRATEGY = PROJECT_ROOT / "strategy" / "examples" / "momentum_v2.py"


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

    # ── Load all editor data ──────────────────────────────────────────

    @router.get("/api/load")
    async def load_editor_data(request: Request, session_id: Optional[str] = Query(None)):
        """Load all editor data: strategy code, data config, custom data functions."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if session_id:
            info = await session_manager.get_session_info(session_id)
            if info:
                return JSONResponse({
                    "strategy_code": info.get("strategy_code") or DEFAULT_STRATEGY.read_text(),
                    "data_config": info.get("data_config") or DEFAULT_DATA_CONFIG,
                    "custom_data_code": info.get("custom_data_code") or [],
                    "source": "session" if info.get("strategy_code") else "default",
                    "session_id": session_id,
                })

        # Fallback: default
        return JSONResponse({
            "strategy_code": DEFAULT_STRATEGY.read_text(),
            "data_config": DEFAULT_DATA_CONFIG,
            "custom_data_code": [],
            "source": "default",
        })

    # ── Validate strategy code ────────────────────────────────────────

    @router.post("/api/validate")
    async def validate_strategy(request: Request):
        """Validate V2 strategy code (main function)."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        code = body.get("code", "")
        data_config = body.get("data_config")

        if not code.strip():
            return JSONResponse({
                "valid": False,
                "errors": ["Code is empty"],
                "warnings": [],
            })

        result = validate_strategy_code(code, data_config)
        return JSONResponse({
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
        })

    # ── Validate custom data function ─────────────────────────────────

    @router.post("/api/validate-custom")
    async def validate_custom(request: Request):
        """Validate a custom data function."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        code = body.get("code", "")
        func_type = body.get("type", "per_stock")

        if not code.strip():
            return JSONResponse({
                "valid": False,
                "errors": ["Code is empty"],
                "warnings": [],
            })

        result = validate_custom_data_function(code, func_type)
        return JSONResponse({
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
        })

    # ── Deploy (save all) ─────────────────────────────────────────────

    @router.post("/api/deploy")
    async def deploy_all(request: Request, session_id: Optional[str] = Query(None)):
        """Validate and save all three sections to DB.

        Body: {
            "strategy_code": "...",
            "data_config": {...},
            "custom_data_code": [...],
            "session_id": "..."
        }
        """
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        strategy_code = body.get("strategy_code", "")
        data_config = body.get("data_config", DEFAULT_DATA_CONFIG)
        custom_data_code = body.get("custom_data_code", [])
        session_id = session_id or body.get("session_id")

        if not session_id:
            return JSONResponse({"deployed": False, "errors": ["No session selected"]})

        errors = []

        # 1. Validate strategy code
        if strategy_code.strip():
            result = validate_strategy_code(strategy_code, data_config)
            if not result.valid:
                errors.extend([f"Strategy: {e}" for e in result.errors])

        # 2. Validate custom data functions
        for i, item in enumerate(custom_data_code):
            code = item.get("code", "")
            func_type = item.get("type", "per_stock")
            name = item.get("name", f"custom_{i}")
            if code.strip():
                result = validate_custom_data_function(code, func_type)
                if not result.valid:
                    errors.extend([f"Custom data '{name}': {e}" for e in result.errors])

        if errors:
            return JSONResponse({"deployed": False, "errors": errors})

        # 3. Save to DB
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

                ts.strategy_code = strategy_code
                ts.data_config = json.dumps(data_config)
                ts.custom_data_code = json.dumps(custom_data_code)

            logger.info("Strategy V2 deployed to session %s", session_id)

            return JSONResponse({
                "deployed": True,
                "message": "Strategy deployed successfully. Restart session to apply changes.",
            })
        except Exception as e:
            logger.exception("Failed to deploy to session %s", session_id)
            return JSONResponse({"deployed": False, "errors": [str(e)]})

    # ── Reset to default ──────────────────────────────────────────────

    @router.post("/api/reset")
    async def reset_to_default(request: Request):
        """Reset to default momentum_v2 strategy and default data config."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        return JSONResponse({
            "strategy_code": DEFAULT_STRATEGY.read_text(),
            "data_config": DEFAULT_DATA_CONFIG,
            "custom_data_code": [],
            "source": "default",
        })

    return router
