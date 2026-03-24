"""Session manager — orchestrates per-session trading pipelines.

Each session runs its own set of asyncio tasks:
  data feed -> strategy engine -> risk manager -> order router -> portfolio tracker

All isolated by session_id via Redis channel namespacing and DB foreign keys.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from db.models import TradingSession
from db.session import get_session
from shared.enums import Exchange, SessionType
from shared.redis_client import RedisClient, session_channel
from strategy.base import BaseStrategy
from strategy.engine import StrategyEngine
from risk.manager import RiskManager
from risk.kill_switch import KillSwitch
from execution.router import OrderRouter
from execution.sim_adapter import SimulationAdapter
from portfolio.tracker import PortfolioTracker

logger = logging.getLogger(__name__)

# Max retries for a crashed session pipeline
MAX_RESTART_ATTEMPTS = 3
RESTART_DELAY = 5  # seconds


class SessionPipeline:
    """All runtime state for a single session."""

    def __init__(self, session_id: str, session_type: SessionType):
        self.session_id = session_id
        self.session_type = session_type
        self.tasks: list[asyncio.Task] = []
        self.feed = None
        self.strategy_engine: StrategyEngine | None = None
        self.risk_manager: RiskManager | None = None
        self.order_router: OrderRouter | None = None
        self.portfolio_tracker: PortfolioTracker | None = None
        self.sim_adapter: SimulationAdapter | None = None
        self.running = False


class SessionManager:
    """Manages multiple trading session pipelines."""

    def __init__(self, config: dict, redis: RedisClient):
        self._config = config
        self._redis = redis
        self._pipelines: dict[str, SessionPipeline] = {}

    # ── CRUD ──────────────────────────────────────────────────────────

    async def create_session(
        self,
        name: str,
        session_type: SessionType,
        symbols: list[str],
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        starting_budget: float = 10000.0,
    ) -> str:
        """Create a new session in the DB and return its ID."""
        is_sim = session_type.is_simulation
        config_data = {
            "symbols": symbols,
            "api_key": api_key,
            "api_secret": api_secret,
            "testnet": testnet,
        }

        async with get_session() as db:
            ts = TradingSession(
                name=name,
                session_type=session_type.value,
                is_simulation=is_sim,
                config_json=json.dumps(config_data),
                starting_budget=starting_budget if is_sim else None,
                status="stopped",
            )
            db.add(ts)
            await db.flush()
            session_id = ts.id
            logger.info("Created session '%s' (id=%s, type=%s)", name, session_id, session_type.value)

        return session_id

    async def delete_session(self, session_id: str) -> bool:
        """Stop and remove a session."""
        # Stop first if running
        if session_id in self._pipelines:
            await self.stop_session(session_id)

        async with get_session() as db:
            from sqlalchemy import select, delete as sa_delete
            from db.models import Trade, Position, Order, EquitySnapshot, AlertLog

            # Delete dependent records first
            for model in [Trade, Position, Order, EquitySnapshot, AlertLog]:
                await db.execute(
                    sa_delete(model).where(model.session_id == session_id)
                )
            await db.execute(
                sa_delete(TradingSession).where(TradingSession.id == session_id)
            )

        logger.info("Deleted session %s", session_id)
        return True

    async def get_all_sessions(self) -> list[dict]:
        """Return info about all sessions from DB."""
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(TradingSession).order_by(TradingSession.created_at.desc())
            )
            sessions = result.scalars().all()
            return [self._session_to_dict(s) for s in sessions]

    async def get_session_info(self, session_id: str) -> dict | None:
        """Get info about a single session."""
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(TradingSession).where(TradingSession.id == session_id)
            )
            ts = result.scalar_one_or_none()
            if ts is None:
                return None
            return self._session_to_dict(ts)

    async def update_session(self, session_id: str, **kwargs) -> bool:
        """Update session fields (name, symbols, budget, api keys, etc.)."""
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(TradingSession).where(TradingSession.id == session_id)
            )
            ts = result.scalar_one_or_none()
            if ts is None:
                return False

            config_data = json.loads(ts.config_json or "{}")

            if "name" in kwargs and kwargs["name"] is not None:
                ts.name = kwargs["name"]
            if "symbols" in kwargs and kwargs["symbols"] is not None:
                config_data["symbols"] = kwargs["symbols"]
            if "api_key" in kwargs and kwargs["api_key"] is not None:
                config_data["api_key"] = kwargs["api_key"]
            if "api_secret" in kwargs and kwargs["api_secret"] is not None:
                config_data["api_secret"] = kwargs["api_secret"]
            if "testnet" in kwargs and kwargs["testnet"] is not None:
                config_data["testnet"] = kwargs["testnet"]
            if "starting_budget" in kwargs and kwargs["starting_budget"] is not None:
                ts.starting_budget = kwargs["starting_budget"]

            ts.config_json = json.dumps(config_data)

        return True

    # ── Start / Stop ──────────────────────────────────────────────────

    async def start_session(self, session_id: str) -> bool:
        """Start a session's trading pipeline."""
        if session_id in self._pipelines and self._pipelines[session_id].running:
            logger.warning("Session %s already running", session_id)
            return True

        info = await self.get_session_info(session_id)
        if info is None:
            logger.error("Session %s not found", session_id)
            return False

        session_type = SessionType(info["session_type"])
        config_data = info.get("config", {})
        symbols = config_data.get("symbols", ["BTCUSDT"])
        starting_budget = info.get("starting_budget") or self._config.get("sessions", {}).get("default_sim_budget", 10000.0)

        pipeline = SessionPipeline(session_id, session_type)
        self._pipelines[session_id] = pipeline

        try:
            await self._start_pipeline(pipeline, config_data, symbols, starting_budget)
            # Update DB status
            await self._set_session_status(session_id, "active")
            logger.info("Session %s started (type=%s, symbols=%s)", session_id, session_type.value, symbols)
            return True
        except Exception:
            logger.exception("Failed to start session %s", session_id)
            await self._set_session_status(session_id, "error")
            return False

    async def stop_session(self, session_id: str) -> bool:
        """Stop a session's trading pipeline."""
        pipeline = self._pipelines.get(session_id)
        if pipeline is None:
            return True

        pipeline.running = False

        # Cancel all tasks
        for task in pipeline.tasks:
            task.cancel()
        for task in pipeline.tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # Disconnect feed
        if pipeline.feed:
            try:
                await pipeline.feed.disconnect()
            except Exception:
                pass

        del self._pipelines[session_id]
        await self._set_session_status(session_id, "stopped")
        logger.info("Session %s stopped", session_id)
        return True

    async def stop_all(self) -> None:
        """Stop all running sessions."""
        for session_id in list(self._pipelines.keys()):
            await self.stop_session(session_id)

    def is_running(self, session_id: str) -> bool:
        pipeline = self._pipelines.get(session_id)
        return pipeline is not None and pipeline.running

    # ── Pipeline construction ────────────────────────────────────────

    async def _start_pipeline(
        self,
        pipeline: SessionPipeline,
        config_data: dict,
        symbols: list[str],
        starting_budget: float,
    ) -> None:
        """Build and start all components for a session."""
        sid = pipeline.session_id
        st = pipeline.session_type
        exchange = st.exchange

        # Build per-session config (channel overrides)
        session_config = self._build_session_config(sid, config_data, symbols)

        # 1. Data feed
        feed = self._create_feed(pipeline, symbols)
        pipeline.feed = feed

        # 2. Strategy engine (session-aware)
        engine = StrategyEngine(session_config, self._redis)
        pipeline.strategy_engine = engine

        # 3. Risk manager (session-aware)
        risk_mgr = RiskManager(session_config, self._redis)
        pipeline.risk_manager = risk_mgr

        # 4. Order router — sim or real
        if st.is_simulation:
            sim_adapter = SimulationAdapter(
                session_id=sid,
                starting_budget=starting_budget,
                exchange=exchange,
                redis=self._redis,
            )
            pipeline.sim_adapter = sim_adapter
            router = OrderRouter(session_config, self._redis, sim_adapter=sim_adapter, session_id=sid)
        else:
            router = OrderRouter(session_config, self._redis, session_id=sid)
        pipeline.order_router = router

        # 5. Portfolio tracker (session-aware)
        tracker = PortfolioTracker(session_config, self._redis, session_id=sid, starting_cash=starting_budget)
        pipeline.portfolio_tracker = tracker

        pipeline.running = True

        # Start everything as tasks with auto-restart
        pipeline.tasks = [
            asyncio.create_task(
                self._run_with_restart(sid, "feed", self._run_feed(feed)),
                name=f"session_{sid}_feed",
            ),
            asyncio.create_task(
                self._run_with_restart(sid, "strategy", engine.start()),
                name=f"session_{sid}_strategy",
            ),
            asyncio.create_task(
                self._run_with_restart(sid, "risk", risk_mgr.start()),
                name=f"session_{sid}_risk",
            ),
            asyncio.create_task(
                self._run_with_restart(sid, "router", router.start()),
                name=f"session_{sid}_router",
            ),
            asyncio.create_task(
                self._run_with_restart(sid, "portfolio", tracker.start()),
                name=f"session_{sid}_portfolio",
            ),
        ]

        if pipeline.sim_adapter:
            pipeline.tasks.append(
                asyncio.create_task(
                    self._run_with_restart(sid, "sim_price", sim_adapter.start_price_listener()),
                    name=f"session_{sid}_sim_price",
                )
            )

    def _create_feed(self, pipeline: SessionPipeline, symbols: list[str]):
        """Create the appropriate data feed for the session type."""
        st = pipeline.session_type
        sid = pipeline.session_id

        if st == SessionType.BINANCE_SIM:
            from data.binance_sim_feed import BinanceSimFeed
            return BinanceSimFeed(sid, symbols, self._redis)
        elif st == SessionType.ALPACA_SIM:
            from data.yfinance_feed import YFinanceFeed
            poll_interval = self._config.get("sessions", {}).get("yfinance_poll_interval_sec", 2)
            return YFinanceFeed(sid, symbols, self._redis, poll_interval=poll_interval)
        elif st == SessionType.BINANCE:
            from data.binance_feed import BinanceFeed
            # Build config with session-specific API keys
            session_cfg = json.loads(pipeline.__dict__.get("_config_json", "{}")) if hasattr(pipeline, "_config_json") else {}
            # Use the session-aware BinanceFeed (will be refactored later)
            from data.binance_sim_feed import BinanceSimFeed
            # For real Binance, use same feed structure (public WS for data)
            return BinanceSimFeed(sid, symbols, self._redis)
        elif st == SessionType.ALPACA:
            from data.yfinance_feed import YFinanceFeed
            # For real Alpaca, data still comes from yfinance (Alpaca data needs keys)
            poll_interval = self._config.get("sessions", {}).get("yfinance_poll_interval_sec", 2)
            return YFinanceFeed(sid, symbols, self._redis, poll_interval=poll_interval)
        else:
            raise ValueError(f"Unknown session type: {st}")

    async def _run_feed(self, feed) -> None:
        """Connect and subscribe a feed."""
        await feed.connect()
        await feed.subscribe()
        # Keep alive — some feeds block here, others don't
        if hasattr(feed, "run"):
            await feed.run()
        else:
            while True:
                await asyncio.sleep(1)

    def _build_session_config(self, session_id: str, config_data: dict, symbols: list[str]) -> dict:
        """Build a per-session config dict with namespaced Redis channels."""
        # Start with a copy of the global config
        import copy
        cfg = copy.deepcopy(self._config)

        # Override channels with session-namespaced versions
        cfg.setdefault("redis", {}).setdefault("channels", {})
        cfg["redis"]["channels"] = {
            "market_data": session_channel(session_id, "market:ticks"),
            "signals": session_channel(session_id, "strategy:signals"),
            "orders": session_channel(session_id, "execution:orders"),
            "order_updates": session_channel(session_id, "execution:updates"),
            "alerts": session_channel(session_id, "monitoring:alerts"),
        }

        # Override risk keys
        cfg.setdefault("risk", {})["kill_switch_key"] = session_channel(session_id, "risk:kill_switch")
        cfg["risk"]["portfolio_state_key"] = session_channel(session_id, "portfolio:state")

        # Set session-specific exchange config
        if config_data.get("api_key"):
            exchange_key = "binance" if "binance" in config_data.get("type", "") else "alpaca"
            cfg.setdefault(exchange_key, {}).update({
                "api_key": config_data.get("api_key", ""),
                "api_secret": config_data.get("api_secret", ""),
                "symbols": symbols,
            })

        return cfg

    async def _run_with_restart(self, session_id: str, component: str, coro) -> None:
        """Run a coroutine with auto-restart on failure."""
        for attempt in range(1, MAX_RESTART_ATTEMPTS + 1):
            try:
                await coro
                return  # Clean exit
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(
                    "Session %s component '%s' crashed (attempt %d/%d)",
                    session_id, component, attempt, MAX_RESTART_ATTEMPTS,
                )
                if attempt < MAX_RESTART_ATTEMPTS:
                    await asyncio.sleep(RESTART_DELAY)
                else:
                    logger.error(
                        "Session %s component '%s' exhausted retries",
                        session_id, component,
                    )
                    await self._set_session_status(session_id, "error")

    # ── Helpers ──────────────────────────────────────────────────────

    async def _set_session_status(self, session_id: str, status: str) -> None:
        """Update a session's status in the DB."""
        from sqlalchemy import select

        try:
            async with get_session() as db:
                result = await db.execute(
                    select(TradingSession).where(TradingSession.id == session_id)
                )
                ts = result.scalar_one_or_none()
                if ts:
                    ts.status = status
        except Exception:
            logger.exception("Failed to update session status for %s", session_id)

    @staticmethod
    def _session_to_dict(ts: TradingSession) -> dict:
        """Convert a TradingSession ORM object to a dict."""
        config_data = json.loads(ts.config_json or "{}")
        return {
            "id": ts.id,
            "name": ts.name,
            "session_type": ts.session_type,
            "is_simulation": ts.is_simulation,
            "status": ts.status,
            "starting_budget": ts.starting_budget,
            "symbols": config_data.get("symbols", []),
            "strategy_class": ts.strategy_class,
            "strategy_code": ts.strategy_code or "",
            "config": config_data,
            "created_at": ts.created_at.isoformat() if ts.created_at else "",
        }
