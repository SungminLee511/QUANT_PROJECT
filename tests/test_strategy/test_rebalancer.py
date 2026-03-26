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

    def test_rebalance_mode_sell_capped(self, rebalancer):
        """In rebalance (default) mode, sell quantity is capped to current holdings."""
        weights = np.array([-0.5, 0.5, 0.0])  # negative weight, but rebalance mode
        positions = {"AAPL": 5.0}  # only 5 shares
        prices = np.array([100.0, 100.0, 100.0])
        orders = rebalancer.rebalance(weights, positions, 10000, prices)
        # In rebalance mode, negative weight target → sell, but capped to 5 shares
        sell_orders = [o for o in orders if o.side == Side.SELL]
        for o in sell_orders:
            if o.symbol == "AAPL":
                assert o.quantity <= 5.0


class TestLongShortRebalancer:
    """Long-short mode: allows selling beyond holdings (opens short)."""

    @pytest.fixture
    def rebalancer(self):
        return WeightRebalancer(
            session_id="test",
            symbols=["AAPL", "MSFT", "GOOGL"],
            exchange=Exchange.ALPACA,
            strategy_mode="long_short",
        )

    def test_short_opens_from_zero(self, rebalancer):
        """Negative weight with no position → SELL order (opens short)."""
        weights = np.array([0.3, -0.3, 0.0])
        positions = {}  # no holdings
        prices = np.array([100.0, 100.0, 100.0])
        orders = rebalancer.rebalance(weights, positions, 10000, prices)
        sides = {o.symbol: o.side for o in orders}
        assert sides.get("AAPL") == Side.BUY
        assert sides.get("MSFT") == Side.SELL  # short opened!

    def test_short_sell_not_capped(self, rebalancer):
        """In long_short mode, sell quantity is NOT capped to current holdings."""
        weights = np.array([-0.5, 0.5, 0.0])
        positions = {}  # zero holdings
        prices = np.array([100.0, 100.0, 100.0])
        orders = rebalancer.rebalance(weights, positions, 10000, prices)
        sell_orders = [o for o in orders if o.side == Side.SELL and o.symbol == "AAPL"]
        assert len(sell_orders) == 1
        # Should try to sell $5000 worth = 50 shares, not capped to 0
        assert sell_orders[0].quantity == pytest.approx(50.0, rel=0.01)

    def test_flatten_short_generates_buy(self, rebalancer):
        """Going from short position to zero weight → BUY to cover."""
        weights = np.array([0.0, 0.0, 0.0])
        positions = {"AAPL": -20.0}  # short 20 shares
        prices = np.array([100.0, 100.0, 100.0])
        total_equity = 10000 + 20 * 100  # cash + short value adjustment
        orders = rebalancer.rebalance(weights, positions, total_equity, prices)
        buy_orders = [o for o in orders if o.side == Side.BUY and o.symbol == "AAPL"]
        assert len(buy_orders) == 1  # buy to cover
