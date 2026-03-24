"""Tests for risk limit checks and kill switch."""

import pytest

from shared.enums import Signal
from shared.schemas import TradeSignal
from risk.limits import (
    check_daily_loss,
    check_drawdown,
    check_max_positions,
    check_position_size,
)


@pytest.fixture
def risk_config():
    return {
        "risk": {
            "max_position_pct": 0.10,
            "max_drawdown_pct": 0.05,
            "max_daily_loss_pct": 0.03,
            "max_open_positions": 3,
            "kill_switch_key": "risk:kill_switch",
        }
    }


@pytest.fixture
def buy_signal():
    return TradeSignal(
        symbol="BTCUSDT",
        signal=Signal.BUY,
        strength=0.8,
        strategy_id="test",
    )


class TestPositionSize:
    def test_approves_within_limits(self, buy_signal, risk_config):
        state = {"total_equity": 10000, "prices": {"BTCUSDT": 50000}}
        approved, reason = check_position_size(buy_signal, state, risk_config)
        assert approved is True

    def test_no_equity_allows_through(self, buy_signal, risk_config):
        state = {"total_equity": 0, "prices": {}}
        approved, _ = check_position_size(buy_signal, state, risk_config)
        assert approved is True


class TestMaxPositions:
    def test_rejects_when_at_max(self, buy_signal, risk_config):
        state = {
            "open_positions": 3,
            "position_symbols": {"ETHUSDT", "AAPL", "SPY"},
        }
        approved, reason = check_max_positions(buy_signal, state, risk_config)
        assert approved is False
        assert "Max open positions" in reason

    def test_allows_existing_symbol(self, buy_signal, risk_config):
        state = {
            "open_positions": 3,
            "position_symbols": {"BTCUSDT", "AAPL", "SPY"},
        }
        approved, _ = check_max_positions(buy_signal, state, risk_config)
        assert approved is True

    def test_allows_below_max(self, buy_signal, risk_config):
        state = {"open_positions": 1, "position_symbols": {"AAPL"}}
        approved, _ = check_max_positions(buy_signal, state, risk_config)
        assert approved is True


class TestDrawdown:
    def test_rejects_on_excessive_drawdown(self, risk_config):
        state = {"peak_equity": 10000, "total_equity": 9400}  # 6% drawdown
        approved, reason = check_drawdown(state, risk_config)
        assert approved is False
        assert "Drawdown" in reason

    def test_allows_within_limits(self, risk_config):
        state = {"peak_equity": 10000, "total_equity": 9800}  # 2% drawdown
        approved, _ = check_drawdown(state, risk_config)
        assert approved is True


class TestDailyLoss:
    def test_rejects_excessive_daily_loss(self, risk_config):
        state = {"day_start_equity": 10000, "daily_pnl": -400}  # 4% loss
        approved, reason = check_daily_loss(state, risk_config)
        assert approved is False
        assert "Daily loss" in reason

    def test_allows_within_limits(self, risk_config):
        state = {"day_start_equity": 10000, "daily_pnl": -100}  # 1% loss
        approved, _ = check_daily_loss(state, risk_config)
        assert approved is True

    def test_allows_positive_pnl(self, risk_config):
        state = {"day_start_equity": 10000, "daily_pnl": 500}
        approved, _ = check_daily_loss(state, risk_config)
        assert approved is True
