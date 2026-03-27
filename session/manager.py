"""Session manager — orchestrates per-session trading pipelines (V2).

Each session runs:
  DataCollector -> StrategyExecutor -> WeightRebalancer -> OrderRouter -> PortfolioTracker

All isolated by session_id via Redis channel namespacing and DB foreign keys.
"""

import asyncio
import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from db.models import TradingSession
from db.session import get_session
from shared.enums import Exchange, SessionType
from shared.redis_client import RedisClient, session_channel
from shared.schemas import LogEntry, MarketTick

from data.collector import DataCollector
from strategy.executor import StrategyExecutor
from strategy.rebalancer import WeightRebalancer
from execution.router import OrderRouter
from execution.sim_adapter import SimulationAdapter
from portfolio.tracker import PortfolioTracker
from risk.kill_switch import KillSwitch
from risk.limits import check_portfolio_risk, check_short_loss
from shared.market_calendar import MarketCalendar

logger = logging.getLogger(__name__)

# Max retries for a crashed session pipeline
MAX_RESTART_ATTEMPTS = 3
RESTART_DELAY = 5  # seconds

# Default data config for new sessions
DEFAULT_DATA_CONFIG = {
    "resolution": "1min",
    "exec_every_n": 1,
    "schedule_mode": "always_on",
    "strategy_mode": "rebalance",
    "short_loss_limit_pct": 1.0,
    "max_daily_loss_pct": 0.03,
    "commission_pct": 0.0,
    "fields": {
        "price": {"enabled": True, "lookback": 20},
    },
    "custom_data": [],
    "custom_global_data": [],
}

DEFAULT_STRATEGY_PATH = Path(__file__).resolve().parent.parent / "strategy" / "examples" / "momentum_v2.py"


class SessionPipeline:
    """All runtime state for a single session."""

    def __init__(self, session_id: str, session_type: SessionType, schedule_mode: str = "always_on", strategy_mode: str = "rebalance"):
        self.session_id = session_id
        self.session_type = session_type
        self.schedule_mode = schedule_mode
        self.strategy_mode = strategy_mode
        self.calendar: MarketCalendar | None = None
        self.tasks: list[asyncio.Task] = []
        self.collector: DataCollector | None = None
        self.executor: StrategyExecutor | None = None
        self.rebalancer: WeightRebalancer | None = None
        self.order_router: OrderRouter | None = None
        self.portfolio_tracker: PortfolioTracker | None = None
        self.sim_adapter: SimulationAdapter | None = None
        self.running = False
        self.data_config: dict = {}
        # Short position entry prices — for kill switch tracking
        self.short_entry_prices: dict[str, float] = {}


class SessionManager:
    """Manages multiple trading session pipelines."""

    def __init__(self, config: dict, redis: RedisClient):
        self._config = config
        self._redis = redis
        self._pipelines: dict[str, SessionPipeline] = {}

    # ── Public Accessors ─────────────────────────────────────────────

    def get_pipeline(self, session_id: str) -> SessionPipeline | None:
        """Return the pipeline for a running session, or None."""
        return self._pipelines.get(session_id)

    @property
    def redis(self) -> RedisClient:
        """Return the shared Redis client."""
        return self._redis

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
        universe_preset: str = "",
    ) -> str:
        """Create a new session in the DB and return its ID."""
        is_sim = session_type.is_simulation
        config_data = {
            "symbols": symbols,
            "api_key": api_key,
            "api_secret": api_secret,
            "testnet": testnet,
        }
        if universe_preset:
            config_data["universe_preset"] = universe_preset

        # Default strategy code
        default_code = ""
        if DEFAULT_STRATEGY_PATH.exists():
            default_code = DEFAULT_STRATEGY_PATH.read_text()

        async with get_session() as db:
            ts = TradingSession(
                name=name,
                session_type=session_type.value,
                is_simulation=is_sim,
                config_json=json.dumps(config_data),
                starting_budget=starting_budget if is_sim else None,
                status="stopped",
                strategy_code=default_code,
                data_config=json.dumps(DEFAULT_DATA_CONFIG),
                custom_data_code=json.dumps([]),
            )
            db.add(ts)
            await db.flush()
            session_id = ts.id
            logger.info("Created session '%s' (id=%s, type=%s)", name, session_id, session_type.value)

        return session_id

    async def delete_session(self, session_id: str) -> bool:
        """Stop and remove a session."""
        if session_id in self._pipelines:
            await self.stop_session(session_id)

        async with get_session() as db:
            from sqlalchemy import select, delete as sa_delete
            from db.models import Trade, Position, Order, EquitySnapshot, AlertLog

            for model in [Trade, Position, Order, EquitySnapshot, AlertLog]:
                await db.execute(
                    sa_delete(model).where(model.session_id == session_id)
                )
            await db.execute(
                sa_delete(TradingSession).where(TradingSession.id == session_id)
            )

        # Clean up in-memory log buffers
        from monitoring.logs import cleanup_session_logs
        cleanup_session_logs(session_id)

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

    async def get_session_info(self, session_id: str, *, mask_secrets: bool = True) -> dict | None:
        """Get info about a single session."""
        from sqlalchemy import select

        try:
            async with get_session() as db:
                result = await db.execute(
                    select(TradingSession).where(TradingSession.id == session_id)
                )
                ts = result.scalar_one_or_none()
                if ts is None:
                    return None
                return self._session_to_dict(ts, mask_secrets=mask_secrets)
        except Exception:
            logger.exception("Failed to fetch session info for %s", session_id)
            return None

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

            # BUG-19 fix: handle strategy_code, data_config, custom_data_code
            if "strategy_code" in kwargs and kwargs["strategy_code"] is not None:
                ts.strategy_code = kwargs["strategy_code"]
            if "data_config" in kwargs and kwargs["data_config"] is not None:
                ts.data_config = json.dumps(kwargs["data_config"]) if isinstance(kwargs["data_config"], dict) else kwargs["data_config"]
            if "custom_data_code" in kwargs and kwargs["custom_data_code"] is not None:
                ts.custom_data_code = json.dumps(kwargs["custom_data_code"]) if isinstance(kwargs["custom_data_code"], list) else kwargs["custom_data_code"]

            ts.config_json = json.dumps(config_data)

        return True

    # ── Start / Stop ──────────────────────────────────────────────────

    async def start_session(self, session_id: str) -> bool:
        """Start a session's trading pipeline."""
        if session_id in self._pipelines and self._pipelines[session_id].running:
            logger.warning("Session %s already running", session_id)
            return True

        info = await self.get_session_info(session_id, mask_secrets=False)
        if info is None:
            logger.error("Session %s not found", session_id)
            return False

        session_type = SessionType(info["session_type"])
        config_data = info.get("config", {})
        symbols = config_data.get("symbols", ["BTCUSDT"])
        starting_budget = info.get("starting_budget") or self._config.get("sessions", {}).get("default_sim_budget", 10000.0)
        strategy_code = info.get("strategy_code", "")
        data_config = info.get("data_config") or DEFAULT_DATA_CONFIG
        custom_data_code = info.get("custom_data_code") or []
        schedule_mode = data_config.get("schedule_mode", "always_on")
        strategy_mode = data_config.get("strategy_mode", "rebalance")

        # Binance doesn't support short selling — force rebalance mode
        if strategy_mode == "long_short" and session_type.exchange == Exchange.BINANCE:
            logger.warning(
                "Session %s: long_short not supported on Binance, falling back to rebalance",
                session_id,
            )
            strategy_mode = "rebalance"

        pipeline = SessionPipeline(session_id, session_type, schedule_mode=schedule_mode, strategy_mode=strategy_mode)
        # Create market calendar if schedule_mode is not always_on
        if schedule_mode != "always_on":
            pipeline.calendar = MarketCalendar(session_type.exchange)
        self._pipelines[session_id] = pipeline

        try:
            await self._start_pipeline(
                pipeline, config_data, symbols, starting_budget,
                strategy_code, data_config, custom_data_code,
            )
            await self._set_session_status(session_id, "active")
            await self._publish_log(
                session_id, "session_event",
                f"Session started (type={session_type.value}, symbols={symbols})",
                metadata={"symbols": symbols, "type": session_type.value, "budget": starting_budget},
            )
            logger.info("Session %s started (type=%s, symbols=%s)", session_id, session_type.value, symbols)
            return True
        except Exception:
            logger.exception("Failed to start session %s", session_id)
            # BUG-18 fix: cancel any orphaned tasks and remove pipeline from dict
            for task in pipeline.tasks:
                task.cancel()
            for task in pipeline.tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            self._pipelines.pop(session_id, None)
            await self._set_session_status(session_id, "error")
            await self._publish_log(session_id, "session_event", "Session failed to start", level="error")
            return False

    async def stop_session(self, session_id: str) -> bool:
        """Stop a session's trading pipeline."""
        pipeline = self._pipelines.get(session_id)
        if pipeline is None:
            return True

        pipeline.running = False

        # Stop collector
        if pipeline.collector:
            try:
                await pipeline.collector.stop()
            except Exception:
                logger.debug("Error stopping collector for session %s", session_id, exc_info=True)

        # Cancel all tasks
        for task in pipeline.tasks:
            task.cancel()
        for task in pipeline.tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Error awaiting task cancellation for session %s", session_id, exc_info=True)

        self._pipelines.pop(session_id, None)
        await self._set_session_status(session_id, "stopped")
        await self._publish_log(session_id, "session_event", "Session stopped")
        logger.info("Session %s stopped", session_id)
        return True

    async def stop_all(self) -> None:
        """Stop all running sessions."""
        for session_id in list(self._pipelines.keys()):
            await self.stop_session(session_id)

    def is_running(self, session_id: str) -> bool:
        pipeline = self._pipelines.get(session_id)
        return pipeline is not None and pipeline.running

    # ── Pipeline construction (V2) ────────────────────────────────────

    async def _start_pipeline(
        self,
        pipeline: SessionPipeline,
        config_data: dict,
        symbols: list[str],
        starting_budget: float,
        strategy_code: str,
        data_config: dict,
        custom_data_code: list[dict],
    ) -> None:
        """Build and start all V2 components for a session."""
        sid = pipeline.session_id
        st = pipeline.session_type
        exchange = st.exchange

        # Build per-session config (for OrderRouter/PortfolioTracker)
        session_config = self._build_session_config(sid, config_data, symbols)

        pipeline.data_config = data_config

        # 1. Strategy Executor
        executor = StrategyExecutor(sid, symbols, strategy_mode=pipeline.strategy_mode)
        if strategy_code:
            executor.load_strategy(strategy_code)
        pipeline.executor = executor

        # 2. Weight Rebalancer
        rebalancer = WeightRebalancer(sid, symbols, exchange, strategy_mode=pipeline.strategy_mode)
        pipeline.rebalancer = rebalancer

        # 3. Order Router — sim or real
        if st.is_simulation:
            commission_pct = data_config.get("commission_pct", 0.0)
            sim_adapter = SimulationAdapter(
                session_id=sid,
                starting_budget=starting_budget,
                exchange=exchange,
                redis=self._redis,
                strategy_mode=pipeline.strategy_mode,
                commission_pct=commission_pct,
            )
            pipeline.sim_adapter = sim_adapter
            router = OrderRouter(session_config, self._redis, sim_adapter=sim_adapter, session_id=sid)
        else:
            router = OrderRouter(session_config, self._redis, session_id=sid)
        pipeline.order_router = router

        # 4. Portfolio Tracker
        tracker = PortfolioTracker(session_config, self._redis, session_id=sid, starting_cash=starting_budget)
        pipeline.portfolio_tracker = tracker

        # 5. DataCollector — with strategy trigger callback
        async def on_strategy_trigger(data_snapshot: dict):
            """Called by DataCollector every N scrapes."""
            await self._run_strategy_cycle(pipeline, data_snapshot, starting_budget)

        async def on_scrape_complete(scrape_count: int, min_fill: int, max_needed: int):
            """Called after each data scrape — publish prices + status to logs."""
            # Publish current prices as MarketTick to feed SimAdapter + PortfolioTracker
            if pipeline.collector:
                current_prices = pipeline.collector.get_current_prices()
                if current_prices is not None:
                    market_channel = session_channel(sid, "market:ticks")
                    for i, symbol in enumerate(symbols):
                        tick = MarketTick(
                            symbol=symbol,
                            price=float(current_prices[i]),
                            volume=0.0,
                            exchange=exchange,
                            session_id=sid,
                            source="collector",
                        )
                        await self._redis.publish(market_channel, tick)

            if min_fill < max_needed:
                await self._publish_log(
                    sid, "data_scrape",
                    f"Scrape #{scrape_count} — filling buffers ({min_fill}/{max_needed})",
                    metadata={"scrape": scrape_count, "fill": min_fill, "needed": max_needed},
                )
            else:
                await self._publish_log(
                    sid, "data_scrape",
                    f"Scrape #{scrape_count} — data collected",
                    metadata={"scrape": scrape_count, "fill": min_fill},
                )

        # Build Alpaca credentials — try session-level keys first, then global config
        alpaca_creds = {}
        session_api_key = config_data.get("api_key", "")
        session_api_secret = config_data.get("api_secret", "")
        if session_api_key:
            alpaca_creds = {"api_key": session_api_key, "api_secret": session_api_secret}
        else:
            # Fall back to global config
            alpaca_cfg = self._config.get("alpaca", {})
            if alpaca_cfg.get("api_key"):
                alpaca_creds = {"api_key": alpaca_cfg["api_key"], "api_secret": alpaca_cfg.get("api_secret", "")}

        collector = DataCollector(
            session_id=sid,
            symbols=symbols,
            data_config=data_config,
            exchange=exchange,
            on_strategy_trigger=on_strategy_trigger,
            on_scrape_complete=on_scrape_complete,
            alpaca_credentials=alpaca_creds,
            calendar=pipeline.calendar,
        )

        # Load custom data functions
        if custom_data_code:
            collector.load_custom_data_functions(custom_data_code)

        pipeline.collector = collector
        pipeline.running = True

        # Start tasks — pass lambda factories so _run_with_restart can create
        # a fresh coroutine on each retry (coroutine objects are single-use).
        pipeline.tasks = [
            asyncio.create_task(
                self._run_with_restart(sid, "collector", lambda: collector.start()),
                name=f"session_{sid}_collector",
            ),
            asyncio.create_task(
                self._run_with_restart(sid, "router", lambda: router.start()),
                name=f"session_{sid}_router",
            ),
            asyncio.create_task(
                self._run_with_restart(sid, "portfolio", lambda: tracker.start()),
                name=f"session_{sid}_portfolio",
            ),
        ]

        if pipeline.sim_adapter:
            pipeline.tasks.append(
                asyncio.create_task(
                    self._run_with_restart(sid, "sim_price", lambda: sim_adapter.start_price_listener()),
                    name=f"session_{sid}_sim_price",
                )
            )

        # Market calendar schedule loop (liquidation, etc.)
        if pipeline.calendar and pipeline.schedule_mode != "always_on":
            pipeline.tasks.append(
                asyncio.create_task(
                    self._schedule_loop(pipeline, starting_budget),
                    name=f"session_{sid}_schedule",
                )
            )

    async def _schedule_loop(self, pipeline: SessionPipeline, starting_budget: float) -> None:
        """Monitor market calendar and trigger liquidation before close."""
        calendar = pipeline.calendar
        if calendar is None or pipeline.schedule_mode == "always_on":
            return

        sid = pipeline.session_id
        liquidate_minutes = self._config.get("calendar", {}).get(
            "liquidate_minutes_before_close", 5
        )
        liquidated_today = False

        while pipeline.running:
            try:
                if calendar.is_market_open():
                    # Reset daily liquidation flag on new trading day
                    if not liquidated_today:
                        pass  # market open, haven't liquidated yet — normal operation

                    # Check if we need to liquidate before close
                    if (
                        pipeline.schedule_mode == "market_hours_liquidate"
                        and not liquidated_today
                        and calendar.should_liquidate(liquidate_minutes)
                    ):
                        await self._liquidate_session(pipeline, starting_budget)
                        liquidated_today = True
                        await self._publish_log(
                            sid, "schedule_event",
                            f"Pre-close liquidation triggered ({liquidate_minutes} min before close)",
                            metadata={"schedule_mode": pipeline.schedule_mode},
                        )
                else:
                    # Market closed — reset liquidation flag for next day
                    liquidated_today = False

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Schedule loop error (session=%s)", sid)

            await asyncio.sleep(30)  # check every 30 seconds

    async def _liquidate_session(self, pipeline: SessionPipeline, starting_budget: float) -> None:
        """Force-rebalance to zero weights (flatten all positions)."""
        if not pipeline.executor or not pipeline.rebalancer or not pipeline.collector:
            return

        sid = pipeline.session_id
        prices = pipeline.collector.get_current_prices()
        if prices is None:
            logger.warning("Session %s: no prices for liquidation", sid)
            return

        # Get current positions
        current_positions = {}
        total_equity = starting_budget

        if pipeline.sim_adapter is not None:
            balances = await pipeline.sim_adapter.get_balances()
            total_equity = balances.get("total_equity", starting_budget)
            pos_snap = await pipeline.sim_adapter.get_positions_snapshot()
            for sym, pos in pos_snap.items():
                qty = pos.get("quantity", 0)
                if abs(qty) > 0.0001:
                    current_positions[sym] = qty
        else:
            portfolio_key = session_channel(sid, "portfolio:state")
            state = await self._redis.get_flag(portfolio_key)
            if state:
                total_equity = state.get("total_equity", starting_budget)
                for pos in state.get("positions", []):
                    current_positions[pos["symbol"]] = pos.get("quantity", 0)

        # Zero weights → flatten everything (sell longs, cover shorts)
        weights = np.zeros(len(pipeline.executor.symbols))
        orders = pipeline.rebalancer.rebalance(
            target_weights=weights,
            current_positions=current_positions,
            total_equity=total_equity,
            current_prices=prices,
        )

        if orders:
            orders_channel = session_channel(sid, "execution:orders")
            for order in orders:
                await self._redis.publish(orders_channel, order)
                await self._publish_log(
                    sid, "liquidation_order",
                    f"Liquidation: {order.side.value} {order.quantity:.6f} {order.symbol}",
                    symbol=order.symbol,
                    metadata={"side": order.side.value, "quantity": order.quantity},
                )
            logger.info("Session %s: liquidation orders submitted (%d orders)", sid, len(orders))
        else:
            logger.info("Session %s: no positions to liquidate", sid)

    async def _run_strategy_cycle(
        self,
        pipeline: SessionPipeline,
        data_snapshot: dict,
        starting_budget: float,
    ) -> None:
        """Execute one strategy cycle: main() -> normalize -> rebalance -> orders."""
        sid = pipeline.session_id

        if not pipeline.executor or not pipeline.rebalancer:
            return

        try:
            # Check kill switch
            ks_key = session_channel(sid, "risk:kill_switch")
            kill_switch = KillSwitch(self._redis, ks_key)
            if await kill_switch.is_active():
                logger.debug("Session %s: kill switch active, skipping strategy", sid)
                return

            # 1. Run strategy
            weights = pipeline.executor.execute(data_snapshot)

            if len(weights) != len(pipeline.executor.symbols):
                logger.error(
                    "Session %s: strategy returned %d weights but %d symbols — skipping cycle",
                    sid, len(weights), len(pipeline.executor.symbols),
                )
                return

            await self._publish_log(
                sid, "strategy_eval",
                f"Strategy returned weights: {weights.tolist()}",
                metadata={"weights": weights.tolist()},
            )

            # 2. Get current state for rebalancing
            prices = pipeline.collector.get_current_prices() if pipeline.collector else None
            if prices is None:
                logger.debug("Session %s: no current prices, skipping rebalance", sid)
                return

            # Validate prices array matches symbol count
            n_symbols = len(pipeline.executor.symbols)
            if len(prices) != n_symbols:
                logger.error(
                    "Session %s: prices array length %d != symbol count %d — skipping cycle",
                    sid, len(prices), n_symbols,
                )
                return

            # Get portfolio state for risk checks + rebalancing
            # For sim sessions, read positions directly from SimAdapter (source of
            # truth for execution) to avoid drift with the Redis-published state
            # from PortfolioTracker which lags by up to 5 seconds.
            portfolio_key = session_channel(sid, "portfolio:state")
            state = await self._redis.get_flag(portfolio_key)

            current_positions = {}
            total_equity = starting_budget

            if pipeline.sim_adapter is not None:
                # Sim: read directly from the adapter that will execute the orders
                balances = await pipeline.sim_adapter.get_balances()
                total_equity = balances.get("total_equity", starting_budget)
                pos_snap = await pipeline.sim_adapter.get_positions_snapshot()
                for sym, pos in pos_snap.items():
                    qty = pos.get("quantity", 0)
                    if abs(qty) > 0.0001:
                        current_positions[sym] = qty
            elif state:
                total_equity = state.get("total_equity", starting_budget)
                for pos in state.get("positions", []):
                    current_positions[pos["symbol"]] = pos.get("quantity", 0)

            # 3. Portfolio risk checks (drawdown + daily loss)
            #    Override global risk config with per-session data_config value
            risk_cfg_override = copy.deepcopy(self._config)
            risk_cfg_override.setdefault("risk", {})["max_daily_loss_pct"] = pipeline.data_config.get(
                "max_daily_loss_pct", 0.03
            )
            risk_ok, risk_reason = check_portfolio_risk(
                {
                    "total_equity": total_equity,
                    "peak_equity": state.get("peak_equity", total_equity) if state else total_equity,
                    "day_start_equity": state.get("day_start_equity", total_equity) if state else total_equity,
                    "daily_pnl": state.get("daily_pnl", 0) if state else 0,
                },
                risk_cfg_override,
            )
            if not risk_ok:
                # Breach → activate kill switch and flatten all positions
                await kill_switch.activate(risk_reason)
                weights = np.zeros(len(pipeline.executor.symbols))
                await self._publish_log(
                    sid, "risk_reject",
                    f"Risk breach: {risk_reason} — flattening all positions",
                    level="warning",
                    metadata={"reason": risk_reason},
                )

            # 3b. Short position loss check (long_short mode only)
            if risk_ok and pipeline.strategy_mode == "long_short" and pipeline.short_entry_prices:
                prices_dict = {}
                if prices is not None:
                    for i, sym in enumerate(pipeline.executor.symbols):
                        prices_dict[sym] = float(prices[i])
                short_loss_limit = pipeline.data_config.get("short_loss_limit_pct", 1.0)
                short_ok, short_reason = check_short_loss(
                    positions=current_positions,
                    current_prices=prices_dict,
                    entry_prices=pipeline.short_entry_prices,
                    short_loss_limit_pct=short_loss_limit,
                )
                if not short_ok:
                    await kill_switch.activate(short_reason)
                    weights = np.zeros(len(pipeline.executor.symbols))
                    await self._publish_log(
                        sid, "risk_reject",
                        f"Short loss kill switch: {short_reason} — flattening all positions",
                        level="warning",
                        metadata={"reason": short_reason},
                    )

            # 4. Generate rebalancing orders
            orders = pipeline.rebalancer.rebalance(
                target_weights=weights,
                current_positions=current_positions,
                total_equity=total_equity,
                current_prices=prices,
            )

            # 5. Submit orders via Redis
            if orders:
                orders_channel = session_channel(sid, "execution:orders")
                for order in orders:
                    await self._redis.publish(orders_channel, order)
                    await self._publish_log(
                        sid, "order_submit",
                        f"Order: {order.side.value} {order.quantity:.6f} {order.symbol}",
                        symbol=order.symbol,
                        metadata={"side": order.side.value, "quantity": order.quantity},
                    )

            # 6. Track short entry prices (long_short mode only)
            if pipeline.strategy_mode == "long_short" and prices is not None:
                for i, symbol in enumerate(pipeline.executor.symbols):
                    old_qty = current_positions.get(symbol, 0.0)
                    target_value = weights[i] * total_equity
                    price = float(prices[i]) if prices[i] > 0 else 0
                    new_qty = target_value / price if price > 0 else old_qty

                    if old_qty >= 0 and new_qty < 0:
                        # Opened new short position
                        pipeline.short_entry_prices[symbol] = price
                    elif old_qty < 0 and new_qty >= 0:
                        # Covered short position
                        pipeline.short_entry_prices.pop(symbol, None)
                    elif old_qty < 0 and new_qty < 0 and abs(new_qty) > abs(old_qty):
                        # Increased short — weighted average entry price
                        prev_entry = pipeline.short_entry_prices.get(symbol, price)
                        added_qty = abs(new_qty) - abs(old_qty)
                        pipeline.short_entry_prices[symbol] = (
                            prev_entry * abs(old_qty) + price * added_qty
                        ) / abs(new_qty)

        except Exception:
            logger.exception("Session %s: strategy cycle error", sid)
            await self._publish_log(sid, "strategy_error", "Strategy cycle failed", level="error")

    def _build_session_config(self, session_id: str, config_data: dict, symbols: list[str]) -> dict:
        """Build a per-session config dict with namespaced Redis channels."""
        cfg = copy.deepcopy(self._config)

        cfg.setdefault("redis", {}).setdefault("channels", {})
        cfg["redis"]["channels"] = {
            "market_data": session_channel(session_id, "market:ticks"),
            "signals": session_channel(session_id, "strategy:signals"),
            "orders": session_channel(session_id, "execution:orders"),
            "order_updates": session_channel(session_id, "execution:updates"),
            "alerts": session_channel(session_id, "monitoring:alerts"),
            "logs": session_channel(session_id, "logs"),
        }

        cfg.setdefault("risk", {})["kill_switch_key"] = session_channel(session_id, "risk:kill_switch")
        cfg["risk"]["portfolio_state_key"] = session_channel(session_id, "portfolio:state")

        if config_data.get("api_key"):
            exchange_key = "binance" if "binance" in config_data.get("type", "") else "alpaca"
            cfg.setdefault(exchange_key, {}).update({
                "api_key": config_data.get("api_key", ""),
                "api_secret": config_data.get("api_secret", ""),
                "symbols": symbols,
            })

        return cfg

    async def _run_with_restart(self, session_id: str, component: str, coro_factory) -> None:
        """Run a coroutine with auto-restart on failure.

        Args:
            coro_factory: A zero-arg callable that returns a NEW coroutine each time.
                          Coroutine objects can only be awaited once, so we need a
                          factory to create a fresh one for each retry attempt.
        """
        for attempt in range(1, MAX_RESTART_ATTEMPTS + 1):
            try:
                await coro_factory()
                return
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
                    await self._publish_log(
                        session_id, "session_event",
                        f"Component '{component}' crashed after {MAX_RESTART_ATTEMPTS} retries",
                        level="error",
                    )

    # ── Logging helper ─────────────────────────────────────────────

    async def _publish_log(
        self, session_id: str, event_type: str, message: str,
        level: str = "info", symbol: str = "", metadata: dict | None = None,
    ) -> None:
        """Publish a LogEntry to the session's logs channel."""
        try:
            entry = LogEntry(
                event_type=event_type,
                session_id=session_id,
                symbol=symbol,
                message=message,
                level=level,
                source="session",
                metadata=metadata or {},
            )
            channel = session_channel(session_id, "logs")
            await self._redis.publish(channel, entry)
        except Exception:
            logger.debug("Failed to publish session log", exc_info=True)

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
    def _session_to_dict(ts: TradingSession, *, mask_secrets: bool = True) -> dict:
        """Convert a TradingSession ORM object to a dict.

        Args:
            mask_secrets: If True, mask api_key/api_secret in the returned config.
                          Set to False for internal use (e.g. starting pipelines).
        """
        config_data = json.loads(ts.config_json or "{}")

        # Parse data_config
        data_config = None
        if ts.data_config:
            try:
                data_config = json.loads(ts.data_config)
            except (json.JSONDecodeError, TypeError):
                pass

        # Parse custom_data_code
        custom_data_code = []
        if ts.custom_data_code:
            try:
                custom_data_code = json.loads(ts.custom_data_code)
            except (json.JSONDecodeError, TypeError):
                pass

        # Mask sensitive keys before returning config to API consumers
        if mask_secrets:
            safe_config = dict(config_data)
            for key in ("api_key", "api_secret"):
                if key in safe_config and safe_config[key]:
                    val = safe_config[key]
                    safe_config[key] = "****" + val[-4:] if len(val) >= 4 else "****"
        else:
            safe_config = config_data

        return {
            "id": ts.id,
            "name": ts.name,
            "session_type": ts.session_type,
            "is_simulation": ts.is_simulation,
            "status": ts.status,
            "starting_budget": ts.starting_budget,
            "symbols": config_data.get("symbols", []),
            "universe_preset": config_data.get("universe_preset", ""),
            "strategy_class": ts.strategy_class,
            "strategy_code": ts.strategy_code or "",
            "data_config": data_config,
            "custom_data_code": custom_data_code,
            "config": safe_config,
            "created_at": ts.created_at.isoformat() if ts.created_at else "",
        }
