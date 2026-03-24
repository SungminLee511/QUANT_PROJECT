"""Settings router — API key management via the web UI, saved to .env file."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import get_current_user, require_auth
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Keys we manage through the settings page
MANAGED_KEYS = [
    "QT_BINANCE_API_KEY",
    "QT_BINANCE_API_SECRET",
    "QT_ALPACA_API_KEY",
    "QT_ALPACA_API_SECRET",
    "QT_BINANCE_TESTNET",
    "QT_ALPACA_PAPER",
]


def _read_env() -> dict[str, str]:
    """Read .env file into a dict. Ignores comments and blank lines."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    """Write dict back to .env file, preserving comments for unmanaged keys."""
    lines = []
    existing_lines = []
    written_keys = set()

    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text().splitlines()

    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in env:
                lines.append(f"{key}={env[key]}")
                written_keys.add(key)
                continue
        lines.append(line)

    # Append new keys not already in the file
    for key, value in env.items():
        if key not in written_keys:
            lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n")


def _mask_key(value: str) -> str:
    """Mask API key for display: show first 4 and last 4 chars."""
    if not value or len(value) <= 8:
        return "****" if value else ""
    return value[:4] + "****" + value[-4:]


def create_settings_router(
    config: dict, redis: RedisClient, templates: Jinja2Templates
) -> APIRouter:
    router = APIRouter(prefix="/settings")

    @router.get("")
    async def settings_page(request: Request):
        redirect = require_auth(request)
        if redirect:
            return redirect
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "user": get_current_user(request),
        })

    @router.get("/api/load")
    async def load_settings(request: Request):
        """Load current API key settings (masked) and toggle states."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        env = _read_env()
        return JSONResponse({
            "binance_api_key": _mask_key(env.get("QT_BINANCE_API_KEY", "")),
            "binance_api_secret": _mask_key(env.get("QT_BINANCE_API_SECRET", "")),
            "alpaca_api_key": _mask_key(env.get("QT_ALPACA_API_KEY", "")),
            "alpaca_api_secret": _mask_key(env.get("QT_ALPACA_API_SECRET", "")),
            "binance_testnet": env.get("QT_BINANCE_TESTNET", "true").lower() == "true",
            "alpaca_paper": env.get("QT_ALPACA_PAPER", "true").lower() == "true",
            "has_binance": bool(env.get("QT_BINANCE_API_KEY", "")),
            "has_alpaca": bool(env.get("QT_ALPACA_API_KEY", "")),
        })

    @router.post("/api/save")
    async def save_settings(request: Request):
        """Save API keys and toggles to .env file."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        env = _read_env()

        # Only overwrite keys if user actually provided a new value (not masked)
        for field, env_key in [
            ("binance_api_key", "QT_BINANCE_API_KEY"),
            ("binance_api_secret", "QT_BINANCE_API_SECRET"),
            ("alpaca_api_key", "QT_ALPACA_API_KEY"),
            ("alpaca_api_secret", "QT_ALPACA_API_SECRET"),
        ]:
            value = body.get(field, "")
            if value and "****" not in value:
                env[env_key] = value

        # Toggles always get written
        env["QT_BINANCE_TESTNET"] = str(body.get("binance_testnet", True)).lower()
        env["QT_ALPACA_PAPER"] = str(body.get("alpaca_paper", True)).lower()

        # Ensure env is set
        if "QT_ENV" not in env:
            env["QT_ENV"] = "dev"

        _write_env(env)
        logger.info("Settings saved to %s", ENV_FILE)

        return JSONResponse({
            "saved": True,
            "message": "Settings saved. Restart services to apply changes.",
        })

    return router
