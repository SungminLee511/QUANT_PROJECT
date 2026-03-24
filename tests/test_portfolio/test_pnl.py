"""Tests for P&L calculator."""

from portfolio.pnl import PnLCalculator


class TestPnLCalculator:
    def test_unrealized_pnl(self):
        pnl = PnLCalculator.unrealized_pnl(
            quantity=10, avg_entry_price=100, current_price=110
        )
        assert pnl == 100.0  # 10 * (110 - 100)

    def test_record_close_profit(self):
        calc = PnLCalculator()
        result = calc.record_close("AAPL", 10, 100, 110, "sell")
        assert result == 100.0
        assert calc.total_realized() == 100.0

    def test_record_close_loss(self):
        calc = PnLCalculator()
        result = calc.record_close("AAPL", 10, 100, 90, "sell")
        assert result == -100.0

    def test_win_rate(self):
        calc = PnLCalculator()
        calc.record_close("AAPL", 10, 100, 110, "sell")  # Win
        calc.record_close("AAPL", 10, 100, 90, "sell")   # Loss
        calc.record_close("AAPL", 10, 100, 120, "sell")  # Win
        assert calc.win_rate() == pytest.approx(2 / 3)

    def test_daily_pnl(self):
        calc = PnLCalculator()
        result = calc.daily_pnl(current_equity=10500, day_start_equity=10000)
        assert result == 500.0

    def test_summary(self):
        calc = PnLCalculator()
        calc.record_close("AAPL", 10, 100, 110, "sell")
        summary = calc.get_summary(current_equity=10100, day_start_equity=10000)
        assert summary["realized_pnl"] == 100.0
        assert summary["daily_pnl"] == 100.0
        assert summary["total_trades"] == 1
        assert summary["win_rate"] == 1.0


# Need pytest for approx
import pytest
