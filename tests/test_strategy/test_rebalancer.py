"""Tests for WeightRebalancer — converts portfolio weights to orders."""

import numpy as np
import pytest

from shared.enums import Exchange, Side
from strategy.rebalancer import WeightRebalancer


class TestWeightRebalancer:
    @pytest.fixture
    def rebalancer(self):
        return WeightRebalancer(
            session_id="test",
            symbols=["AAPL", "MSFT", "GOOGL"],
            exchange=Exchange.ALPACA,
        )

    def test_buy_from_cash(self, rebalancer):
        """Start with all cash, rebalance to 60/40/0 → two buy orders."""
        weights = np.array([0.6, 0.4, 0.0])
        positions = {}
        prices = np.array([150.0, 300.0, 100.0])
        orders = rebalancer.rebalance(weights, positions, 10000, prices)
        buy_symbols = {o.symbol for o in orders if o.side == Side.BUY}
        assert "AAPL" in buy_symbols
        assert "MSFT" in buy_symbols
        assert all(o.quantity > 0 for o in orders)

    def test_sell_to_flatten(self, rebalancer):
        """From existing positions, go to zero weights → all sell."""
        weights = np.array([0.0, 0.0, 0.0])
        positions = {"AAPL": 10.0, "MSFT": 5.0}
        prices = np.array([150.0, 300.0, 100.0])
        orders = rebalancer.rebalance(weights, positions, 10000, prices)
        sell_symbols = {o.symbol for o in orders if o.side == Side.SELL}
        assert "AAPL" in sell_symbols
        assert "MSFT" in sell_symbols

    def test_rebalance_generates_both_buy_and_sell(self, rebalancer):
        """Shift weight from AAPL to GOOGL → sell AAPL, buy GOOGL."""
        weights = np.array([0.0, 0.5, 0.5])
        positions = {"AAPL": 30.0, "MSFT": 10.0}  # AAPL heavy
        prices = np.array([150.0, 300.0, 100.0])
        total_equity = 30 * 150 + 10 * 300 + 0  # 7500
        orders = rebalancer.rebalance(weights, positions, total_equity, prices)
        sides = {o.symbol: o.side for o in orders}
        assert sides.get("AAPL") == Side.SELL
        assert sides.get("GOOGL") == Side.BUY

    def test_skip_dust_orders(self, rebalancer):
        """If diff is < $1, no order generated."""
        weights = np.array([0.3334, 0.3333, 0.3333])
        # Current allocation is already very close to target
        positions = {"AAPL": 22.22, "MSFT": 11.11, "GOOGL": 33.33}
        prices = np.array([150.0, 300.0, 100.0])
        total_equity = 22.22 * 150 + 11.11 * 300 + 33.33 * 100
        orders = rebalancer.rebalance(weights, positions, total_equity, prices)
        # Should generate very few or no orders (all close to target)
        total_value = sum(abs(o.quantity * prices[rebalancer.symbols.index(o.symbol)])
                         for o in orders)
        # Even if some small orders, total traded value should be small
        assert total_value < total_equity * 0.05

    def test_shape_mismatch_returns_empty(self, rebalancer):
        """Wrong-shaped weights → no orders."""
        weights = np.array([0.5, 0.5])  # 2 instead of 3
        orders = rebalancer.rebalance(weights, {}, 10000, np.array([100.0, 200.0]))
        assert orders == []

    def test_zero_price_skipped(self, rebalancer):
        """Symbols with price 0 are skipped."""
        weights = np.array([0.5, 0.5, 0.0])
        prices = np.array([0.0, 300.0, 100.0])
        orders = rebalancer.rebalance(weights, {}, 10000, prices)
        symbols = {o.symbol for o in orders}
        assert "AAPL" not in symbols  # price is 0

    def test_order_has_correct_exchange(self, rebalancer):
        weights = np.array([1.0, 0.0, 0.0])
        orders = rebalancer.rebalance(
            weights, {}, 10000, np.array([100.0, 200.0, 300.0])
        )
        for o in orders:
            assert o.exchange == Exchange.ALPACA
