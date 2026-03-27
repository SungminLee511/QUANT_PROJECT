# Concurrency — Open Issues

> Full audit: 2026-03-27.

---

## HIGH

### CONC-5: Unguarded access to `sim_adapter._positions` dict

**File:** `session/manager.py` — Lines 559, 644
**Severity:** HIGH

`pipeline.sim_adapter._positions` read directly without acquiring the `_lock`. Concurrent modifications during iteration can cause `RuntimeError: dictionary changed size during iteration`.

**Fix:** Add `get_positions_snapshot()` method to SimAdapter that acquires lock and returns a copy.

---

### CONC-6: Task cancellation suppresses all exceptions

**File:** `session/manager.py` — Lines 292–298, 320–328
**Severity:** HIGH

`except (asyncio.CancelledError, Exception): pass` swallows non-cancellation errors that may indicate resource leaks (DB connections, file handles). No logging of suppressed errors.

**Fix:** Use `asyncio.gather(*tasks, return_exceptions=True)`, then log non-CancelledError exceptions.

---

## MEDIUM

### CONC-7: Kill switch check-then-act race

**File:** `risk/kill_switch.py` — Lines 16–19
**Severity:** MEDIUM

`is_active()` + subsequent order placement is not atomic. Another service can activate kill switch between check and action. Signals can slip through.

**Fix:** Use Redis transactions (WATCH/MULTI/EXEC) or check inside order emission critical section.

---

### CONC-8: SSE reconnection timer scoped incorrectly

**File:** `monitoring/templates/logs.html` — Lines 158–188
**Severity:** MEDIUM

`disconnectTimer` is function-scoped in `connectSSE()`. Re-calling creates new closures referencing new variable; old closures reference old variable → zombie timers, incorrect UI state.

**Fix:** Move `disconnectTimer` to global/module scope. Clear on reconnect.

---

### CONC-9: DOM manipulation race in `appendEntry()`

**File:** `monitoring/templates/logs.html` — Lines 101–114
**Severity:** MEDIUM

`viewport.children[1]` assumes empty message is always at `[0]`. Rapid SSE arrivals can cause the index assumption to break if empty message was removed. `removeChild(children[1])` loop assumes stable indexing during removal.

**Fix:** Use `querySelectorAll('.log-entry')` for precise targeting instead of children index.

---

### CONC-10: Schedule loop 30s sleep delays shutdown detection

**File:** `session/manager.py` — Lines 510–539
**Severity:** MEDIUM

`_schedule_loop()` sleeps 30s. Takes up to 30s to notice `pipeline.running = False` or `CancelledError`. Also, non-cancellation exceptions in the loop aren't handled cleanly.

**Fix:** Split sleep into shorter intervals or use `asyncio.wait_for()`.

---

### ~~CONC-11: Position update and DB persist not atomic~~ ✅ FIXED

**Fixed in:** commit (CONC-11). Added `_position_lock` (asyncio.Lock) guarding all position + cash mutations. Extracted `_apply_fill()` method called under lock. Persist is already awaited.

---

## ACCEPTED (LOW)

### CONC-2: `_sse_queues` concurrent modification — ACCEPTED

**File:** `monitoring/logs.py` — Safe in single-threaded asyncio.

### CONC-4: `_open_orders` dict modified during iteration — ACCEPTED

**File:** `execution/router.py` — Protected by `list()` copy.
