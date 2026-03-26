# Bugs — Open Issues

> Full audit: 2026-03-26. Covers all directories (data, strategy, execution, portfolio, session, monitoring, shared, db, backtest).

---

## ~~BUG-14: `close` field returns yesterday's close across all sources — FIXED~~

---

## ~~BUG-15: Validator ALLOWED_IMPORTS doesn't match executor _IMPORT_WHITELIST — FIXED~~

---

## ~~BUG-16: Partial fill double-counting in PortfolioTracker — FIXED~~

---

## ~~BUG-17: `_persist_order` queries by `external_id=None` for failed orders — FIXED~~

---

## BUG-18: Pipeline leak on `start_session` failure — HIGH

**File:** `session/manager.py:226-246`

Pipeline is added to `self._pipelines` at line 227 *before* `_start_pipeline` runs. If `_start_pipeline` raises (caught at line 242), status is set to "error" but the pipeline is never removed from the dict. Any partially-created asyncio tasks in the pipeline are orphaned (never cancelled).

**Impact:** Resource leak. Orphaned tasks may keep running (e.g., sim price listener, data collector).

**Fix:** In the except block, add `self._pipelines.pop(session_id, None)` and cancel any tasks on the pipeline.

---

## BUG-19: `update_session` silently ignores `strategy_code`, `data_config`, `custom_data_code` — HIGH

**File:** `session/manager.py:174-203`

The method only handles `name, symbols, api_key, api_secret, testnet, starting_budget`. The sessions REST API whitelist (sessions.py:66) includes `strategy_code, data_config, custom_data_code`, but `update_session` discards them. PUT returns `{"updated": True}` but nothing was saved.

**Impact:** REST API for updating strategy code is silently broken. (Editor deploy works via direct DB write, so the UI path is unaffected.)

**Fix:** Add handling for the three fields in `update_session`.

---

## ~~BUG-20: Binance `cancel_order` missing required `symbol` parameter — FIXED~~

---

## ~~BUG-21: Alpaca adapter blocks event loop with synchronous HTTP calls — FIXED~~

---

## BUG-22: Stale PubSub object reused after Redis connection failure — HIGH

**File:** `shared/redis_client.py:117-128`

The CONC-3 retry loop re-subscribes using the same `self._pubsub` object after a connection error. If the underlying connection is dead, the PubSub object is stale and `.subscribe()` may also fail, causing an infinite retry loop that never recovers.

**Impact:** After a Redis connection blip, pub/sub may never recover. The system looks running but no messages flow (ticks, signals, orders all dead).

**Fix:** Create a fresh PubSub object before re-subscribing: `self._pubsub = self._redis.pubsub()`.

---

## BUG-23: `float("inf")` profit factor breaks JSON serialization — MEDIUM

**File:** `backtest/engine.py:358`

When wins > 0 but losses == 0, `profit_factor = float("inf")`. Python's `json.dumps(float("inf"))` raises `ValueError`.

**Impact:** Backtest API returns 500 error when a backtest has only winning trades.

**Fix:** Use a large finite number (e.g., `9999.99`) or `None`.

---

## BUG-24: Backtest `day_change_pct` field never computed — MEDIUM

**File:** `backtest/engine.py:442-445`

`col_to_field` has no mapping for `day_change_pct`, and there's no special-case computation (unlike `vwap`). If enabled in data config, the buffer stays at zero/NaN forever.

**Impact:** Strategies depending on `day_change_pct` get all zeros in backtests, producing incorrect signals.

**Fix:** Compute from consecutive close values per symbol (requires tracking previous close per bar).

---

## BUG-25: Backtest fills missing data with 0.0 instead of NaN — MEDIUM

**File:** `backtest/engine.py:506-507`

When a symbol has no data for a given date and no prior buffer value, `0.0` is used. A price of 0.0 silently corrupts strategy calculations.

**Impact:** Strategies see 0.0 prices for missing symbols, producing nonsensical weights.

**Fix:** Use `np.nan` and ensure `_build_data_snapshot` handles NaN (e.g., skip symbols or require all non-NaN).

---

## ~~BUG-26: `avg_price` never persisted to DB on order updates — FIXED (with BUG-17)~~

---

## BUG-27: `PnLCalculator.record_close` never called — realized P&L always 0 — MEDIUM

**File:** `portfolio/tracker.py` (entire file), `portfolio/pnl.py`

`PortfolioTracker._on_order_update` handles SELL fills by updating positions and cash, but never calls `PnLCalculator.record_close()`. The PnLCalculator exists but is completely disconnected from actual trades.

**Impact:** All realized P&L metrics (total, win rate, summary) are always zero. Dashboard P&L reporting is meaningless.

**Fix:** Call `self._pnl.record_close(symbol, qty, entry_price, fill_price, "sell")` when processing SELL fills.

---

## BUG-28: Default strategy file `read_text()` unguarded — crashes if file missing — MEDIUM

**Files:** `monitoring/backtest.py:149`, `monitoring/editor.py:65,74,214`

Multiple endpoints call `DEFAULT_STRATEGY.read_text()` without existence check. If `strategy/examples/momentum_v2.py` is deleted/renamed, these return 500 errors.

**Impact:** Editor page, backtest page, and reset endpoint all crash with FileNotFoundError.

**Fix:** Add `if DEFAULT_STRATEGY.exists()` guard, or try/except with a fallback.

---

## BUG-29: Custom data validator missing `open` in FORBIDDEN_NAMES — MEDIUM

**File:** `strategy/custom_validator.py:25-30`

`validator_v2.py` blocks `open` but `custom_validator.py` does not. Custom data functions can reference `open()` to read/write files on the server.

**Impact:** Custom data code can access the filesystem (read/write arbitrary files).

**Fix:** Add `"open"` to FORBIDDEN_NAMES in `custom_validator.py`.

---

## BUG-30: `check_position_size` approves on zero/negative equity — MEDIUM

**File:** `risk/limits.py:27-28`

When `total_equity <= 0` or `current_price <= 0`, returns `(True, "")` — allows the trade. This bypasses position size limits when portfolio state is unavailable or corrupted.

**Impact:** Position size limits ineffective when state is missing. (V1 legacy — only affects live sessions using V1 risk checks.)

**Fix:** Return `(False, "Cannot evaluate: equity or price unavailable")` instead.

---

## BUG-31: Non-numeric port env var silently passes through as string — MEDIUM

**Files:** `shared/config.py:56-58`, `db/session.py:19-21`

If `QT_DATABASE_PORT` is set to a non-numeric string, `int()` cast fails silently (bare `except: pass`). The string flows through to the DB URL, causing an opaque connection error.

**Fix:** Log a warning or raise on parse failure instead of silent pass.
