"""Abstract base class for all trading strategies."""

from abc import ABC, abstractmethod
from typing import Any

from shared.schemas import MarketTick, OHLCVBar, TradeSignal


class BaseStrategy(ABC):
    """Interface that all strategies must implement.

    The strategy engine calls on_tick() for each price update and
    on_bar() for each completed OHLCV bar. Return a TradeSignal to
    emit a buy/sell, or None to do nothing.

    Both methods receive an optional extra_data dict containing custom
    data from data/custom_data.py (user-provided scraping pipeline).
    Access via: extra_data.get("AAPL", {}).get("put_call_ratio")
    """

    def __init__(self, strategy_id: str, params: dict):
        self.strategy_id = strategy_id
        self.params = params

    @abstractmethod
    async def on_tick(self, tick: MarketTick, extra_data: dict[str, dict[str, Any]] | None = None) -> TradeSignal | None:
        """Process a single tick. Return a signal or None.

        Args:
            tick: MarketTick with symbol, price, volume, timestamp, exchange
            extra_data: Custom data keyed by symbol from data/custom_data.py.
                        e.g. {"AAPL": {"put_call_ratio": 0.85, ...}}
                        None if no custom pipeline configured.
        """
        ...

    @abstractmethod
    async def on_bar(self, bar: OHLCVBar, extra_data: dict[str, dict[str, Any]] | None = None) -> TradeSignal | None:
        """Process a completed OHLCV bar. Return a signal or None.

        Args:
            bar: OHLCVBar with symbol, open, high, low, close, volume, interval, timestamp
            extra_data: Custom data keyed by symbol from data/custom_data.py.
                        None if no custom pipeline configured.
        """
        ...

    async def on_start(self) -> None:
        """Called once when the strategy starts. Override for initialization."""
        pass

    async def on_stop(self) -> None:
        """Called on shutdown. Override for cleanup."""
        pass
