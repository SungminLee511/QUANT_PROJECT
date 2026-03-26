# Performance & Error Handling — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## Performance

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

