"""Data feed lifecycle manager — starts, monitors, and restarts feeds."""

import asyncio
import logging
import signal

from data.alpaca_feed import AlpacaFeed
from data.binance_feed import BinanceFeed
from shared.redis_client import RedisClient, create_redis_client

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds


class DataFeedManager:
    def __init__(self, config: dict):
        self._config = config
        self._redis: RedisClient | None = None
        self._feeds: list = []
        self._shutdown_event = asyncio.Event()

    async def run(self) -> None:
        # Connect Redis
        self._redis = create_redis_client(self._config)
        await self._redis.connect()

        # Determine which feeds to start
        binance_symbols = self._config.get("binance", {}).get("symbols", [])
        alpaca_symbols = self._config.get("alpaca", {}).get("symbols", [])

        tasks = []

        if binance_symbols:
            tasks.append(
                asyncio.create_task(
                    self._run_with_retry("Binance", self._run_binance),
                    name="binance_feed",
                )
            )

        if alpaca_symbols:
            tasks.append(
                asyncio.create_task(
                    self._run_with_retry("Alpaca", self._run_alpaca),
                    name="alpaca_feed",
                )
            )

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        logger.info("Data feed manager started (%d feeds)", len(tasks))

        if not tasks:
            logger.warning("No feeds configured — nothing to do")
            return

        # Wait until shutdown or all feeds die
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                logger.error("Feed task failed: %s", task.exception())

        await self._cleanup()

    async def _run_binance(self) -> None:
        feed = BinanceFeed(self._config, self._redis)
        self._feeds.append(feed)
        await feed.connect()
        await feed.subscribe()
        # Keep running until cancelled
        await self._shutdown_event.wait()
        await feed.disconnect()

    async def _run_alpaca(self) -> None:
        feed = AlpacaFeed(self._config, self._redis)
        self._feeds.append(feed)
        await feed.connect()
        await feed.subscribe()
        await feed.run()

    async def _run_with_retry(self, name: str, coro_fn) -> None:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info("Starting %s feed (attempt %d/%d)", name, attempt, MAX_RETRIES)
                await coro_fn()
                return  # clean exit
            except asyncio.CancelledError:
                logger.info("%s feed cancelled", name)
                return
            except Exception:
                logger.exception(
                    "%s feed died (attempt %d/%d)", name, attempt, MAX_RETRIES
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
        logger.error("%s feed exhausted retries", name)

    def _handle_signal(self) -> None:
        logger.info("Shutdown signal received")
        self._shutdown_event.set()

    async def _cleanup(self) -> None:
        for feed in self._feeds:
            try:
                await feed.disconnect()
            except Exception:
                logger.exception("Error disconnecting feed")
        if self._redis:
            await self._redis.disconnect()
        logger.info("Data feed manager stopped")
