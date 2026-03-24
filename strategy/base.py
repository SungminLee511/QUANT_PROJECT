"""Abstract base class for all trading strategies."""

from abc import ABC, abstractmethod

from shared.schemas import MarketTick, OHLCVBar, TradeSignal


class BaseStrategy(ABC):
    """Interface that all strategies must implement.

    The strategy engine calls on_tick() for each price update and
    on_bar() for each completed OHLCV bar. Return a TradeSignal to
    emit a buy/sell, or None to do nothing.
    """

    def __init__(self, strategy_id: str, params: dict):
        self.strategy_id = strategy_id
        self.params = params

    @abstractmethod
    async def on_tick(self, tick: MarketTick) -> TradeSignal | None:
        """Process a single tick. Return a signal or None."""
        ...

    @abstractmethod
    async def on_bar(self, bar: OHLCVBar) -> TradeSignal | None:
        """Process a completed OHLCV bar. Return a signal or None."""
        ...

    async def on_start(self) -> None:
        """Called once when the strategy starts. Override for initialization."""
        pass

    async def on_stop(self) -> None:
        """Called on shutdown. Override for cleanup."""
        pass
