"""Alpaca Market Data source — fetches live quotes + daily bars for US stocks."""

import logging
import numpy as np
import requests

logger = logging.getLogger(__name__)

ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"


class AlpacaSource:
    """Fetches market data from Alpaca Market Data API.

    Live fields: price, bid, ask, spread
    Daily fields: open, high, low, close, volume, vwap

    Requires API key (APCA-API-KEY-ID + APCA-API-SECRET-KEY).
    """

    LIVE_FIELDS = {"price", "bid", "ask", "spread"}
    DAILY_FIELDS = {"open", "high", "low", "close", "volume", "vwap"}
    ALL_FIELDS = LIVE_FIELDS | DAILY_FIELDS

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self._session = requests.Session()
        if api_key:
            self._session.headers.update({
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
            })

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def fetch(self, symbols: list[str], requested_fields: set[str]) -> dict[str, np.ndarray]:
        """Fetch all requested fields for all symbols.

        Returns empty dict if no API credentials.
        """
        if not self.has_credentials:
            logger.warning("Alpaca API: no credentials configured, skipping fetch")
            return {}

        fields_to_fetch = requested_fields & self.ALL_FIELDS
        if not fields_to_fetch:
            return {}

        n = len(symbols)
        result: dict[str, np.ndarray] = {}

        needs_live = bool(fields_to_fetch & self.LIVE_FIELDS)
        needs_daily = bool(fields_to_fetch & self.DAILY_FIELDS)

        # Symbol -> index mapping
        sym_idx = {s: i for i, s in enumerate(symbols)}

        # 1. Fetch live data (latest trade + latest quote)
        if needs_live:
            # Latest trades (for price)
            if "price" in fields_to_fetch:
                prices = np.zeros(n, dtype=np.float64)
                try:
                    symbols_param = ",".join(symbols)
                    resp = self._session.get(
                        f"{ALPACA_DATA_BASE}/stocks/trades/latest",
                        params={"symbols": symbols_param, "feed": "iex"},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json().get("trades", {})
                    for sym, trade in data.items():
                        idx = sym_idx.get(sym)
                        if idx is not None:
                            p = trade.get("p")
                            if p is not None:
                                prices[idx] = float(p)
                except Exception:
                    logger.warning("Alpaca latest trades fetch error", exc_info=True)
                result["price"] = prices

            # Latest quotes (for bid, ask, spread)
            if fields_to_fetch & {"bid", "ask", "spread"}:
                bids = np.zeros(n, dtype=np.float64)
                asks = np.zeros(n, dtype=np.float64)
                try:
                    symbols_param = ",".join(symbols)
                    resp = self._session.get(
                        f"{ALPACA_DATA_BASE}/stocks/quotes/latest",
                        params={"symbols": symbols_param, "feed": "iex"},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json().get("quotes", {})
                    for sym, quote in data.items():
                        idx = sym_idx.get(sym)
                        if idx is not None:
                            bids[idx] = float(quote.get("bp", 0))
                            asks[idx] = float(quote.get("ap", 0))
                except Exception:
                    logger.warning("Alpaca latest quotes fetch error", exc_info=True)

                if "bid" in fields_to_fetch:
                    result["bid"] = bids
                if "ask" in fields_to_fetch:
                    result["ask"] = asks
                if "spread" in fields_to_fetch:
                    result["spread"] = asks - bids

        # 2. Fetch daily data (latest bar)
        if needs_daily:
            daily_fields = fields_to_fetch & self.DAILY_FIELDS
            opens = np.zeros(n, dtype=np.float64)
            highs = np.zeros(n, dtype=np.float64)
            lows = np.zeros(n, dtype=np.float64)
            closes = np.zeros(n, dtype=np.float64)
            volumes = np.zeros(n, dtype=np.float64)
            vwaps = np.zeros(n, dtype=np.float64)

            try:
                symbols_param = ",".join(symbols)
                resp = self._session.get(
                    f"{ALPACA_DATA_BASE}/stocks/bars/latest",
                    params={"symbols": symbols_param, "feed": "iex"},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json().get("bars", {})
                for sym, bar in data.items():
                    idx = sym_idx.get(sym)
                    if idx is not None:
                        opens[idx] = float(bar["o"]) if "o" in bar else np.nan
                        highs[idx] = float(bar["h"]) if "h" in bar else np.nan
                        lows[idx] = float(bar["l"]) if "l" in bar else np.nan
                        closes[idx] = float(bar["c"]) if "c" in bar else np.nan
                        volumes[idx] = float(bar.get("v", 0))
                        vwaps[idx] = float(bar.get("vw", 0))
                        if any(np.isnan(x) for x in [opens[idx], closes[idx]]):
                            logger.warning("Alpaca bar missing OHLC for %s", sym)
            except Exception:
                logger.warning("Alpaca latest bars fetch error", exc_info=True)

            if "open" in daily_fields:
                result["open"] = opens
            if "high" in daily_fields:
                result["high"] = highs
            if "low" in daily_fields:
                result["low"] = lows
            if "close" in daily_fields:
                result["close"] = closes
            if "volume" in daily_fields:
                result["volume"] = volumes
            if "vwap" in daily_fields:
                result["vwap"] = vwaps

        return result

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
        if not self.has_credentials:
            logger.warning("Alpaca API: no credentials, skipping history backfill")
            return {}

        fields_to_fetch = requested_fields & self.ALL_FIELDS
        # bid/ask/spread have no historical quotes endpoint — skip them
        bar_fields = fields_to_fetch & {"open", "high", "low", "close", "volume", "vwap", "price"}
        if not bar_fields:
            return {}

        # Map resolution to Alpaca timeframe
        res_map = {
            "1min": "1Min", "5min": "5Min", "15min": "15Min",
            "30min": "30Min", "60min": "1Hour", "1day": "1Day",
        }
        timeframe = res_map.get(resolution, "1Day")

        n = len(symbols)
        result: dict[str, np.ndarray] = {}

        try:
            symbols_param = ",".join(symbols)
            resp = self._session.get(
                f"{ALPACA_DATA_BASE}/stocks/bars",
                params={
                    "symbols": symbols_param,
                    "timeframe": timeframe,
                    "limit": lookback,
                    "feed": "iex",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("bars", {})

            sym_idx = {s: i for i, s in enumerate(symbols)}

            # Initialize arrays
            field_arrays: dict[str, np.ndarray] = {}
            for f in bar_fields:
                field_arrays[f] = np.full((n, lookback), np.nan, dtype=np.float64)

            # Parse bars per symbol
            for sym, bars in data.items():
                idx = sym_idx.get(sym)
                if idx is None:
                    continue

                bar_count = len(bars)
                take = min(bar_count, lookback)
                recent_bars = bars[-take:]  # oldest first

                for j, bar in enumerate(recent_bars):
                    col = lookback - take + j
                    if "open" in field_arrays:
                        field_arrays["open"][idx, col] = float(bar["o"]) if "o" in bar else np.nan
                    if "high" in field_arrays:
                        field_arrays["high"][idx, col] = float(bar["h"]) if "h" in bar else np.nan
                    if "low" in field_arrays:
                        field_arrays["low"][idx, col] = float(bar["l"]) if "l" in bar else np.nan
                    if "close" in field_arrays:
                        field_arrays["close"][idx, col] = float(bar["c"]) if "c" in bar else np.nan
                    if "price" in field_arrays:
                        field_arrays["price"][idx, col] = float(bar["c"]) if "c" in bar else np.nan
                    if "volume" in field_arrays:
                        field_arrays["volume"][idx, col] = float(bar.get("v", 0))
                    if "vwap" in field_arrays:
                        field_arrays["vwap"][idx, col] = float(bar.get("vw", 0))

            result.update(field_arrays)

        except Exception:
            logger.warning("Alpaca history fetch error", exc_info=True)

        return result
