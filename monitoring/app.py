"""FastAPI app factory — mounts auth, dashboard, editor, settings, and sessions routers."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import check_credentials, create_session, destroy_session, get_current_user, require_auth

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Set by run_monitor.py before uvicorn starts
_boot_config: dict | None = None


class _Proxy:
    """Mutable proxy — set the real object later with .set(), attribute access delegates."""

    def __init__(self):
        self._obj = None

    def set(self, obj):
        self._obj = obj

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if self._obj is None:
            raise RuntimeError("Proxy not initialized yet")
        return getattr(self._obj, name)

    def __bool__(self):
        return self._obj is not None


def build_app() -> FastAPI:
    """Factory callable for ``uvicorn --factory`` mode.

    All async init (DB, Redis) happens in the lifespan so that
    everything runs inside uvicorn's event loop (avoids asyncpg
    'attached to a different loop' errors).
    """
    config = _boot_config
    if config is None:
        from shared.config import load_config
        config = load_config()

    return create_app(config)


def create_app(config: dict) -> FastAPI:
    """Create the FastAPI application with all routes."""

    # Proxies filled during lifespan — routers capture them in closures,
    # but never dereference until a request arrives (after lifespan startup).
    redis_proxy = _Proxy()
    sm_proxy = _Proxy()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from db.session import init_engine, init_db, close_db
        from shared.redis_client import create_redis_client
        from session.manager import SessionManager

        # ── Async init (runs inside uvicorn's event loop) ──
        init_engine(config)
        await init_db()
        logger.info("Database initialized")

        redis = create_redis_client(config)
        await redis.connect()
        logger.info("Redis connected")

        session_manager = SessionManager(config, redis)

        # Fill proxies so routers can use them
        redis_proxy.set(redis)
        sm_proxy.set(session_manager)

        app.state.config = config
        app.state.redis = redis
        app.state.session_manager = session_manager

        # Auto-restart previously active sessions
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

        logger.info("Shutting down — stopping all sessions...")
        await session_manager.stop_all()
        await redis.disconnect()
        await close_db()

    app = FastAPI(title="Quant Trader", lifespan=lifespan)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # ── Auth routes ──────────────────────────────────────────────────

    @app.get("/login")
    async def login_page(request: Request):
        user = get_current_user(request)
        if user:
            return RedirectResponse(url="/overview", status_code=302)
        return templates.TemplateResponse(request, "login.html", {
            "error": None,
        })

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")

        if check_credentials(username, password, config):
            response = RedirectResponse(url="/overview", status_code=302)
            ttl = config.get("auth", {}).get("session_ttl_hours", 24)
            create_session(response, username, ttl)
            logger.info("User '%s' logged in", username)
            return response

        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid username or password",
        })

    @app.get("/logout")
    async def logout(request: Request):
        response = RedirectResponse(url="/login", status_code=302)
        destroy_session(request, response)
        return response

    # ── Dashboard ────────────────────────────────────────────────────

    from monitoring.dashboard import create_dashboard_router
    app.include_router(create_dashboard_router(config, redis_proxy, templates, sm_proxy))

    # ── Strategy Editor ──────────────────────────────────────────────

    from monitoring.editor import create_editor_router
    app.include_router(create_editor_router(config, redis_proxy, templates, sm_proxy))

    # ── Settings ─────────────────────────────────────────────────────

    from monitoring.settings import create_settings_router
    app.include_router(create_settings_router(config, redis_proxy, templates, sm_proxy))

    # ── Backtest ──────────────────────────────────────────────────────

    from monitoring.backtest import create_backtest_router
    app.include_router(create_backtest_router(config, redis_proxy, templates, sm_proxy))

    # ── Logs ──────────────────────────────────────────────────────────

    from monitoring.logs import create_logs_router
    app.include_router(create_logs_router(config, redis_proxy, templates, sm_proxy))

    # ── Sessions API ─────────────────────────────────────────────────

    from monitoring.sessions import create_sessions_router
    app.include_router(create_sessions_router(sm_proxy))

    return app
