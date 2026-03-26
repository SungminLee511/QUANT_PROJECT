# Code Quality & Architecture — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25).

---

## Code Quality

---

## Architecture

### ARCH-7: Module-level globals prevent multi-worker — LOW

**Files:** `monitoring/logs.py`, `monitoring/auth.py`

In-memory dicts/sets break with multiple uvicorn workers. Fine for single-worker.

**Fix:** Document as scaling constraint. Use Redis-backed stores if scaling needed.
