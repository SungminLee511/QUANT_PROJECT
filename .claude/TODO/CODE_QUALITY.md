# Code Quality & Architecture — Open Issues

> Full audit: 2026-03-27.

---

## Validation

### ~~VAL-1: No symbol list validation in `start_session()`~~ ✅ FIXED

**Fixed in:** commit 5f427af, 1e0dbcf. Validates and deduplicates symbol list.

---

### ~~VAL-2: `OrderRequest.price` not validated for LIMIT orders~~ ✅ FIXED

**Fixed in:** commit 91bc29f. Added model_validator for LIMIT price (same as BUG-83).

---

### ~~VAL-3: Pydantic models allow negative prices/volumes/quantities~~ ✅ FIXED

**Fixed in:** commit efd8b90 (BUG-94). Added Field(gt=0) for prices, Field(ge=0) for volumes.

---

### ~~VAL-4: `LogEntry.event_type` is unvalidated string~~ ✅ FIXED

**Fixed in:** commit 7cea080 (BUG-90). Changed to Literal type with all 12 valid values.

---

## Schema & Data Integrity

### ~~SCHEMA-1: Trade model missing unique constraint on `(session_id, order_id)`~~ ✅ FIXED

**Fixed in:** commit 2666e5d (BUG-84). Added unique constraint.

---

### ~~SCHEMA-2: `EquitySnapshot` allows duplicate `(session_id, timestamp)`~~ ✅ FIXED

**Fixed in:** commit 2d72c78 (BUG-91). Added unique constraint + Alembic migration 003.

---

### ~~SCHEMA-3: `Order.avg_price` nullable but typed as non-optional float~~ ✅ FIXED

**Fixed in:** commit ac36890 (BUG-64). Changed to `Mapped[float | None]`.

---

## Observability

### ~~OBS-1: `_publish_log()` swallows errors at debug level~~ ✅ FIXED

**Fixed in:** commit 29e5999 (BUG-100). Changed to WARNING level for publish failures.

---

### ~~OBS-2: DEBUG-level logs for fallback paths across data sources~~ ✅ FIXED

**Fixed in:** OBS-2 commit. Changed batch download fallback, fast_info None, and Binance VWAP zero-volume fallback logs from DEBUG to WARNING.

---

## Architecture

### ARCH-7: Module-level globals prevent multi-worker — ACCEPTED

**Files:** `monitoring/logs.py`, `monitoring/auth.py`

In-memory dicts/sets break with multiple uvicorn workers. Fine for single-worker.

**Status:** Accepted constraint for personal-use single-worker system.

---

### ~~ARCH-8: Multiple sources of truth for portfolio state~~ ✅ FIXED

**Fixed in:** ARCH-8 commit. Added `_reconcile_positions()` to PortfolioTracker — runs every ~5 minutes, compares in-memory positions with DB, logs WARNING on symbol mismatches or quantity drift > 1%. Warning-only (no auto-correct) to avoid masking bugs.

---

### ~~ARCH-9: Exchange detection relies on symbol suffix matching~~ ✅ FIXED

**Fixed in:** ARCH-9 commit. Added optional `exchange` field to `TradeSignal` schema. `_signal_to_order()` uses exchange hint when present, falls back to `_detect_exchange()` (suffix matching) with warning. Suffix matching isolated to single static method.
