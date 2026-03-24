"""Tests for strategy engine and momentum strategy."""

import pytest

from shared.enums import Exchange, Signal
from shared.schemas import MarketTick, OHLCVBar
from strategy.examples.momentum import MomentumStrategy


class TestMomentumStrategy:
    @pytest.fixture
    def strategy(self):
        return MomentumStrategy(
            strategy_id="test",
            params={"lookback": 5, "threshold": 0.02},
        )

    @pytest.mark.asyncio
    async def test_not_enough_data_returns_none(self, strategy):
        tick = MarketTick(symbol="BTCUSDT", price=100, volume=1, exchange=Exchange.BINANCE)
        result = await strategy.on_tick(tick)
        assert result is None

    @pytest.mark.asyncio
    async def test_buy_signal_on_price_increase(self, strategy):
        # Fill window with stable prices
        for _ in range(5):
            tick = MarketTick(symbol="BTCUSDT", price=100, volume=1, exchange=Exchange.BINANCE)
            await strategy.on_tick(tick)

        # Price jumps up 5% (above 2% threshold)
        tick = MarketTick(symbol="BTCUSDT", price=105, volume=1, exchange=Exchange.BINANCE)
        result = await strategy.on_tick(tick)
        assert result is not None
        assert result.signal == Signal.BUY

    @pytest.mark.asyncio
    async def test_sell_signal_on_price_decrease(self, strategy):
        for _ in range(5):
            tick = MarketTick(symbol="BTCUSDT", price=100, volume=1, exchange=Exchange.BINANCE)
            await strategy.on_tick(tick)

        # Price drops 5%
        tick = MarketTick(symbol="BTCUSDT", price=95, volume=1, exchange=Exchange.BINANCE)
        result = await strategy.on_tick(tick)
        assert result is not None
        assert result.signal == Signal.SELL

    @pytest.mark.asyncio
    async def test_no_signal_within_threshold(self, strategy):
        for _ in range(5):
            tick = MarketTick(symbol="BTCUSDT", price=100, volume=1, exchange=Exchange.BINANCE)
            await strategy.on_tick(tick)

        # Price moves only 1% (below 2% threshold)
        tick = MarketTick(symbol="BTCUSDT", price=101, volume=1, exchange=Exchange.BINANCE)
        result = await strategy.on_tick(tick)
        assert result is None
