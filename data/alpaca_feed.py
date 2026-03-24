"""Alpaca streaming data feed — trades and bars for US equities."""

import asyncio
import logging

from alpaca.data.live import StockDataStream

from data.base_feed import BaseFeed
from data.normalizer import normalize_alpaca_bar, normalize_alpaca_trade
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


class AlpacaFeed(BaseFeed):
    def __init__(self, config: dict, redis: RedisClient):
        self._config = config
        self._redis = redis
        self._stream: StockDataStream | None = None
        self._running = False

        alpaca_cfg = config.get("alpaca", {})
        self._api_key = alpaca_cfg.get("api_key", "")
        self._api_secret = alpaca_cfg.get("api_secret", "")
        self._paper = alpaca_cfg.get("paper", True)
        self._symbols = alpaca_cfg.get("symbols", ["AAPL"])
        self._channel = config.get("redis", {}).get("channels", {}).get(
            "market_data", "market:ticks"
        )

    async def connect(self) -> None:
        feed = "iex" if self._paper else "sip"
        self._stream = StockDataStream(
            api_key=self._api_key,
            secret_key=self._api_secret,
            feed=feed,
        )
        self._running = True
        logger.info(
            "Alpaca feed initialized (paper=%s, symbols=%s, feed=%s)",
            self._paper,
            self._symbols,
            feed,
        )

    async def disconnect(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass
        logger.info("Alpaca feed disconnected")

    async def subscribe(self, symbols: list[str] | None = None) -> None:
        symbols = symbols or self._symbols

        async def _handle_trade(trade):
            if not self._running:
                return
            try:
                tick = normalize_alpaca_trade(trade)
                await self._redis.publish(self._channel, tick)
            except Exception:
                logger.exception("Error processing Alpaca trade")

        async def _handle_bar(bar):
            if not self._running:
                return
            try:
                ohlcv = normalize_alpaca_bar(bar)
                await self._redis.publish(self._channel, ohlcv)
            except Exception:
                logger.exception("Error processing Alpaca bar")

        self._stream.subscribe_trades(_handle_trade, *symbols)
        self._stream.subscribe_bars(_handle_bar, *symbols)

        logger.info("Subscribed to Alpaca streams for %s", symbols)

    async def run(self) -> None:
        """Start the Alpaca stream (blocking). Call after subscribe()."""
        if self._stream is None:
            raise RuntimeError("Call connect() before run()")
        try:
            await self._stream._run_forever()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Alpaca stream error")
