"""Simple momentum strategy — placeholder for testing the pipeline.

Tracks a rolling window of prices per symbol. If current price exceeds the
window average by threshold%, emit BUY. If below by threshold%, emit SELL.
"""

import logging
from collections import defaultdict, deque

from shared.enums import Signal
from shared.schemas import MarketTick, OHLCVBar, TradeSignal
from strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class MomentumStrategy(BaseStrategy):
    def __init__(self, strategy_id: str, params: dict):
        super().__init__(strategy_id, params)
        self.lookback: int = params.get("lookback", 20)
        self.threshold: float = params.get("threshold", 0.02)  # 2%
        self._windows: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.lookback)
        )

    async def on_start(self) -> None:
        logger.info(
            "MomentumStrategy started (lookback=%d, threshold=%.2f%%)",
            self.lookback,
            self.threshold * 100,
        )

    async def on_tick(self, tick: MarketTick) -> TradeSignal | None:
        window = self._windows[tick.symbol]
        window.append(tick.price)

        if len(window) < self.lookback:
            return None  # Not enough data yet

        avg = sum(window) / len(window)
        deviation = (tick.price - avg) / avg

        if deviation > self.threshold:
            return TradeSignal(
                symbol=tick.symbol,
                signal=Signal.BUY,
                strength=min(abs(deviation) / self.threshold, 1.0),
                strategy_id=self.strategy_id,
                metadata={"avg": avg, "deviation": deviation},
            )
        elif deviation < -self.threshold:
            return TradeSignal(
                symbol=tick.symbol,
                signal=Signal.SELL,
                strength=min(abs(deviation) / self.threshold, 1.0),
                strategy_id=self.strategy_id,
                metadata={"avg": avg, "deviation": deviation},
            )
        return None

    async def on_bar(self, bar: OHLCVBar) -> TradeSignal | None:
        # Use close price of completed bars as additional data points
        window = self._windows[bar.symbol]
        window.append(bar.close)
        return None  # Only signal on ticks for this simple strategy
