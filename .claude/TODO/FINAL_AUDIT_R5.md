# Final Audit Round 5 — 2026-03-28

> Fifth comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous rounds: `FINAL_AUDIT.md` (FAUDIT-1–23), `FINAL_AUDIT_R2.md` (R2-1–15), `FINAL_AUDIT_R3.md` (R3-1–13), `FINAL_AUDIT_R4.md` (R4-1–11).

---

## HIGH

### R5-1: Alpaca adapter `str(order.side) == "buy"` always evaluates to False — all orders reported as SELL

**File:** `execution/alpaca_adapter.py` line 120
**Code:**
```python
side=Side.BUY if str(order.side) == "buy" else Side.SELL,
```
**Problem:** The Alpaca SDK's `OrderSide` enum's `__str__()` returns `"OrderSide.buy"` (not `"buy"`). The comparison `str(order.side) == "buy"` is therefore **always False**, and every order — including buys — is reported as `Side.SELL` in the `OrderUpdate`.

**Impact:** The `PortfolioTracker` receives incorrect side information for every Alpaca order. Buy fills are treated as sells, corrupting position tracking (quantities go negative when they should go positive). This makes Alpaca live trading completely broken for position tracking.

**Fix:** Use `order.side.value == "buy"` or compare against the enum directly: `order.side == OrderSide.BUY`. Same issue exists on the `status_map` lookup at line 121 — verify `str(order.status)` also matches expected strings.

---

## MEDIUM

### R5-2: Strategy re-opens positions after pre-close liquidation — no suppression flag

**File:** `session/manager.py` lines 570–583 (liquidation) + lines 676–683 (strategy gate)
**Problem:** When `schedule_mode == "market_hours_liquidate"`, the schedule loop liquidates all positions N minutes before close (line 575). However, the market is still technically open during this window. The strategy cycle (`_run_strategy_cycle`) only gates on `is_market_open()` (R4-2 fix, line 681), which returns True because the market hasn't closed yet. The strategy keeps executing and can immediately re-open positions that were just liquidated.

**Impact:** Positions re-opened in the final minutes before close won't be liquidated (because `liquidated_today` is already True). They carry overnight risk, which defeats the entire purpose of the liquidation feature.

**Fix:** Add a `liquidated_today` flag (or similar) to `SessionPipeline` and check it in `_run_strategy_cycle` to suppress trading after liquidation until market close.

---

### R5-3: Binance live fetch initializes `volumes` and `num_trades` with `np.zeros` instead of `np.full(NaN)`

**File:** `data/sources/binance_source.py` lines 53, 55
**Code:**
```python
volumes = np.zeros(n, dtype=np.float64)
num_trades = np.zeros(n, dtype=np.float64)
```
**Problem:** When the 24hr ticker API call fails (line 95 `except Exception`), these arrays retain their initial value of `0.0`. Downstream consumers (strategies, dashboard) see `volume=0` and `num_trades=0` as real data, not as missing data. All other arrays in the same block (`prices`, `opens`, `highs`, `lows`, etc.) correctly use `np.full(n, np.nan)`.

**Impact:** A strategy that uses volume (e.g., volume-weighted signals) would treat a failed API call as "zero volume" rather than "no data", potentially generating incorrect signals.

**Fix:** Change both lines to `np.full(n, np.nan, dtype=np.float64)`.

---

### R5-4: Binance orderbook `as_completed` timeout raises unhandled `TimeoutError` — drops ALL results including successful ones

**File:** `data/sources/binance_source.py` line 141
**Code:**
```python
for future in as_completed(futures, timeout=15):
```
**Problem:** `concurrent.futures.as_completed(timeout=...)` raises `TimeoutError` when the iterator exhausts the timeout before all futures complete. The current code has no `except TimeoutError` handler around the for-loop. When the timeout fires, the `TimeoutError` propagates up, skipping all remaining (possibly successful) futures. The entire `bids` and `asks` arrays — including results from symbols that completed before the timeout — are abandoned because the exception jumps past the `if "bid" in fields_to_fetch` block at lines 157–162.

**Impact:** One slow symbol can cause ALL orderbook data (including already-fetched symbols) to be lost for that tick. The outer `except Exception` at line 95 doesn't cover this block.

**Fix:** Wrap the for-loop in `try/except TimeoutError: pass` so that successfully completed futures are still harvested.

---

### R5-5: `run_all.py` cancels tasks but never awaits them — unclean shutdown

**File:** `scripts/run_all.py` lines 45–48
**Code:**
```python
for task in tasks:
    task.cancel()

print("Shutdown complete.")
```
**Problem:** After calling `task.cancel()`, the code immediately prints "Shutdown complete" and exits `main()`. It never `await`s the cancelled tasks. This means:
1. Tasks don't get a chance to handle `CancelledError` and run cleanup code
2. Python emits `RuntimeWarning: coroutine ... was never awaited` or `Task was destroyed but it is pending`
3. The uvicorn server doesn't get a clean shutdown — open connections, DB sessions, and Redis subscriptions may not be closed properly

**Fix:** Add `await asyncio.gather(*tasks, return_exceptions=True)` after the cancel loop.

---

## LOW

### R5-6: yfinance `fetch` uses `0.0` fallback for volume instead of NaN

**File:** `data/sources/yfinance_source.py` line 217
**Problem:** In the live `fetch()` method, volume is extracted with `float(fi.last_volume or 0)`. When `last_volume` is `None` (API failure or missing data), this produces `0.0` instead of `NaN`. Other fields in the same method correctly fall back to `NaN`.

**Impact:** Minor — a missing volume reads as zero rather than missing. Strategies using volume could misinterpret this.

**Fix:** Use `float(fi.last_volume) if fi.last_volume is not None else np.nan`.

---

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 1 |
| MEDIUM | 4 |
| LOW | 1 |
| **Total** | **6** |
