"""Binance WebSocket data feed — trades and klines."""

import asyncio
import logging

from binance import AsyncClient, BinanceSocketManager

from data.base_feed import BaseFeed
from data.normalizer import normalize_binance_kline, normalize_binance_trade
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


class BinanceFeed(BaseFeed):
    def __init__(self, config: dict, redis: RedisClient):
        self._config = config
        self._redis = redis
        self._client: AsyncClient | None = None
        self._bsm: BinanceSocketManager | None = None
        self._tasks: list[asyncio.Task] = []
        self._running = False

        binance_cfg = config.get("binance", {})
        self._api_key = binance_cfg.get("api_key", "")
        self._api_secret = binance_cfg.get("api_secret", "")
        self._testnet = binance_cfg.get("testnet", True)
        self._symbols = binance_cfg.get("symbols", ["BTCUSDT"])
        self._channel = config.get("redis", {}).get("channels", {}).get(
            "market_data", "market:ticks"
        )

    async def connect(self) -> None:
        self._client = await AsyncClient.create(
            api_key=self._api_key,
            api_secret=self._api_secret,
            testnet=self._testnet,
        )
        self._bsm = BinanceSocketManager(self._client)
        self._running = True
        logger.info(
            "Binance feed connected (testnet=%s, symbols=%s)",
            self._testnet,
            self._symbols,
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
        if self._client:
            await self._client.close_connection()
        logger.info("Binance feed disconnected")

    async def subscribe(self, symbols: list[str] | None = None) -> None:
        symbols = symbols or self._symbols
        for symbol in symbols:
            sym_lower = symbol.lower()
            # Trade stream
            task = asyncio.create_task(
                self._listen_trades(sym_lower), name=f"binance_trade_{sym_lower}"
            )
            self._tasks.append(task)
            # Kline stream (1m candles)
            task = asyncio.create_task(
                self._listen_klines(sym_lower), name=f"binance_kline_{sym_lower}"
            )
            self._tasks.append(task)
        logger.info("Subscribed to Binance streams for %s", symbols)

    async def _listen_trades(self, symbol: str) -> None:
        try:
            ts = self._bsm.trade_socket(symbol)
            async with ts as stream:
                while self._running:
                    msg = await stream.recv()
                    if msg is None:
                        continue
                    tick = normalize_binance_trade(msg)
                    await self._redis.publish(self._channel, tick)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Binance trade stream error for %s", symbol)

    async def _listen_klines(self, symbol: str) -> None:
        try:
            ks = self._bsm.kline_socket(symbol, interval="1m")
            async with ks as stream:
                while self._running:
                    msg = await stream.recv()
                    if msg is None:
                        continue
                    bar = normalize_binance_kline(msg)
                    if bar is not None:
                        await self._redis.publish(self._channel, bar)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Binance kline stream error for %s", symbol)
