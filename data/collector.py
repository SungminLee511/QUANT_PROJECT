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
from data.sources import FIELD_MAP, DataSource, get_default_source

logger = logging.getLogger(__name__)

# Built-in data fields — all fields from the registry
BUILTIN_FIELDS = set(FIELD_MAP.keys())


class DataCollector:
    """Collects market data at a fixed time resolution and maintains rolling buffers.

    Args:
        session_id: Unique session identifier.
        symbols: List of ticker symbols (universe).
        data_config: Configuration dict with resolution, fields, lookbacks, etc.
        exchange: Exchange enum (BINANCE or ALPACA).
        on_strategy_trigger: Async callback called every exec_every_n scrapes
                             with the data snapshot dict.
        on_scrape_complete: Async callback called after each scrape.
        alpaca_credentials: Optional dict with api_key and api_secret for Alpaca.
    """

    def __init__(
        self,
        session_id: str,
        symbols: list[str],
        data_config: dict,
        exchange: Exchange,
        on_strategy_trigger: Optional[Callable] = None,
        on_scrape_complete: Optional[Callable] = None,
        alpaca_credentials: dict | None = None,
    ):
        self.session_id = session_id
        self.symbols = symbols
        self.n_symbols = len(symbols)
        self.exchange = exchange
        self.on_strategy_trigger = on_strategy_trigger
        self.on_scrape_complete = on_scrape_complete

        # Parse config
        self.resolution = DataResolution(data_config.get("resolution", "1min"))
        self.exec_every_n = data_config.get("exec_every_n", 1)

        # Determine if this is a crypto session
        self._is_crypto = (exchange == Exchange.BINANCE)

        # Parse fields, lookbacks, and per-field source routing
        self.fields: dict[str, int] = {}  # field_name -> lookback
        self._field_sources: dict[str, str] = {}  # field_name -> source name
        for field_name, field_cfg in data_config.get("fields", {}).items():
            if isinstance(field_cfg, dict):
                if field_cfg.get("enabled") and field_cfg.get("lookback", 0) > 0:
                    self.fields[field_name] = field_cfg["lookback"]
                    self._field_sources[field_name] = field_cfg.get(
                        "source", get_default_source(field_name, self._is_crypto)
                    )
            elif isinstance(field_cfg, int) and field_cfg > 0:
                self.fields[field_name] = field_cfg
                self._field_sources[field_name] = get_default_source(field_name, self._is_crypto)

        # Fallback: if no builtin fields enabled, default to price with lookback 20
        if not self.fields:
            self.fields["price"] = 20
            self._field_sources["price"] = get_default_source("price", self._is_crypto)

        # Custom data configs
        self.custom_data = data_config.get("custom_data", [])
        self.custom_global_data = data_config.get("custom_global_data", [])
        self._custom_data_fns: dict[str, Callable] = {}
        self._custom_global_fns: dict[str, Callable] = {}

        # Rolling buffers: field_name -> np.ndarray [N, buffer_size]
        self._buffers: dict[str, np.ndarray] = {}
        self._buffer_fill: dict[str, int] = {}  # how many values have been written
        self._init_buffers()

        # Lazily created source instances
        self._source_instances: dict[str, object] = {}
        self._alpaca_credentials = alpaca_credentials or {}
        self._init_sources()

        # State
        self._scrape_count = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _init_sources(self) -> None:
        """Initialize data source instances based on which sources are needed."""
        needed_sources: set[str] = set()
        for field_name in self.fields:
            if field_name in BUILTIN_FIELDS:
                needed_sources.add(self._field_sources.get(field_name, "yfinance"))

        for source_name in needed_sources:
            if source_name == DataSource.YFINANCE.value:
                from data.sources.yfinance_source import YFinanceSource
                self._source_instances[source_name] = YFinanceSource()
            elif source_name == DataSource.ALPACA.value:
                from data.sources.alpaca_source import AlpacaSource
                api_key = self._alpaca_credentials.get("api_key", "")
                api_secret = self._alpaca_credentials.get("api_secret", "")
                source = AlpacaSource(api_key=api_key, api_secret=api_secret)
                if not source.has_credentials:
                    logger.warning(
                        "Alpaca source requested but no credentials provided (session=%s). "
                        "Alpaca fields will return empty data.",
                        self.session_id,
                    )
                self._source_instances[source_name] = source
            elif source_name == DataSource.BINANCE.value:
                from data.sources.binance_source import BinanceSource
                self._source_instances[source_name] = BinanceSource()

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
        """Start the data collection loop (blocks until stopped or cancelled)."""
        self._running = True
        logger.info(
            "DataCollector started (session=%s, resolution=%s, exec_every=%d, fields=%s)",
            self.session_id, self.resolution.value, self.exec_every_n,
            list(self.fields.keys()),
        )

        # Pre-fill buffers with historical data so strategy can fire immediately
        await self._backfill_buffers()

        await self._collection_loop()

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

    async def _backfill_buffers(self) -> None:
        """Pre-fill rolling buffers with historical data from each source.

        Runs fetch_history on each source in a thread executor (blocking I/O).
        If backfill fails for any source/field, logs a warning and continues —
        the live collection loop will fill buffers naturally as a fallback.
        """
        loop = asyncio.get_event_loop()

        # Group builtin fields by source (same grouping as _collect_once)
        source_fields: dict[str, set[str]] = {}
        for field_name in self.fields:
            if field_name in BUILTIN_FIELDS:
                src = self._field_sources.get(field_name, "yfinance")
                source_fields.setdefault(src, set()).add(field_name)

        if not source_fields:
            return

        backfilled_count = 0
        resolution_str = self.resolution.value

        for source_name, field_set in source_fields.items():
            fetcher = self._source_instances.get(source_name)
            if fetcher is None:
                continue

            if not hasattr(fetcher, "fetch_history"):
                logger.debug("Source '%s' has no fetch_history method, skipping backfill", source_name)
                continue

            # Determine the max lookback needed for this source's fields
            max_lookback = max(self.fields[f] for f in field_set)

            try:
                history = await loop.run_in_executor(
                    None,
                    fetcher.fetch_history,
                    self.symbols,
                    field_set,
                    resolution_str,
                    max_lookback,
                )

                for fname, hist_arr in history.items():
                    if fname not in self._buffers:
                        continue

                    lookback = self.fields[fname]
                    buf = self._buffers[fname]

                    # hist_arr shape: [N_symbols, max_lookback]
                    # Take the last `lookback` columns
                    if hist_arr.shape[1] >= lookback:
                        buf[:, -lookback:] = hist_arr[:, -lookback:]
                    else:
                        # Partial fill: use whatever history is available
                        avail = hist_arr.shape[1]
                        buf[:, -avail:] = hist_arr

                    filled = min(lookback, hist_arr.shape[1])
                    self._buffer_fill[fname] = max(self._buffer_fill[fname], filled)
                    backfilled_count += 1

            except Exception:
                logger.warning(
                    "Backfill failed for source '%s' (session=%s) — "
                    "live loop will fill buffers naturally",
                    source_name, self.session_id, exc_info=True,
                )

        logger.info(
            "Backfill complete: %d fields pre-filled (session=%s)",
            backfilled_count, self.session_id,
        )

    async def _collection_loop(self) -> None:
        """Main loop: collect data, append to buffers, trigger strategy."""
        interval = self.resolution.seconds

        while self._running:
            try:
                await self._collect_once()
                self._scrape_count += 1

                # Notify scrape complete (for logging to UI)
                if self.on_scrape_complete:
                    min_fill = min(self._buffer_fill.values()) if self._buffer_fill else 0
                    max_needed = max(self.fields.values()) if self.fields else 1
                    await self.on_scrape_complete(self._scrape_count, min_fill, max_needed)

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

        # 1. Group builtin fields by source
        source_fields: dict[str, set[str]] = {}  # source_name -> set of field names
        for field_name in self.fields:
            if field_name in BUILTIN_FIELDS:
                src = self._field_sources.get(field_name, "yfinance")
                source_fields.setdefault(src, set()).add(field_name)

        # Fetch from each source
        for source_name, field_set in source_fields.items():
            fetcher = self._source_instances.get(source_name)
            if fetcher is None:
                continue
            try:
                data = await loop.run_in_executor(
                    None, fetcher.fetch, self.symbols, field_set
                )
                for fname, values in data.items():
                    if fname in self._buffers:
                        self._append_to_buffer(fname, values)
            except Exception:
                logger.exception(
                    "Source '%s' fetch error (session=%s)", source_name, self.session_id
                )

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
