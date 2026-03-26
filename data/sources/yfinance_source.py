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

    def fetch(self, symbols: list[str], requested_fields: set[str]) -> dict[str, np.ndarray]:
        """Fetch all requested fields for all symbols.

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

        result: dict[str, list[float]] = {f: [] for f in fields_to_fetch}

        # Determine if we need fundamentals (slow) or just fast_info (fast)
        needs_fundamentals = bool(fields_to_fetch & {"market_cap", "pe_ratio", "week52_high", "week52_low"})

        for symbol in symbols:
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

                if "price" in result:
                    result["price"].append(price)
                if "open" in result:
                    result["open"].append(float(fi.get("open", 0) or 0))
                if "high" in result:
                    result["high"].append(float(fi.get("dayHigh", 0) or fi.get("day_high", 0) or 0))
                if "low" in result:
                    result["low"].append(float(fi.get("dayLow", 0) or fi.get("day_low", 0) or 0))
                if "close" in result:
                    result["close"].append(prev_close if prev_close else price)
                if "volume" in result:
                    result["volume"].append(float(fi.get("lastVolume", 0) or fi.get("last_volume", 0) or 0))
                if "day_change_pct" in result:
                    if prev_close and prev_close > 0:
                        pct = ((price - prev_close) / prev_close) * 100
                    else:
                        pct = 0.0
                    result["day_change_pct"].append(pct)

                # Fundamentals (slower — requires full info dict)
                if needs_fundamentals:
                    try:
                        info = ticker.info
                    except Exception:
                        info = {}

                    if "market_cap" in result:
                        result["market_cap"].append(float(info.get("marketCap", 0) or 0))
                    if "pe_ratio" in result:
                        result["pe_ratio"].append(float(info.get("trailingPE", 0) or 0))
                    if "week52_high" in result:
                        result["week52_high"].append(float(info.get("fiftyTwoWeekHigh", 0) or 0))
                    if "week52_low" in result:
                        result["week52_low"].append(float(info.get("fiftyTwoWeekLow", 0) or 0))

            except Exception:
                logger.warning("yfinance fetch error for %s", symbol, exc_info=True)
                for f in result:
                    if len(result[f]) < symbols.index(symbol) + 1:
                        result[f].append(0.0)

        return {k: np.array(v, dtype=np.float64) for k, v in result.items()}

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
