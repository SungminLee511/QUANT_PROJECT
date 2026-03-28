"""Backtest router — run backtests from the web UI and return results."""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from monitoring.auth import get_current_user, require_auth
from session.manager import SessionManager
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


def create_backtest_router(
    config: dict, redis: RedisClient, templates: Jinja2Templates,
    session_manager: SessionManager,
) -> APIRouter:
    router = APIRouter(prefix="/backtest")

    # ── Page ─────────────────────────────────────────────────────────

    @router.get("")
    async def backtest_page(request: Request, session_id: Optional[str] = Query(None)):
        redirect = require_auth(request)
        if redirect:
            return redirect
        sessions = await session_manager.get_all_sessions()
        for s in sessions:
            s["is_running"] = session_manager.is_running(s["id"])
        return templates.TemplateResponse(request, "backtest.html", {
            "user": get_current_user(request),
            "sessions": sessions,
            "active_page": "backtest",
            "selected_session": session_id,
        })

    # ── API ──────────────────────────────────────────────────────────

    @router.post("/api/run")
    async def run_backtest(request: Request):
        """Run a backtest with the provided parameters.

        Expected JSON body:
        {
            "strategy_code": "...",          # Python source code
            "symbols": ["AAPL", "MSFT"],     # List of symbols
            "start_date": "2024-01-01",      # YYYY-MM-DD
            "end_date": "2025-01-01",        # YYYY-MM-DD
            "starting_cash": 10000,          # Starting portfolio value
            "interval": "1d",               # Bar interval (1d, 1wk, 1mo)
            "strategy_params": {},           # Optional params dict
            "session_id": "..."             # Optional — load code from session
        }
        """
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()

        # Get strategy code — from body or from session
        strategy_code = body.get("strategy_code", "")
        session_id = body.get("session_id")

        if not strategy_code and session_id:
            info = await session_manager.get_session_info(session_id)
            if info and info.get("strategy_code"):
                strategy_code = info["strategy_code"]

        if not strategy_code.strip():
            return JSONResponse({
                "success": False,
                "errors": ["No strategy code provided"],
            })

        symbols = body.get("symbols", [])
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]

        if not symbols:
            return JSONResponse({
                "success": False,
                "errors": ["No symbols provided"],
            })

        start_date = body.get("start_date", "")
        end_date = body.get("end_date", "")
        if not start_date or not end_date:
            return JSONResponse({
                "success": False,
                "errors": ["Start date and end date are required"],
            })

        # FAUDIT-22: Safely convert numeric inputs (reject non-numeric with user-friendly error)
        try:
            starting_cash = float(body.get("starting_cash", 10000))
            short_loss_limit_pct = float(body.get("short_loss_limit_pct", 1.0))
            commission_pct = float(body.get("commission_pct", 0.0))
        except (ValueError, TypeError) as e:
            return JSONResponse({
                "success": False,
                "errors": [f"Invalid numeric input: {e}"],
            })
        interval = body.get("interval", "1d")
        # Track which fields user explicitly provided vs. defaulted
        _has_strategy_mode = "strategy_mode" in body
        _has_short_loss = "short_loss_limit_pct" in body
        _has_commission = "commission_pct" in body

        strategy_mode = body.get("strategy_mode", "rebalance")

        # Determine if crypto session — check multiple signals
        is_crypto = False
        session_type = body.get("session_type", "")

        # Get data config from body or session
        data_config = body.get("data_config")
        if session_id:
            info = await session_manager.get_session_info(session_id)
            if info:
                if not data_config and info.get("data_config"):
                    data_config = info["data_config"]
                if not session_type:
                    session_type = info.get("session_type", "")

        # Signal 1: explicit session_type
        if session_type.startswith("binance"):
            is_crypto = True

        # Signal 2: auto-detect from symbols (BTCUSDT, ETHBUSD, etc.)
        if not is_crypto and symbols:
            crypto_suffixes = ("USDT", "BUSD", "USDC")
            if any(s.upper().endswith(crypto_suffixes) for s in symbols):
                is_crypto = True

        logger.info("Backtest: session_type=%r, is_crypto=%s, symbols=%s",
                     session_type, is_crypto, symbols[:3])

        # Run backtest in a thread executor (yfinance is blocking)
        from backtest.engine import run_backtest_async

        try:
            # Fall back to data_config values only if user didn't explicitly provide them
            if data_config:
                if not _has_strategy_mode:
                    strategy_mode = data_config.get("strategy_mode", strategy_mode)
                if not _has_short_loss:
                    short_loss_limit_pct = float(data_config.get("short_loss_limit_pct", short_loss_limit_pct))
                if not _has_commission:
                    commission_pct = float(data_config.get("commission_pct", commission_pct))

            result = await run_backtest_async(
                strategy_code=strategy_code,
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                starting_cash=starting_cash,
                interval=interval,
                data_config=data_config,
                strategy_mode=strategy_mode,
                short_loss_limit_pct=short_loss_limit_pct,
                commission_pct=commission_pct,
                is_crypto=is_crypto,
            )
            return JSONResponse(result.to_dict())

        except Exception as e:
            logger.exception("Backtest failed")
            return JSONResponse({
                "success": False,
                "errors": ["Backtest failed — see server logs"],
            })

    @router.get("/api/load-code")
    async def load_strategy_code(request: Request, session_id: Optional[str] = Query(None)):
        """Load strategy code + data config for the backtest page."""
        if not get_current_user(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if session_id:
            info = await session_manager.get_session_info(session_id)
            if info and info.get("strategy_code"):
                return JSONResponse({
                    "code": info["strategy_code"],
                    "data_config": info.get("data_config"),
                    "source": "session",
                    "symbols": info.get("symbols", []),
                    "starting_budget": info.get("starting_budget", 10000),
                    "session_type": info.get("session_type", ""),
                })

        # Fallback to default strategy
        from pathlib import Path
        from session.manager import DEFAULT_DATA_CONFIG
        default = Path(__file__).resolve().parent.parent / "strategy" / "examples" / "momentum_v2.py"
        # BUG-28 fix: guard against missing file
        try:
            code = default.read_text()
        except (FileNotFoundError, OSError):
            code = "import numpy as np\n\ndef main(data):\n    return np.zeros(data['price'].shape[0])\n"
        return JSONResponse({
            "code": code,
            "data_config": DEFAULT_DATA_CONFIG,
            "source": "default",
            "symbols": [],
        })

    return router
