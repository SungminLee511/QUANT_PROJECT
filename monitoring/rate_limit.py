"""Lightweight in-memory rate limiter for FastAPI — no external dependencies.

Uses a fixed-window counter per (client_ip, route_key). Good enough for a
single-worker, personal-use system. Does NOT survive restarts (by design).

Usage:
    from monitoring.rate_limit import RateLimiter, add_rate_limit_middleware

    limiter = RateLimiter()
    add_rate_limit_middleware(app, limiter)

    # Then in endpoint:
    if err := limiter.check("backtest", request, limit=5, window=60):
        return err  # JSONResponse 429
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limit configuration per route prefix
# ---------------------------------------------------------------------------

@dataclass
class RateRule:
    """Fixed-window rate limit rule."""
    limit: int       # Max requests per window
    window: int      # Window size in seconds

    def __post_init__(self):
        if self.limit < 1 or self.window < 1:
            raise ValueError("limit and window must be >= 1")


# Default rules — keyed by route prefix
DEFAULT_RULES: dict[str, RateRule] = {
    # SEC-13: Brute-force protection on login
    "/login": RateRule(limit=10, window=60),
    # Expensive: yfinance download + CPU-bound strategy replay
    "/backtest/api/run": RateRule(limit=5, window=60),
    # Session lifecycle — moderate
    "/api/sessions": RateRule(limit=30, window=60),
    # Editor deploy — moderate
    "/editor/api/deploy": RateRule(limit=10, window=60),
    # Validation — lighter but still CPU
    "/editor/api/validate": RateRule(limit=20, window=60),
}


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

@dataclass
class _WindowCounter:
    """Tracks request count within a fixed window."""
    count: int = 0
    window_start: float = 0.0


class RateLimiter:
    """In-memory fixed-window rate limiter.

    Thread-safe within single-threaded asyncio (no locks needed).
    Counters are periodically pruned to prevent unbounded memory growth.
    """

    def __init__(self, rules: dict[str, RateRule] | None = None):
        self.rules = rules or DEFAULT_RULES
        # key: (client_key, route_key) -> _WindowCounter
        self._counters: dict[tuple[str, str], _WindowCounter] = {}
        self._last_cleanup: float = time.monotonic()
        self._cleanup_interval: float = 300.0  # prune every 5 min

    def _get_client_key(self, request: Request) -> str:
        """Extract client identifier from request."""
        # Use X-Forwarded-For if behind Cloudflare tunnel, else client host
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _match_rule(self, path: str) -> tuple[str, RateRule] | None:
        """Find the most specific matching rule for a path."""
        best_match: tuple[str, RateRule] | None = None
        best_len = 0
        for prefix, rule in self.rules.items():
            if path.startswith(prefix) and len(prefix) > best_len:
                best_match = (prefix, rule)
                best_len = len(prefix)
        return best_match

    def _maybe_cleanup(self) -> None:
        """Prune expired window counters to prevent memory growth."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        expired = []
        for key, counter in self._counters.items():
            # Find the rule for this key's route
            _, route_key = key
            rule = self.rules.get(route_key)
            window = rule.window if rule else 60
            if now - counter.window_start > window * 2:
                expired.append(key)
        for key in expired:
            del self._counters[key]

    def check(self, request: Request) -> JSONResponse | None:
        """Check if a request is rate-limited.

        Returns None if allowed, or a 429 JSONResponse if rate-limited.
        """
        match = self._match_rule(request.url.path)
        if match is None:
            return None

        route_key, rule = match
        client_key = self._get_client_key(request)
        now = time.monotonic()
        counter_key = (client_key, route_key)

        counter = self._counters.get(counter_key)
        if counter is None or now - counter.window_start >= rule.window:
            # New window
            self._counters[counter_key] = _WindowCounter(count=1, window_start=now)
            self._maybe_cleanup()
            return None

        counter.count += 1
        if counter.count > rule.limit:
            remaining = rule.window - (now - counter.window_start)
            logger.warning(
                "Rate limited: client=%s route=%s (%d/%d in %ds window, retry in %.0fs)",
                client_key, route_key, counter.count, rule.limit,
                rule.window, remaining,
            )
            return JSONResponse(
                {"error": f"Rate limit exceeded. Try again in {int(remaining)}s."},
                status_code=429,
                headers={"Retry-After": str(int(remaining))},
            )

        return None
