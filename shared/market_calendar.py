"""Market calendar — market hours lookup per exchange.

Pure utility, no async, no state. Hardcoded schedules for now;
can be extended with exchange_calendars library later.
"""

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from shared.enums import Exchange

logger = logging.getLogger(__name__)

# US Eastern timezone (handles EST/EDT automatically)
_ET = ZoneInfo("America/New_York")

# NYSE regular trading hours
_MARKET_OPEN = time(9, 30)   # 9:30 AM ET
_MARKET_CLOSE = time(16, 0)  # 4:00 PM ET

# NYSE holidays for 2025-2030 (major ones — covers current usage)
# Format: (month, day). Some move year-to-year; these are approximate.
# For exact dates, can later fetch from Alpaca API: GET /v2/calendar
_NYSE_HOLIDAYS: dict[int, set[tuple[int, int]]] = {
    2025: {
        (1, 1), (1, 20), (2, 17), (4, 18), (5, 26),
        (6, 19), (7, 4), (9, 1), (11, 27), (12, 25),
    },
    2026: {
        (1, 1), (1, 19), (2, 16), (4, 3), (5, 25),
        (6, 19), (7, 3), (9, 7), (11, 26), (12, 25),
    },
    2027: {
        (1, 1), (1, 18), (2, 15), (3, 26), (5, 31),
        (6, 18), (7, 5), (9, 6), (11, 25), (12, 24),
    },
    2028: {
        (1, 17), (2, 21), (4, 14), (5, 29),
        (6, 19), (7, 4), (9, 4), (11, 23), (12, 25),
    },
    2029: {
        (1, 1), (1, 15), (2, 19), (3, 30), (5, 28),
        (6, 19), (7, 4), (9, 3), (11, 22), (12, 25),
    },
    2030: {
        (1, 1), (1, 21), (2, 18), (4, 19), (5, 27),
        (6, 19), (7, 4), (9, 2), (11, 28), (12, 25),
    },
}
_WARNED_YEARS: set[int] = set()


class MarketCalendar:
    """Market hours lookup per exchange.

    Usage:
        cal = MarketCalendar(Exchange.ALPACA)
        if cal.is_market_open():
            ...
        minutes_left = cal.minutes_until_close()
    """

    def __init__(self, exchange: Exchange):
        self._exchange = exchange
        self._is_crypto = (exchange == Exchange.BINANCE)
        if not self._is_crypto and exchange != Exchange.ALPACA:
            logger.warning(
                "MarketCalendar: unknown exchange '%s' — defaulting to US equity hours",
                exchange,
            )

    @property
    def exchange(self) -> Exchange:
        return self._exchange

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """Check if market is open at the given UTC time (default: now)."""
        if self._is_crypto:
            return True  # 24/7

        dt_utc = dt or datetime.now(timezone.utc)
        dt_et = dt_utc.astimezone(_ET)

        # Weekend check
        if dt_et.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Holiday check
        year = dt_et.year
        if year not in _NYSE_HOLIDAYS and year not in _WARNED_YEARS:
            logger.warning(
                "No NYSE holiday data for year %d — holiday checks will be skipped. "
                "Update _NYSE_HOLIDAYS in shared/market_calendar.py.",
                year,
            )
            _WARNED_YEARS.add(year)
        year_holidays = _NYSE_HOLIDAYS.get(year, set())
        if (dt_et.month, dt_et.day) in year_holidays:
            return False

        # Hours check
        current_time = dt_et.time()
        return _MARKET_OPEN <= current_time < _MARKET_CLOSE

    def next_open(self, dt: datetime | None = None) -> datetime:
        """Return the next market open time (UTC).

        If market is currently open, returns the *next* open (tomorrow or later).
        """
        if self._is_crypto:
            # Always open — return now
            return dt or datetime.now(timezone.utc)

        dt_utc = dt or datetime.now(timezone.utc)
        dt_et = dt_utc.astimezone(_ET)

        # Start searching from tomorrow if market is currently open
        candidate = dt_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if candidate <= dt_et:
            candidate += timedelta(days=1)

        # Skip weekends and holidays (max 10 days lookahead)
        for _ in range(10):
            if candidate.weekday() < 5:  # weekday
                year_holidays = _NYSE_HOLIDAYS.get(candidate.year, set())
                if (candidate.month, candidate.day) not in year_holidays:
                    return candidate.astimezone(timezone.utc)
            candidate += timedelta(days=1)

        # Fallback: return the candidate even if we couldn't verify holidays
        return candidate.astimezone(timezone.utc)

    def next_close(self, dt: datetime | None = None) -> datetime:
        """Return the next market close time (UTC).

        If market is currently open, returns today's close.
        If closed, returns the close time of the next trading day.
        """
        if self._is_crypto:
            # Never closes — return far future
            return datetime(2099, 12, 31, tzinfo=timezone.utc)

        dt_utc = dt or datetime.now(timezone.utc)
        dt_et = dt_utc.astimezone(_ET)

        today_close = dt_et.replace(hour=16, minute=0, second=0, microsecond=0)

        # If market is open now, today's close is the answer
        if self.is_market_open(dt_utc):
            return today_close.astimezone(timezone.utc)

        # Otherwise find the next trading day's close
        candidate = today_close
        if candidate <= dt_et:
            candidate += timedelta(days=1)

        for _ in range(10):
            if candidate.weekday() < 5:
                year_holidays = _NYSE_HOLIDAYS.get(candidate.year, set())
                if (candidate.month, candidate.day) not in year_holidays:
                    return candidate.astimezone(timezone.utc)
            candidate += timedelta(days=1)

        return candidate.astimezone(timezone.utc)

    def minutes_until_close(self, dt: datetime | None = None) -> float | None:
        """Minutes until market close. None if market is closed.

        For crypto, returns None (never closes).
        """
        if self._is_crypto:
            return None  # meaningless for 24/7

        dt_utc = dt or datetime.now(timezone.utc)

        if not self.is_market_open(dt_utc):
            return None

        close_dt = self.next_close(dt_utc)
        delta = (close_dt - dt_utc).total_seconds() / 60
        return max(delta, 0.0)

    def should_liquidate(self, minutes_before_close: float = 5.0, dt: datetime | None = None) -> bool:
        """True if market is open and closes within `minutes_before_close` minutes."""
        if self._is_crypto:
            return False

        remaining = self.minutes_until_close(dt)
        if remaining is None:
            return False
        return remaining <= minutes_before_close
