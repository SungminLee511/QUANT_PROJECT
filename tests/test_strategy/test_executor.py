"""Tests for StrategyExecutor — mode-aware weight normalization."""

import numpy as np
import pytest

from strategy.executor import StrategyExecutor


class TestRebalanceMode:
    """Long-only (rebalance) mode: clamp negatives, cap sum at 1."""

    def _make_executor(self, symbols, code):
        ex = StrategyExecutor("test", symbols, strategy_mode="rebalance")
        ex.load_strategy(code)
        return ex

    def test_clamp_negatives(self):
        """Negative weights clamped to 0, sum <= 1 kept as-is."""
        code = "import numpy as np\ndef main(data):\n    return np.array([0.5, -0.3, 0.2])"
        ex = self._make_executor(["A", "B", "C"], code)
        w = ex.execute({"tickers": ["A", "B", "C"]})
        np.testing.assert_allclose(w, [0.5, 0.0, 0.2])

    def test_cap_sum_over_one(self):
        """Weights exceeding sum=1 are scaled down proportionally."""
        code = "import numpy as np\ndef main(data):\n    return np.array([0.6, 0.5, 0.3])"
        ex = self._make_executor(["A", "B", "C"], code)
        w = ex.execute({"tickers": ["A", "B", "C"]})
        assert abs(np.sum(w) - 1.0) < 1e-9
        # Proportions preserved
        assert w[0] > w[1] > w[2]

    def test_cash_holding(self):
        """Weights summing to less than 1 are kept (remainder = cash)."""
        code = "import numpy as np\ndef main(data):\n    return np.array([0.3, 0.2])"
        ex = self._make_executor(["A", "B"], code)
        w = ex.execute({"tickers": ["A", "B"]})
        np.testing.assert_allclose(w, [0.3, 0.2])

    def test_all_zeros(self):
        """All-zero weights stay zero."""
        code = "import numpy as np\ndef main(data):\n    return np.array([0.0, 0.0])"
        ex = self._make_executor(["A", "B"], code)
        w = ex.execute({"tickers": ["A", "B"]})
        np.testing.assert_allclose(w, [0.0, 0.0])

    def test_all_negative_returns_zero(self):
        """If all weights are negative, clamping gives all zeros."""
        code = "import numpy as np\ndef main(data):\n    return np.array([-0.5, -0.3])"
        ex = self._make_executor(["A", "B"], code)
        w = ex.execute({"tickers": ["A", "B"]})
        np.testing.assert_allclose(w, [0.0, 0.0])


class TestLongShortMode:
    """Long-short mode: allow negatives, cap sum(|w|) at 1."""

    def _make_executor(self, symbols, code):
        ex = StrategyExecutor("test", symbols, strategy_mode="long_short")
        ex.load_strategy(code)
        return ex

    def test_keep_negatives(self):
        """Negative weights preserved when sum(|w|) <= 1."""
        code = "import numpy as np\ndef main(data):\n    return np.array([0.4, -0.3, 0.2])"
        ex = self._make_executor(["A", "B", "C"], code)
        w = ex.execute({"tickers": ["A", "B", "C"]})
        np.testing.assert_allclose(w, [0.4, -0.3, 0.2])

    def test_cap_abs_sum(self):
        """sum(|w|) > 1 → scale down, preserving signs."""
        code = "import numpy as np\ndef main(data):\n    return np.array([0.5, -0.5, 0.3])"
        ex = self._make_executor(["A", "B", "C"], code)
        w = ex.execute({"tickers": ["A", "B", "C"]})
        assert abs(np.sum(np.abs(w)) - 1.0) < 1e-9
        assert w[0] > 0  # still positive
        assert w[1] < 0  # still negative
        assert w[2] > 0  # still positive

    def test_cash_holding(self):
        """sum(|w|) < 1 → kept as-is (remainder = cash)."""
        code = "import numpy as np\ndef main(data):\n    return np.array([0.3, -0.2])"
        ex = self._make_executor(["A", "B"], code)
        w = ex.execute({"tickers": ["A", "B"]})
        np.testing.assert_allclose(w, [0.3, -0.2])

    def test_clip_extreme_values(self):
        """Individual weights clipped to [-1, 1]."""
        code = "import numpy as np\ndef main(data):\n    return np.array([2.0, -3.0])"
        ex = self._make_executor(["A", "B"], code)
        w = ex.execute({"tickers": ["A", "B"]})
        # Clipped to [1.0, -1.0], sum(|w|) = 2.0 > 1 → scaled to [0.5, -0.5]
        np.testing.assert_allclose(w, [0.5, -0.5])
