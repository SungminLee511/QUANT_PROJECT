# Final Audit Round 3 — 2026-03-28

> Third comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous rounds: `FINAL_AUDIT.md` (FAUDIT-1–23), `FINAL_AUDIT_R2.md` (R2-1–15).

---

## HIGH

### ~~R3-1: Self-cancellation deadlock in `_run_with_restart` — session status stuck as "active"~~ ✅ FIXED

**Fixed in:** R3-1 commit. Sets status to "error" BEFORE calling stop_session. Catches CancelledError explicitly.

---

### ~~R3-2: Tracker publishes positions without `exchange` field — R2-7 reconciler fix is broken~~ ✅ FIXED

**Fixed in:** R3-2 commit. Added `"exchange": p.get("exchange", "")` to published position dict.

---

### ~~R3-3: XSS via unescaped values in editor.html feedback panel~~ ✅ FIXED

**Fixed in:** R3-3 commit. All interpolated values (c.name, server errors, deploy messages) wrapped in escHtml().

---

### ~~R3-4: XSS via attribute injection in logs.html — `escHtml` missing quote escaping~~ ✅ FIXED

**Fixed in:** R3-4 commit. Added `"` and `'` escaping to escHtml function.

---

## MEDIUM

### ~~R3-5: `_publish_state_loop` uses 0.0 fallback for missing prices — bogus dashboard data~~ ✅ FIXED

**Fixed in:** R3-2 commit (combined fix). Changed fallback from `0.0` to `p["avg_entry_price"]`.

---

### ~~R3-6: `get_data_snapshot` leaks mutable reference to `self.symbols` — strategy can corrupt collector~~ ✅ FIXED

**Fixed in:** R3-6 commit. Changed to `list(self.symbols)` defensive copy.

---

### ~~R3-7: Binance `fetch_history` returns all-NaN `day_change_pct` when `close`/`price` not co-requested~~ ✅ FIXED

**Fixed in:** R3-7 commit. Builds temporary close cache from kline data when close/price aren't in configured fields.

---

### ~~R3-8: Editor deploy endpoint leaks exception details to client~~ ✅ FIXED

**Fixed in:** R3-8 commit. Returns generic "Deploy failed — see server logs".

---

### ~~R3-9: Backtest run endpoint leaks exception details to client~~ ✅ FIXED

**Fixed in:** R3-9 commit. Returns generic "Backtest failed — see server logs".

---

## LOW

### ~~R3-10: `_last_filled` entries for PARTIAL→CANCELLED orders never cleaned up (memory leak)~~ ✅ FIXED

**Fixed in:** R3-10 commit. CANCELLED/FAILED statuses now set sentinel -1.0 for proper cleanup.

---

### ~~R3-11: V1 `RiskManager` converts "hold" signals into SELL orders~~ ✅ FIXED

**Fixed in:** R3-11 commit. Added early return None for hold signals.

---

### ~~R3-12: V1 `check_position_size` blocks sell/close signals for oversized positions~~ ✅ FIXED

**Fixed in:** R3-12 commit. Bypasses additive exposure check for sell signals.

---

### ~~R3-13: `fmtTime` in logs.html — try/catch is dead code, invalid timestamps show garbled output~~ ✅ FIXED

**Fixed in:** R3-13 commit. Replaced dead try/catch with explicit isNaN(d.getTime()) check.

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| HIGH | 4 | 4 |
| MEDIUM | 5 | 5 |
| LOW | 4 | 4 |
| **Total** | **13** | **13** |
