"""FastAPI app factory — mounts auth, dashboard, editor, settings, and sessions routers."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import check_credentials, create_session, destroy_session, get_current_user, require_auth
from session.manager import SessionManager
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(config: dict, redis: RedisClient, session_manager: SessionManager) -> FastAPI:
    """Create the FastAPI application with all routes."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # On startup: auto-restart previously active sessions
        try:
            sessions = await session_manager.get_all_sessions()
            active = [s for s in sessions if s.get("status") == "active"]
            if active:
                logger.info("Auto-restarting %d previously active session(s)...", len(active))
                for s in active:
                    try:
                        await session_manager.start_session(s["id"])
                        logger.info("  Restarted session '%s' (%s)", s["name"], s["id"])
                    except Exception:
                        logger.exception("  Failed to restart session '%s' (%s)", s["name"], s["id"])
        except Exception:
            logger.exception("Error during session auto-restart")

        yield

        # On shutdown: stop all running sessions gracefully
        logger.info("Shutting down — stopping all sessions...")
        await session_manager.stop_all()

    app = FastAPI(title="Quant Trader", lifespan=lifespan)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Store config, redis, session_manager, templates in app state
    app.state.config = config
    app.state.redis = redis
    app.state.session_manager = session_manager
    app.state.templates = templates

    # ── Auth routes ──────────────────────────────────────────────────

    @app.get("/login")
    async def login_page(request: Request):
        user = get_current_user(request)
        if user:
            return RedirectResponse(url="/", status_code=302)
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": None,
        })

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")

        if check_credentials(username, password, config):
            response = RedirectResponse(url="/", status_code=302)
            ttl = config.get("auth", {}).get("session_ttl_hours", 24)
            create_session(response, username, ttl)
            logger.info("User '%s' logged in", username)
            return response

        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password",
        })

    @app.get("/logout")
    async def logout(request: Request):
        response = RedirectResponse(url="/login", status_code=302)
        destroy_session(request, response)
        return response

    # ── Dashboard ────────────────────────────────────────────────────

    from monitoring.dashboard import create_dashboard_router
    app.include_router(create_dashboard_router(config, redis, templates, session_manager))

    # ── Strategy Editor ──────────────────────────────────────────────

    from monitoring.editor import create_editor_router
    app.include_router(create_editor_router(config, redis, templates, session_manager))

    # ── Settings ─────────────────────────────────────────────────────

    from monitoring.settings import create_settings_router
    app.include_router(create_settings_router(config, redis, templates, session_manager))

    # ── Sessions API ─────────────────────────────────────────────────

    from monitoring.sessions import create_sessions_router
    app.include_router(create_sessions_router(session_manager))

    return app
