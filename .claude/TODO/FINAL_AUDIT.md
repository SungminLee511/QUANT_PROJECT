# Final Audit — 2026-03-27

> Comprehensive codebase audit after completing all Round 5 fixes. Only **real, verified bugs** — no style nits or theoretical improvements.

---

## CRITICAL

### ~~FAUDIT-1: Duplicate FILLED messages re-apply entire fill (double-counted positions)~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Changed from `pop()` to sentinel value `-1.0` on FILLED. Duplicate messages hit early return. Sentinels pruned in snapshot loop.

---

## HIGH

### ~~FAUDIT-2: `_build_session_config` always maps API keys to "alpaca" — Binance sessions broken~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Added `session_type` parameter to `_build_session_config()`. Uses `session_type.exchange == Exchange.BINANCE` for correct key placement.

---

### ~~FAUDIT-3: `OrderStatus.PARTIALLY_FILLED` doesn't exist — every live order immediate-fill check silently fails~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Changed `OrderStatus.PARTIALLY_FILLED` to `OrderStatus.PARTIAL`.

---

### ~~FAUDIT-4: `check_position_size` is a no-op — risk limit never fires~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Now checks total exposure (existing position value + proposed order) against the limit, not just the proposed order alone.

---

### ~~FAUDIT-5: Backtest cash goes negative when buying with commission~~ ✅ FIXED

**Fixed in:** FAUDIT commit. `max_buy_value = self.cash / (1 + commission_rate)` reserves room for the fee.

---

### ~~FAUDIT-6: XSS in backtest trade table — symbol/side not escaped~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Added `escHtml()` function. Applied to `t.timestamp`, `t.symbol`, `t.side` in innerHTML.

---

### ~~FAUDIT-7: XSS in onclick handlers — session name breaks out of JS string~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Replaced inline `onclick` with `data-sid`/`data-sname` attributes + `this.dataset` access in base.html and overview.html.

---

## MEDIUM

### ~~FAUDIT-8: Rebalancer creates `OrderRequest` with `quantity=0.0` — unhandled Pydantic crash~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Added `if rounded_qty <= 0: continue` after `round_quantity()`.

---

### ~~FAUDIT-9: `_run_strategy_cycle` has no `pipeline.running` guard — phantom orders after stop~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Added `if not pipeline.running: return` guard at top of `_run_strategy_cycle`.

---

### ~~FAUDIT-10: yfinance batch fetch uses `np.zeros` — invalid symbols get price=0.0 instead of NaN~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Changed `np.zeros(n)` to `np.full(n, np.nan)`. `_col()` and `_prev_close()` return `np.nan` on failure.

---

### ~~FAUDIT-11: Binance orderbook zeros masquerade as real data on fetch failure~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Changed `np.zeros(n)` to `np.full(n, np.nan)` for bids/asks arrays.

---

### ~~FAUDIT-12: Dashboard LIMIT applied before WHERE — wrong result count~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Reordered to apply `.where()` before `.order_by().limit()` in both orders and equity-history queries.

---

### ~~FAUDIT-13: Failed orders never publish `OrderUpdate` — downstream never notified~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Added `OrderUpdate(status=FAILED)` publish before returning. Also removes failed orders from `_open_orders` (fixes FAUDIT-19).

---

### ~~FAUDIT-14: `liquidated_today` flag incorrectly reset by transient market-closed detection~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Tracks `last_liquidation_date`. Only resets `liquidated_today` when `date.today()` differs from last liquidation date.

---

### ~~FAUDIT-15: Binance `_order_symbols` lost on adapter restart — can't cancel open orders~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Added `get_open_orders()` call in `connect()` to rebuild the order-symbol map on startup.

---

### ~~FAUDIT-16: Race in `_write_env` — non-atomic settings file write~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Write-to-temp-then-rename pattern for atomic file writes.

---

## LOW

### ~~FAUDIT-17: yfinance `day_change_pct` returns 0% instead of NaN when previous close unavailable~~ ✅ FIXED

**Fixed in:** FAUDIT commit (alongside FAUDIT-10). `_prev_close()` returns `np.nan`. `day_change_pct` stays NaN when prev close unavailable.

---

### FAUDIT-18: Backtest trade pairing uses FIFO single-entry price, not average entry — ACCEPTED

**Status:** Accepted limitation. FIFO pairing is a standard approach. Weighted-average pairing would be a feature enhancement, not a bug fix. Affects reporting metrics only — not live trading.

---

### ~~FAUDIT-19: Failed sim-mode orders leak in `_open_orders` — never cleaned up~~ ✅ FIXED

**Fixed in:** FAUDIT-13 commit. Failed orders no longer added to `_open_orders`.

---

### ~~FAUDIT-20: Reconciler filters out short positions with `quantity > 0` check~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Changed to `abs(p.get("quantity", 0)) > 0.0001`.

---

### ~~FAUDIT-21: Rate limiter `/login` rule applies to GET too — page refreshes trigger lockout~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Added `GET` method bypass for `/login` route in `check()`.

---

### ~~FAUDIT-22: `backtest.py` float conversion crash on invalid input~~ ✅ FIXED

**Fixed in:** FAUDIT commit. Wrapped numeric conversions in try/except with user-friendly error response.

---

### FAUDIT-23: Stale `total_equity` used for all orders in a single backtest rebalance — ACCEPTED

**Status:** Accepted limitation. Recomputing equity mid-rebalance would change the algorithm semantics (order-dependent results). The drift is small per-cycle. Affects backtest accuracy only.

---

## Summary

| Severity | Count | Fixed | Accepted |
|----------|-------|-------|----------|
| CRITICAL | 1 | 1 | 0 |
| HIGH | 6 | 6 | 0 |
| MEDIUM | 8 | 8 | 0 |
| LOW | 7 | 5 | 2 |
| **Total** | **22** | **20** | **2** |
