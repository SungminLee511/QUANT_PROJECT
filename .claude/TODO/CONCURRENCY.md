# Concurrency — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## CONC-1: SimulationAdapter state not thread-safe — HIGH

**File:** `execution/sim_adapter.py`

`_cash`, `_positions`, `_last_prices` modified from both `_on_price_update` (Redis pubsub) and `place_order` (order path). Context switch between check and mutation could cause negative cash.

**Fix:** Add `asyncio.Lock` to guard the critical section in `place_order`.

---

## CONC-2: `_sse_queues` concurrent modification — MEDIUM

**File:** `monitoring/logs.py`

Safe in single-threaded asyncio, breaks with multiple uvicorn workers.

**Fix:** Fine for current single-worker setup. Document as scaling constraint.

---

## CONC-3: Redis `_listen` task never restarts on error — MEDIUM

**File:** `shared/redis_client.py` (~lines 80–104)

If `_listen()` exits on exception, all subscriptions silently die. No reconnection logic.

**Fix:** Wrap in retry loop with exponential backoff and re-subscribe.

---

## CONC-4: `_open_orders` dict modified during iteration — LOW

**File:** `execution/router.py` (~line 181)

Safe due to `list()` copy + single-threaded asyncio. Fragile if architecture changes.

**Fix:** Document or use a proper concurrent data structure.
