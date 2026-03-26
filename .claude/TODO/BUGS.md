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

## ~~BUG-18: Pipeline leak on `start_session` failure — FIXED~~

---

## ~~BUG-19: `update_session` silently ignores `strategy_code`, `data_config`, `custom_data_code` — FIXED~~

---

## ~~BUG-20: Binance `cancel_order` missing required `symbol` parameter — FIXED~~

---

## ~~BUG-21: Alpaca adapter blocks event loop with synchronous HTTP calls — FIXED~~

---

## ~~BUG-22: Stale PubSub object reused after Redis connection failure — FIXED~~

---

## ~~BUG-23: `float("inf")` profit factor breaks JSON serialization — FIXED~~

---

## ~~BUG-24: Backtest `day_change_pct` field never computed — FIXED~~

---

## ~~BUG-25: Backtest fills missing data with 0.0 instead of NaN — FIXED~~

---

## ~~BUG-26: `avg_price` never persisted to DB on order updates — FIXED (with BUG-17)~~

---

## ~~BUG-27: `PnLCalculator.record_close` never called — realized P&L always 0 — FIXED~~

---

## BUG-28: Default strategy file `read_text()` unguarded — crashes if file missing — MEDIUM

**Files:** `monitoring/backtest.py:149`, `monitoring/editor.py:65,74,214`

Multiple endpoints call `DEFAULT_STRATEGY.read_text()` without existence check. If `strategy/examples/momentum_v2.py` is deleted/renamed, these return 500 errors.

**Impact:** Editor page, backtest page, and reset endpoint all crash with FileNotFoundError.

**Fix:** Add `if DEFAULT_STRATEGY.exists()` guard, or try/except with a fallback.

---

## ~~BUG-29: Custom data validator missing `open` in FORBIDDEN_NAMES — FIXED~~

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
