"""yfinance data source — fetches live price + daily fundamentals for US stocks."""

import logging
import numpy as np

logger = logging.getLogger(__name__)


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
                logger.debug("Batch download failed, falling back to per-symbol fast_info")
                self._fetch_fast_info_fallback(symbols, batch_fields, result)

        # ── Fundamentals: per-symbol ticker.info (no batch API available) ──
        if fundamental_fields:
            for field_name in fundamental_fields:
                values = np.zeros(n, dtype=np.float64)
                for i, sym in enumerate(symbols):
                    try:
                        info = yf.Ticker(sym).info or {}
                        info_map = {
                            "market_cap": "marketCap",
                            "pe_ratio": "trailingPE",
                            "week52_high": "fiftyTwoWeekHigh",
                            "week52_low": "fiftyTwoWeekLow",
                        }
                        values[i] = float(info.get(info_map[field_name], 0) or 0)
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
            # period="2d" gives today + yesterday (needed for prev_close / day_change_pct)
            df = yf.download(
                symbols if n > 1 else symbols[0],
                period="2d",
                interval="1d",
                progress=False,
                threads=True,
            )
            if df.empty:
                return False

            multi = n > 1

            def _col(yf_col: str, sym: str) -> float:
                """Extract latest value for a symbol from the download dataframe."""
                try:
                    series = df[(yf_col, sym)] if multi else df[yf_col]
                    vals = series.dropna()
                    return float(vals.iloc[-1]) if len(vals) > 0 else 0.0
                except (KeyError, IndexError):
                    return 0.0

            def _prev_close(sym: str) -> float:
                """Get previous day's close (second-to-last row)."""
                try:
                    series = df[("Close", sym)] if multi else df["Close"]
                    vals = series.dropna()
                    return float(vals.iloc[-2]) if len(vals) >= 2 else 0.0
                except (KeyError, IndexError):
                    return 0.0

            for field_name in fields:
                values = np.zeros(n, dtype=np.float64)
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
                        pc = _prev_close(sym)
                        values[i] = pc if pc else _col("Close", sym)
                    elif field_name == "volume":
                        values[i] = _col("Volume", sym)
                    elif field_name == "day_change_pct":
                        price = _col("Close", sym)
                        prev = _prev_close(sym)
                        values[i] = ((price - prev) / prev * 100) if prev > 0 else 0.0
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
        # Initialize arrays
        for field_name in fields:
            if field_name not in result:
                result[field_name] = np.zeros(n, dtype=np.float64)

        for i, symbol in enumerate(symbols):
            try:
                ticker = yf.Ticker(symbol)
                try:
                    fi = ticker.fast_info
                except Exception:
                    fi = None
                if fi is None:
                    logger.debug("fast_info returned None for %s, using fallback zeros", symbol)
                    fi = {}

                price = float(fi.get("lastPrice", 0) or fi.get("last_price", 0) or 0)
                prev_close = float(fi.get("previousClose", 0) or fi.get("previous_close", 0) or 0)

                if "price" in fields:
                    result["price"][i] = price
                if "open" in fields:
                    result["open"][i] = float(fi.get("open", 0) or 0)
                if "high" in fields:
                    result["high"][i] = float(fi.get("dayHigh", 0) or fi.get("day_high", 0) or 0)
                if "low" in fields:
                    result["low"][i] = float(fi.get("dayLow", 0) or fi.get("day_low", 0) or 0)
                if "close" in fields:
                    result["close"][i] = prev_close if prev_close else price
                if "volume" in fields:
                    result["volume"][i] = float(fi.get("lastVolume", 0) or fi.get("last_volume", 0) or 0)
                if "day_change_pct" in fields:
                    if prev_close and prev_close > 0:
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
        interval = res_map.get(resolution, "1d")

        # Choose a generous period to ensure we get enough bars
        period_map = {
            "1m": "5d", "5m": "5d", "15m": "5d",
            "30m": "1mo", "60m": "1mo", "1d": "3mo",
        }
        period = period_map.get(interval, "3mo")

        n = len(symbols)
        ohlcv_fields = fields_to_fetch & {"open", "high", "low", "close", "price", "volume"}
        fundamental_fields = fields_to_fetch & {"market_cap", "pe_ratio", "week52_high",
                                                  "week52_low", "day_change_pct"}

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

        # For fundamentals: no per-bar history, repeat current value
        if fundamental_fields:
            import yfinance as yf
            for field_name in fundamental_fields:
                arr = np.full((n, lookback), np.nan, dtype=np.float64)
                for i, sym in enumerate(symbols):
                    try:
                        ticker = yf.Ticker(sym)
                        if field_name == "day_change_pct":
                            try:
                                fi = ticker.fast_info
                            except Exception:
                                fi = None
                            if fi is None:
                                fi = {}
                            price = float(fi.get("lastPrice", 0) or fi.get("last_price", 0) or 0)
                            prev = float(fi.get("previousClose", 0) or fi.get("previous_close", 0) or 0)
                            val = ((price - prev) / prev * 100) if prev else 0.0
                        else:
                            info = ticker.info
                            info_map = {
                                "market_cap": "marketCap",
                                "pe_ratio": "trailingPE",
                                "week52_high": "fiftyTwoWeekHigh",
                                "week52_low": "fiftyTwoWeekLow",
                            }
                            val = float(info.get(info_map[field_name], 0) or 0)
                        arr[i, :] = val
                    except Exception:
                        logger.warning("yfinance history fundamental error for %s/%s", sym, field_name)
                result[field_name] = arr

        return result
