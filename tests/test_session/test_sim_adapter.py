"""Tests for the SimulationAdapter."""

import pytest
from unittest.mock import AsyncMock

from execution.sim_adapter import SimulationAdapter
from shared.enums import Exchange, OrderStatus, OrderType, Side
from shared.schemas import OrderRequest


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.subscribe = AsyncMock()
    redis.publish = AsyncMock()
    return redis


@pytest.fixture
def sim_adapter(mock_redis):
    adapter = SimulationAdapter(
        session_id="test-session",
        starting_budget=10000.0,
        exchange=Exchange.BINANCE,
        redis=mock_redis,
    )
    # Pre-set a price for testing
    adapter._last_prices["BTCUSDT"] = 50000.0
    return adapter


class TestSimulationAdapter:
    @pytest.mark.asyncio
    async def test_buy_order_fills_instantly(self, sim_adapter):
        request = OrderRequest(
            symbol="BTCUSDT",
            side=Side.BUY,
            quantity=0.1,
            order_type=OrderType.MARKET,
            exchange=Exchange.BINANCE,
            strategy_id="test",
        )
        order_id = await sim_adapter.place_order(request)
        assert order_id.startswith("sim-")

        status = await sim_adapter.get_order_status(order_id)
        assert status.status == OrderStatus.FILLED
        assert status.filled_qty == 0.1
        assert status.avg_price == 50000.0

    @pytest.mark.asyncio
    async def test_buy_reduces_cash(self, sim_adapter):
        request = OrderRequest(
            symbol="BTCUSDT",
            side=Side.BUY,
            quantity=0.1,
            order_type=OrderType.MARKET,
            exchange=Exchange.BINANCE,
            strategy_id="test",
        )
        await sim_adapter.place_order(request)
        balances = await sim_adapter.get_balances()
        assert balances["cash"] == pytest.approx(10000.0 - 0.1 * 50000.0)

    @pytest.mark.asyncio
    async def test_sell_after_buy(self, sim_adapter):
        buy = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, quantity=0.1,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        await sim_adapter.place_order(buy)

        sell = OrderRequest(
            symbol="BTCUSDT", side=Side.SELL, quantity=0.1,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        await sim_adapter.place_order(sell)

        positions = await sim_adapter.get_positions()
        assert len(positions) == 0

        balances = await sim_adapter.get_balances()
        assert balances["cash"] == pytest.approx(10000.0)  # round-trip, no fees

    @pytest.mark.asyncio
    async def test_buy_exceeding_cash_clips_quantity(self, sim_adapter):
        # Try to buy way more than we can afford
        request = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, quantity=100.0,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        order_id = await sim_adapter.place_order(request)
        status = await sim_adapter.get_order_status(order_id)
        # Should have clipped to 10000/50000 = 0.2
        assert status.filled_qty == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_sell_without_position_raises(self, sim_adapter):
        # Set a price so it doesn't fail on price check first
        sim_adapter._last_prices["ETHUSDT"] = 3000.0
        request = OrderRequest(
            symbol="ETHUSDT", side=Side.SELL, quantity=1.0,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        with pytest.raises(ValueError, match="No position"):
            await sim_adapter.place_order(request)

    @pytest.mark.asyncio
    async def test_no_price_raises(self, sim_adapter):
        request = OrderRequest(
            symbol="UNKNOWN", side=Side.BUY, quantity=1.0,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        with pytest.raises(ValueError, match="No market price"):
            await sim_adapter.place_order(request)

    @pytest.mark.asyncio
    async def test_cancel_always_succeeds(self, sim_adapter):
        result = await sim_adapter.cancel_order("anything")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_positions_after_buy(self, sim_adapter):
        request = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, quantity=0.1,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        await sim_adapter.place_order(request)

        positions = await sim_adapter.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTCUSDT"
        assert positions[0]["quantity"] == pytest.approx(0.1)
        assert positions[0]["avg_entry_price"] == pytest.approx(50000.0)
