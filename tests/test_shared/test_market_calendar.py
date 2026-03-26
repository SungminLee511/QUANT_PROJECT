"""Tests for MarketCalendar — market hours, holidays, liquidation timing."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from shared.enums import Exchange
from shared.market_calendar import MarketCalendar

_ET = ZoneInfo("America/New_York")


class TestBinanceCalendar:
    """Binance is 24/7 — always open, never liquidates."""

    def setup_method(self):
        self.cal = MarketCalendar(Exchange.BINANCE)

    def test_always_open(self):
        # Saturday midnight UTC
        dt = datetime(2026, 3, 28, 0, 0, tzinfo=timezone.utc)
        assert self.cal.is_market_open(dt) is True

    def test_never_liquidates(self):
        assert self.cal.should_liquidate(5) is False

    def test_minutes_until_close_is_none(self):
        assert self.cal.minutes_until_close() is None

    def test_next_open_returns_now(self):
        dt = datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc)
        assert self.cal.next_open(dt) == dt


class TestAlpacaCalendar:
    """Alpaca follows NYSE hours: 9:30-16:00 ET, weekdays, minus holidays."""

    def setup_method(self):
        self.cal = MarketCalendar(Exchange.ALPACA)

    def test_open_during_market_hours(self):
        # Wednesday 2026-03-25 at 10:00 AM ET = 14:00 UTC
        dt = datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc)
        assert self.cal.is_market_open(dt) is True

    def test_closed_before_open(self):
        # Wednesday 2026-03-25 at 9:00 AM ET = 13:00 UTC
        dt = datetime(2026, 3, 25, 13, 0, tzinfo=timezone.utc)
        assert self.cal.is_market_open(dt) is False

    def test_closed_after_close(self):
        # Wednesday 2026-03-25 at 4:30 PM ET = 20:30 UTC
        dt = datetime(2026, 3, 25, 20, 30, tzinfo=timezone.utc)
        assert self.cal.is_market_open(dt) is False

    def test_closed_on_saturday(self):
        # Saturday 2026-03-28 at noon ET
        dt = datetime(2026, 3, 28, 16, 0, tzinfo=timezone.utc)
        assert self.cal.is_market_open(dt) is False

    def test_closed_on_sunday(self):
        dt = datetime(2026, 3, 29, 16, 0, tzinfo=timezone.utc)
        assert self.cal.is_market_open(dt) is False

    def test_closed_on_holiday(self):
        # 2026-01-01 is New Year's Day (NYSE holiday)
        dt = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)  # 10 AM ET
        assert self.cal.is_market_open(dt) is False

    def test_next_open_from_weekend(self):
        # Saturday 2026-03-28 → next open is Monday 2026-03-30 9:30 AM ET
        dt = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)
        nxt = self.cal.next_open(dt)
        nxt_et = nxt.astimezone(_ET)
        assert nxt_et.weekday() == 0  # Monday
        assert nxt_et.hour == 9
        assert nxt_et.minute == 30

    def test_next_close_when_open(self):
        # Wednesday 2026-03-25 at 2:00 PM ET = 18:00 UTC
        dt = datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc)
        close = self.cal.next_close(dt)
        close_et = close.astimezone(_ET)
        assert close_et.hour == 16
        assert close_et.minute == 0
        assert close_et.day == 25

    def test_minutes_until_close(self):
        # 3:55 PM ET = 5 min before close. March 25 2026 is EDT so ET = UTC-4
        dt = datetime(2026, 3, 25, 19, 55, tzinfo=timezone.utc)
        remaining = self.cal.minutes_until_close(dt)
        assert remaining is not None
        assert abs(remaining - 5.0) < 0.1

    def test_minutes_until_close_when_closed(self):
        dt = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)  # Saturday
        assert self.cal.minutes_until_close(dt) is None

    def test_should_liquidate_5min(self):
        # 3:56 PM ET → 4 min to close → should liquidate with 5-min threshold
        dt = datetime(2026, 3, 25, 19, 56, tzinfo=timezone.utc)
        assert self.cal.should_liquidate(5.0, dt) is True

    def test_should_not_liquidate_early(self):
        # 2:00 PM ET → 120 min to close → should NOT liquidate
        dt = datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc)
        assert self.cal.should_liquidate(5.0, dt) is False

    def test_should_not_liquidate_when_closed(self):
        dt = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)
        assert self.cal.should_liquidate(5.0, dt) is False
