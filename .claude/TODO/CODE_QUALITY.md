# Code Quality & Architecture — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## Code Quality

---

## Architecture

### ARCH-7: Module-level globals prevent multi-worker — LOW (ACCEPTED)

**Files:** `monitoring/logs.py`, `monitoring/auth.py`

In-memory dicts/sets break with multiple uvicorn workers. Fine for single-worker.

**Status:** Accepted constraint for personal-use single-worker system. Would need Redis-backed stores for multi-worker scaling.
