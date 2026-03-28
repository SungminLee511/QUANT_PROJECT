# Final Audit Round 4 — 2026-03-28

> Fourth comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous rounds: `FINAL_AUDIT.md` (FAUDIT-1–23), `FINAL_AUDIT_R2.md` (R2-1–15), `FINAL_AUDIT_R3.md` (R3-1–13).

---

## HIGH

### R4-1: `stop_session` overwrites "error" status with "stopped" — R3-1 fix defeated

**File:** `session/manager.py`, lines 372, 899-901
**Severity:** HIGH

```python
# Line 899 (_run_with_restart):
await self._set_session_status(session_id, "error")
try:
    await self.stop_session(session_id)

# Line 372 (stop_session):
await self._set_session_status(session_id, "stopped")
```

The R3-1 fix sets status to "error" BEFORE calling `stop_session()`. But `stop_session()` unconditionally overwrites the status to "stopped" (line 372). The "error" status set on line 899 is immediately clobbered.

**Incorrect behavior:** Sessions that crashed from exhausted restart attempts display as "stopped" instead of "error". Users cannot distinguish a clean stop from a crash.

**Fix:** `stop_session` should accept an optional `target_status` parameter (defaulting to `"stopped"`), and the call from `_run_with_restart` passes `"error"`.

---

### R4-2: `schedule_mode="market_hours"` does not gate trading — trades execute 24/7

**File:** `session/manager.py`, lines 540-598, 654-669
**Severity:** HIGH

```python
# _schedule_loop body only acts on "market_hours_liquidate":
if calendar.is_market_open():
    if pipeline.schedule_mode == "market_hours_liquidate" and ...:
        await self._liquidate_session(...)

# _run_strategy_cycle has no market hours check:
async def _run_strategy_cycle(self, pipeline, data_snapshot, starting_budget):
    if not pipeline.running:
        return
    # ... executes trades unconditionally
```

The `_schedule_loop` starts for any `schedule_mode != "always_on"`, which includes `"market_hours"`. But neither the schedule loop nor `_run_strategy_cycle` prevents strategy execution when the market is closed. The schedule loop only handles the liquidation path for `"market_hours_liquidate"`.

**Incorrect behavior:** Sessions with `schedule_mode="market_hours"` execute trades during nights, weekends, and holidays — identical to `"always_on"`. For live Alpaca sessions, orders are submitted when the market is closed.

**Fix:** Add `if pipeline.calendar and not pipeline.calendar.is_market_open(): return` at the top of `_run_strategy_cycle` when `pipeline.schedule_mode` is not `"always_on"`.

---

### R4-3: Missing adapter silently drops order — no Redis publish, no DB persist

**File:** `execution/router.py`, lines 104-108
**Severity:** HIGH

```python
adapter = self._get_adapter(request.exchange)
if adapter is None:
    logger.error("No adapter for exchange %s (session=%s)", request.exchange.value, self._session_id)
    order.transition(OrderStatus.FAILED)
    return  # ← silent return
```

When no adapter exists for the requested exchange, the order is marked FAILED internally but: (1) no `OrderUpdate` is published to Redis, so the portfolio tracker, risk manager, and dashboard never learn the order failed; (2) no DB record is created. Compare with the `place_order` exception handler (lines 141-160) which correctly publishes a FAILED update and persists to DB.

**Incorrect behavior:** The order is silently lost. The strategy believes it submitted an order, the tracker never records it, and there is no DB audit trail. In a weight-based system, the rebalancer will keep trying to submit the same order every cycle.

**Fix:** Add `OrderUpdate(status=FAILED)` publish and `_persist_order(order)` before the return, matching the pattern in the exception handler.

---

## MEDIUM

### R4-4: Rebalancer NaN price passes `<= 0` guard — generates garbage orders

**File:** `strategy/rebalancer.py`, line 70
**Severity:** MEDIUM

```python
if price <= 0:
    logger.warning(...)
    continue
```

`np.nan <= 0` evaluates to `False` (all NaN comparisons return False). If `current_prices` contains NaN (e.g., from a failed data fetch), the NaN price passes the guard. Subsequent computations (`target_value - current_value`, `diff_value / price`) produce NaN-derived quantities that pass all downstream checks (NaN comparisons are always False).

**Incorrect behavior:** An order with a NaN-derived quantity is generated and sent to the router, where it will either crash Pydantic validation or submit a garbage order.

**Fix:** `if price <= 0 or np.isnan(price):`

---

### R4-5: `_refresh_portfolio_state` overwrites `peak_equity` — drawdown check bypassed

**File:** `risk/manager.py`, lines 288-289
**Severity:** MEDIUM

```python
if state:
    self._portfolio_state.update(state)
```

`dict.update()` blindly overwrites all keys including `peak_equity`. If the Redis portfolio state has a stale or lower `peak_equity` (e.g., tracker restarted and lost the high-water mark), the local `peak_equity` is lowered. `peak_equity` should be monotonically non-decreasing (high-water mark), but `update()` doesn't enforce this.

**Incorrect behavior:** Drawdown check `(peak - current) / peak` uses a lowered peak, understating the actual drawdown. Trading continues beyond the configured maximum drawdown limit.

**Fix:** After `update()`, enforce monotonicity: `self._portfolio_state["peak_equity"] = max(self._portfolio_state.get("peak_equity", 0), prev_peak)`

---

### R4-6: Binance `_close_cache` stored as instance attribute — stale data leak

**File:** `data/sources/binance_source.py`, lines 215-217
**Severity:** MEDIUM

```python
if needs_temp_close:
    self._close_cache = np.full((n, lookback), np.nan, dtype=np.float64)
else:
    self._close_cache = None
```

`_close_cache` is set on `self` (the singleton `BinanceSource`) rather than as a local variable. It persists after the call returns, leaking memory for the lifetime of the source. Additionally, if `fetch_history` is called with different parameters on the next invocation, the old array is orphaned but the instance attribute points to the new one — stale data from a previous call could be referenced if the attribute is checked elsewhere.

**Incorrect behavior:** Memory leak proportional to `n * lookback * 8 bytes` per call that needs temp close. The array persists until the next call or process exit.

**Fix:** Use a local variable instead of `self._close_cache`. Pass it through the kline parsing loop.

---

## LOW

### R4-7: yfinance volume fallback path uses `np.zeros` — failed fetch looks like zero volume

**File:** `data/sources/yfinance_source.py`, lines 181-182
**Severity:** LOW

```python
if field_name == "volume":
    result[field_name] = np.zeros(n, dtype=np.float64)
```

FAUDIT-10 fixed `np.zeros → np.full(np.nan)` for price fields, but volume in the fast_info fallback path was intentionally left as zeros. If a symbol's `fast_info` call fails entirely (caught by the broad `except` on line 223), that symbol's volume stays at `0.0` instead of `NaN`, making a failed fetch indistinguishable from genuine zero volume.

**Fix:** Use `np.full(n, np.nan)` for volume too. The `or 0.0` default on line 219 can be changed to handle NaN explicitly.

---

### R4-8: yfinance `day_change_pct` uses `is not None` check — semantically wrong for NaN sentinel

**File:** `data/sources/yfinance_source.py`, line 221
**Severity:** LOW

```python
if prev_close is not None and prev_close > 0:
    result["day_change_pct"][i] = ((price - prev_close) / prev_close) * 100
```

`prev_close` is `np.nan` when missing (line 202), not `None`. `np.nan is not None` → `True`. The guard works by accident because `np.nan > 0` → `False`. But if `price` is NaN and `prev_close` is valid, the computation produces NaN silently without logging. The batch path (lines 338-339) correctly uses `not np.isnan()` for both values.

**Fix:** `if not np.isnan(prev_close) and not np.isnan(price) and prev_close > 0:`

---

### R4-9: Negative `max_daily_loss_pct` config causes instant kill switch activation

**File:** `risk/limits.py`, line 117
**Severity:** LOW

```python
if not max_daily:
    return True, ""
```

`not -0.03` → `False`, so the code proceeds. Then `loss_pct >= max_daily` becomes `loss_pct >= -0.03` which is always true (loss_pct ≥ 0), immediately triggering the kill switch with zero actual loss.

**Incorrect behavior:** A misconfigured negative value causes instant trading halt on every risk check, instead of being rejected as invalid.

**Fix:** `if max_daily <= 0: return True, ""`

---

### R4-10: editor.html `resetAll` catch block — `e.message` not escaped

**File:** `monitoring/templates/editor.html`, line 859
**Severity:** LOW

```javascript
showFeedback([`<div class="err-line">Error: ${e.message}</div>`]);
```

The R3-3 fix escaped all other feedback interpolations with `escHtml()`, but missed this one in the `resetAll` catch block. `showFeedback` sets `innerHTML` directly.

**Fix:** `showFeedback([\`<div class="err-line">Error: ${escHtml(e.message)}</div>\`]);`

---

### R4-11: CSS selector injection in logs.html and editor.html — missing `CSS.escape()`

**File:** `monitoring/templates/logs.html`, line 154; `monitoring/templates/editor.html`, line 866
**Severity:** LOW

```javascript
// logs.html:154
const item = document.querySelector(`.session-item[data-id="${currentSessionId}"] .s-name`);

// editor.html:866
const item = sessionId ? document.querySelector(`.session-item[data-id="${sessionId}"]`) : null;
```

Session IDs are injected directly into CSS selector strings without `CSS.escape()`. If the ID contains `]`, `"`, or `\`, `querySelector` throws `DOMException`. The same file (editor.html line 686) correctly uses `CSS.escape()` elsewhere.

**Fix:** Use `CSS.escape(currentSessionId)` / `CSS.escape(sessionId)`.

---

## Summary

| Severity | ID | Description |
|----------|-----|-------------|
| HIGH | R4-1 | `stop_session` overwrites "error" with "stopped" — R3-1 fix defeated |
| HIGH | R4-2 | `market_hours` mode doesn't gate trading — executes 24/7 |
| HIGH | R4-3 | Missing adapter silently drops order — no publish, no persist |
| MEDIUM | R4-4 | Rebalancer NaN price passes `<= 0` guard |
| MEDIUM | R4-5 | `peak_equity` overwritten by Redis — drawdown check bypassed |
| MEDIUM | R4-6 | Binance `_close_cache` on instance — stale data leak |
| LOW | R4-7 | yfinance volume fallback uses zeros instead of NaN |
| LOW | R4-8 | yfinance `day_change_pct` uses `is not None` for NaN sentinel |
| LOW | R4-9 | Negative `max_daily_loss_pct` causes instant kill switch |
| LOW | R4-10 | editor `resetAll` unescaped `e.message` |
| LOW | R4-11 | CSS selector injection in logs.html and editor.html |

| Severity | Count |
|----------|-------|
| HIGH | 3 |
| MEDIUM | 3 |
| LOW | 5 |
| **Total** | **11** |
