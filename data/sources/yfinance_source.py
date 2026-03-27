"""yfinance data source — fetches live price + daily fundamentals for US stocks."""

import logging
import time

import numpy as np

logger = logging.getLogger(__name__)

# BUG-86: Retry settings for yfinance calls (which handle HTTP internally)
_YF_MAX_RETRIES = 2
_YF_BACKOFF_SEC = 1.0


class YFinanceSource:
    """Fetches market data from Yahoo Finance.

    Live fields: price
    Daily fields: open, high, low, close, volume, day_change_pct, market_cap, pe_ratio, week52_high, week52_low

    Note: yfinance does NOT provide bid/ask/spread or VWAP.
    """

    # Which fields this source can provide
    LIVE_FIELDS = {"price"}
    DAILY_FIELDS = {"open", "high", "low", "close", "volume", "day_change_pct",
                    "market_cap", "pe_ratio", "week52_high", "week52_low"}
    ALL_FIELDS = LIVE_FIELDS | DAILY_FIELDS

    # Fields that can be batch-fetched via yf.download()
    _BATCH_FIELDS = {"price", "open", "high", "low", "close", "volume", "day_change_pct"}
    _FUNDAMENTAL_FIELDS = {"market_cap", "pe_ratio", "week52_high", "week52_low"}

    def fetch(self, symbols: list[str], requested_fields: set[str]) -> dict[str, np.ndarray]:
        """Fetch all requested fields for all symbols.

        Uses yf.download() for batch price/OHLCV data (1 HTTP request for all
        symbols), falling back to individual fast_info calls only on failure.
        Fundamentals still require per-symbol ticker.info calls.

        Args:
            symbols: List of ticker symbols (e.g. ["AAPL", "MSFT"])
            requested_fields: Set of field names to fetch

        Returns:
            Dict mapping field_name -> np.ndarray of shape [N_symbols]
        """
        import yfinance as yf

        fields_to_fetch = requested_fields & self.ALL_FIELDS
        if not fields_to_fetch:
            return {}

        n = len(symbols)
        result: dict[str, np.ndarray] = {}
        batch_fields = fields_to_fetch & self._BATCH_FIELDS
        fundamental_fields = fields_to_fetch & self._FUNDAMENTAL_FIELDS

        # ── Batch fetch price/OHLCV via yf.download() (single HTTP request) ──
        if batch_fields:
            batch_ok = self._fetch_batch(symbols, batch_fields, result)
            if not batch_ok:
                # Fallback: per-symbol fast_info (N requests)
                logger.warning("Batch download failed, falling back to per-symbol fast_info")
                self._fetch_fast_info_fallback(symbols, batch_fields, result)

        # ── Fundamentals: per-symbol ticker.info (no batch API available) ──
        if fundamental_fields:
            for field_name in fundamental_fields:
                values = np.full(n, np.nan, dtype=np.float64)
                for i, sym in enumerate(symbols):
                    try:
                        info = yf.Ticker(sym).info or {}
                        info_map = {
                            "market_cap": "marketCap",
                            "pe_ratio": "trailingPE",
                            "week52_high": "fiftyTwoWeekHigh",
                            "week52_low": "fiftyTwoWeekLow",
                        }
                        raw = info.get(info_map[field_name])
                        if raw is not None:
                            values[i] = float(raw)
                    except Exception:
                        logger.warning("yfinance fundamental fetch error for %s/%s", sym, field_name, exc_info=True)
                result[field_name] = values

        return result

    def _fetch_batch(
        self, symbols: list[str], fields: set[str], result: dict[str, np.ndarray],
    ) -> bool:
        """Batch-fetch price/OHLCV fields using yf.download(). Returns True on success."""
        import yfinance as yf

        n = len(symbols)
        try:
            # BUG-86: Retry yf.download on transient failures
            df = None
            for attempt in range(_YF_MAX_RETRIES + 1):
                df = yf.download(
                    symbols if n > 1 else symbols[0],
                    period="2d",
                    interval="1d",
                    progress=False,
                    threads=True,
                )
                if not df.empty:
                    break
                if attempt < _YF_MAX_RETRIES:
                    logger.warning(
                        "yf.download returned empty (attempt %d/%d), retrying after %.1fs",
                        attempt + 1, _YF_MAX_RETRIES, _YF_BACKOFF_SEC * (attempt + 1),
                    )
                    time.sleep(_YF_BACKOFF_SEC * (attempt + 1))
            if df is None or df.empty:
                return False

            multi = n > 1

            def _col(yf_col: str, sym: str) -> float:
                """Extract latest value for a symbol from the download dataframe."""
                try:
                    series = df[(yf_col, sym)] if multi else df[yf_col]
                    vals = series.dropna()
                    # FAUDIT-10: Return NaN (not 0.0) on missing data
                    return float(vals.iloc[-1]) if len(vals) > 0 else np.nan
                except (KeyError, IndexError):
                    return np.nan

            def _prev_close(sym: str) -> float:
                """Get previous day's close (second-to-last row)."""
                try:
                    series = df[("Close", sym)] if multi else df["Close"]
                    vals = series.dropna()
                    # FAUDIT-17: Return NaN (not 0.0) when prev close unavailable
                    return float(vals.iloc[-2]) if len(vals) >= 2 else np.nan
                except (KeyError, IndexError):
                    return np.nan

            for field_name in fields:
                # FAUDIT-10: Use NaN default so missing symbols don't get 0.0
                values = np.full(n, np.nan, dtype=np.float64)
                for i, sym in enumerate(symbols):
                    if field_name == "price":
                        values[i] = _col("Close", sym)
                    elif field_name == "open":
                        values[i] = _col("Open", sym)
                    elif field_name == "high":
                        values[i] = _col("High", sym)
                    elif field_name == "low":
                        values[i] = _col("Low", sym)
                    elif field_name == "close":
                        values[i] = _col("Close", sym)
                    elif field_name == "volume":
                        values[i] = _col("Volume", sym)
                    elif field_name == "day_change_pct":
                        price = _col("Close", sym)
                        prev = _prev_close(sym)
                        # FAUDIT-17: Use NaN when prev close unavailable (0% is meaningful data)
                        if not np.isnan(prev) and not np.isnan(price) and prev > 0:
                            values[i] = (price - prev) / prev * 100
                        # else: stays NaN from np.full initialization
                result[field_name] = values

            return True

        except Exception:
            logger.warning("yf.download batch fetch failed", exc_info=True)
            return False

    def _fetch_fast_info_fallback(
        self, symbols: list[str], fields: set[str], result: dict[str, np.ndarray],
    ) -> None:
        """Per-symbol fast_info fallback (N HTTP requests). Used when batch fails."""
        import yfinance as yf

        n = len(symbols)
        # Initialize arrays — NaN for price fields, zero for volume
        for field_name in fields:
            if field_name not in result:
                if field_name == "volume":
                    result[field_name] = np.zeros(n, dtype=np.float64)
                else:
                    result[field_name] = np.full(n, np.nan, dtype=np.float64)

        for i, symbol in enumerate(symbols):
            try:
                ticker = yf.Ticker(symbol)
                try:
                    fi = ticker.fast_info
                except Exception:
                    fi = None
                if fi is None:
                    logger.warning("fast_info returned None for %s, using NaN defaults", symbol)
                    fi = {}

                _last = fi.get("lastPrice") or fi.get("last_price")
                price = float(_last) if _last is not None else np.nan
                _prev = fi.get("previousClose") or fi.get("previous_close")
                prev_close = float(_prev) if _prev is not None else np.nan

                if "price" in fields:
                    result["price"][i] = price
                if "open" in fields:
                    _o = fi.get("open")
                    result["open"][i] = float(_o) if _o is not None else np.nan
                if "high" in fields:
                    _h = fi.get("dayHigh") or fi.get("day_high")
                    result["high"][i] = float(_h) if _h is not None else np.nan
                if "low" in fields:
                    _l = fi.get("dayLow") or fi.get("day_low")
                    result["low"][i] = float(_l) if _l is not None else np.nan
                if "close" in fields:
                    result["close"][i] = price
                if "volume" in fields:
                    _v = fi.get("lastVolume") or fi.get("last_volume")
                    result["volume"][i] = float(_v) if _v is not None else 0.0
                if "day_change_pct" in fields:
                    if prev_close is not None and prev_close > 0:
                        result["day_change_pct"][i] = ((price - prev_close) / prev_close) * 100
            except Exception:
                logger.warning("yfinance fast_info fallback error for %s", symbol, exc_info=True)

    def fetch_history(
        self,
        symbols: list[str],
        requested_fields: set[str],
        resolution: str,
        lookback: int,
    ) -> dict[str, np.ndarray]:
        """Fetch historical bars to backfill rolling buffers.

        Args:
            symbols: List of ticker symbols.
            requested_fields: Set of field names to fetch.
            resolution: Data resolution string (e.g. "1min", "5min", "1day").
            lookback: Number of historical bars requested.

        Returns:
            Dict mapping field_name -> np.ndarray of shape [N_symbols, lookback].
            Columns are oldest-first (left=oldest, right=most recent).
        """
        import yfinance as yf

        fields_to_fetch = requested_fields & self.ALL_FIELDS
        if not fields_to_fetch:
            return {}

        # Map resolution to yfinance interval
        res_map = {
            "1min": "1m", "5min": "5m", "15min": "15m",
            "30min": "30m", "60min": "60m", "1day": "1d",
        }
        if resolution not in res_map:
            logger.error(
                "Unsupported resolution '%s' for yfinance history. Supported: %s",
                resolution, list(res_map.keys()),
            )
            return {}
        interval = res_map[resolution]

        # Choose a generous period to ensure we get enough bars
        period_map = {
            "1m": "5d", "5m": "5d", "15m": "5d",
            "30m": "1mo", "60m": "1mo", "1d": "3mo",
        }
        period = period_map.get(interval, "3mo")

        n = len(symbols)
        ohlcv_fields = fields_to_fetch & {"open", "high", "low", "close", "price", "volume"}
        # BUG-33 fix: day_change_pct computed from historical close, not as a fundamental
        needs_day_change = "day_change_pct" in fields_to_fetch
        fundamental_fields = fields_to_fetch & {"market_cap", "pe_ratio", "week52_high",
                                                  "week52_low"}

        result: dict[str, np.ndarray] = {}

        # Fetch OHLCV history if any bar-based fields are requested
        if ohlcv_fields:
            try:
                df = yf.download(
                    symbols if len(symbols) > 1 else symbols[0],
                    period=period,
                    interval=interval,
                    progress=False,
                    threads=True,
                )

                if df.empty:
                    logger.warning("yfinance history: empty dataframe returned")
                else:
                    multi_symbol = len(symbols) > 1

                    # Column mapping: yfinance col -> our field names
                    col_map = {
                        "Open": "open", "High": "high", "Low": "low",
                        "Close": "close", "Volume": "volume",
                    }

                    for yf_col, field_name in col_map.items():
                        if field_name not in ohlcv_fields and not (
                            field_name == "close" and "price" in ohlcv_fields
                        ):
                            continue

                        arr = np.full((n, lookback), np.nan, dtype=np.float64)
                        for i, sym in enumerate(symbols):
                            try:
                                if multi_symbol:
                                    series = df[(yf_col, sym)].dropna().values
                                else:
                                    series = df[yf_col].dropna().values

                                series = series.astype(np.float64)
                                take = min(len(series), lookback)
                                arr[i, -take:] = series[-take:]
                            except (KeyError, Exception):
                                pass  # leave as NaN

                        if field_name in ohlcv_fields:
                            result[field_name] = arr
                        if field_name == "close" and "price" in ohlcv_fields:
                            result["price"] = arr.copy()

            except Exception:
                logger.warning("yfinance history fetch error", exc_info=True)

        # BUG-33 fix: compute day_change_pct per-bar from historical close prices
        if needs_day_change:
            # Ensure we have close data to derive from
            close_arr = result.get("close") or result.get("price")
            if close_arr is not None:
                dcp_arr = np.full((n, lookback), np.nan, dtype=np.float64)
                for i in range(n):
                    for j in range(1, lookback):
                        prev_val = close_arr[i, j - 1]
                        curr_val = close_arr[i, j]
                        if not np.isnan(prev_val) and not np.isnan(curr_val) and prev_val != 0:
                            dcp_arr[i, j] = (curr_val - prev_val) / prev_val * 100
                result["day_change_pct"] = dcp_arr
            else:
                # No close data available — fetch close history specifically for day_change_pct
                try:
                    df = yf.download(
                        symbols if len(symbols) > 1 else symbols[0],
                        period=period_map.get(interval, "3mo"),
                        interval=interval,
                        progress=False,
                        threads=True,
                    )
                    if not df.empty:
                        multi_symbol = len(symbols) > 1
                        dcp_arr = np.full((n, lookback), np.nan, dtype=np.float64)
                        for i, sym in enumerate(symbols):
                            try:
                                if multi_symbol:
                                    series = df[("Close", sym)].dropna().values.astype(np.float64)
                                else:
                                    series = df["Close"].dropna().values.astype(np.float64)
                                # Compute pct changes
                                pct = np.diff(series) / series[:-1] * 100
                                take = min(len(pct), lookback)
                                dcp_arr[i, -take:] = pct[-take:]
                            except (KeyError, Exception):
                                pass
                        result["day_change_pct"] = dcp_arr
                except Exception:
                    logger.warning("yfinance day_change_pct fetch error", exc_info=True)

        # For fundamentals: no per-bar history, repeat current value
        if fundamental_fields:
            import yfinance as yf
            for field_name in fundamental_fields:
                arr = np.full((n, lookback), np.nan, dtype=np.float64)
                for i, sym in enumerate(symbols):
                    try:
                        ticker = yf.Ticker(sym)
                        info = ticker.info
                        info_map = {
                            "market_cap": "marketCap",
                            "pe_ratio": "trailingPE",
                            "week52_high": "fiftyTwoWeekHigh",
                            "week52_low": "fiftyTwoWeekLow",
                        }
                        raw = info.get(info_map[field_name])
                        if raw is not None:
                            arr[i, :] = float(raw)
                    except Exception:
                        logger.warning("yfinance history fundamental error for %s/%s", sym, field_name)
                result[field_name] = arr

        return result
