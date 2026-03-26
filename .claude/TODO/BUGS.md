# Bugs — Open Issues

> Last verified against code: 2026-03-26. All items confirmed still present.

---

## BUG-6: Reconciler completely broken in multi-session mode — MEDIUM

**File:** `portfolio/reconciler.py` (lines 13–51)

Two problems:
1. `__init__` has no `session_id` parameter
2. Reads hardcoded `"portfolio:state"` key instead of `session_channel(session_id, "portfolio:state")`

In multi-session mode, reconciler reads wrong/empty state and can never match any session's actual portfolio.

**Fix:** Add `session_id` param to `__init__`, use `session_channel()` for all Redis keys. Or remove reconciler entirely — it's not wired into the V2 `SessionPipeline` and may be dead code.
