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


@pytest.fixture
def sim_adapter_with_commission(mock_redis):
    adapter = SimulationAdapter(
        session_id="test-session",
        starting_budget=10000.0,
        exchange=Exchange.BINANCE,
        redis=mock_redis,
        commission_pct=0.1,  # 0.1%
    )
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


class TestSimulationAdapterCommission:
    @pytest.mark.asyncio
    async def test_buy_deducts_commission(self, sim_adapter_with_commission):
        """0.1% commission on buy should reduce cash beyond trade value."""
        adapter = sim_adapter_with_commission
        request = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, quantity=0.1,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        await adapter.place_order(request)
        balances = await adapter.get_balances()
        trade_value = 0.1 * 50000.0  # 5000
        fee = trade_value * 0.001     # 5.0
        assert balances["cash"] == pytest.approx(10000.0 - trade_value - fee)
        assert balances["total_fees"] == pytest.approx(fee)

    @pytest.mark.asyncio
    async def test_roundtrip_with_commission(self, sim_adapter_with_commission):
        """Buy then sell at same price with 0.1% commission should lose money."""
        adapter = sim_adapter_with_commission
        buy = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, quantity=0.1,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        await adapter.place_order(buy)
        sell = OrderRequest(
            symbol="BTCUSDT", side=Side.SELL, quantity=0.1,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        await adapter.place_order(sell)
        balances = await adapter.get_balances()
        trade_value = 0.1 * 50000.0
        expected_total_fees = trade_value * 0.001 * 2  # fee on buy + sell
        assert balances["cash"] == pytest.approx(10000.0 - expected_total_fees)
        assert balances["total_fees"] == pytest.approx(expected_total_fees)

    @pytest.mark.asyncio
    async def test_zero_commission_no_fees(self, sim_adapter):
        """Default adapter (no commission) should have zero fees."""
        request = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, quantity=0.1,
            order_type=OrderType.MARKET, exchange=Exchange.BINANCE, strategy_id="test",
        )
        await sim_adapter.place_order(request)
        balances = await sim_adapter.get_balances()
        assert balances.get("total_fees", 0) == 0
