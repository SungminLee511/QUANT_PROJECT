"""yfinance polling data feed — real stock data without API keys.

Polls Yahoo Finance every N seconds for latest price data and publishes
MarketTick messages to the session's Redis channel.
"""

import asyncio
import logging
from datetime import datetime, timezone

from data.base_feed import BaseFeed
from shared.enums import Exchange
from shared.redis_client import RedisClient, session_channel
from shared.schemas import MarketTick, OHLCVBar

logger = logging.getLogger(__name__)

# Default poll interval (seconds)
DEFAULT_POLL_INTERVAL = 2


class YFinanceFeed(BaseFeed):
    """Polls Yahoo Finance for US equity data. No API key needed.

    Publishes MarketTick to session-namespaced Redis channels.
    """

    def __init__(
        self,
        session_id: str,
        symbols: list[str],
        redis: RedisClient,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self._session_id = session_id
        self._symbols = symbols or ["AAPL"]
        self._redis = redis
        self._poll_interval = poll_interval
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._channel = session_channel(session_id, "market:ticks")
        self._last_prices: dict[str, float] = {}

    async def connect(self) -> None:
        # Import yfinance lazily to avoid import-time issues
        import yfinance  # noqa: F401
        self._running = True
        logger.info(
            "YFinanceFeed connected (session=%s, symbols=%s, interval=%.1fs)",
            self._session_id,
            self._symbols,
            self._poll_interval,
        )

    async def disconnect(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("YFinanceFeed disconnected (session=%s)", self._session_id)

    async def subscribe(self, symbols: list[str] | None = None) -> None:
        symbols = symbols or self._symbols
        task = asyncio.create_task(
            self._poll_loop(symbols),
            name=f"yfinance_poll_{self._session_id}",
        )
        self._tasks.append(task)
        logger.info("YFinanceFeed subscribed to %s (session=%s)", symbols, self._session_id)

    async def _poll_loop(self, symbols: list[str]) -> None:
        """Continuously poll Yahoo Finance for latest prices."""
        import yfinance as yf

        while self._running:
            try:
                # Run the blocking yfinance call in a thread pool
                data = await asyncio.get_event_loop().run_in_executor(
                    None, self._fetch_prices, symbols
                )

                for symbol, info in data.items():
                    price = info.get("price", 0)
                    volume = info.get("volume", 0)

                    if price and price > 0:
                        tick = MarketTick(
                            symbol=symbol,
                            price=price,
                            volume=volume,
                            timestamp=datetime.now(timezone.utc),
                            exchange=Exchange.ALPACA,  # treat as equity exchange
                            session_id=self._session_id,
                            source="data.yfinance",
                        )
                        await self._redis.publish(self._channel, tick)
                        self._last_prices[symbol] = price

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("YFinanceFeed poll error (session=%s)", self._session_id)

            await asyncio.sleep(self._poll_interval)

    @staticmethod
    def _fetch_prices(symbols: list[str]) -> dict[str, dict]:
        """Fetch latest prices from Yahoo Finance (blocking call)."""
        import yfinance as yf

        result = {}
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                fast_info = ticker.fast_info
                result[symbol] = {
                    "price": float(fast_info.get("lastPrice", 0) or fast_info.get("last_price", 0)),
                    "volume": float(fast_info.get("lastVolume", 0) or fast_info.get("last_volume", 0)),
                }
            except Exception:
                logger.warning("Failed to fetch yfinance data for %s", symbol)
                result[symbol] = {"price": 0, "volume": 0}
        return result
