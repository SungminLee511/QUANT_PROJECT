# Final Audit — 2026-03-27

> Comprehensive codebase audit after completing all Round 5 fixes. Only **real, verified bugs** — no style nits or theoretical improvements.

---

## CRITICAL

### FAUDIT-1: Duplicate FILLED messages re-apply entire fill (double-counted positions)

**File:** `portfolio/tracker.py` — Lines 95–101
**Severity:** CRITICAL

When `status == FILLED`, the tracker pops the `_last_filled` entry on line 101. If the exchange sends a duplicate FILLED message (common with WebSocket reconnects on Binance), the second message finds no entry in `_last_filled`, defaults `prev_filled=0.0`, computes `delta_qty = filled_qty - 0 = filled_qty`, and re-applies the entire fill amount.

**Trigger:** Exchange sends duplicate FILLED message for the same order (Binance WebSocket reconnect, network retry).
**Impact:** Position quantity doubled, cash accounting corrupted. Potentially catastrophic on a live account.
**Fix:** Don't pop the tracking entry on FILLED — instead, mark it as completed (e.g., set to `-1` sentinel) so duplicates produce `delta_qty <= 0` and hit the early return on line 103.

---

## HIGH

### FAUDIT-2: `_build_session_config` always maps API keys to "alpaca" — Binance sessions broken

**File:** `session/manager.py` — Lines 829–835
**Severity:** HIGH

`config_data.get("type", "")` always returns `""` because `config_data` (from `config_json` in DB) never contains a `"type"` key — the session type is stored in `TradingSession.session_type`, not in `config_json`. Therefore `"binance" in ""` is always `False`, and `exchange_key` is always `"alpaca"`.

**Trigger:** Create and start a real (non-sim) Binance session with API keys.
**Impact:** Binance API keys are placed under `cfg["alpaca"]` instead of `cfg["binance"]`. The Binance adapter never receives credentials — all real Binance order placements fail with auth errors.
**Fix:** Pass `session_type` into `_build_session_config` and use `session_type.exchange == Exchange.BINANCE` instead of inspecting `config_data`.

---

### FAUDIT-3: `OrderStatus.PARTIALLY_FILLED` doesn't exist — every live order immediate-fill check silently fails

**File:** `execution/router.py` — Line 133
**Severity:** HIGH

The code references `OrderStatus.PARTIALLY_FILLED`, but the enum defines `OrderStatus.PARTIAL = "partial"`. This raises `AttributeError`, caught by the broad `except Exception` on line 137. The immediate fill detection (lines 126–138) silently fails for **every** real exchange order.

**Trigger:** Any live (non-sim) order placed on Binance or Alpaca.
**Impact:** Market orders that fill instantly remain in `PLACED` status until the 10-second poller catches up. During that 10s window, downstream consumers (portfolio tracker, risk manager) see stale order status.
**Fix:** Change `OrderStatus.PARTIALLY_FILLED` to `OrderStatus.PARTIAL`.

---

### FAUDIT-4: `check_position_size` is a no-op — risk limit never fires

**File:** `risk/limits.py` — Lines 33–35
**Severity:** HIGH

`estimated_value = signal.strength * max_pct * total_equity` and `max_allowed = total_equity * max_pct`. Since `signal.strength` is constrained to `[0.0, 1.0]` by the Pydantic schema, `estimated_value <= max_allowed` is always true. The check `if estimated_value > max_allowed` can never pass.

**Trigger:** Any signal with valid strength. The position size limit is effectively disabled.
**Impact:** V1 risk manager never rejects signals for being too large. A strategy returning `strength=1.0` is always approved regardless of existing position concentration.
**Fix:** The check should compare the new position's total value (existing + proposed) against the limit, not just the proposed signal alone.

---

### FAUDIT-5: Backtest cash goes negative when buying with commission

**File:** `backtest/engine.py` — Lines 146–153
**Severity:** HIGH

The buy branch caps `actual_value` at `self.cash` (line 147), then deducts `trade_value + fee` (line 153). The fee is computed *after* capping, so when `actual_value == self.cash`, `self.cash -= trade_value + fee` pushes cash to `-fee`.

**Trigger:** Any buy trade that uses all remaining cash with `commission_pct > 0`.
**Impact:** Negative cash inflates effective leverage, corrupts equity calculations for all subsequent bars, and makes backtest results unreliable.
**Fix:** Cap `actual_value` at `self.cash / (1 + self.commission_rate)` to reserve room for the fee.

---

### FAUDIT-6: XSS in backtest trade table — symbol/side not escaped

**File:** `monitoring/templates/backtest.html` — Lines 352–361
**Severity:** HIGH (Security)

`showResults()` renders trade data directly into `innerHTML` via template literals without escaping: `<td>${t.symbol}</td>`, `<td class="${t.side}">`. If backtest results contain a crafted symbol name, arbitrary JavaScript executes.

**Trigger:** A session with a symbol like `<img src=x onerror=alert(1)>` runs a backtest.
**Impact:** XSS — cookie theft, session hijacking.
**Fix:** Escape all user-derived values through `escHtml()` before inserting into innerHTML.

---

### FAUDIT-7: XSS in onclick handlers — session name breaks out of JS string

**Files:** `monitoring/templates/base.html` line 173, `monitoring/templates/overview.html` line 275
**Severity:** HIGH (Security)

Session name is injected into `onclick="deleteSession('{{ s.id }}', '{{ s.name }}')"`. Jinja2 auto-escaping produces HTML entities, but the HTML parser decodes them before the JS executes. A session name like `'); alert(document.cookie); //` breaks out of the JS string context.

**Trigger:** Create a session with name containing `'` or `)` and visit overview/sidebar.
**Impact:** XSS — arbitrary JavaScript execution.
**Fix:** Use `data-*` attributes + `addEventListener` instead of inline `onclick`, or JSON-encode the session name and parse it in JS.

---

## MEDIUM

### FAUDIT-8: Rebalancer creates `OrderRequest` with `quantity=0.0` — unhandled Pydantic crash

**File:** `strategy/rebalancer.py` — Lines 91–104
**Severity:** MEDIUM

`qty = abs(diff_value) / price` produces a small number. `round_quantity(qty, exchange)` rounds to 2 decimals for Alpaca. If the result is `0.00`, `OrderRequest(quantity=0.0)` fails Pydantic validation (`quantity: float = Field(gt=0)`) with an unhandled `ValidationError`, crashing the entire rebalance cycle.

**Trigger:** Small position adjustment where `abs(diff_value) / price` rounds to 0.0 at exchange precision. E.g., $200 stock, $0.50 diff → qty=0.0025 → rounds to 0.00.
**Fix:** After `round_quantity`, check `qty <= 0` and skip.

---

### FAUDIT-9: `_run_strategy_cycle` has no `pipeline.running` guard — phantom orders after stop

**File:** `session/manager.py` — Lines 642–810 vs 336–368
**Severity:** MEDIUM

`_run_strategy_cycle` is a callback from DataCollector, not a managed task. It never checks `pipeline.running`. If DataCollector fires the callback just before `stop_session` cancels it, the strategy cycle runs concurrently with teardown and can submit orders after the pipeline is removed and status set to "stopped".

**Trigger:** DataCollector fires `on_strategy_trigger` just as `stop_session` is called.
**Impact:** Phantom orders submitted for a stopped session; position corruption.
**Fix:** Add `if not pipeline.running: return` at the top of `_run_strategy_cycle`.

---

### FAUDIT-10: yfinance batch fetch uses `np.zeros` — invalid symbols get price=0.0 instead of NaN

**File:** `data/sources/yfinance_source.py` — Lines 123, 109–111
**Severity:** MEDIUM

`values = np.zeros(n)` and `_col()` returns `0.0` on failure. Missing/delisted symbols get `price=0.0` written to buffers as real data, indistinguishable from an actual zero price.

**Trigger:** Include a delisted or misspelled ticker in the universe.
**Impact:** Permanent buffer corruption with 0.0 values. Strategy receives false data.
**Fix:** Initialize with `np.full(n, np.nan)`, return `np.nan` from `_col()` on failure.

---

### FAUDIT-11: Binance orderbook zeros masquerade as real data on fetch failure

**File:** `data/sources/binance_source.py` — Lines 116–117, 129–130
**Severity:** MEDIUM

`bids` and `asks` initialized with `np.zeros(n)`. If an orderbook fetch fails, the symbol retains `bid=0.0, ask=0.0, spread=0.0` — indistinguishable from real data.

**Trigger:** Any per-symbol orderbook HTTP error or timeout.
**Impact:** Strategy receives bid=0, ask=0, spread=0 as real values for failed symbols.
**Fix:** Initialize with `np.full(n, np.nan)`.

---

### FAUDIT-12: Dashboard LIMIT applied before WHERE — wrong result count

**File:** `monitoring/dashboard.py` — Lines 123–125, 157–163
**Severity:** MEDIUM

```python
stmt = select(Order).order_by(...).limit(100)
if session_id:
    stmt = stmt.where(Order.session_id == session_id)
```

The LIMIT is applied before the WHERE filter. With many sessions, the query first takes the 100 most recent orders globally, then filters — returning fewer than 100 for a specific session even when more exist.

**Trigger:** Multiple sessions with many orders; request orders for a specific session.
**Impact:** Dashboard shows incomplete order/equity history for a session.
**Fix:** Apply `.where()` before `.limit()`.

---

### FAUDIT-13: Failed orders never publish `OrderUpdate` — downstream never notified

**File:** `execution/router.py` — Lines 139–150
**Severity:** MEDIUM

When `place_order` throws, the code transitions to FAILED and persists, but never publishes an `OrderUpdate`. The portfolio tracker and risk manager are never notified the order failed.

**Trigger:** Any order placement failure on any adapter.
**Impact:** Downstream systems may hold stale state expecting an order that will never fill.
**Fix:** Publish an `OrderUpdate` with `status=FAILED` before returning.

---

### FAUDIT-14: `liquidated_today` flag incorrectly reset by transient market-closed detection

**File:** `session/manager.py` — Lines 551–575
**Severity:** MEDIUM

If `is_market_open()` briefly returns False during market hours (API glitch, stale calendar), `liquidated_today` resets to False. The next iteration re-triggers liquidation, submitting duplicate flatten orders. In `long_short` mode, selling an already-flat position opens an unintended short.

**Trigger:** Momentary `is_market_open()` returning False during market hours.
**Impact:** Duplicate liquidation orders; unintended short positions in long_short mode.
**Fix:** Only reset `liquidated_today` on a genuine session-day boundary (compare dates, not just market open state).

---

### FAUDIT-15: Binance `_order_symbols` lost on adapter restart — can't cancel open orders

**File:** `execution/binance_adapter.py` — Line 29
**Severity:** MEDIUM

`_order_symbols` is an in-memory dict mapping order IDs to symbols. Binance's cancel API requires the symbol, so after a restart, all open order cancellations fail silently because the symbol mapping is lost.

**Trigger:** Adapter restart while limit orders are open on Binance.
**Impact:** Unable to cancel previously placed Binance orders through the system.
**Fix:** Persist order-symbol mappings to DB, or query open orders from Binance on startup to rebuild the map.

---

### FAUDIT-16: Race in `_write_env` — non-atomic settings file write

**File:** `monitoring/settings.py` — Lines 42–66
**Severity:** MEDIUM

`_write_env` reads the file, modifies in-memory, then writes back. Two concurrent requests can overwrite each other's changes. A read during a write could see a partial file.

**Trigger:** Two simultaneous settings save requests.
**Impact:** One save's changes are silently lost.
**Fix:** Use a file lock or write-to-temp-then-rename pattern.

---

## LOW

### FAUDIT-17: yfinance `day_change_pct` returns 0% instead of NaN when previous close unavailable

**File:** `data/sources/yfinance_source.py` — Lines 130–136, 153–156
**Severity:** LOW

`_prev_close` returns `0.0` when data is missing. The `if prev > 0` guard catches it, so `day_change_pct` becomes `0.0`. But 0% ("unchanged") is meaningful data — not the same as "unknown".

**Trigger:** Symbol with only 1 day of data.
**Fix:** Return `np.nan` from `_prev_close` on failure.

---

### FAUDIT-18: Backtest trade pairing uses FIFO single-entry price, not average entry

**File:** `backtest/engine.py` — Lines 478–498
**Severity:** LOW

The FIFO pairing pairs trades of opposite sides using the first entry's price. For weight-based rebalancing with multiple buys at different prices, win/loss calculations use only the first entry price, not the weighted average.

**Trigger:** Multiple buys at different prices followed by a partial sell.
**Impact:** Win rate, avg_win_pct, avg_loss_pct, and profit_factor are inaccurate. Affects reporting only — not live trading.

---

### FAUDIT-19: Failed sim-mode orders leak in `_open_orders` — never cleaned up

**File:** `execution/router.py` — Line 142
**Severity:** LOW

When `place_order` throws in sim mode, the order (now FAILED) is added to `_open_orders`. But the poller is never started in sim mode, so these entries accumulate forever.

**Trigger:** Sim mode + repeated order failures.
**Impact:** Slow memory leak proportional to failed order count.

---

### FAUDIT-20: Reconciler filters out short positions with `quantity > 0` check

**File:** `portfolio/reconciler.py` — Lines 76, 87
**Severity:** LOW

`exchange_symbols = {p["symbol"] for p in exchange_positions if p["quantity"] > 0}` ignores short positions (negative qty). The reconciler can't detect drift on short positions.

**Trigger:** Any short position on Binance or Alpaca.
**Impact:** False drift warnings; reconciler blind to short position discrepancies.
**Fix:** Use `abs(p["quantity"]) > 0.0001`.

---

### FAUDIT-21: Rate limiter `/login` rule applies to GET too — page refreshes trigger lockout

**File:** `monitoring/rate_limit.py` — Lines 44–45
**Severity:** LOW

The `/login` prefix rule matches both `GET /login` (view form) and `POST /login` (submit). Refreshing the login page 10 times in 60 seconds locks out the user from even viewing the form.

**Trigger:** User refreshes login page repeatedly.
**Fix:** Match only `POST /login`, or use a separate rule for the form vs submission.

---

### FAUDIT-22: `backtest.py` float conversion crash on invalid input

**File:** `monitoring/backtest.py` — Line 96
**Severity:** LOW

`starting_cash = float(body.get("starting_cash", 10000))` raises `ValueError` on non-numeric input (e.g., `"abc"`), returning a 500 error. Same for `short_loss_limit_pct` and `commission_pct` on lines 104–105.

**Trigger:** POST to `/backtest/api/run` with `{"starting_cash": "not_a_number"}`.
**Fix:** Wrap in try/except with a user-friendly error response.

---

### FAUDIT-23: Stale `total_equity` used for all orders in a single backtest rebalance

**File:** `backtest/engine.py` — Line 116 vs 137–186
**Severity:** LOW

`total_equity` is computed once at the start of `rebalance()` (line 116). Sells executed first change cash, but subsequent buys still use the stale equity figure for target calculations. Position sizes drift from intended weights.

**Trigger:** Multiple sells and buys in a single rebalance call.
**Impact:** Accumulated position drift over many rebalance cycles. Affects backtest accuracy only.

---

## Summary

| Severity | Count | IDs |
|----------|-------|-----|
| CRITICAL | 1 | FAUDIT-1 |
| HIGH | 6 | FAUDIT-2, 3, 4, 5, 6, 7 |
| MEDIUM | 8 | FAUDIT-8 through 16 |
| LOW | 7 | FAUDIT-17 through 23 |
| **Total** | **22** | |
