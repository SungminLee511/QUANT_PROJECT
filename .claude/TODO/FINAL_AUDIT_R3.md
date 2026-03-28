# Final Audit Round 3 — 2026-03-28

> Third comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous rounds: `FINAL_AUDIT.md` (FAUDIT-1–23), `FINAL_AUDIT_R2.md` (R2-1–15).

---

## HIGH

### R3-1: Self-cancellation deadlock in `_run_with_restart` — session status stuck as "active"

**File:** `session/manager.py`, lines 895-901
**Severity:** HIGH

```python
# R2-4 fix calls stop_session from within a pipeline task:
try:
    await self.stop_session(session_id)
except Exception:
    logger.exception("Failed to stop session ...")
await self._set_session_status(session_id, "error")
```

`stop_session()` (line 360-362) calls `task.cancel()` on ALL pipeline tasks, including the one currently executing `_run_with_restart`. When `stop_session` then does `await task` (line 365), a `CancelledError` is raised into the current task. In Python 3.9+, `CancelledError` is a `BaseException`, NOT an `Exception` — so the `except Exception` on line 899 does **not** catch it. The error propagates up, and line 901 (`_set_session_status(session_id, "error")`) **never executes**.

**Incorrect behavior:**
1. Session status stays "active" in DB permanently even though all tasks are dead.
2. `_pipelines.pop()` inside `stop_session` may or may not execute depending on exactly where the cancellation hits.
3. The dashboard shows "active" for a dead session. UI restart attempts may silently fail.

**Fix:** Catch `BaseException` (or specifically `asyncio.CancelledError`) around the `stop_session` call, or use `asyncio.shield()` to protect the cleanup, or set status to "error" BEFORE calling `stop_session`.

---

### R3-2: Tracker publishes positions without `exchange` field — R2-7 reconciler fix is broken

**File:** `portfolio/tracker.py`, lines 287-297
**Severity:** HIGH

```python
"positions": [
    {
        "symbol": s,
        "quantity": p["quantity"],
        "avg_entry_price": p["avg_entry_price"],
        "current_price": self._prices.get(s, 0.0),
        "unrealized_pnl": ...,
    }
    for s, p in self._positions.items()
    ...
]
```

The internal `_positions` dict stores `"exchange"` (set at line 123: `"exchange": update.exchange.value`), but the published state omits it. The R2-7 reconciler fix (`reconciler.py` line 77) reads `p.get("exchange", "").lower()` from this published state — it always gets `""`, so both `binance_local` and `alpaca_local` stay empty. Every position appears as "on exchange but not tracked locally".

**Incorrect behavior:** The R2-7 fix is completely non-functional. The reconciler produces false warnings for every single position, every cycle.

**Fix:** Include `"exchange": p.get("exchange", ""),` in the published position dict.

---

### R3-3: XSS via unescaped values in editor.html feedback panel

**File:** `monitoring/templates/editor.html`, lines 756, 758, 775, 778, 823, 827
**Severity:** HIGH

```javascript
// Line 756 — server errors inserted raw into innerHTML
data.errors.forEach(e => lines.push(`<div class="err-line">&#10007; Strategy: ${e}</div>`));

// Line 775 — user-typed custom data name inserted raw
lines.push(`<div class="ok-line">&#10003; Custom "${c.name}" is valid</div>`);
```

These are passed to `showFeedback()` which sets `fb.innerHTML`. `c.name` comes directly from user-typed input in the custom data name field. Server validation errors typically echo back user code snippets. The `escHtml()` function exists in the file but is **not** used for any of these interpolations.

**Incorrect behavior:** A user typing `<img src=x onerror=alert(1)>` as a custom data function name gets it rendered as executable HTML in the feedback panel.

**Fix:** Wrap every interpolated variable in `escHtml()`:
```javascript
data.errors.forEach(e => lines.push(`<div class="err-line">&#10007; Strategy: ${escHtml(e)}</div>`));
```

---

### R3-4: XSS via attribute injection in logs.html — `escHtml` missing quote escaping

**File:** `monitoring/templates/logs.html`, lines 90-94, 98-100
**Severity:** HIGH

```javascript
function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
// Line 92 — entry.source placed in attribute context:
`<span class="src ${escHtml(entry.source || '')}">${escHtml(...)}</span>`
```

`escHtml` does **not** escape `"` (double-quote). `entry.source` is placed inside a double-quoted HTML attribute (`class="src ..."`). If `entry.source` contains `"`, it breaks out of the attribute and can inject arbitrary attributes like `onmouseover`.

**Incorrect behavior:** A log entry with `source` containing `" onmouseover="alert(document.cookie)` would execute arbitrary JavaScript when the user hovers over the log entry.

**Fix:** Add `.replace(/"/g,'&quot;').replace(/'/g,'&#39;')` to `escHtml`, or use a DOM-based approach (`textContent` then `innerHTML`).

---

## MEDIUM

### R3-5: `_publish_state_loop` uses 0.0 fallback for missing prices — bogus dashboard data

**File:** `portfolio/tracker.py`, line 292
**Severity:** MEDIUM

```python
"current_price": self._prices.get(s, 0.0),
```

When market data hasn't arrived for a symbol, `current_price` shows `0.0`. Meanwhile, `unrealized_pnl` on line 293 correctly uses `self._prices.get(s, p["avg_entry_price"])` (entry price fallback). And `get_total_equity()` uses `_get_price(symbol, pos["avg_entry_price"])`. So the published `current_price` is inconsistent with all other price lookups.

**Incorrect behavior:** Dashboard shows `current_price: $0.00` for positions before first market tick, while the total equity is computed correctly using entry price. A long position at $100 shows current_price=0 and a visually alarming (but incorrect) P&L display.

**Fix:** `"current_price": self._prices.get(s, p["avg_entry_price"]),`

---

### R3-6: `get_data_snapshot` leaks mutable reference to `self.symbols` — strategy can corrupt collector

**File:** `data/collector.py`, line 461
**Severity:** MEDIUM

```python
result["tickers"] = self.symbols
```

All numpy buffer arrays are properly `.copy()`'d (line 459), but `tickers` returns a direct reference to the collector's internal symbol list. If any strategy function mutates `data["tickers"]` (e.g., `.sort()`, `.append()`, `.pop()`), it permanently corrupts the collector's `self.symbols`, breaking the symbol-to-buffer-row mapping.

**Incorrect behavior:** A strategy calling `data["tickers"].sort()` would reorder the collector's symbol list while numpy buffers retain original row order. Every subsequent data collection cycle silently maps fetched prices to the wrong symbols.

**Fix:** `result["tickers"] = list(self.symbols)`

---

### R3-7: Binance `fetch_history` returns all-NaN `day_change_pct` when `close`/`price` not co-requested

**File:** `data/sources/binance_source.py`, lines 269-278
**Severity:** MEDIUM

```python
if "day_change_pct" in field_arrays:
    close_arr = field_arrays.get("close") if field_arrays.get("close") is not None else field_arrays.get("price")
    if close_arr is not None:
        # ... compute from close_arr
```

When a user configures only `day_change_pct` (without `close` or `price`), the kline data is fetched but close values are never stored (because `"close"` and `"price"` aren't in `field_arrays`). The `day_change_pct` remains all-NaN. The yfinance equivalent correctly handles this with a separate close-only fallback download.

**Incorrect behavior:** Buffer backfill for `day_change_pct` produces all-NaN, delaying strategy start until enough live scrapes accumulate. For lookback=20 at 1-min resolution, that's a 20-minute delay instead of immediate startup with history.

**Fix:** Temporarily parse close data from the already-fetched klines when `day_change_pct` is requested, even if `close`/`price` weren't explicitly configured.

---

### R3-8: Editor deploy endpoint leaks exception details to client

**File:** `monitoring/editor.py`, line 243
**Severity:** MEDIUM (security — information disclosure)

```python
except Exception as e:
    logger.exception("Failed to deploy to session %s", session_id)
    return JSONResponse({"deployed": False, "errors": [str(e)]})
```

Same class of issue as R2-12 (which fixed `dashboard.py`). The raw exception from the deploy path is returned to the client, potentially revealing DB schema, SQL fragments, or file paths.

**Fix:** Return `"errors": ["Deploy failed — see server logs"]`.

---

### R3-9: Backtest run endpoint leaks exception details to client

**File:** `monitoring/backtest.py`, lines 169-174
**Severity:** MEDIUM (security — information disclosure)

```python
except Exception as e:
    logger.exception("Backtest failed")
    return JSONResponse({
        "success": False,
        "errors": [f"Backtest error: {str(e)}"],
    })
```

Same class. Raw exception from the backtest engine forwarded to client.

**Fix:** Return `"errors": ["Backtest failed — see server logs"]`.

---

## LOW

### R3-10: `_last_filled` entries for PARTIAL→CANCELLED orders never cleaned up (memory leak)

**File:** `portfolio/tracker.py`, lines 99-106, 330-333
**Severity:** LOW

```python
# Line 105-106: only FILLED orders get the sentinel
if update.status == OrderStatus.FILLED:
    self._last_filled[update.order_id] = -1.0

# Line 330-333: cleanup only removes sentinel entries
completed = [k for k, v in self._last_filled.items() if v < 0]
```

When an order goes PARTIAL then CANCELLED, the tracker stores the cumulative filled qty (positive float) but never sets the -1.0 sentinel (CANCELLED is ignored at line 89). The cleanup only removes entries with `v < 0`. These orphaned positive entries accumulate indefinitely.

**Incorrect behavior:** Slow memory leak in `_last_filled` dict proportional to partially-filled-then-cancelled orders. Each entry is ~100 bytes. In a limit-order-heavy system, this can reach meaningful size over weeks/months.

**Fix:** Also clean entries whose order_id hasn't been seen in the last N snapshot cycles, or set sentinel for CANCELLED status too.

---

### R3-11: V1 `RiskManager` converts "hold" signals into SELL orders

**File:** `risk/manager.py`, line 244
**Severity:** LOW (V1 legacy code path only)

```python
side = Side.BUY if signal.signal.value == "buy" else Side.SELL
```

The `Signal` enum has `buy`, `sell`, and `hold`. A "hold" signal passes all risk checks, reaches `_signal_to_order`, and the ternary maps it to `Side.SELL`. No filtering for hold anywhere in the V1 pipeline.

**Incorrect behavior:** A V1 "hold" signal becomes a market sell order, liquidating the position.

**Fix:** Add `if signal.signal == Signal.HOLD: return None` early in `_signal_to_order`.

---

### R3-12: V1 `check_position_size` blocks sell/close signals for oversized positions

**File:** `risk/limits.py`, lines 34-46
**Severity:** LOW (V1 legacy code path only)

```python
total_exposure = existing_value + proposed_notional
max_allowed = total_equity * max_pct
if total_exposure > max_allowed:
    return False, "Position exposure ... would exceed ..."
```

The check unconditionally ADDS proposed to existing exposure regardless of buy/sell direction. For a sell signal on an at-limit position, the sell is rejected — trapping the position.

**Fix:** Only apply additive check for buy signals.

---

### R3-13: `fmtTime` in logs.html — try/catch is dead code, invalid timestamps show garbled output

**File:** `monitoring/templates/logs.html`, lines 78-84
**Severity:** LOW

```javascript
function fmtTime(isoStr) {
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString(...) + '.' + String(d.getMilliseconds()).padStart(3, '0');
    } catch { return '??:??:??.???'; }
}
```

`new Date(invalid)` returns `Invalid Date` — it does NOT throw. The catch is unreachable. Invalid timestamps produce `"Invalid Date.NaN"` instead of the intended `"??:??:??.???"`.

**Fix:** `const d = new Date(isoStr); if (isNaN(d.getTime())) return '??:??:??.???';`

---

## Summary

| Severity | ID | Description |
|----------|-----|-------------|
| HIGH | R3-1 | `_run_with_restart` self-cancellation — session stuck as "active" |
| HIGH | R3-2 | Published positions missing `exchange` field — reconciler R2-7 fix broken |
| HIGH | R3-3 | XSS in editor feedback panel — unescaped user input and server errors |
| HIGH | R3-4 | XSS in logs.html — `escHtml` missing quote escaping in attribute context |
| MEDIUM | R3-5 | Published `current_price` uses 0.0 fallback — bogus dashboard data |
| MEDIUM | R3-6 | `get_data_snapshot` leaks mutable `self.symbols` — strategy corruption risk |
| MEDIUM | R3-7 | Binance `day_change_pct` backfill all-NaN without co-requested close |
| MEDIUM | R3-8 | Editor deploy endpoint leaks exception details to client |
| MEDIUM | R3-9 | Backtest endpoint leaks exception details to client |
| LOW | R3-10 | `_last_filled` leak for PARTIAL→CANCELLED orders |
| LOW | R3-11 | V1 "hold" signal silently converted to SELL order |
| LOW | R3-12 | V1 `check_position_size` blocks sell signals (traps positions) |
| LOW | R3-13 | `fmtTime` dead catch — invalid timestamps show garbled output |

| Severity | Count |
|----------|-------|
| HIGH | 4 |
| MEDIUM | 5 |
| LOW | 4 |
| **Total** | **13** |
