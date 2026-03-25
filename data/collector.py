"""Unified data collector — collects configured data fields at configured resolution.

Maintains rolling numpy buffers per field per session.
Triggers strategy execution every N scrapes via callback.
"""

import asyncio
import logging
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np

from shared.enums import DataResolution, Exchange

logger = logging.getLogger(__name__)

# Built-in data fields that can be collected
BUILTIN_FIELDS = {
    "price", "open", "high", "low", "volume", "vwap",
    "bid", "ask", "spread", "num_trades",
}

# Fields only available for crypto (Binance)
CRYPTO_ONLY_FIELDS = {"bid", "ask", "spread", "num_trades"}


class DataCollector:
    """Collects market data at a fixed time resolution and maintains rolling buffers.

    Args:
        session_id: Unique session identifier.
        symbols: List of ticker symbols (universe).
        data_config: Configuration dict with resolution, fields, lookbacks, etc.
        exchange: Exchange enum (BINANCE or ALPACA).
        on_strategy_trigger: Async callback called every exec_every_n scrapes
                             with the data snapshot dict.
    """

    def __init__(
        self,
        session_id: str,
        symbols: list[str],
        data_config: dict,
        exchange: Exchange,
        on_strategy_trigger: Optional[Callable] = None,
    ):
        self.session_id = session_id
        self.symbols = symbols
        self.n_symbols = len(symbols)
        self.exchange = exchange
        self.on_strategy_trigger = on_strategy_trigger

        # Parse config
        self.resolution = DataResolution(data_config.get("resolution", "1min"))
        self.exec_every_n = data_config.get("exec_every_n", 1)

        # Parse fields and lookbacks
        self.fields: dict[str, int] = {}  # field_name -> lookback
        for field_name, field_cfg in data_config.get("fields", {}).items():
            if isinstance(field_cfg, dict):
                if field_cfg.get("enabled") and field_cfg.get("lookback", 0) > 0:
                    self.fields[field_name] = field_cfg["lookback"]
            elif isinstance(field_cfg, int) and field_cfg > 0:
                self.fields[field_name] = field_cfg

        # Fallback: if no builtin fields enabled, default to price with lookback 20
        if not self.fields:
            self.fields["price"] = 20

        # Custom data configs
        self.custom_data = data_config.get("custom_data", [])
        self.custom_global_data = data_config.get("custom_global_data", [])
        self._custom_data_fns: dict[str, Callable] = {}
        self._custom_global_fns: dict[str, Callable] = {}

        # Rolling buffers: field_name -> np.ndarray [N, buffer_size]
        self._buffers: dict[str, np.ndarray] = {}
        self._buffer_fill: dict[str, int] = {}  # how many values have been written
        self._init_buffers()

        # State
        self._scrape_count = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _init_buffers(self) -> None:
        """Initialize rolling buffers for all configured fields."""
        for field_name, lookback in self.fields.items():
            # Buffer is slightly larger than lookback for rolling room
            buf_size = lookback + 10
            self._buffers[field_name] = np.full(
                (self.n_symbols, buf_size), np.nan, dtype=np.float64
            )
            self._buffer_fill[field_name] = 0

        # Custom per-stock data buffers
        for custom in self.custom_data:
            name = custom["name"]
            lookback = custom.get("lookback", 1)
            self.fields[name] = lookback
            buf_size = lookback + 10
            self._buffers[name] = np.full(
                (self.n_symbols, buf_size), np.nan, dtype=np.float64
            )
            self._buffer_fill[name] = 0

        # Custom global data buffers (shape [1, buf_size])
        for custom in self.custom_global_data:
            name = custom["name"]
            lookback = custom.get("lookback", 1)
            self.fields[name] = lookback
            buf_size = lookback + 10
            self._buffers[name] = np.full(
                (1, buf_size), np.nan, dtype=np.float64
            )
            self._buffer_fill[name] = 0

    def load_custom_data_functions(self, custom_data_code: list[dict]) -> None:
        """Compile and load custom data fetch functions.

        Args:
            custom_data_code: List of dicts with "name", "type", "code" keys.
        """
        for item in custom_data_code:
            name = item["name"]
            code = item["code"]
            func_type = item.get("type", "per_stock")

            try:
                namespace = {"np": np, "numpy": np}
                exec(compile(code, f"<custom_data_{name}>", "exec"), namespace)

                if "fetch" not in namespace:
                    logger.error("Custom data '%s': no fetch() function found", name)
                    continue

                if func_type == "per_stock":
                    self._custom_data_fns[name] = namespace["fetch"]
                else:
                    self._custom_global_fns[name] = namespace["fetch"]

                logger.info("Loaded custom data function: %s (%s)", name, func_type)
            except Exception:
                logger.exception("Failed to load custom data function: %s", name)

    async def start(self) -> None:
        """Start the data collection loop."""
        self._running = True
        self._task = asyncio.create_task(
            self._collection_loop(),
            name=f"collector_{self.session_id}",
        )
        logger.info(
            "DataCollector started (session=%s, resolution=%s, exec_every=%d, fields=%s)",
            self.session_id, self.resolution.value, self.exec_every_n,
            list(self.fields.keys()),
        )

    async def stop(self) -> None:
        """Stop the data collection loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DataCollector stopped (session=%s)", self.session_id)

    async def _collection_loop(self) -> None:
        """Main loop: collect data, append to buffers, trigger strategy."""
        interval = self.resolution.seconds

        while self._running:
            try:
                await self._collect_once()
                self._scrape_count += 1

                # Trigger strategy every N scrapes
                if (
                    self.on_strategy_trigger
                    and self._scrape_count % self.exec_every_n == 0
                ):
                    snapshot = self.get_data_snapshot()
                    if snapshot is not None:
                        await self.on_strategy_trigger(snapshot)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "DataCollector error (session=%s, scrape=%d)",
                    self.session_id, self._scrape_count,
                )

            await asyncio.sleep(interval)

    async def _collect_once(self) -> None:
        """Fetch all configured data fields and append to buffers."""
        loop = asyncio.get_event_loop()

        # 1. Fetch built-in data
        builtin_data = await loop.run_in_executor(
            None, self._fetch_builtin_data
        )

        for field_name, values in builtin_data.items():
            if field_name in self._buffers:
                self._append_to_buffer(field_name, values)

        # 2. Fetch custom per-stock data
        for name, fn in self._custom_data_fns.items():
            try:
                values = await loop.run_in_executor(
                    None, fn, self.symbols
                )
                values = np.array(values, dtype=np.float64).flatten()
                if values.shape == (self.n_symbols,):
                    self._append_to_buffer(name, values)
                else:
                    logger.warning(
                        "Custom data '%s' returned shape %s, expected (%d,)",
                        name, values.shape, self.n_symbols,
                    )
            except Exception:
                logger.exception("Custom data '%s' fetch error", name)

        # 3. Fetch custom global data
        for name, fn in self._custom_global_fns.items():
            try:
                value = await loop.run_in_executor(None, fn)
                value = float(value)
                self._append_to_buffer(name, np.array([value]))
            except Exception:
                logger.exception("Custom global data '%s' fetch error", name)

    def _fetch_builtin_data(self) -> dict[str, np.ndarray]:
        """Fetch built-in market data for all symbols. Runs in thread executor."""
        if self.exchange == Exchange.BINANCE:
            return self._fetch_binance_data()
        else:
            return self._fetch_yfinance_data()

    def _fetch_yfinance_data(self) -> dict[str, np.ndarray]:
        """Fetch data from Yahoo Finance for all symbols."""
        import yfinance as yf

        result: dict[str, list[float]] = {f: [] for f in self.fields if f in BUILTIN_FIELDS}

        for symbol in self.symbols:
            try:
                ticker = yf.Ticker(symbol)
                fast_info = ticker.fast_info

                price = float(fast_info.get("lastPrice", 0) or fast_info.get("last_price", 0) or 0)
                volume = float(fast_info.get("lastVolume", 0) or fast_info.get("last_volume", 0) or 0)

                if "price" in result:
                    result["price"].append(price)
                if "volume" in result:
                    result["volume"].append(volume)
                if "open" in result:
                    result["open"].append(float(fast_info.get("open", price)))
                if "high" in result:
                    result["high"].append(float(fast_info.get("dayHigh", price) or price))
                if "low" in result:
                    result["low"].append(float(fast_info.get("dayLow", price) or price))
                if "vwap" in result:
                    # yfinance doesn't provide VWAP directly; approximate with price
                    result["vwap"].append(price)

            except Exception:
                logger.warning("yfinance fetch error for %s", symbol)
                for f in result:
                    result[f].append(0.0)

        return {k: np.array(v, dtype=np.float64) for k, v in result.items()}

    def _fetch_binance_data(self) -> dict[str, np.ndarray]:
        """Fetch data from Binance for all symbols."""
        try:
            from binance.client import Client
        except ImportError:
            logger.error("python-binance not installed")
            return {}

        result: dict[str, list[float]] = {f: [] for f in self.fields if f in BUILTIN_FIELDS}

        client = Client("", "")  # Public data, no key needed

        for symbol in self.symbols:
            try:
                # Get latest kline for the configured resolution
                interval_map = {
                    "1min": Client.KLINE_INTERVAL_1MINUTE,
                    "5min": Client.KLINE_INTERVAL_5MINUTE,
                    "15min": Client.KLINE_INTERVAL_15MINUTE,
                    "30min": Client.KLINE_INTERVAL_30MINUTE,
                    "60min": Client.KLINE_INTERVAL_1HOUR,
                    "1day": Client.KLINE_INTERVAL_1DAY,
                }
                interval = interval_map.get(self.resolution.value, Client.KLINE_INTERVAL_1MINUTE)
                klines = client.get_klines(symbol=symbol, interval=interval, limit=1)

                if klines:
                    k = klines[0]
                    # Binance kline format: [open_time, open, high, low, close, volume, ...]
                    if "price" in result:
                        result["price"].append(float(k[4]))  # close
                    if "open" in result:
                        result["open"].append(float(k[1]))
                    if "high" in result:
                        result["high"].append(float(k[2]))
                    if "low" in result:
                        result["low"].append(float(k[3]))
                    if "volume" in result:
                        result["volume"].append(float(k[5]))
                    if "num_trades" in result:
                        result["num_trades"].append(float(k[8]))
                    if "vwap" in result:
                        # Approximate VWAP: quote_volume / volume
                        vol = float(k[5])
                        qvol = float(k[7])
                        result["vwap"].append(qvol / vol if vol > 0 else float(k[4]))
                else:
                    for f in result:
                        result[f].append(0.0)

                # Bid/ask from order book
                if "bid" in result or "ask" in result or "spread" in result:
                    try:
                        book = client.get_order_book(symbol=symbol, limit=1)
                        bid = float(book["bids"][0][0]) if book["bids"] else 0.0
                        ask = float(book["asks"][0][0]) if book["asks"] else 0.0
                        if "bid" in result:
                            result["bid"].append(bid)
                        if "ask" in result:
                            result["ask"].append(ask)
                        if "spread" in result:
                            result["spread"].append(ask - bid)
                    except Exception:
                        if "bid" in result:
                            result["bid"].append(0.0)
                        if "ask" in result:
                            result["ask"].append(0.0)
                        if "spread" in result:
                            result["spread"].append(0.0)

            except Exception:
                logger.warning("Binance fetch error for %s", symbol)
                for f in result:
                    result[f].append(0.0)

        return {k: np.array(v, dtype=np.float64) for k, v in result.items()}

    def _append_to_buffer(self, field_name: str, values: np.ndarray) -> None:
        """Append new values to a rolling buffer by shifting left."""
        buf = self._buffers[field_name]
        # Shift left
        buf[:, :-1] = buf[:, 1:]
        # Write new values to last column
        buf[:, -1] = values
        self._buffer_fill[field_name] = min(
            self._buffer_fill[field_name] + 1,
            buf.shape[1],
        )

    def get_data_snapshot(self) -> dict[str, np.ndarray] | None:
        """Slice buffers to configured lookbacks and return data dict.

        Returns None if not enough data has been collected yet.
        """
        result = {}

        for field_name, lookback in self.fields.items():
            if self._buffer_fill.get(field_name, 0) < lookback:
                logger.debug(
                    "Session %s: field '%s' needs %d values, has %d — skipping strategy",
                    self.session_id, field_name, lookback,
                    self._buffer_fill.get(field_name, 0),
                )
                return None

            buf = self._buffers[field_name]
            result[field_name] = buf[:, -lookback:].copy()  # [N, lookback] or [1, lookback]

        result["tickers"] = self.symbols
        return result

    def get_current_prices(self) -> np.ndarray | None:
        """Return the latest price for each symbol, or None if no price data."""
        if "price" not in self._buffers:
            return None
        buf = self._buffers["price"]
        prices = buf[:, -1].copy()
        if np.any(np.isnan(prices)):
            return None
        return prices
