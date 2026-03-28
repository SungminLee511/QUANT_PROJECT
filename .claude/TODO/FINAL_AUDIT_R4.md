# Final Audit Round 4 — 2026-03-28

> Fourth comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous rounds: `FINAL_AUDIT.md` (FAUDIT-1–23), `FINAL_AUDIT_R2.md` (R2-1–15), `FINAL_AUDIT_R3.md` (R3-1–13).

---

## HIGH

### ~~R4-1: `stop_session` overwrites "error" status with "stopped" — R3-1 fix defeated~~ ✅ FIXED

**Fixed in:** R4-1 commit. Added `target_status` parameter to `stop_session` (default "stopped"). The exhaustion path passes `target_status="error"`.

---

### ~~R4-2: `schedule_mode="market_hours"` does not gate trading — trades execute 24/7~~ ✅ FIXED

**Fixed in:** R4-2 commit. Added market hours check at top of `_run_strategy_cycle` — returns early when market closed for non-`always_on` modes.

---

### ~~R4-3: Missing adapter silently drops order — no Redis publish, no DB persist~~ ✅ FIXED

**Fixed in:** R4-3 commit. Added `OrderUpdate(status=FAILED)` publish and `_persist_order(order)` matching the place_order exception handler pattern.

---

## MEDIUM

### ~~R4-4: Rebalancer NaN price passes `<= 0` guard — generates garbage orders~~ ✅ FIXED

**Fixed in:** R4-4 commit. Added `or np.isnan(price)` to the guard.

---

### ~~R4-5: `_refresh_portfolio_state` overwrites `peak_equity` — drawdown check bypassed~~ ✅ FIXED

**Fixed in:** R4-5 commit. Saves previous peak before `update()`, restores if the new value is lower.

---

### ~~R4-6: Binance `_close_cache` stored as instance attribute — stale data leak~~ ✅ FIXED

**Fixed in:** R4-6 commit. Changed from `self._close_cache` to local variable `_close_cache`.

---

## LOW

### ~~R4-7: yfinance volume fallback path uses `np.zeros` — failed fetch looks like zero volume~~ ✅ FIXED

**Fixed in:** R4-7 commit. All fields now init to `np.full(n, np.nan)` consistently.

---

### ~~R4-8: yfinance `day_change_pct` uses `is not None` check — semantically wrong for NaN sentinel~~ ✅ FIXED

**Fixed in:** R4-8 commit. Changed to `not np.isnan(prev_close) and not np.isnan(price)`.

---

### ~~R4-9: Negative `max_daily_loss_pct` config causes instant kill switch activation~~ ✅ FIXED

**Fixed in:** R4-9 commit. Changed `if not max_daily` to `if max_daily <= 0`.

---

### ~~R4-10: editor.html `resetAll` catch block — `e.message` not escaped~~ ✅ FIXED

**Fixed in:** R4-10 commit. Added `escHtml()` wrapper.

---

### ~~R4-11: CSS selector injection in logs.html and editor.html — missing `CSS.escape()`~~ ✅ FIXED

**Fixed in:** R4-11 commit. Added `CSS.escape()` for session IDs in both files.

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| HIGH | 3 | 3 |
| MEDIUM | 3 | 3 |
| LOW | 5 | 5 |
| **Total** | **11** | **11** |
