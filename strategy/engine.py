"""Strategy event loop — consumes market data, runs strategy, publishes signals."""

import asyncio
import importlib
import logging

from shared.enums import Signal
from shared.redis_client import RedisClient
from shared.schemas import MarketTick, OHLCVBar, TradeSignal
from strategy.base import BaseStrategy

logger = logging.getLogger(__name__)

# Try to import user's custom data pipeline — returns {} if not configured
try:
    from data.custom_data import fetch_custom_data as _fetch_custom
except Exception:
    _fetch_custom = None


class StrategyEngine:
    """Runs one or more strategies against incoming market data."""

    def __init__(self, config: dict, redis: RedisClient, session_id: str = ""):
        self._config = config
        self._redis = redis
        self._session_id = session_id
        self._strategies: list[BaseStrategy] = []
        self._running = False
        self._symbols: list[str] = config.get("binance", {}).get("symbols", []) or config.get("alpaca", {}).get("symbols", [])
        self._extra_data: dict = {}  # Cached custom data from last fetch

        channels = config.get("redis", {}).get("channels", {})
        self._market_channel = channels.get("market_data", "market:ticks")
        self._signal_channel = channels.get("signals", "strategy:signals")

    def _load_strategy(self) -> BaseStrategy:
        """Dynamically import and instantiate the strategy from config."""
        strat_cfg = self._config.get("strategy", {})
        module_path = strat_cfg.get("module", "strategy.examples.momentum")
        class_name = strat_cfg.get("class_name", "MomentumStrategy")
        strategy_id = strat_cfg.get("id", "default")
        params = strat_cfg.get("params", {})

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        if not issubclass(cls, BaseStrategy):
            raise TypeError(f"{class_name} is not a subclass of BaseStrategy")

        return cls(strategy_id=strategy_id, params=params)

    async def start(self) -> None:
        """Load strategy, subscribe to market data, start processing."""
        strategy = self._load_strategy()
        self._strategies.append(strategy)

        await strategy.on_start()
        logger.info(
            "Strategy engine started: %s (%s.%s)",
            strategy.strategy_id,
            self._config.get("strategy", {}).get("module"),
            self._config.get("strategy", {}).get("class_name"),
        )

        self._running = True

        # Subscribe to market data channel
        await self._redis.subscribe(
            self._market_channel,
            self._on_market_data,
        )

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the engine and call strategy cleanup."""
        self._running = False
        for strategy in self._strategies:
            try:
                await strategy.on_stop()
            except Exception:
                logger.exception("Error stopping strategy %s", strategy.strategy_id)
        logger.info("Strategy engine stopped")

    async def _on_market_data(self, data: dict) -> None:
        """Route incoming market data to the appropriate strategy handler."""
        try:
            # Fetch custom data (non-blocking best-effort)
            extra = await self._get_custom_data(data.get("symbol"))

            # Determine message type based on fields
            if "open" in data and "high" in data:
                bar = OHLCVBar.model_validate(data)
                await self._process_bar(bar, extra)
            else:
                tick = MarketTick.model_validate(data)
                await self._process_tick(tick, extra)
        except Exception:
            logger.exception("Error processing market data")

    async def _get_custom_data(self, symbol: str | None = None) -> dict | None:
        """Call the user's custom data pipeline. Returns None if not configured."""
        if _fetch_custom is None:
            return None
        try:
            # Build symbol list — use session symbols or just the current one
            syms = self._symbols or ([symbol] if symbol else [])
            if not syms:
                return None
            # Run in executor to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _fetch_custom, syms)
            if result:
                self._extra_data = result
            return self._extra_data or None
        except Exception:
            logger.debug("Custom data fetch failed, using cached", exc_info=True)
            return self._extra_data or None

    async def _process_tick(self, tick: MarketTick, extra_data: dict | None = None) -> None:
        for strategy in self._strategies:
            try:
                signal = await strategy.on_tick(tick, extra_data=extra_data)
                if signal is not None and signal.signal != Signal.HOLD:
                    await self._redis.publish(self._signal_channel, signal)
                    logger.info(
                        "Signal emitted: %s %s (strength=%.2f) from %s",
                        signal.signal.value,
                        signal.symbol,
                        signal.strength,
                        signal.strategy_id,
                    )
            except Exception:
                logger.exception(
                    "Error in strategy %s on_tick", strategy.strategy_id
                )

    async def _process_bar(self, bar: OHLCVBar, extra_data: dict | None = None) -> None:
        for strategy in self._strategies:
            try:
                signal = await strategy.on_bar(bar, extra_data=extra_data)
                if signal is not None and signal.signal != Signal.HOLD:
                    await self._redis.publish(self._signal_channel, signal)
                    logger.info(
                        "Signal emitted (bar): %s %s from %s",
                        signal.signal.value,
                        signal.symbol,
                        signal.strategy_id,
                    )
            except Exception:
                logger.exception(
                    "Error in strategy %s on_bar", strategy.strategy_id
                )
