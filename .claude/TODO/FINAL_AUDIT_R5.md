# Final Audit Round 5 — 2026-03-28

> Fifth comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous rounds: `FINAL_AUDIT.md` (FAUDIT-1–23), `FINAL_AUDIT_R2.md` (R2-1–15), `FINAL_AUDIT_R3.md` (R3-1–13), `FINAL_AUDIT_R4.md` (R4-1–11).

**All 6 items FIXED** — 2026-03-28

---

## ~~HIGH~~ — FIXED

### ~~R5-1: Alpaca adapter `str(order.side) == "buy"` always evaluates to False~~ ✅ FIXED (4c046d9)
Compare against `OrderSide.BUY` enum directly; also fix status lookup to use `.value`.

---

## ~~MEDIUM~~ — FIXED

### ~~R5-2: Strategy re-opens positions after pre-close liquidation~~ ✅ FIXED (16f7775)
Added `pipeline.liquidated` flag; set after liquidation, checked in `_run_strategy_cycle`, reset on new day.

### ~~R5-3: Binance volumes/num_trades initialized with zeros instead of NaN~~ ✅ FIXED (31b4437)
Changed `np.zeros` to `np.full(NaN)`.

### ~~R5-4: Binance orderbook `as_completed` timeout drops all results~~ ✅ FIXED (429abe4)
Wrapped for-loop in `try/except TimeoutError` to keep already-harvested data.

### ~~R5-5: `run_all.py` tasks not awaited after cancellation~~ ✅ FIXED (b472a61)
Added `await asyncio.gather(*tasks, return_exceptions=True)`.

---

## ~~LOW~~ — FIXED

### ~~R5-6: yfinance volume fallback 0.0 instead of NaN~~ ✅ FIXED (b636456)
Changed fallback from `0.0` to `np.nan`.

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| HIGH | 1 | 1 |
| MEDIUM | 4 | 4 |
| LOW | 1 | 1 |
| **Total** | **6** | **6** |
