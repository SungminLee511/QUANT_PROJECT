# Performance & Error Handling — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## Performance

### PERF-1: N+1 API calls in yfinance source — HIGH

**File:** `data/sources/yfinance_source.py`

Serial `yf.Ticker(symbol)` calls per symbol. 10 symbols × 1–3s each = 10–30s per scrape.

**Fix:** Batch with `yf.download()` for price/OHLCV data. Keep individual calls only for fundamentals.

### PERF-2: N+1 order book requests in Binance source — MEDIUM

**File:** `data/sources/binance_source.py`

Symbol-by-symbol serial HTTP requests for order book data.

**Fix:** Use `asyncio.gather()` for concurrent requests, or batch via combined stream.

### PERF-3: Eager-loading all DB relationships — MEDIUM

**File:** `db/models.py`

`lazy="selectin"` on TradingSession relationships loads ALL trades/orders/positions/snapshots on every query. Kills performance over time.

**Fix:** Change to `lazy="dynamic"` or `lazy="select"` and explicitly eager-load where needed.

### PERF-4: Auth session store never cleaned — LOW

**File:** `monitoring/auth.py`

`_sessions` dict grows unbounded. Expired tokens only removed on access.

**Fix:** Add periodic cleanup task or use TTL cache (e.g. `cachetools.TTLCache`).

### PERF-5: Log buffers grow per-session forever — LOW

**File:** `monitoring/logs.py`

`_buffers` creates new deque per session_id, never removes deleted sessions.

**Fix:** Clean up buffers when sessions are deleted.

---

## Error Handling

### ERR-3: `get_session_info` DB errors not caught — MEDIUM

**File:** `session/manager.py`

No try/except around database call. Error propagates up and can crash session start.

**Fix:** Wrap in try/except, return None on failure, log error.

### ERR-4: No validation of yfinance `fast_info` return — LOW

**File:** `data/sources/yfinance_source.py`

`fast_info` can return None or raise on rate limiting. Behavior depends on yfinance version.

**Fix:** Add defensive checks and try/except around fast_info access.
