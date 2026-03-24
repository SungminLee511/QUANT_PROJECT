"""Binance simulation data feed — real market data via public WebSocket, no API key needed."""

import asyncio
import logging

from binance import AsyncClient, BinanceSocketManager

from data.base_feed import BaseFeed
from data.normalizer import normalize_binance_kline, normalize_binance_trade
from shared.redis_client import RedisClient, session_channel

logger = logging.getLogger(__name__)


class BinanceSimFeed(BaseFeed):
    """Uses Binance public WebSocket (no API key) for real-time crypto data.

    Publishes to session-namespaced Redis channels.
    """

    def __init__(self, session_id: str, symbols: list[str], redis: RedisClient):
        self._session_id = session_id
        self._symbols = symbols or ["BTCUSDT"]
        self._redis = redis
        self._client: AsyncClient | None = None
        self._bsm: BinanceSocketManager | None = None
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._channel = session_channel(session_id, "market:ticks")

    async def connect(self) -> None:
        # Public WebSocket — empty credentials work fine for market data
        self._client = await AsyncClient.create(
            api_key="",
            api_secret="",
            testnet=False,  # Use real Binance for live market data
        )
        self._bsm = BinanceSocketManager(self._client)
        self._running = True
        logger.info(
            "BinanceSimFeed connected (session=%s, symbols=%s)",
            self._session_id,
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
        logger.info("BinanceSimFeed disconnected (session=%s)", self._session_id)

    async def subscribe(self, symbols: list[str] | None = None) -> None:
        symbols = symbols or self._symbols
        for symbol in symbols:
            sym_lower = symbol.lower()
            task = asyncio.create_task(
                self._listen_trades(sym_lower),
                name=f"bsim_trade_{self._session_id}_{sym_lower}",
            )
            self._tasks.append(task)
            task = asyncio.create_task(
                self._listen_klines(sym_lower),
                name=f"bsim_kline_{self._session_id}_{sym_lower}",
            )
            self._tasks.append(task)
        logger.info("BinanceSimFeed subscribed to %s (session=%s)", symbols, self._session_id)

    async def _listen_trades(self, symbol: str) -> None:
        try:
            ts = self._bsm.trade_socket(symbol)
            async with ts as stream:
                while self._running:
                    msg = await stream.recv()
                    if msg is None:
                        continue
                    tick = normalize_binance_trade(msg)
                    tick.session_id = self._session_id
                    await self._redis.publish(self._channel, tick)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("BinanceSimFeed trade stream error for %s", symbol)

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
                        bar.session_id = self._session_id
                        await self._redis.publish(self._channel, bar)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("BinanceSimFeed kline stream error for %s", symbol)
