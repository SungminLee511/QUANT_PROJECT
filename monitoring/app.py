"""FastAPI app factory — mounts auth, dashboard, and editor routers."""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import check_credentials, create_session, destroy_session, get_current_user, require_auth
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(config: dict, redis: RedisClient) -> FastAPI:
    """Create the FastAPI application with all routes."""
    app = FastAPI(title="Quant Trader")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Store config and redis in app state for access in sub-routers
    app.state.config = config
    app.state.redis = redis
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
    app.include_router(create_dashboard_router(config, redis, templates))

    # ── Strategy Editor ──────────────────────────────────────────────

    from monitoring.editor import create_editor_router
    app.include_router(create_editor_router(config, redis, templates))

    return app
