"""Binance data source — fetches live + daily crypto data from public API."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"


class BinanceSource:
    """Fetches market data from Binance public API.

    Live fields: price, bid, ask, spread, num_trades
    Daily fields: open, high, low, close, volume, vwap, day_change_pct

    No API key required (uses public endpoints).
    """

    LIVE_FIELDS = {"price", "bid", "ask", "spread", "num_trades"}
    DAILY_FIELDS = {"open", "high", "low", "close", "volume", "vwap", "day_change_pct"}
    ALL_FIELDS = LIVE_FIELDS | DAILY_FIELDS

    def __init__(self):
        self._session = requests.Session()

    def fetch(self, symbols: list[str], requested_fields: set[str]) -> dict[str, np.ndarray]:
        """Fetch all requested fields for all symbols from Binance."""
        fields_to_fetch = requested_fields & self.ALL_FIELDS
        if not fields_to_fetch:
            return {}

        n = len(symbols)
        result: dict[str, np.ndarray] = {}

        needs_orderbook = bool(fields_to_fetch & {"bid", "ask", "spread"})
        needs_24hr = bool(fields_to_fetch & (self.DAILY_FIELDS | {"price", "num_trades"}))

        sym_idx = {s: i for i, s in enumerate(symbols)}

        # 1. Fetch 24hr ticker stats (gives price, OHLCV, volume, trades count, etc.)
        if needs_24hr:
            prices = np.full(n, np.nan, dtype=np.float64)
            opens = np.full(n, np.nan, dtype=np.float64)
            highs = np.full(n, np.nan, dtype=np.float64)
            lows = np.full(n, np.nan, dtype=np.float64)
            closes = np.full(n, np.nan, dtype=np.float64)
            volumes = np.zeros(n, dtype=np.float64)
            vwaps = np.full(n, np.nan, dtype=np.float64)
            num_trades = np.zeros(n, dtype=np.float64)
            day_change = np.full(n, np.nan, dtype=np.float64)

            try:
                # Use the multi-symbol 24hr ticker endpoint
                symbols_param = str(symbols).replace("'", '"')
                resp = self._session.get(
                    f"{BINANCE_BASE}/api/v3/ticker/24hr",
                    params={"symbols": symbols_param},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()

                if isinstance(data, dict):
                    data = [data]

                for item in data:
                    sym = item.get("symbol", "")
                    idx = sym_idx.get(sym)
                    if idx is None:
                        continue

                    _lp = item.get("lastPrice")
                    prices[idx] = float(_lp) if _lp is not None else np.nan
                    _op = item.get("openPrice")
                    opens[idx] = float(_op) if _op is not None else np.nan
                    _hp = item.get("highPrice")
                    highs[idx] = float(_hp) if _hp is not None else np.nan
                    _lwp = item.get("lowPrice")
                    lows[idx] = float(_lwp) if _lwp is not None else np.nan
                    closes[idx] = float(_lp) if _lp is not None else np.nan
                    volumes[idx] = float(item.get("volume", 0))
                    _vwap = item.get("weightedAvgPrice")
                    vwaps[idx] = float(_vwap) if _vwap is not None else np.nan
                    num_trades[idx] = float(item.get("count", 0))
                    _dc = item.get("priceChangePercent")
                    day_change[idx] = float(_dc) if _dc is not None else np.nan

            except Exception:
                logger.warning("Binance 24hr ticker fetch error", exc_info=True)

            if "price" in fields_to_fetch:
                result["price"] = prices
            if "open" in fields_to_fetch:
                result["open"] = opens
            if "high" in fields_to_fetch:
                result["high"] = highs
            if "low" in fields_to_fetch:
                result["low"] = lows
            if "close" in fields_to_fetch:
                result["close"] = closes
            if "volume" in fields_to_fetch:
                result["volume"] = volumes
            if "vwap" in fields_to_fetch:
                result["vwap"] = vwaps
            if "num_trades" in fields_to_fetch:
                result["num_trades"] = num_trades
            if "day_change_pct" in fields_to_fetch:
                result["day_change_pct"] = day_change

        # 2. Fetch order book for bid/ask/spread (concurrent, no multi-symbol endpoint)
        if needs_orderbook:
            bids = np.zeros(n, dtype=np.float64)
            asks = np.zeros(n, dtype=np.float64)

            def _fetch_book(symbol: str) -> tuple[str, float, float]:
                resp = self._session.get(
                    f"{BINANCE_BASE}/api/v3/depth",
                    params={"symbol": symbol, "limit": 1},
                    timeout=5,
                )
                resp.raise_for_status()
                book = resp.json()
                bids_list = book.get("bids") or []
                asks_list = book.get("asks") or []
                bid = float(bids_list[0][0]) if len(bids_list) > 0 and len(bids_list[0]) > 0 else 0.0
                ask = float(asks_list[0][0]) if len(asks_list) > 0 and len(asks_list[0]) > 0 else 0.0
                return symbol, bid, ask

            failed_count = 0
            with ThreadPoolExecutor(max_workers=min(n, 10)) as pool:
                futures = {pool.submit(_fetch_book, sym): sym for sym in symbols}
                for future in as_completed(futures, timeout=15):
                    sym = futures[future]
                    try:
                        _, bid, ask = future.result(timeout=5)
                        idx = sym_idx[sym]
                        bids[idx] = bid
                        asks[idx] = ask
                    except Exception:
                        failed_count += 1
                        logger.warning("Binance order book fetch error for %s", sym, exc_info=True)
            if failed_count:
                logger.warning(
                    "Binance orderbook: %d/%d symbols failed — partial data returned",
                    failed_count, n,
                )

            if "bid" in fields_to_fetch:
                result["bid"] = bids
            if "ask" in fields_to_fetch:
                result["ask"] = asks
            if "spread" in fields_to_fetch:
                result["spread"] = asks - bids

        return result

    def fetch_history(
        self,
        symbols: list[str],
        requested_fields: set[str],
        resolution: str,
        lookback: int,
    ) -> dict[str, np.ndarray]:
        """Fetch historical klines to backfill rolling buffers.

        Args:
            symbols: List of Binance symbol strings (e.g. ["BTCUSDT"]).
            requested_fields: Set of field names to fetch.
            resolution: Data resolution string (e.g. "1min", "5min", "1day").
            lookback: Number of historical bars requested.

        Returns:
            Dict mapping field_name -> np.ndarray of shape [N_symbols, lookback].
            Columns are oldest-first (left=oldest, right=most recent).
        """
        fields_to_fetch = requested_fields & self.ALL_FIELDS
        # bid/ask/spread have no historical kline data — skip
        bar_fields = fields_to_fetch & {"open", "high", "low", "close", "volume",
                                         "price", "vwap", "day_change_pct", "num_trades"}
        if not bar_fields:
            return {}

        # Map resolution to Binance interval
        res_map = {
            "1min": "1m", "5min": "5m", "15min": "15m",
            "30min": "30m", "60min": "1h", "1day": "1d",
        }
        interval = res_map.get(resolution, "1d")

        n = len(symbols)
        sym_idx = {s: i for i, s in enumerate(symbols)}

        # Initialize arrays
        field_arrays: dict[str, np.ndarray] = {}
        for f in bar_fields:
            field_arrays[f] = np.full((n, lookback), np.nan, dtype=np.float64)

        # Fetch klines per symbol (no multi-symbol klines endpoint)
        for symbol in symbols:
            idx = sym_idx[symbol]
            try:
                resp = self._session.get(
                    f"{BINANCE_BASE}/api/v3/klines",
                    params={
                        "symbol": symbol,
                        "interval": interval,
                        "limit": lookback,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                klines = resp.json()

                # Kline format: [open_time, open, high, low, close, volume,
                #                close_time, quote_volume, num_trades, ...]
                bar_count = len(klines)
                take = min(bar_count, lookback)
                recent = klines[-take:]

                for j, k in enumerate(recent):
                    col = lookback - take + j
                    if len(k) < 9:
                        logger.warning("Binance kline truncated for %s (got %d fields, need 9)", symbol, len(k))
                        continue
                    try:
                        o, h, lo, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
                        quote_vol = float(k[7])
                        trades = float(k[8])
                    except (ValueError, TypeError) as e:
                        logger.warning("Binance kline parse error for %s at bar %d: %s", symbol, j, e)
                        continue

                    if "open" in field_arrays:
                        field_arrays["open"][idx, col] = o
                    if "high" in field_arrays:
                        field_arrays["high"][idx, col] = h
                    if "low" in field_arrays:
                        field_arrays["low"][idx, col] = lo
                    if "close" in field_arrays:
                        field_arrays["close"][idx, col] = c
                    if "price" in field_arrays:
                        field_arrays["price"][idx, col] = c
                    if "volume" in field_arrays:
                        field_arrays["volume"][idx, col] = v
                    if "vwap" in field_arrays:
                        # Approximate VWAP = quote_volume / volume
                        if v > 0:
                            field_arrays["vwap"][idx, col] = quote_vol / v
                        elif c > 0:
                            field_arrays["vwap"][idx, col] = c
                        else:
                            logger.debug("VWAP fallback: zero volume and zero close for %s bar %d", symbol, j)
                    if "num_trades" in field_arrays:
                        field_arrays["num_trades"][idx, col] = trades
            except Exception:
                logger.warning("Binance klines fetch error for %s", symbol, exc_info=True)

        # Compute day_change_pct as bar-over-bar close change (matches yfinance behavior)
        if "day_change_pct" in field_arrays:
            close_arr = field_arrays.get("close") or field_arrays.get("price")
            if close_arr is not None:
                dcp = field_arrays["day_change_pct"]
                for i in range(n):
                    for j in range(1, lookback):
                        prev_val = close_arr[i, j - 1]
                        curr_val = close_arr[i, j]
                        if not np.isnan(prev_val) and not np.isnan(curr_val) and prev_val != 0:
                            dcp[i, j] = (curr_val - prev_val) / prev_val * 100

        return {k: v for k, v in field_arrays.items() if k in bar_fields}
