# Performance & Error Handling — Open Issues

> Full audit: 2026-03-27.

---

## Error Handling

### ~~ERR-1: No API retry logic or rate-limit handling across all data sources~~ ✅ FIXED

**Fixed in:** commit 47279c9. Added warning on Redis state refresh failure.

---

### ~~ERR-2: JSON deserialization without error handling in session manager~~ ✅ FIXED

**Fixed in:** commits 3a440c6, 6df5e32, 1e0dbcf. Added try-except with fallback defaults.

---

### ~~ERR-3: Strategy code load failure not caught in `_start_pipeline()`~~ ✅ FIXED

**Fixed in:** commits 35dbcde, 6df5e32, 1e0dbcf. Strategy load wrapped in try-catch.

---

### ~~ERR-4: `_set_session_status()` swallows exceptions~~ ✅ FIXED

**Fixed in:** commit 7065fe1. Added defensive checks for status updates.

---

### ~~ERR-5: Missing error handling in backtest JSON response parsing~~ ✅ FIXED

**Fixed in:** commit 5b0dbf6. Added try-catch and error type validation.

---

### ~~ERR-6: Router Redis callback has no timeout protection~~ ✅ FIXED

**Fixed in:** commit (ERR-6). Wrapped `_on_order_request` with `asyncio.wait_for(timeout=30)`. Extracted `_process_order_request` inner method. Timeout logs error without crashing subscriber.

---

### ~~ERR-7: Custom data code not validated before execution~~ ✅ FIXED

**Fixed in:** collector.py `_custom_data_builtins()` restricts builtins (removes eval/exec/compile/__import__) and provides whitelist-based import. Custom code runs in sandboxed namespace with error catching.

---

### ~~ERR-8: Unsupported resolution silently defaults to 1d in yfinance~~ ✅ FIXED

**Fixed in:** commit 1e1d24d. Rejects unsupported resolutions (same as BUG-87).

---

## Performance

### ~~PERF-1: Session auto-restart is sequential on server boot~~ ✅ FIXED

**Fixed in:** commit 77d1586. Batch yfinance fetch with yf.download().

---

### ~~PERF-2: Binance orderbook fetch ThreadPool has no `as_completed()` timeout~~ ✅ FIXED

**Fixed in:** commit c62c9d2. Parallelized Binance order book requests with ThreadPoolExecutor timeout.

---
