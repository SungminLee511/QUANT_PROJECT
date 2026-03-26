"""Tests for check_short_loss — short position kill switch."""

import pytest

from risk.limits import check_short_loss


class TestCheckShortLoss:
    """Short position loss limit checks."""

    def test_no_shorts_ok(self):
        """All long positions → OK."""
        ok, reason = check_short_loss(
            positions={"AAPL": 10.0, "MSFT": 5.0},
            current_prices={"AAPL": 150.0, "MSFT": 300.0},
            entry_prices={},
            short_loss_limit_pct=1.0,
        )
        assert ok is True
        assert reason == ""

    def test_short_profitable_ok(self):
        """Short at $100, now $80 → profitable → OK."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0},
            current_prices={"AAPL": 80.0},
            entry_prices={"AAPL": 100.0},
            short_loss_limit_pct=1.0,
        )
        assert ok is True

    def test_short_loss_under_limit_ok(self):
        """Short at $100, now $140 → 40% loss < 100% limit → OK."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0},
            current_prices={"AAPL": 140.0},
            entry_prices={"AAPL": 100.0},
            short_loss_limit_pct=1.0,
        )
        assert ok is True

    def test_short_loss_at_limit_kill(self):
        """Short at $100, now $200 → 100% loss = limit → KILL."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0},
            current_prices={"AAPL": 200.0},
            entry_prices={"AAPL": 100.0},
            short_loss_limit_pct=1.0,
        )
        assert ok is False
        assert "AAPL" in reason
        assert "100%" in reason

    def test_short_loss_over_limit_kill(self):
        """Short at $100, now $250 → 150% loss > 100% limit → KILL."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0},
            current_prices={"AAPL": 250.0},
            entry_prices={"AAPL": 100.0},
            short_loss_limit_pct=1.0,
        )
        assert ok is False

    def test_custom_limit_50pct(self):
        """Custom 50% limit: short at $100, now $150 → 50% loss = limit → KILL."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0},
            current_prices={"AAPL": 150.0},
            entry_prices={"AAPL": 100.0},
            short_loss_limit_pct=0.5,
        )
        assert ok is False
        assert "50%" in reason

    def test_custom_limit_50pct_under(self):
        """Custom 50% limit: short at $100, now $140 → 40% loss < 50% → OK."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0},
            current_prices={"AAPL": 140.0},
            entry_prices={"AAPL": 100.0},
            short_loss_limit_pct=0.5,
        )
        assert ok is True

    def test_multiple_shorts_one_bad(self):
        """Two shorts: one profitable, one at limit → KILL (catches the bad one)."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0, "MSFT": -5.0},
            current_prices={"AAPL": 80.0, "MSFT": 200.0},
            entry_prices={"AAPL": 100.0, "MSFT": 100.0},
            short_loss_limit_pct=1.0,
        )
        assert ok is False
        assert "MSFT" in reason

    def test_empty_positions_ok(self):
        """No positions at all → OK."""
        ok, reason = check_short_loss(
            positions={},
            current_prices={},
            entry_prices={},
        )
        assert ok is True

    def test_missing_entry_price_skipped(self):
        """Short position with no entry price record → skipped (not killed)."""
        ok, reason = check_short_loss(
            positions={"AAPL": -10.0},
            current_prices={"AAPL": 200.0},
            entry_prices={},  # no entry price recorded
            short_loss_limit_pct=1.0,
        )
        assert ok is True
