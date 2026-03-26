# Code Quality & Architecture — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## Code Quality

### CQ-4: Incorrect type hint — LOW

**File:** `data/collector.py` (~line 48)

`alpaca_credentials: dict = None` should be `dict | None = None`.

### CQ-5: `RiskManager` class largely dead code in V2 — LOW

**File:** `risk/manager.py`

V2 pipeline calls `check_portfolio_risk()` directly, never instantiates `RiskManager`. The class and `_signal_to_order()` are unused V1 legacy.

**Fix:** Remove unused class or mark as deprecated.

---

## Architecture

### ARCH-3: No CSRF protection — MEDIUM

**Files:** `monitoring/sessions.py`, `monitoring/dashboard.py`

All POST endpoints use cookie auth with no CSRF tokens. Malicious page could forge requests.

**Fix:** Add CSRF token middleware (FastAPI has community packages for this).

### ARCH-4: Single Redis connection shared across sessions — MEDIUM

**File:** `session/manager.py`

Slow subscriber in one session delays all others (sequential `_listen()` loop).

**Fix:** Per-session Redis connections, or async message dispatch.

### ARCH-5: No rate limiting on API endpoints — MEDIUM

Backtest endpoint spawns blocking yfinance downloads. Concurrent abuse could exhaust thread pool.

**Fix:** Add rate limiting middleware (e.g. `slowapi`).

### ARCH-6: Backtest blocks main thread pool — MEDIUM

**File:** `backtest/engine.py`

`run_in_executor(None, ...)` uses default thread pool. Multiple concurrent backtests can starve live sessions.

**Fix:** Use a dedicated thread pool for backtests with max concurrency.

### ARCH-7: Module-level globals prevent multi-worker — LOW

**Files:** `monitoring/logs.py`, `monitoring/auth.py`

In-memory dicts/sets break with multiple uvicorn workers. Fine for single-worker.

**Fix:** Document as scaling constraint. Use Redis-backed stores if scaling needed.
