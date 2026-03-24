"""Tests for the backtesting engine."""

import pytest

from backtest.engine import (
    BacktestResult,
    BacktestTrade,
    _VirtualPortfolio,
    _compute_metrics,
    _load_strategy_from_code,
)
from shared.enums import Signal
from shared.schemas import TradeSignal


# ---------------------------------------------------------------------------
# Strategy code fixtures
# ---------------------------------------------------------------------------

VALID_STRATEGY = '''
from strategy.base import BaseStrategy
from shared.schemas import MarketTick, OHLCVBar, TradeSignal
from shared.enums import Signal

class TestStrategy(BaseStrategy):
    def __init__(self, strategy_id, params):
        super().__init__(strategy_id, params)
        self._count = 0

    async def on_tick(self, tick, extra_data=None):
        self._count += 1
        if self._count == 3:
            return TradeSignal(
                symbol=tick.symbol,
                signal=Signal.BUY,
                strength=0.5,
                strategy_id=self.strategy_id,
            )
        return None

    async def on_bar(self, bar, extra_data=None):
        return None
'''

ALWAYS_BUY_STRATEGY = '''
from strategy.base import BaseStrategy
from shared.schemas import MarketTick, OHLCVBar, TradeSignal
from shared.enums import Signal

class AlwaysBuy(BaseStrategy):
    async def on_tick(self, tick, extra_data=None):
        return TradeSignal(
            symbol=tick.symbol,
            signal=Signal.BUY,
            strength=0.1,
            strategy_id=self.strategy_id,
        )

    async def on_bar(self, bar, extra_data=None):
        return None
'''

INVALID_STRATEGY = '''
class NotAStrategy:
    def run(self):
        pass
'''


# ---------------------------------------------------------------------------
# _load_strategy_from_code
# ---------------------------------------------------------------------------

class TestLoadStrategy:
    def test_valid_strategy_loads(self):
        strategy = _load_strategy_from_code(VALID_STRATEGY)
        assert strategy.strategy_id == "backtest"

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="No BaseStrategy subclass"):
            _load_strategy_from_code(INVALID_STRATEGY)

    def test_strategy_with_params(self):
        strategy = _load_strategy_from_code(
            VALID_STRATEGY,
            strategy_id="custom",
            params={"lookback": 10},
        )
        assert strategy.strategy_id == "custom"
        assert strategy.params == {"lookback": 10}


# ---------------------------------------------------------------------------
# _VirtualPortfolio
# ---------------------------------------------------------------------------

class TestVirtualPortfolio:
    def test_initial_state(self):
        p = _VirtualPortfolio(10000)
        assert p.cash == 10000
        assert p.get_equity() == 10000
        assert p.positions == {}

    def test_buy_signal(self):
        p = _VirtualPortfolio(10000)
        p.update_price("AAPL", 150.0)
        signal = TradeSignal(
            symbol="AAPL", signal=Signal.BUY, strength=0.5,
            strategy_id="test",
        )
        trade = p.execute_signal(signal, 150.0)
        assert trade is not None
        assert trade.side == "buy"
        assert trade.symbol == "AAPL"
        assert p.cash < 10000
        assert "AAPL" in p.positions

    def test_sell_signal_no_position(self):
        p = _VirtualPortfolio(10000)
        signal = TradeSignal(
            symbol="AAPL", signal=Signal.SELL, strength=1.0,
            strategy_id="test",
        )
        trade = p.execute_signal(signal, 150.0)
        assert trade is None

    def test_buy_then_sell(self):
        p = _VirtualPortfolio(10000)
        p.update_price("AAPL", 100.0)
        buy_signal = TradeSignal(
            symbol="AAPL", signal=Signal.BUY, strength=1.0,
            strategy_id="test",
        )
        p.execute_signal(buy_signal, 100.0)
        assert "AAPL" in p.positions

        # Price goes up
        p.update_price("AAPL", 110.0)
        sell_signal = TradeSignal(
            symbol="AAPL", signal=Signal.SELL, strength=1.0,
            strategy_id="test",
        )
        trade = p.execute_signal(sell_signal, 110.0)
        assert trade is not None
        assert trade.side == "sell"
        # Should have profit
        assert p.get_equity() > 10000

    def test_hold_signal_ignored(self):
        p = _VirtualPortfolio(10000)
        signal = TradeSignal(
            symbol="AAPL", signal=Signal.HOLD, strength=1.0,
            strategy_id="test",
        )
        trade = p.execute_signal(signal, 150.0)
        assert trade is None
        assert p.cash == 10000

    def test_equity_tracks_positions(self):
        p = _VirtualPortfolio(10000)
        p.update_price("AAPL", 100.0)
        buy = TradeSignal(
            symbol="AAPL", signal=Signal.BUY, strength=1.0,
            strategy_id="test",
        )
        p.execute_signal(buy, 100.0)

        # Price doubles
        p.update_price("AAPL", 200.0)
        equity = p.get_equity()
        # Equity should be > 10000 due to position appreciation
        assert equity > 10000


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
        # Peak was 11000, trough was 9000 → drawdown = 2000/11000 ≈ 18.18%
        assert m.max_drawdown_pct == pytest.approx(18.18, abs=0.1)

    def test_trade_win_rate(self):
        trades = [
            BacktestTrade("2024-01-01", "AAPL", "buy", 10, 100, 9000, 10000),
            BacktestTrade("2024-01-02", "AAPL", "sell", 10, 120, 10200, 10200),  # win
            BacktestTrade("2024-01-03", "AAPL", "buy", 10, 110, 9100, 10200),
            BacktestTrade("2024-01-04", "AAPL", "sell", 10, 100, 10100, 10100),  # loss
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
