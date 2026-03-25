"""Tests for the V2 backtesting engine."""

import numpy as np
import pytest

from backtest.engine import (
    BacktestResult,
    BacktestTrade,
    _VirtualPortfolio,
    _compute_metrics,
    _build_data_snapshot,
    _append_to_buffer,
)


# ---------------------------------------------------------------------------
# Strategy code fixtures (V2 format)
# ---------------------------------------------------------------------------

MOMENTUM_V2 = '''
import numpy as np

def main(data: dict) -> np.ndarray:
    prices = data["price"]
    current = prices[:, -1]
    mean = prices.mean(axis=1)
    safe_mean = np.where(mean != 0, mean, 1.0)
    deviation = (current - safe_mean) / safe_mean
    return deviation
'''

ALL_LONG = '''
import numpy as np

def main(data: dict) -> np.ndarray:
    n = len(data["tickers"])
    return np.ones(n) / n  # equal weight long
'''

ALL_ZERO = '''
import numpy as np

def main(data: dict) -> np.ndarray:
    return np.zeros(len(data["tickers"]))
'''

INVALID_STRATEGY = '''
def not_main(x):
    pass
'''


# ---------------------------------------------------------------------------
# _VirtualPortfolio (V2 — weight-based)
# ---------------------------------------------------------------------------

class TestVirtualPortfolio:
    def test_initial_state(self):
        p = _VirtualPortfolio(10000, ["AAPL", "MSFT"])
        assert p.cash == 10000
        assert p.get_equity() == 10000
        assert p.positions == {}

    def test_rebalance_buy(self):
        p = _VirtualPortfolio(10000, ["AAPL", "MSFT"])
        p.update_prices({"AAPL": 150.0, "MSFT": 300.0})
        weights = np.array([0.6, 0.4])
        trades = p.rebalance(weights, "2024-01-01")
        assert len(trades) == 2
        assert all(t.side == "buy" for t in trades)
        # Cash should be reduced
        assert p.cash < 10000
        assert p.get_equity() == pytest.approx(10000, abs=5)

    def test_rebalance_sell(self):
        p = _VirtualPortfolio(10000, ["AAPL"])
        p.update_prices({"AAPL": 100.0})
        # First buy in
        weights_buy = np.array([0.8])
        p.rebalance(weights_buy, "2024-01-01")
        assert "AAPL" in p.positions
        # Now rebalance down
        weights_sell = np.array([0.2])
        trades = p.rebalance(weights_sell, "2024-01-02")
        sell_trades = [t for t in trades if t.side == "sell"]
        assert len(sell_trades) >= 1

    def test_rebalance_zero_weights_sells_all(self):
        p = _VirtualPortfolio(10000, ["AAPL"])
        p.update_prices({"AAPL": 100.0})
        p.rebalance(np.array([1.0]), "2024-01-01")
        assert "AAPL" in p.positions
        # Flatten
        trades = p.rebalance(np.array([0.0]), "2024-01-02")
        assert len(trades) >= 1
        assert p.positions.get("AAPL", 0) < 0.01

    def test_equity_tracks_price_changes(self):
        p = _VirtualPortfolio(10000, ["AAPL"])
        p.update_prices({"AAPL": 100.0})
        p.rebalance(np.array([1.0]), "2024-01-01")
        # Price doubles
        p.update_prices({"AAPL": 200.0})
        assert p.get_equity() > 10000

    def test_wrong_shape_returns_no_trades(self):
        p = _VirtualPortfolio(10000, ["AAPL", "MSFT"])
        p.update_prices({"AAPL": 100.0, "MSFT": 200.0})
        trades = p.rebalance(np.array([1.0]), "2024-01-01")  # wrong shape
        assert trades == []


# ---------------------------------------------------------------------------
# Rolling buffer helpers
# ---------------------------------------------------------------------------

class TestRollingBuffers:
    def test_append_and_snapshot(self):
        symbols = ["A", "B"]
        fields = {"price": 3}
        buffers = {"price": np.full((2, 13), np.nan)}
        fill_counts = {"price": 0}

        # Append 3 bars
        for i in range(3):
            vals = np.array([100.0 + i, 200.0 + i])
            _append_to_buffer(buffers, fill_counts, "price", vals)

        assert fill_counts["price"] == 3

        snapshot = _build_data_snapshot(buffers, fill_counts, fields, symbols)
        assert snapshot is not None
        assert snapshot["price"].shape == (2, 3)
        assert snapshot["price"][0, -1] == 102.0
        assert snapshot["price"][1, -1] == 202.0
        assert snapshot["tickers"] == symbols

    def test_snapshot_returns_none_if_insufficient_data(self):
        fields = {"price": 5}
        buffers = {"price": np.full((2, 15), np.nan)}
        fill_counts = {"price": 2}
        result = _build_data_snapshot(buffers, fill_counts, fields, ["A", "B"])
        assert result is None


# ---------------------------------------------------------------------------
# _compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_empty_curve(self):
        m = _compute_metrics([], [], 10000)
        assert m.total_return_pct == 0

    def test_positive_return(self):
        curve = [
            {"date": "2024-01-01", "equity": 10000},
            {"date": "2024-01-02", "equity": 10100},
            {"date": "2024-01-03", "equity": 10200},
        ]
        m = _compute_metrics(curve, [], 10000)
        assert m.total_return_pct == 2.0
        assert m.trading_days == 3

    def test_max_drawdown(self):
        curve = [
            {"date": "2024-01-01", "equity": 10000},
            {"date": "2024-01-02", "equity": 11000},
            {"date": "2024-01-03", "equity": 9000},
            {"date": "2024-01-04", "equity": 10000},
        ]
        m = _compute_metrics(curve, [], 10000)
        assert m.max_drawdown_pct == pytest.approx(18.18, abs=0.1)

    def test_trade_win_rate(self):
        trades = [
            BacktestTrade("2024-01-01", "AAPL", "buy", 10, 100, 1000, 9000, 10000),
            BacktestTrade("2024-01-02", "AAPL", "sell", 10, 120, 1200, 10200, 10200),
            BacktestTrade("2024-01-03", "AAPL", "buy", 10, 110, 1100, 9100, 10200),
            BacktestTrade("2024-01-04", "AAPL", "sell", 10, 100, 1000, 10100, 10100),
        ]
        curve = [
            {"date": "2024-01-01", "equity": 10000},
            {"date": "2024-01-02", "equity": 10200},
            {"date": "2024-01-03", "equity": 10200},
            {"date": "2024-01-04", "equity": 10100},
        ]
        m = _compute_metrics(curve, trades, 10000)
        assert m.total_trades == 4
        assert m.winning_trades == 1
        assert m.losing_trades == 1
        assert m.win_rate_pct == 50.0

    def test_sharpe_ratio_positive(self):
        # Steady gains -> positive Sharpe
        curve = [{"date": f"2024-01-{i+1:02d}", "equity": 10000 + i * 10}
                 for i in range(30)]
        m = _compute_metrics(curve, [], 10000)
        assert m.sharpe_ratio > 0
