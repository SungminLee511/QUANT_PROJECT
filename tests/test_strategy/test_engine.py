"""Tests for V2 strategy executor and momentum_v2 strategy."""

import numpy as np
import pytest

from strategy.executor import StrategyExecutor


# ---------------------------------------------------------------------------
# Strategy code fixtures
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
    return np.ones(n)
'''

FIFTY_FIFTY = '''
import numpy as np

def main(data: dict) -> np.ndarray:
    n = len(data["tickers"])
    w = np.zeros(n)
    w[0] = 1.0
    w[1] = -1.0 if n > 1 else 0.0
    return w
'''

INVALID_NO_MAIN = '''
import numpy as np

def compute(data):
    return np.zeros(3)
'''

RETURNS_WRONG_SHAPE = '''
import numpy as np

def main(data: dict) -> np.ndarray:
    return np.array([1.0, 2.0])  # always 2 elements
'''

RAISES_ERROR = '''
import numpy as np

def main(data: dict) -> np.ndarray:
    raise RuntimeError("strategy crash")
'''


# ---------------------------------------------------------------------------
# StrategyExecutor
# ---------------------------------------------------------------------------

class TestStrategyExecutor:
    def _make_data(self, symbols, lookback=5, trend="flat"):
        """Build a synthetic data snapshot."""
        n = len(symbols)
        if trend == "flat":
            prices = np.full((n, lookback), 100.0)
        elif trend == "up":
            prices = np.tile(np.linspace(90, 110, lookback), (n, 1))
        elif trend == "down":
            prices = np.tile(np.linspace(110, 90, lookback), (n, 1))
        else:
            prices = np.full((n, lookback), 100.0)
        return {"price": prices, "tickers": symbols}

    def test_load_and_execute_momentum(self):
        symbols = ["AAPL", "MSFT", "GOOGL"]
        ex = StrategyExecutor("test", symbols)
        ex.load_strategy(MOMENTUM_V2)
        data = self._make_data(symbols, lookback=20, trend="up")
        weights = ex.execute(data)
        assert weights.shape == (3,)
        # Rebalance mode: sum(w) <= 1 (no longer forced to exactly 1)
        assert np.sum(weights) <= 1.0 + 1e-9
        assert np.all(weights >= 0)  # uptrend -> positive weights (negatives clamped)

    def test_all_long_normalized(self):
        symbols = ["A", "B", "C"]
        ex = StrategyExecutor("test", symbols)
        ex.load_strategy(ALL_LONG)
        data = self._make_data(symbols)
        weights = ex.execute(data)
        assert weights.shape == (3,)
        assert np.isclose(np.sum(np.abs(weights)), 1.0)
        assert np.allclose(weights, 1 / 3)

    def test_long_short_normalized(self):
        """FIFTY_FIFTY strategy with long_short mode preserves negative weights."""
        symbols = ["A", "B"]
        ex = StrategyExecutor("test", symbols, strategy_mode="long_short")
        ex.load_strategy(FIFTY_FIFTY)
        data = self._make_data(symbols)
        weights = ex.execute(data)
        assert weights.shape == (2,)
        assert np.isclose(np.sum(np.abs(weights)), 1.0)
        assert weights[0] > 0
        assert weights[1] < 0

    def test_no_main_raises(self):
        ex = StrategyExecutor("test", ["A"])
        with pytest.raises(ValueError, match="main"):
            ex.load_strategy(INVALID_NO_MAIN)

    def test_wrong_shape_returns_zeros(self):
        symbols = ["A", "B", "C"]
        ex = StrategyExecutor("test", symbols)
        ex.load_strategy(RETURNS_WRONG_SHAPE)
        data = self._make_data(symbols)
        weights = ex.execute(data)
        assert np.allclose(weights, 0)

    def test_exception_returns_zeros(self):
        symbols = ["A", "B"]
        ex = StrategyExecutor("test", symbols)
        ex.load_strategy(RAISES_ERROR)
        data = self._make_data(symbols)
        weights = ex.execute(data)
        assert np.allclose(weights, 0)

    def test_no_strategy_loaded_returns_zeros(self):
        ex = StrategyExecutor("test", ["A", "B"])
        data = self._make_data(["A", "B"])
        weights = ex.execute(data)
        assert np.allclose(weights, 0)

    def test_flat_prices_zero_weights(self):
        """Momentum on perfectly flat prices returns zero deviation -> zero weights."""
        symbols = ["A", "B"]
        ex = StrategyExecutor("test", symbols)
        ex.load_strategy(MOMENTUM_V2)
        data = self._make_data(symbols, lookback=20, trend="flat")
        weights = ex.execute(data)
        assert np.allclose(weights, 0)
