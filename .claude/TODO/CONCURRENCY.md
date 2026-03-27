# Concurrency — Open Issues

> Full audit: 2026-03-27.

---

## HIGH

### ~~CONC-5: Unguarded access to `sim_adapter._positions` dict~~ ✅ FIXED

**Fixed in:** commit 1af2d72. Lock-guarded position access in SimAdapter.

---

### ~~CONC-6: Task cancellation suppresses all exceptions~~ ✅ FIXED

**Fixed in:** commit 9e251b1. Logs non-cancellation errors during task teardown at WARNING level.

---

## MEDIUM

### ~~CONC-7: Kill switch check-then-act race~~ ✅ FIXED

**Fixed in:** CONC-7 commit. Added kill switch re-check immediately before `redis.publish(order)` in V1 RiskManager. Minimizes race window to synchronous code between check and emit. Full WATCH/MULTI/EXEC overkill for single-worker asyncio.

---

### ~~CONC-8: SSE reconnection timer scoped incorrectly~~ ✅ FIXED

**Fixed in:** CONC-8 commit. Moved `disconnectTimer` to module scope. `connectSSE()` now clears any pending timer from previous connection before creating new EventSource.

---

### ~~CONC-9: DOM manipulation race in `appendEntry()`~~ ✅ FIXED

**Fixed in:** CONC-9 commit. Replaced `children[1]` index-based trimming with `querySelectorAll('.log-entry')` for stable element selection. Excess entries removed by direct `.remove()` call.

---

### ~~CONC-10: Schedule loop 30s sleep delays shutdown detection~~ ✅ FIXED

**Fixed in:** commit 1e0dbcf. Split sleep and improved shutdown detection.

---

### ~~CONC-11: Position update and DB persist not atomic~~ ✅ FIXED

**Fixed in:** commit (CONC-11). Added `_position_lock` (asyncio.Lock) guarding all position + cash mutations. Extracted `_apply_fill()` method called under lock. Persist is already awaited.

---

## ACCEPTED (LOW)

### CONC-2: `_sse_queues` concurrent modification — ACCEPTED

**File:** `monitoring/logs.py` — Safe in single-threaded asyncio.

### CONC-4: `_open_orders` dict modified during iteration — ACCEPTED

**File:** `execution/router.py` — Protected by `list()` copy.
