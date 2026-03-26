# Code Quality & Architecture — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## Code Quality

---

## Architecture

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
