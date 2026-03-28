# Final Audit Round 2 — 2026-03-28

> Second comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous FAUDIT-1 through FAUDIT-23 are in `FINAL_AUDIT.md`.

---

## CRITICAL

### ~~R2-1: `scripts/run_all.py` calls `create_app()` with wrong signature — immediate crash~~ ✅ FIXED

**Fixed in:** R2-1 commit. Removed duplicate DB/Redis/SessionManager init; call `create_app(config)` only.

---

## HIGH

### ~~R2-2: `or` on numpy arrays crashes `fetch_history` for multi-symbol sessions~~ ✅ FIXED

**Fixed in:** R2-2 commit. Changed to `x if x is not None else y` in both yfinance_source.py and binance_source.py.

---

### ~~R2-3: CSP header blocks all CDN scripts — Backtest and Editor pages non-functional~~ ✅ FIXED

**Fixed in:** R2-3 commit. Added `cdn.jsdelivr.net` and `cdnjs.cloudflare.com` to CSP `script-src` and `style-src`.

---

### ~~R2-4: `_run_with_restart` doesn't stop pipeline on component exhaustion — zombie sessions~~ ✅ FIXED

**Fixed in:** R2-4 commit. Now calls `stop_session()` to cancel all tasks before setting status to "error".

---

## MEDIUM

### ~~R2-5: Binance `_fetch_book` returns `0.0` for empty order book, contradicting NaN initialization~~ ✅ FIXED

**Fixed in:** R2-5 commit. Changed fallback from `0.0` to `np.nan`.

---

### ~~R2-6: Sim adapter caps short cover by available cash — shorts become unclosable~~ ✅ FIXED

**Fixed in:** R2-6 commit. Removed cash cap for short covers; cash may go temporarily negative (margin-like).

---

### ~~R2-7: Reconciler checks all local symbols against each exchange — false positives in multi-exchange~~ ✅ FIXED

**Fixed in:** R2-7 commit. Partitions local positions by exchange field before comparing.

---

### ~~R2-8: `date.today()` uses server UTC time, not ET market time in schedule loop~~ ✅ FIXED

**Fixed in:** R2-8 commit. Uses `datetime.now(ZoneInfo("US/Eastern")).date()` for correct trading-day boundaries.

---

### ~~R2-9: Kill switch restore logs "staying halted" but starts pipeline anyway~~ ✅ FIXED

**Fixed in:** R2-9 commit. Sets DB status to "halted" and includes kill switch state in startup log.

---

### ~~R2-10: `showFeedback` in editor.html double-escapes HTML — feedback shows raw tags~~ ✅ FIXED

**Fixed in:** R2-10 commit. Removed `escHtml()` call — lines contain intentional HTML from code, not user input.

---

### ~~R2-11: `_open_orders` memory leak in sim mode~~ ✅ FIXED

**Fixed in:** R2-11 commit. Sim orders (instantly terminal) are no longer added to `_open_orders`.

---

### ~~R2-12: Dashboard API endpoints leak exception details to client~~ ✅ FIXED

**Fixed in:** R2-12 commit. Returns generic "Internal server error" instead of `str(e)`.

---

### ~~R2-13: Binance `avgPrice` string `"0.00000000"` is truthy — prevents fallback to `price` field~~ ✅ FIXED

**Fixed in:** R2-13 commit. Convert to float first, then apply `or` fallback.

---

## LOW

### ~~R2-14: `or` pattern on numeric dict lookups drops zero values in yfinance fast_info~~ ✅ FIXED

**Fixed in:** R2-14 commit. Replaced `or` with explicit `is not None` checks for all fast_info lookups.

---

### ~~R2-15: `.env` read doesn't strip quotes — API keys may include literal quote characters~~ ✅ FIXED

**Fixed in:** R2-15 commit. Strips surrounding single/double quotes from values.

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| CRITICAL | 1 | 1 |
| HIGH | 3 | 3 |
| MEDIUM | 9 | 9 |
| LOW | 2 | 2 |
| **Total** | **15** | **15** |
