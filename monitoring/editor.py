"""Strategy editor router — load, save, validate, and deploy user strategies."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import get_current_user, require_auth
from shared.redis_client import RedisClient
from strategy.validator import validate_strategy_code

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STRATEGY = PROJECT_ROOT / "strategy" / "examples" / "momentum.py"
USER_STRATEGIES_DIR = PROJECT_ROOT / "strategy" / "user_strategies"
ACTIVE_STRATEGY_FILE = USER_STRATEGIES_DIR / "active_strategy.py"


def create_editor_router(
    config: dict, redis: RedisClient, templates: Jinja2Templates
) -> APIRouter:
    router = APIRouter(prefix="/editor")

    # ── Page ─────────────────────────────────────────────────────────

    @router.get("")
    async def editor_page(request: Request):
        redirect = require_auth(request)
        if redirect:
            return redirect
        return templates.TemplateResponse("editor.html", {
            "request": request,
            "user": get_current_user(request),
        })

    # ── API ──────────────────────────────────────────────────────────

    @router.get("/api/load")
    async def load_strategy(request: Request):
        """Load the current active strategy, or the default if none exists."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        # Try active user strategy first, then fall back to default
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
    async def deploy_strategy(request: Request):
        """Validate, save, and hot-reload the strategy."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        code = body.get("code", "")

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

        # Save to user_strategies/active_strategy.py
        USER_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVE_STRATEGY_FILE.write_text(code)
        logger.info(
            "Strategy deployed: class=%s, saved to %s",
            result.class_name, ACTIVE_STRATEGY_FILE,
        )

        # Signal the strategy engine to reload via Redis
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
