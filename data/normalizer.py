"""Normalize exchange-specific data into unified MarketTick / OHLCVBar models."""

from datetime import datetime, timezone

from shared.enums import Exchange
from shared.schemas import MarketTick, OHLCVBar


# ── Binance ──────────────────────────────────────────────────────────────────


def normalize_binance_trade(msg: dict) -> MarketTick:
    """Convert a Binance WebSocket trade message to MarketTick.

    Binance trade stream payload keys:
        s = symbol, p = price, q = quantity, T = trade time (ms)
    """
    return MarketTick(
        symbol=msg.get("s", ""),
        price=float(msg.get("p", 0)),
        volume=float(msg.get("q", 0)),
        timestamp=datetime.fromtimestamp(msg.get("T", 0) / 1000, tz=timezone.utc),
        exchange=Exchange.BINANCE,
        source="data.binance",
    )


def normalize_binance_kline(msg: dict) -> OHLCVBar | None:
    """Convert a Binance kline message to OHLCVBar (only on bar close).

    Binance kline payload: k = kline dict with
        s, i, o, h, l, c, v, t (start time), x (is closed)
    """
    k = msg.get("k", {})
    if not k.get("x", False):
        # Bar not closed yet
        return None
    return OHLCVBar(
        symbol=k.get("s", ""),
        open=float(k.get("o", 0)),
        high=float(k.get("h", 0)),
        low=float(k.get("l", 0)),
        close=float(k.get("c", 0)),
        volume=float(k.get("v", 0)),
        interval=k.get("i", "1m"),
        timestamp=datetime.fromtimestamp(k.get("t", 0) / 1000, tz=timezone.utc),
        exchange=Exchange.BINANCE,
        source="data.binance",
    )


# ── Alpaca ───────────────────────────────────────────────────────────────────


def normalize_alpaca_trade(trade) -> MarketTick:
    """Convert an Alpaca Trade object to MarketTick.

    alpaca-py Trade attrs: symbol, price, size, timestamp
    """
    return MarketTick(
        symbol=trade.symbol,
        price=float(trade.price),
        volume=float(trade.size),
        timestamp=trade.timestamp if trade.timestamp else datetime.now(timezone.utc),
        exchange=Exchange.ALPACA,
        source="data.alpaca",
    )


def normalize_alpaca_bar(bar) -> OHLCVBar:
    """Convert an Alpaca Bar object to OHLCVBar.

    alpaca-py Bar attrs: symbol, open, high, low, close, volume, timestamp
    """
    return OHLCVBar(
        symbol=bar.symbol,
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        volume=float(bar.volume),
        interval="1m",
        timestamp=bar.timestamp if bar.timestamp else datetime.now(timezone.utc),
        exchange=Exchange.ALPACA,
        source="data.alpaca",
    )
