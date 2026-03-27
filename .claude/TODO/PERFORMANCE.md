# Performance & Error Handling — Open Issues

> Full audit: 2026-03-27.

---

## Error Handling

### ERR-1: No API retry logic or rate-limit handling across all data sources

**Files:** `data/sources/yfinance_source.py`, `alpaca_source.py`, `binance_source.py`
**Severity:** MEDIUM

All HTTP calls have fixed timeouts, no retry, no exponential backoff, no 429 handling. Single rate-limit hit → complete data failure for that scrape cycle.

**Fix:** Add retry with exponential backoff; differentiate timeout, 429, and permanent errors.

---

### ERR-2: JSON deserialization without error handling in session manager

**File:** `session/manager.py` — Lines 212, 257
**Severity:** MEDIUM

`json.loads(ts.config_json or "{}")` — corrupted DB data crashes `start_session()` with `JSONDecodeError`.

**Fix:** Wrap in try-except, fall back to defaults.

---

### ERR-3: Strategy code load failure not caught in `_start_pipeline()`

**File:** `session/manager.py` — Lines 368–370
**Severity:** MEDIUM

`executor.load_strategy(strategy_code)` has no try-catch. Syntax errors in user code bubble up and crash the pipeline start without a user-friendly error.

**Fix:** Catch and log with clear "Strategy load failed: <reason>" message.

---

### ERR-4: `_set_session_status()` swallows exceptions

**File:** `session/manager.py` — Lines 833–846
**Severity:** MEDIUM

DB status updates fail silently. If DB is down, status never updates and caller doesn't know. Breaks observability.

**Fix:** Return bool success; callers should check.

---

### ERR-5: Missing error handling in backtest JSON response parsing

**File:** `monitoring/templates/backtest.html` — Lines 295, 301–304
**Severity:** MEDIUM

`await resp.json()` with no try-catch. Non-JSON responses crash the function. `data.errors.join()` assumes array — string errors break.

**Fix:** Wrap in try-catch, validate `errors` type.

---

### ~~ERR-6: Router Redis callback has no timeout protection~~ ✅ FIXED

**Fixed in:** commit (ERR-6). Wrapped `_on_order_request` with `asyncio.wait_for(timeout=30)`. Extracted `_process_order_request` inner method. Timeout logs error without crashing subscriber.

---

### ERR-7: Custom data code not validated before execution

**File:** `session/manager.py` — Lines 458–459
**Severity:** MEDIUM

`collector.load_custom_data_functions(custom_data_code)` — no validation. Unlike strategy executor which has import whitelisting, custom data functions have no equivalent safeguard.

---

### ERR-8: Unsupported resolution silently defaults to 1d in yfinance

**File:** `data/sources/yfinance_source.py` — Lines 217–228
**Severity:** MEDIUM

`res_map.get(resolution, "1d")` — typo or unsupported value silently changes data granularity. Strategy expects 1-min bars, gets daily.

**Fix:** Raise error on unsupported resolution instead of defaulting.

---

## Performance

### PERF-1: Session auto-restart is sequential on server boot

**File:** `monitoring/app.py` — Lines 104–115
**Severity:** LOW

Sessions restarted one-by-one. If one hangs (e.g., broker API timeout), all subsequent sessions wait.

**Fix:** Use `asyncio.gather()` with per-session timeout.

---

### PERF-2: Binance orderbook fetch ThreadPool has no `as_completed()` timeout

**File:** `data/sources/binance_source.py` — Lines 125–135
**Severity:** LOW

If one worker hangs, `as_completed()` waits forever. No global timeout on the pool.

**Fix:** Add `timeout=15` to `as_completed()`.

---
