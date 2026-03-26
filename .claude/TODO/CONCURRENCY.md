# Concurrency — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## CONC-2: `_sse_queues` concurrent modification — LOW (ACCEPTED)

**File:** `monitoring/logs.py`

Safe in single-threaded asyncio, breaks with multiple uvicorn workers.

**Status:** Accepted constraint for personal-use single-worker system.

---

## CONC-4: `_open_orders` dict modified during iteration — LOW (ACCEPTED)

**File:** `execution/router.py` (~line 181)

Safe due to `list()` copy + single-threaded asyncio. Fragile if architecture changes.

**Status:** Accepted — already protected by `list()` copy.
