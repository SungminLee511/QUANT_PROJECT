"""Custom data pipeline placeholder — USER FILLS THIS IN.

This module provides additional data (beyond price/volume) to strategies.
It is called once per strategy tick (~2 seconds). Your scraping code MUST
complete within that window or it will block the strategy loop.

HOW IT WORKS:
    1. The StrategyEngine calls `fetch_custom_data(symbols)` each tick.
    2. Your code scrapes/computes whatever data you want.
    3. You return a dict keyed by symbol, each value is a dict of your data fields.
    4. The strategy receives this as `extra_data` parameter in on_tick() / on_bar().

EXPECTED RETURN FORMAT:
    {
        "AAPL": {
            "put_call_ratio": 0.85,
            "short_interest": 0.032,
            "sentiment_score": 0.6,
            # ... any keys you want, the strategy reads them by name
        },
        "MSFT": {
            "put_call_ratio": 1.12,
            "short_interest": 0.018,
            "sentiment_score": -0.2,
        },
        # One entry per symbol in the session. Missing symbols = empty dict.
    }

RULES:
    - Return type: dict[str, dict[str, float | int | str | bool | None]]
    - Must complete in < 2 seconds (the tick interval)
    - Must not raise exceptions — return {} on failure
    - No heavy imports at module level (import inside the function if needed)
    - Safe to use: requests, urllib, bs4, json, re, etc.
    - This file is NOT validated by the strategy validator — you have full Python

EXAMPLE (uncomment and modify):

    import requests

    def fetch_custom_data(symbols: list[str]) -> dict[str, dict]:
        result = {}
        for sym in symbols:
            try:
                # Example: scrape put/call ratio from some API
                resp = requests.get(f"https://example.com/api/pcr/{sym}", timeout=1.5)
                data = resp.json()
                result[sym] = {
                    "put_call_ratio": data.get("pcr", None),
                    "volume_24h": data.get("volume", None),
                }
            except Exception:
                result[sym] = {}
        return result
"""

from typing import Any


def fetch_custom_data(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch custom data for the given symbols.

    Args:
        symbols: List of ticker symbols (e.g. ["AAPL", "MSFT"] or ["BTCUSDT"])

    Returns:
        Dict mapping each symbol to a dict of custom data fields.
        Strategy accesses these via extra_data[symbol][field_name].
        Return {} if you have nothing to provide.
    """
    # ── REPLACE THIS WITH YOUR SCRAPING CODE ──
    # Example skeleton:
    #
    #   import requests
    #   result = {}
    #   for sym in symbols:
    #       try:
    #           resp = requests.get(f"https://your-api.com/{sym}", timeout=1.5)
    #           result[sym] = resp.json()
    #       except Exception:
    #           result[sym] = {}
    #   return result

    return {}
