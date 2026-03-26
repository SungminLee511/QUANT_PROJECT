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

---

## SEC-5: API keys exposed in session info API — HIGH (was)

**Fix:** Added `mask_secrets` parameter to `_session_to_dict()` and `get_session_info()`. API responses now show `"****" + last4` for api_key/api_secret. Internal `start_session` uses `mask_secrets=False` to get real keys.
**Date:** 2026-03-26

---

## SEC-6: Session update accepts arbitrary `**kwargs` — MEDIUM (was)

**Fix:** Added whitelist of allowed update fields in `monitoring/sessions.py` PUT endpoint. Only `name`, `symbols`, `api_key`, `api_secret`, `testnet`, `starting_budget`, `strategy_code`, `data_config`, `custom_data_code` are accepted.
**Date:** 2026-03-26

---

## SEC-7: Credential timing attack — LOW (was)

**Fix:** Replaced `==` with `hmac.compare_digest()` for both username and password comparison in `check_credentials()` in `monitoring/auth.py`.
**Date:** 2026-03-26

---

## SEC-3: Plaintext credentials in config — HIGH (was)

**Fix:** Password `==` comparison already fixed by SEC-7 (hmac.compare_digest). Full bcrypt hashing and API key encryption deferred — accepted risk for personal-use system per original TODO assessment.
**Date:** 2026-03-26

---

## SEC-4: Session cookie not `secure` — HIGH (was)

**Fix:** Added `secure=True` to `set_cookie()` in `monitoring/auth.py`. Cookie now only sent over HTTPS (Cloudflare tunnel provides this).
**Date:** 2026-03-26

---

## SEC-1: Strategy `exec()` sandbox is bypassable — CRITICAL (was)

**Fix:** Removed `type` from allowed builtins (prevents metaclass-based sandbox escapes). Documented remaining numpy.os reachability as accepted risk for personal-use system. Full isolation requires subprocess/Wasm sandboxing.
**Date:** 2026-03-26

---

## SEC-2: Custom data `exec()` has no sandbox at all — CRITICAL (was)

**Fix:** Added `_custom_data_builtins()` in `data/collector.py` with restricted builtins — blocks eval/exec/compile, provides whitelist-based `__import__` (allows network libs like requests/urllib but blocks os/subprocess/sys).
**Date:** 2026-03-26

---

## ARCH-3: No CSRF protection — MEDIUM (was)

**Fix:** Added per-session CSRF tokens stored in auth sessions. CSRF middleware in `monitoring/app.py` validates `X-CSRF-Token` header on all POST/PUT/DELETE requests (except login). Token auto-injected into `base.html` meta tag and all `fetch()` calls via JS monkey-patch.
**Date:** 2026-03-26

---

## ARCH-4: Single Redis connection shared across sessions — MEDIUM (was)

**Fix:** Changed `_listen()` in `shared/redis_client.py` to dispatch callbacks as `asyncio.create_task()` instead of awaiting sequentially. Slow subscribers no longer block other sessions' message processing.
**Date:** 2026-03-26

---

## ARCH-5: No rate limiting on API endpoints — MEDIUM (was)

**Fix:** Added lightweight in-memory fixed-window rate limiter (`monitoring/rate_limit.py`). Configured per-route limits for expensive endpoints: backtest run (5/min), session CRUD (30/min), editor deploy (10/min), validation (20/min). Wired as outermost middleware in `monitoring/app.py`. No external dependencies.
**Date:** 2026-03-26

---

## ARCH-6: Backtest blocks main thread pool — MEDIUM (was)

**Fix:** Changed `run_backtest_async()` in `backtest/engine.py` to use a dedicated `ThreadPoolExecutor` (max 2 workers) instead of the default thread pool. Added `asyncio.Semaphore` to cap concurrent backtests. Queued backtests log a waiting message.
**Date:** 2026-03-26

---

## CONC-3: Redis `_listen` task never restarts on error — MEDIUM (was)

**Fix:** Added retry loop with exponential backoff (1s → 60s max) in `_listen()` in `shared/redis_client.py`. On reconnect, re-subscribes to all tracked channels. Only exits on `CancelledError` or normal pubsub close.
**Date:** 2026-03-26

---

## BUG-14: `close` field returns yesterday's close across all sources — HIGH (was)

**Fix:** yfinance batch: changed `close` from `_prev_close(sym)` to `_col("Close", sym)`. yfinance fallback: changed from `prev_close` to `price`. Binance: changed from `prevClosePrice` to `lastPrice`. All three paths now return the current/latest close.
**Date:** 2026-03-26

---

## BUG-15: Validator ALLOWED_IMPORTS doesn't match executor _IMPORT_WHITELIST — HIGH (was)

**Fix:** Added `datetime, decimal, typing, logging, pandas` to executor's `_IMPORT_WHITELIST` in `strategy/executor.py`. Now matches validator's `ALLOWED_IMPORTS`. All are safe (no I/O, no network).
**Date:** 2026-03-26

---

## BUG-16: Partial fill double-counting in PortfolioTracker — HIGH (was)

**Fix:** Added `_last_filled` dict tracking cumulative `filled_qty` per `order_id`. `_on_order_update` now computes `delta_qty = filled_qty - prev_filled` and only applies the incremental fill. Cleaned up on FILLED status. Prevents position quantity drift on partial fills from Binance/Alpaca.
**Date:** 2026-03-26

---

## BUG-17: `_persist_order` queries by `external_id=None` for failed orders — HIGH (was)

**Fix:** Rewrote `_persist_order` in `execution/router.py` to use `order_id` (internal UUID) as primary lookup key instead of `external_id`. Fallback to `external_id` lookup for backward compat. Failed orders now always INSERT with `order_id`, never match other NULL rows.
**Date:** 2026-03-26

---

## BUG-26: `avg_price` never persisted to DB on order updates — MEDIUM (was)

**Fix:** Added `avg_price` column to `Order` model in `db/models.py`. `_persist_order` now writes `avg_price` in both update and insert branches. Fixed alongside BUG-17.
**Date:** 2026-03-26

---

## BUG-20: Binance `cancel_order` missing required `symbol` parameter — HIGH (was)

**Fix:** Added `_order_symbols` dict to `BinanceAdapter`, populated during `place_order`. `cancel_order` now looks up the symbol and passes it to the Binance API. Returns False with error log if symbol is unknown.
**Date:** 2026-03-26

---

## BUG-21: Alpaca adapter blocks event loop with synchronous HTTP calls — HIGH (was)

**Fix:** Wrapped all 5 sync `TradingClient` calls in `await asyncio.to_thread()`: `submit_order`, `cancel_order_by_id`, `get_order_by_id`, `get_account`, `get_all_positions`. Event loop no longer blocks during Alpaca HTTP requests.
**Date:** 2026-03-26

---

## BUG-27: `PnLCalculator.record_close` never called — realized P&L always 0 — MEDIUM (was)

**Fix:** Instantiated `PnLCalculator` in `PortfolioTracker.__init__`. `_on_order_update` now calls `_pnl.record_close()` on SELL fills with entry/exit prices and delta quantity. Published portfolio state now includes `realized_pnl`, `total_closed_trades`, and `win_rate` from P&L summary.
**Date:** 2026-03-26

---

## BUG-18: Pipeline leak on `start_session` failure — HIGH (was)

**Fix:** In `start_session`'s except block, cancel all orphaned asyncio tasks on the pipeline and remove the pipeline from `self._pipelines` dict before setting error status. Prevents resource leaks from partially-created tasks (collector, router, portfolio tracker, sim price listener).
**Date:** 2026-03-26

---

## BUG-19: `update_session` silently ignores strategy/data config fields — HIGH (was)

**Fix:** Added handling for `strategy_code`, `data_config`, and `custom_data_code` in `update_session`. Dict/list values are JSON-serialized before storage; string values passed through as-is.
**Date:** 2026-03-26

---

## BUG-22: Stale PubSub object reused after Redis connection failure — HIGH (was)

**Fix:** In `_listen()` retry loop, close the old PubSub object and create a fresh one via `self._redis.pubsub()` before re-subscribing. Prevents stale connection from causing infinite retry loops where no messages flow.
**Date:** 2026-03-26

---

## BUG-23: `float("inf")` profit factor breaks JSON serialization — MEDIUM (was)

**Fix:** Replaced `float("inf")` with `9999.99` for profit factor when there are winning trades but zero losses. Prevents `json.dumps` from raising `ValueError` on backtest results.
**Date:** 2026-03-26

---

## BUG-24: Backtest `day_change_pct` field never computed — MEDIUM (was)

**Fix:** Added `prev_close` array to track previous bar's close per symbol. Computes `day_change_pct = (close - prev_close) / prev_close * 100` as a special case alongside `vwap`. Updates `prev_close` after each bar.
**Date:** 2026-03-26

---

## BUG-25: Backtest fills missing data with 0.0 instead of NaN — MEDIUM (was)

**Fix:** Changed fallback from `0.0` to keeping `np.nan` when no prior buffer value exists. Also added NaN check on buffer lookback to avoid propagating stale NaN. Strategies now see NaN instead of fake 0.0 prices for truly missing data.
**Date:** 2026-03-26

---

## BUG-29: Custom data validator missing `open` in FORBIDDEN_NAMES — MEDIUM (was)

**Fix:** Added `"open"` to FORBIDDEN_NAMES in `custom_validator.py`, matching the strategy validator. Prevents custom data functions from accessing the filesystem.
**Date:** 2026-03-26

---

## BUG-30: `check_position_size` approves on zero/negative equity — MEDIUM (was)

**Fix:** Changed `check_position_size` to return `(False, "Cannot evaluate...")` when `total_equity <= 0` or `current_price <= 0`, instead of blindly approving. Updated test to match new rejection behavior.
**Date:** 2026-03-26

---

## BUG-28: Default strategy file `read_text()` unguarded — MEDIUM (was)

**Fix:** Added `_read_default_strategy()` helper in `editor.py` with try/except and a minimal fallback strategy. Applied to all 3 call sites in editor.py and 1 in backtest.py. Endpoints now return a safe fallback instead of 500 errors when the default file is missing.
**Date:** 2026-03-26

---

## BUG-31: Non-numeric port env var silently passes through as string — MEDIUM (was)

**Fix:** In `shared/config.py`, changed bare `except: pass` to log a warning and `continue` (skip the invalid value). In `db/session.py`, added `int()` cast with fallback to default port 5432 for non-numeric values.
**Date:** 2026-03-26
