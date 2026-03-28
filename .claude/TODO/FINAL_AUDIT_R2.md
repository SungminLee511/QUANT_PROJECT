# Final Audit Round 2 — 2026-03-28

> Second comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous FAUDIT-1 through FAUDIT-23 are in `FINAL_AUDIT.md`.

---

## CRITICAL

### R2-1: `scripts/run_all.py` calls `create_app()` with wrong signature — immediate crash

**File:** `scripts/run_all.py`, line 17
**Severity:** CRITICAL

```python
app = create_app(config, redis, session_manager)
```

`create_app()` in `monitoring/app.py` (line 69) accepts **one** argument: `def create_app(config: dict) -> FastAPI:`. It manages Redis and SessionManager internally via its lifespan. Calling it with 3 arguments raises `TypeError: create_app() takes 1 positional argument but 3 were given`. Additionally, `run_all.py` lines 30-32 manually call `init_engine(config)`, `init_db()`, and create Redis/SessionManager — but `create_app()`'s lifespan does the same thing, causing double-initialization.

**Incorrect behavior:** `scripts/run_all.py` is completely broken and cannot start.

---

## HIGH

### R2-2: `or` on numpy arrays crashes `fetch_history` for multi-symbol sessions

**File:** `data/sources/yfinance_source.py`, line 331; `data/sources/binance_source.py`, line 270
**Severity:** HIGH

```python
# yfinance_source.py:331
close_arr = result.get("close") or result.get("price")

# binance_source.py:270
close_arr = field_arrays.get("close") or field_arrays.get("price")
```

When `result.get("close")` returns a numpy array (2D, shape `[n_symbols, lookback]`), the `or` operator calls `bool(arr)`. For multi-element arrays, this raises `ValueError: The truth value of an array with more than one element is ambiguous`. This crashes whenever both `"close"` and `"day_change_pct"` are in `requested_fields` **and** there are 2+ symbols.

**Incorrect behavior:** Historical data backfill crashes with `ValueError`, preventing strategy from having any history on startup. Affects all multi-symbol sessions that include `day_change_pct` in their data config.

**Fix:** `close_arr = result.get("close") if result.get("close") is not None else result.get("price")`

---

### R2-3: CSP header blocks all CDN scripts — Backtest and Editor pages non-functional

**File:** `monitoring/app.py`, lines 148-151
**Severity:** HIGH

```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'"
)
```

The CSP allows scripts only from `'self'` and `'unsafe-inline'`. But `backtest.html` loads **Chart.js** from `cdn.jsdelivr.net` and `editor.html` loads **CodeMirror** from `cdnjs.cloudflare.com`. The browser blocks these external scripts entirely.

**Incorrect behavior:** The Backtest page has no equity chart (Chart.js blocked). The Editor page has no code editor (CodeMirror blocked). Both pages render as broken shells.

**Fix:** Add `cdn.jsdelivr.net` and `cdnjs.cloudflare.com` to `script-src` and `style-src` directives.

---

### R2-4: `_run_with_restart` doesn't stop pipeline on component exhaustion — zombie sessions

**File:** `session/manager.py`, lines 855-886
**Severity:** HIGH

```python
async def _run_with_restart(self, session_id, component, coro_factory):
    for attempt in range(1, MAX_RESTART_ATTEMPTS + 1):
        try:
            await coro_factory()
            return
        except asyncio.CancelledError:
            return
        except Exception:
            if attempt < MAX_RESTART_ATTEMPTS:
                await asyncio.sleep(RESTART_DELAY)
            else:
                await self._set_session_status(session_id, "error")
                # ← Does NOT set pipeline.running = False
                # ← Does NOT cancel other component tasks
```

When a critical component exhausts all restart attempts, the method sets DB status to "error" but does **not** set `pipeline.running = False` or cancel sibling tasks. The other components keep running. Worse: `start_session()` at line 252 checks `if session_id in self._pipelines and self._pipelines[session_id].running` — since `running` is still True, a restart attempt from the UI returns True without actually restarting anything. The user sees "active" but the session is half-dead.

**Incorrect behavior:** Partially-dead sessions consume resources indefinitely. Manual restart attempts silently fail. Only a full server restart recovers the session.

---

## MEDIUM

### R2-5: Binance `_fetch_book` returns `0.0` for empty order book, contradicting NaN initialization

**File:** `data/sources/binance_source.py`, lines 134-135
**Severity:** MEDIUM

```python
bid = float(bids_list[0][0]) if len(bids_list) > 0 and len(bids_list[0]) > 0 else 0.0
ask = float(asks_list[0][0]) if len(asks_list) > 0 and len(asks_list[0]) > 0 else 0.0
```

When the Binance API returns a successful response with empty `bids`/`asks` arrays (e.g., delisted pair, very illiquid market), this function returns `(symbol, 0.0, 0.0)`. These values overwrite the NaN-initialized arrays. The `except` on line 148 doesn't fire because the request itself succeeded.

**Incorrect behavior:** A symbol with an empty order book gets `bid=0.0, ask=0.0, spread=0.0` instead of `NaN`. Strategies see a zero-spread "free" market instead of missing data.

**Fix:** Return `np.nan` instead of `0.0` in the else clause.

---

### R2-6: Sim adapter caps short cover by available cash — shorts become unclosable

**File:** `execution/sim_adapter.py`, lines 90-97
**Severity:** MEDIUM

```python
if self._strategy_mode == "long_short" and pos["quantity"] < 0:
    # Covering a short — cost comes from cash
    if cost > self._cash:
        quantity = self._cash / price
        if quantity < 0.0001:
            raise ValueError(f"Insufficient cash to cover short for {symbol}")
        cost = price * quantity
    self._cash -= cost
```

When covering a short position (mandatory buy-back), the code caps the buy quantity based on available cash. But if other trades have consumed the cash, the system cannot fully close the short. The kill switch's "flatten all positions" (zero weights) depends on the rebalancer being able to close all positions.

**Incorrect behavior:** A sim session with depleted cash gets stuck with an unclosable short position. The kill switch flatten fails, leaving the session in a permanent risk-breached state.

**Fix:** Short covers should not be capped by cash — the trader is obligated to cover. Allow cash to go temporarily negative for short covers (or reserve the cash when opening the short).

---

### R2-7: Reconciler checks all local symbols against each exchange — false positives in multi-exchange

**File:** `portfolio/reconciler.py`, lines 69-91
**Severity:** MEDIUM

```python
local_symbols = set(local_state.get("position_symbols", []))
# ...
self._check_drift("Binance", local_symbols, exchange_symbols)  # ← all symbols, not just Binance symbols
# ...
self._check_drift("Alpaca", local_symbols, exchange_symbols)   # ← all symbols, not just Alpaca symbols
```

`local_symbols` is a flat set of **all** positions across all exchanges. When checking against Binance, any Alpaca-only symbol appears as "tracked locally but not on exchange" (false positive), and vice versa.

**Incorrect behavior:** Every reconciliation cycle produces spurious drift warnings in multi-exchange setups. Operators learn to ignore reconciliation warnings, defeating the purpose of the safety net.

**Fix:** Partition `local_symbols` by exchange before comparing (the position data includes an `exchange` field).

---

### R2-8: `date.today()` uses server UTC time, not ET market time in schedule loop

**File:** `session/manager.py`, lines 565-578
**Severity:** MEDIUM

```python
from datetime import date
last_liquidation_date = date.today().isoformat()  # ← UTC date
# ...
today = date.today().isoformat()  # ← UTC date
if last_liquidation_date and today != last_liquidation_date:
    liquidated_today = False
```

Server is UTC. `date.today()` returns the UTC date. The market calendar operates in US Eastern time. The UTC date rolls over at midnight UTC (7 PM or 8 PM ET depending on DST) — which is **during US market hours**.

**Incorrect behavior:** Two failure modes:
1. If a pre-close liquidation happens after midnight UTC but before market close, and the schedule loop iterates again, `date.today()` returns a new UTC date → `liquidated_today` resets → a second liquidation is triggered in the same trading day.
2. The reset of `liquidated_today` for a genuinely new trading day may happen too early (during the previous trading session).

**Fix:** Use `datetime.now(ZoneInfo("US/Eastern")).date()` instead of `date.today()`.

---

### R2-9: Kill switch restore logs "staying halted" but starts pipeline anyway

**File:** `session/manager.py`, lines 298-309
**Severity:** MEDIUM

```python
ks = KillSwitch(self._redis, ks_key, session_id=session_id)
if await ks.restore_from_db():
    logger.warning("Session %s: kill switch was active before restart — staying halted", session_id)

await self._start_pipeline(...)     # ← runs unconditionally
await self._set_session_status(session_id, "active")  # ← set to "active" even if kill switch is on
```

The log says "staying halted" but the code proceeds to start all components (collector, router, tracker, sim adapter). Trading is blocked by the kill switch's `is_active()` check inside strategy cycles, but all infrastructure runs and consumes resources. The DB status shows "active".

**Incorrect behavior:** Misleading log message. Session shows "active" in UI when it is actually trading-halted. All components run unnecessarily. User may not realize they need to manually deactivate the kill switch.

---

### R2-10: `showFeedback` in editor.html double-escapes HTML — feedback shows raw tags

**File:** `monitoring/templates/editor.html`, lines 674-678
**Severity:** MEDIUM

```javascript
function showFeedback(lines) {
    const fb = document.getElementById('feedback');
    if (!lines || lines.length === 0) { fb.style.display = 'none'; return; }
    fb.style.display = 'block';
    fb.innerHTML = lines.map(l => escHtml(l)).join('<br>');
}
```

Every caller passes lines containing HTML markup (e.g., `'<div class="ok-line">✓ Strategy code is valid</div>'` at line 788, `'<div class="err-line">✗ Select a session first</div>'` at line 798, etc.). But `showFeedback` runs each line through `escHtml()` which escapes `<`, `>`, `&`, `"`. The escaped HTML renders as visible text.

**Incorrect behavior:** All validate/deploy/reset feedback shows raw HTML tags as plain text instead of styled content. E.g., user sees `<div class="ok-line">&#10003; Deployed successfully</div>` instead of a green checkmark.

**Fix:** Remove the `escHtml()` call — the HTML is intentionally constructed by the code (not user input), so escaping is unnecessary and harmful.

---

### R2-11: `_open_orders` memory leak in sim mode

**File:** `execution/router.py`, lines 62-63, 163
**Severity:** MEDIUM

```python
# Line 62-63: Poll task only starts for live mode
if self._sim_adapter is None:
    asyncio.create_task(self._poll_open_orders())

# Line 163: But orders are added for ALL modes
self._open_orders[order_id] = order
```

In sim mode, every order is added to `_open_orders` but the polling task that cleans up terminal orders never starts. Sim orders are instantly FILLED but stay in the dict forever. Over a long-running sim with thousands of trades, this dict grows without bound.

**Incorrect behavior:** Unbounded memory growth proportional to total sim orders placed. Long-running sim sessions will gradually consume memory.

**Fix:** Either don't add sim orders to `_open_orders`, or skip `_open_orders` for instantly-completed orders.

---

### R2-12: Dashboard API endpoints leak exception details to client

**File:** `monitoring/dashboard.py`, lines 145-147, 177-179
**Severity:** MEDIUM (security — information disclosure)

```python
except Exception as e:
    logger.exception("Error fetching orders")
    return JSONResponse({"orders": [], "error": str(e)})
```

Raw exception messages (which can include database connection strings, SQL statements, table structures, or file paths) are returned directly to the browser.

**Incorrect behavior:** Internal error details exposed to the client. An attacker probing the API can learn about the database schema, connection info, and internal file structure.

**Fix:** Return a generic error message to the client; keep `str(e)` in the server log only.

---

### R2-13: Binance `avgPrice` string `"0.00000000"` is truthy — prevents fallback to `price` field

**File:** `execution/binance_adapter.py`, line 153
**Severity:** MEDIUM

```python
avg_price=float(result.get("avgPrice", 0) or result.get("price", 0)),
```

`result.get("avgPrice", 0)` returns the raw API value — a string `"0.00000000"` for orders where Binance hasn't populated the field yet. This non-empty string is truthy, so the `or` fallback to `price` never triggers. `float("0.00000000")` → `0.0`. In the tracker (line 91), `update.avg_price <= 0` causes the fill to be silently dropped.

**Incorrect behavior:** For Binance orders where `avgPrice` is temporarily `"0.00000000"` (freshly placed orders before fill price is populated), the fill is recorded with price 0 in the DB, and the tracker ignores it entirely — the position is never recorded.

**Fix:** Convert to float first, then apply fallback: `avg = float(result.get("avgPrice", 0)); avg_price = avg if avg > 0 else float(result.get("price", 0))`

---

## LOW

### R2-14: `or` pattern on numeric dict lookups drops zero values in yfinance fast_info

**File:** `data/sources/yfinance_source.py`, lines 197, 199, 208, 211, 216
**Severity:** LOW

```python
_last = fi.get("lastPrice") or fi.get("last_price")
_prev = fi.get("previousClose") or fi.get("previous_close")
_v = fi.get("lastVolume") or fi.get("last_volume")
```

The `or` operator treats `0` and `0.0` as falsy. If the first key exists with value `0` (e.g., zero volume for a halted stock via `lastVolume`), Python falls through to the second key, which may return `None`. For volume, the final `or 0.0` default masks the issue. For prices, 0.0 is practically impossible for listed equities.

**Incorrect behavior:** Structurally wrong pattern. Real impact is negligible for prices, but the code is fragile and confusing for maintenance.

**Fix:** Use `fi.get("lastPrice") if fi.get("lastPrice") is not None else fi.get("last_price")` pattern.

---

### R2-15: `.env` read doesn't strip quotes — API keys may include literal quote characters

**File:** `monitoring/settings.py`, lines 28-38
**Severity:** LOW

```python
def _read_env() -> dict[str, str]:
    ...
    if "=" in line:
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env
```

If the `.env` file uses `KEY="value"` format (common convention), `value.strip()` returns `"value"` with literal quotes. These quoted values are then passed to the Binance/Alpaca API, causing authentication failures.

**Incorrect behavior:** API keys with surrounding quotes in the `.env` file fail authentication when passed to exchanges. The `save_settings` function writes values without quotes, so the problem is self-correcting after the first save — but initial setup from a manually-edited `.env` file will break.

**Fix:** Strip surrounding quotes: `value = value.strip().strip("'\"")`.

---

## Summary

| Severity | ID | Description |
|----------|-----|-------------|
| CRITICAL | R2-1 | `run_all.py` wrong `create_app()` signature — immediate crash |
| HIGH | R2-2 | `or` on numpy arrays crashes multi-symbol `fetch_history` |
| HIGH | R2-3 | CSP blocks CDN scripts — Backtest & Editor pages broken |
| HIGH | R2-4 | `_run_with_restart` doesn't stop pipeline — zombie sessions |
| MEDIUM | R2-5 | Binance empty orderbook returns 0.0 instead of NaN |
| MEDIUM | R2-6 | Sim short cover capped by cash — shorts unclosable |
| MEDIUM | R2-7 | Reconciler false positives in multi-exchange setup |
| MEDIUM | R2-8 | `date.today()` uses UTC not ET in schedule loop |
| MEDIUM | R2-9 | Kill switch restore doesn't prevent pipeline start |
| MEDIUM | R2-10 | `showFeedback` double-escapes HTML — broken editor feedback |
| MEDIUM | R2-11 | `_open_orders` memory leak in sim mode |
| MEDIUM | R2-12 | Dashboard API leaks exception details to client |
| MEDIUM | R2-13 | Binance `avgPrice` "0.00000000" truthy string drops fills |
| LOW | R2-14 | `or` on numeric dict lookups drops zero values |
| LOW | R2-15 | `.env` read doesn't strip quotes from values |

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH | 3 |
| MEDIUM | 9 |
| LOW | 2 |
| **Total** | **15** |
