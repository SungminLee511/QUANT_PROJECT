# Completed Items

> Items moved here after fix is committed and pushed.

---

## BUG-2: OrderRequest schema lacks `metadata` field — CRITICAL (was)

**Fix:** Added `metadata: dict = Field(default_factory=dict)` to `OrderRequest` in `shared/schemas.py`.
**Date:** 2026-03-26

---

## BUG-3: `check_position_size` always approves — HIGH (was)

**Fix:** Changed comparison from tautological `estimated_value > total_equity` to `signal.strength * total_equity > total_equity * max_pct`. Added `test_rejects_oversized` test.
**Date:** 2026-03-26

---

## ARCH-1: DB password not URL-encoded — HIGH (was)

**Fix:** Added `urllib.parse.quote_plus()` for user and password in `db/session.py` `_build_url()`.
**Date:** 2026-03-26

---

## BUG-4: Router logs "FILLED" for non-sim PLACED orders — MEDIUM (was)

**Fix:** Split log path — checks `order.status == FILLED` before logging fill details. Live PLACED orders now log "PLACED" with correct info.
**Date:** 2026-03-26

---

## BUG-5: Backtest `close` field has no mapping — LOW (was)

**Fix:** Added `"close": "Close"` to `col_to_field` in `backtest/engine.py`.
**Date:** 2026-03-26

---

## BUG-6: Reconciler broken in multi-session mode — MEDIUM (was)

**Fix:** Added `session_id` param to `Reconciler.__init__()`, uses `_session_channel()` for Redis key. Also documented that reconciler is not wired into V2 SessionPipeline (legacy only).
**Date:** 2026-03-26

---

## ERR-1: Silent `pass` on Redis state refresh failure — HIGH (was)

**Fix:** Replaced `except: pass` with `logger.warning()` including exc_info in `risk/manager.py` `_refresh_portfolio_state()`.
**Date:** 2026-03-26

---

## CONC-1: SimulationAdapter state not thread-safe — HIGH (was)

**Fix:** Added `asyncio.Lock` guarding `_cash`, `_positions`, `_last_prices` in both `_on_price_update` and `place_order` in `execution/sim_adapter.py`.
**Date:** 2026-03-26

---

## CQ-1: Duplicate `ValidationResult` class — MEDIUM (was)

**Fix:** Extracted `ValidationResult` dataclass to `shared/schemas.py`. Both `strategy/validator_v2.py` and `strategy/custom_validator.py` now import from there.
**Date:** 2026-03-26

---

## CQ-3: Dead code — `data/custom_data.py` — LOW (was)

**Fix:** Verified file is never imported anywhere. V2 uses `collector.load_custom_data_functions()` for dynamic custom data. Deleted the unused V1 file.
**Date:** 2026-03-26

---

## CQ-4: Incorrect type hint — LOW (was)

**Fix:** Changed `alpaca_credentials: dict = None` to `dict | None = None` in `data/collector.py`.
**Date:** 2026-03-26

---

## CQ-5: `RiskManager` class largely dead code in V2 — LOW (was)

**Fix:** Marked class as deprecated with docstring. Still used by V1 `scripts/run_execution.py` so not deleted — just clearly documented as legacy.
**Date:** 2026-03-26

---

## ERR-2: Silent exception swallowing in `_publish_log` — MEDIUM (was)

**Fix:** Replaced `except Exception: pass` with `logger.debug(..., exc_info=True)` in `execution/router.py`, `risk/manager.py`, `portfolio/tracker.py`, and `session/manager.py` (collector stop + task cancellation).
**Date:** 2026-03-26

---

## ERR-3: `get_session_info` DB errors not caught — MEDIUM (was)

**Fix:** Wrapped DB query in `get_session_info()` with try/except, returns None on failure, logs exception. Prevents unhandled DB errors from crashing session start.
**Date:** 2026-03-26

---

## ERR-4: No validation of yfinance `fast_info` return — LOW (was)

**Fix:** Added try/except around `ticker.fast_info` access in both `fetch()` and `fetch_history()`. Falls back to empty dict if `fast_info` returns None or raises (e.g. rate limiting).
**Date:** 2026-03-26

---

## PERF-1: N+1 API calls in yfinance source — HIGH (was)

**Fix:** Refactored `fetch()` to use `yf.download()` for batch price/OHLCV data (1 HTTP request for all symbols). Falls back to per-symbol `fast_info` on failure. Fundamentals still use individual `ticker.info` (no batch API).
**Date:** 2026-03-26

---

## PERF-2: N+1 order book requests in Binance source — MEDIUM (was)

**Fix:** Replaced serial per-symbol order book requests with `ThreadPoolExecutor` (max 10 workers) for concurrent fetching in `data/sources/binance_source.py`.
**Date:** 2026-03-26

---

## PERF-3: Eager-loading all DB relationships — MEDIUM (was)

**Fix:** Changed `lazy="selectin"` to `lazy="select"` on all 4 TradingSession relationships (trades, positions, orders, equity_snapshots) in `db/models.py`. No code accesses these relationships on session objects.
**Date:** 2026-03-26

---

## PERF-4: Auth session store never cleaned — LOW (was)

**Fix:** Added `cleanup_expired_sessions()` and amortized `_maybe_cleanup()` (every 5 min) called from `get_current_user()` in `monitoring/auth.py`. Expired tokens now pruned automatically.
**Date:** 2026-03-26

---

## PERF-5: Log buffers grow per-session forever — LOW (was)

**Fix:** Added `cleanup_session_logs()` in `monitoring/logs.py` and called it from `session/manager.py` `delete_session()`. Removes log buffer and subscription tracking when a session is deleted.
**Date:** 2026-03-26
