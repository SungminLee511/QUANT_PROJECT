# Completed Items

> Items moved here after fix is committed and pushed.

---

## BUG-2: OrderRequest schema lacks `metadata` field — CRITICAL (was)

**Fix:** Added `metadata: dict = Field(default_factory=dict)` to `OrderRequest` in `shared/schemas.py`.
**Date:** 2026-03-26

---

## BUG-3: `check_position_size` always approves — HIGH (was)

**Fix:** Changed comparison from tautological `estimated_value > total_equity` to `signal.strength * total_equity > total_equity * max_pct`. Added `test_rejects_oversized` test.
**Date:** 2026-03-26
