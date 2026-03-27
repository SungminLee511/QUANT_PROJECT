# Bugs — Open Issues

> Full audit: 2026-03-27. Covers session, execution, strategy, data, portfolio, risk, backtest, DB, shared.

---

## CRITICAL

### BUG-44: Redis client null dereference on early disconnect

**File:** `shared/redis_client.py` — Lines 55, 58, 153, 157, 164
**Severity:** CRITICAL

`publish()`, `set_flag()`, `get_flag()`, `delete_flag()` don't check if `self._redis is None`. If `disconnect()` fires before these methods return (shutdown race), `AttributeError: 'NoneType' object has no attribute 'publish'` crashes the caller.

**Fix:** Guard all Redis operations with `if self._redis is None: raise RuntimeError(...)`.

---

### BUG-45: DB session null reference in `init_db()`

**File:** `db/session.py` — Line 43
**Severity:** CRITICAL

`init_db()` calls `_engine.begin()` without checking if `_engine is None`. Crashes if called before `init_engine()`.

**Fix:** Add `if _engine is None: raise RuntimeError(...)`.

---

### BUG-46: Market calendar returns invalid results for years beyond 2027

**File:** `shared/market_calendar.py` — Lines 72–74, 100–106, 134–139
**Severity:** CRITICAL

`_NYSE_HOLIDAYS` dict only contains 2025–2027. For 2028+, `.get(year, set())` returns empty → treats all holidays as trading days. A call on 2028-01-01 (New Year's) incorrectly thinks market is open.

**Fix:** Dynamically fetch holidays from Alpaca API, or extend dict, or raise on unsupported years.

---

### BUG-47: Backtest silently skips early bars when lookback isn't filled

**File:** `backtest/engine.py` — Lines 370–384, 680–681
**Severity:** CRITICAL (accuracy)

`_build_data_snapshot()` returns None if any field hasn't accumulated enough lookback. Strategy execution is silently skipped for those bars, biasing backtest results with no user notification.

**Fix:** Log a warning and/or document the skip behavior in backtest results.

---

### BUG-48: Unguarded index access in `_run_strategy_cycle()`

**File:** `session/manager.py` — Lines 413, 684–685, 725
**Severity:** CRITICAL

`current_prices[i]` and `prices[i]` accessed without validating array length matches `pipeline.executor.symbols`. If symbol list changed mid-session (via `update_session()`), crashes with `IndexError`.

**Fix:** Add `if prices is None or len(prices) != len(symbols): return` before accessing.

---

### BUG-49: Race condition — `del self._pipelines[session_id]` in `stop_session()`

**File:** `session/manager.py` — Lines 299 vs 330
**Severity:** CRITICAL

Line 299 uses safe `self._pipelines.pop(session_id, None)`, but line 330 uses `del self._pipelines[session_id]`. Double `stop_session()` call (or call after `start_session()` failure) raises `KeyError`.

**Fix:** Use `.pop(session_id, None)` consistently.

---

### BUG-50: NaN propagation in `momentum_v2.py` silently zeros out all weights

**File:** `strategy/examples/momentum_v2.py` — Lines 27–41
**Severity:** CRITICAL

If any price in the lookback window is NaN: `mean()` → NaN, `deviation` → NaN, `deviation.min()` → NaN, `shifted` → all NaN, `total` → NaN (≠ 0), `weights = NaN / NaN`. Executor converts to all-zero weights with no warning.

**Fix:** Use `np.nanmean()`, or check `np.any(np.isnan(prices))` and return equal weights or zeros with a warning.

---

### BUG-51: Binance `fetch_history()` unchecked kline array indexing

**File:** `data/sources/binance_source.py` — Lines 211–213
**Severity:** CRITICAL

Assumes kline arrays always have ≥9 elements. If API returns truncated data, `IndexError` crashes the entire backfill process.

**Fix:** Validate `len(k) >= 9` before unpacking.

---

### BUG-52: Binance `_fetch_book()` empty orderbook array crash

**File:** `data/sources/binance_source.py` — Lines 121–122
**Severity:** CRITICAL

Checks `if book.get("bids")` but empty list `[]` is truthy. During low liquidity, `bids[0][0]` crashes with `IndexError`.

**Fix:** Check `if bids and len(bids) > 0`.

---

### BUG-53: Zero/negative prices silently skipped in rebalancer

**File:** `strategy/rebalancer.py` — Lines 63–64
**Severity:** CRITICAL

Assets with price ≤ 0 silently skipped — no order generated, no logging. Portfolio allocation drifts from target without operator awareness.

**Fix:** Log a warning when skipping a symbol due to invalid price.

---

## HIGH

### BUG-54: Negative/zero `total_equity` not validated in rebalancer

**File:** `strategy/rebalancer.py` — Lines 31–50
**Severity:** HIGH

With negative equity, `target_value = weight * negative_equity` → generates sell orders larger than holdings. With zero equity, all target values are 0 → silent no-op.

**Fix:** Return empty orders and log error if `total_equity <= 0`.

---

### BUG-55: Router publishes unfilled OrderUpdate immediately after `place_order`

**File:** `execution/router.py` — Lines 134–146
**Severity:** HIGH

`OrderUpdate` published with `filled_qty=0`, `avg_price=0` before polling catches actual fill. Races the 10-second polling loop, causing dashboard flicker.

**Fix:** Query actual status from adapter immediately after place_order before publishing.

---

### BUG-56: SimAdapter BUY with zero clipped quantity

**File:** `execution/sim_adapter.py` — Lines 107–120
**Severity:** HIGH

If cash clips quantity to near-zero, avg_price computation can be unstable. The `if quantity <= 0: raise` guard exists but threshold should match position cleanup threshold (0.0001).

**Fix:** Use `if quantity < 0.0001: raise ValueError(...)`.

---

### BUG-57: Binance adapter silent cancel failure

**File:** `execution/binance_adapter.py` — Lines 93–107
**Severity:** HIGH

If `_order_symbols` map loses the symbol (adapter restart), `cancel_order()` returns `False` silently. Caller doesn't check — order remains open on exchange.

**Fix:** Raise exception instead of returning False.

---

### ~~BUG-58: Router `_persist_order` misuses `external_id` for failed orders~~ ✅ FIXED

**Fixed in:** commit (BUG-58). Added dedicated `order_id` column to Order model + Alembic migration 002. Router now uses `order_id` for lookup and stores `external_id=None` until exchange confirms. Failed orders no longer pollute `external_id`.

---

### BUG-59: Extreme strategy weights overflow to infinity → silent all-zero

**File:** `strategy/executor.py` — Lines 93–104
**Severity:** HIGH

If strategy returns 1e308 weights, `sum → inf`, `weights / inf → [0, 0, ...]`. Silent signal loss.

**Fix:** Clip weights to reasonable bounds (e.g., ±1e6) before summing.

---

### BUG-60: Alpaca adapter `filled_avg_price=None` becomes 0

**File:** `execution/alpaca_adapter.py` — Line 117
**Severity:** HIGH

`float(order.filled_avg_price or 0)` — rejected/cancelled orders get avg_price=0. Indistinguishable from a real 0-price fill downstream.

**Fix:** Use `None` sentinel or explicit status check before setting avg_price.

---

### BUG-61: Short positions excluded from equity calculation

**File:** `portfolio/tracker.py` — Lines 215–242
**Severity:** HIGH

`get_total_equity()`, `get_positions_value()`, `get_all_positions()` all filter with `if pos["quantity"] > 0`. Short positions (negative qty) are excluded → equity overstated, risk checks incomplete.

**Fix:** Change filter to `if abs(pos["quantity"]) > 0.0001` or `if pos["quantity"] != 0`.

---

### BUG-62: DB commit not explicitly awaited in tracker persistence

**File:** `portfolio/tracker.py` — Lines 295–305, 312–341
**Severity:** HIGH

`session.add()` called but `session.commit()` never explicitly awaited. Relies on context manager auto-commit. If DB error occurs after add but before exit, partial writes are silently lost.

**Fix:** Add explicit `await session.commit()` after `session.add()`.

---

### BUG-63: Redis `get_flag()` crashes on malformed JSON

**File:** `shared/redis_client.py` — Lines 155–160
**Severity:** HIGH

`json.loads(raw)` with no try-except. Corrupted Redis data crashes all callers (kill switch checks, portfolio state reads).

**Fix:** Wrap in `try/except json.JSONDecodeError`, log and return None.

---

### BUG-64: `Order.avg_price` nullable but typed as `float`

**File:** `db/models.py` — Line 124
**Severity:** HIGH

Column is `nullable=True` but Python type is `Mapped[float]`. DB can return None → downstream `TypeError` on arithmetic.

**Fix:** Use `Mapped[float | None]` or set `nullable=False`.

---

### BUG-65: Backfill failure silently ignored — strategy runs on empty buffers

**File:** `data/collector.py` — Lines 265–300
**Severity:** HIGH

If `fetch_history()` fails, a WARNING is logged and live loop fills naturally. But strategy may fire before buffers have enough data, using partial/stale data.

**Fix:** Track fill level explicitly; don't fire strategy until minimum threshold met.

---

### BUG-66: Binance VWAP division by zero fallback uses potentially-zero close

**File:** `data/sources/binance_source.py` — Line 229
**Severity:** HIGH

`(quote_vol / v) if v > 0 else c` — if close `c` is also 0 or NaN, VWAP is 0/NaN. Breaks rebalancing.

**Fix:** Chain fallback: try quote_vol/v, then c, then log warning if both fail.

---

### BUG-67: YFinance `_fetch_fast_info_fallback()` percent-change division by zero

**File:** `data/sources/yfinance_source.py` — Lines 186–187
**Severity:** HIGH

`if prev_close and prev_close > 0` uses Python truthiness (False for 0.0 **and** None). Should be explicit `if prev_close is not None and prev_close > 0`.

---

### BUG-68: Position size check uses signal strength instead of actual notional (V1)

**File:** `risk/limits.py` — Lines 31–34
**Severity:** HIGH

`estimated_value = signal.strength * total_equity` doesn't match actual order sizing logic in `risk/manager.py`. Risk check is bypassed by low-strength signals.

**Fix:** Use same sizing formula as `_signal_to_order()` for the check.

---

### BUG-69: Daily loss check mixes realized and unrealized P&L

**File:** `risk/limits.py` — Lines 85–107
**Severity:** HIGH

`daily_pnl = current_equity - day_start_equity` includes both realized and unrealized. Unrealized losses that reverse could trigger kill switch prematurely, or short-term spikes could mask real losses.

**Fix:** Separate realized vs unrealized daily P&L; document behavior.

---

## MEDIUM

### BUG-70: `avg_entry_price` corruption on short cover

**File:** `portfolio/tracker.py` — Lines 132–142
**Severity:** MEDIUM

When a short is fully covered without remainder, `avg_entry_price` stays at the old short entry price. Next long buy uses stale short price for average calculation.

**Fix:** Zero out `avg_entry_price` when `pos["quantity"]` becomes 0.

---

### BUG-71: Concurrent position update race in tracker

**File:** `portfolio/tracker.py` — Lines 192–195
**Severity:** MEDIUM

Position updated in memory, then `_persist_position()` called but not awaited. Concurrent update for same symbol can overwrite with stale data.

**Fix:** Await persist or use per-symbol lock.

---

### BUG-72: Stale price fallback in equity calculations

**File:** `portfolio/tracker.py` — Lines 218, 226, 236–237
**Severity:** MEDIUM

When `_prices` lacks a symbol, falls back to `avg_entry_price`. If market data feed stalls, equity freezes at entry price, risk checks use stale values.

---

### BUG-73: Kill switch state lost on Redis restart

**File:** `risk/kill_switch.py` — All
**Severity:** MEDIUM

Kill switch stored only in Redis (volatile). Redis restart → trading resumes even if halt was warranted. No DB audit trail.

**Fix:** Persist activations to DB; restore on startup.

---

### BUG-74: String-based kill switch auto-activation is fragile

**File:** `risk/manager.py` — Lines 114–116
**Severity:** MEDIUM

`if "drawdown" in result.reason.lower()` — relies on reason text containing specific substrings. Changing message text silently breaks auto-activation.

**Fix:** Return structured check IDs, not string matching.

---

### BUG-75: Order quantity rounding uses fixed 8 decimals

**File:** `risk/manager.py` — Lines 178–185
**Severity:** MEDIUM

`round(quantity, 8)` — crypto needs variable precision per token; stocks need integers or 0.001. Alpaca rejects fractional shares with too many decimals.

**Fix:** Use exchange-specific precision rules.

---

### BUG-76: `_signal_to_order()` doesn't validate computed quantity

**File:** `risk/manager.py` — Lines 174–189
**Severity:** MEDIUM

If `max(price, 0.01)` is 0.01 (micro price), quantity explodes. If `total_equity` negative, quantity is negative. No bounds check before creating `OrderRequest`.

---

### BUG-77: Missing portfolio state not detected

**File:** `risk/manager.py` — Lines 191–212
**Severity:** MEDIUM

If Redis key missing, `get_flag()` returns None → `if state:` fails → `_portfolio_state` unchanged. Risk checks run on stale cached state with no warning.

---

### ~~BUG-78: Custom data shape mismatch in `_append_to_buffer()`~~ ✅ FIXED

**Fixed in:** commit (BUG-78). Added shape validation `values.shape != (expected_rows,)` at top of `_append_to_buffer()`. Mismatched shapes are logged and skipped.

---

### BUG-79: Empty symbol list unchecked in DataCollector

**File:** `data/collector.py` — Line 52
**Severity:** MEDIUM

`symbols = []` → `n_symbols = 0`, zero-shape buffers, silent no-op. No error message; session appears to work but collects nothing.

---

### ~~BUG-80: Missing data filled with 0.0 instead of NaN across all sources~~ ✅ FIXED

**Fixed in:** commit (BUG-80). All three sources now use `np.nan` for missing price/OHLC/VWAP fields. Volume and trade counts remain 0 (valid default). Covers initial arrays, per-item parsing, fundamentals, and history.

---

### BUG-81: Binance thread pool exceptions swallowed — partial fills silent

**File:** `data/sources/binance_source.py` — Lines 125–135
**Severity:** MEDIUM

ThreadPoolExecutor catches all exceptions generically. 5/10 symbols succeed, 5 silently return 0.0. No count of failures or warning about incomplete data.

---

### BUG-82: Alpaca malformed bars silently return zeros

**File:** `data/sources/alpaca_source.py` — Lines 230–243
**Severity:** MEDIUM

Uses `.get("o", 0)` — missing OHLCV fields default to 0.0. Corrupts backtest data silently.

---

### BUG-83: `OrderRequest.price` not validated for LIMIT orders

**File:** `shared/schemas.py` — Lines 81–95
**Severity:** MEDIUM

`price: Optional[float] = None` with no validator. LIMIT orders with `price=None` crash in execution router.

**Fix:** Add Pydantic validator: if `order_type == LIMIT`, require `price is not None`.

---

### BUG-84: Trade model missing unique constraint on `(session_id, order_id)`

**File:** `db/models.py` — Lines 63–87
**Severity:** MEDIUM

Duplicate trades (from retries) can be inserted without error, corrupting audit trail.

---

### BUG-85: Redis listener task not cancelled on reconnect

**File:** `shared/redis_client.py` — Lines 117–134
**Severity:** MEDIUM

When `_listen()` catches exception, new PubSub created but old listener task may still be running → duplicate listeners.

---

### BUG-86: No API retry logic or rate-limit handling across all data sources

**Files:** `yfinance_source.py`, `alpaca_source.py`, `binance_source.py`
**Severity:** MEDIUM

All HTTP calls have fixed timeouts, no retry, no exponential backoff, no 429 handling. Single rate-limit hit causes complete data failure for that scrape.

---

### BUG-87: Unsupported resolution silently defaults to 1d in yfinance

**File:** `data/sources/yfinance_source.py` — Lines 217–228
**Severity:** MEDIUM

`res_map.get(resolution, "1d")` — typo like "30sec" silently becomes daily data. Strategy expects 1-min bars but gets 1-day bars.

---

### ~~BUG-88: Backtest NaN handling silently skips symbols~~ ✅ FIXED

**Fixed in:** commit (BUG-88). Changed missing data default from `0.0` to `np.nan`. Added per-bar warning when symbols have NaN price with no forward-fill available, listing affected symbols by name.

---

### ~~BUG-89: Set/list serialization mismatch in risk manager~~ ✅ FIXED

**Fixed in:** commit (BUG-89). Added type validation before converting `position_symbols`: accepts list/set/tuple, resets to empty set for None or unexpected types (dict, string, int) with warning log.

---

### ~~BUG-90: `LogEntry.event_type` allows arbitrary strings~~ ✅ FIXED

**Fixed in:** commit (BUG-90). Changed `event_type` from `str` to `Literal[...]` with all 12 valid event types. Pydantic now rejects unknown event types at validation time.

---

## LOW

### ~~BUG-91: `EquitySnapshot` model allows duplicate snapshots~~ ✅ FIXED

**Fixed in:** commit (BUG-91). Added `UniqueConstraint("session_id", "timestamp")` to EquitySnapshot model + Alembic migration 003.

### ~~BUG-92: Backtest equity curve rounded to 2 decimals~~ ✅ FIXED

**Fixed in:** commit (BUG-92). Changed equity curve snapshot rounding from 2 to 6 decimal places. ~16,000x reduction in cumulative rounding error over long backtests.

### BUG-93: `MarketCalendar` constructor doesn't validate exchange parameter

**File:** `shared/market_calendar.py` — Lines 51–53 — New exchanges default to equity hours silently.

### BUG-94: Pydantic models allow negative prices/volumes/quantities

**File:** `shared/schemas.py` — Multiple — No `Field(gt=0)` constraints.

### BUG-95: Backtest `start_date`/`end_date` empty strings if no data

**File:** `backtest/engine.py` — Lines 416–420 — Should use "N/A" or raise.

### BUG-96: Default strategy path not validated at module load

**File:** `session/manager.py` — Line 56 — If file deleted, empty strategy code with no warning.

### BUG-97: No timeout on collector stop in `stop_session()`

**File:** `session/manager.py` — Line 315 — Hung collector blocks entire session stop.

### BUG-98: Session status not atomic with pipeline state

**File:** `session/manager.py` — Lines 281, 300 — DB write failure leaves pipeline running but DB says stopped.

### BUG-99: Duplicate symbols in session config not detected

**File:** `session/manager.py` — Line 254 — Causes array index confusion in price tracking.

### BUG-100: `_publish_log()` silently swallows all errors at debug level

**File:** `session/manager.py` — Lines 816–829 — Loss of observability in production.

### BUG-101: Sharpe ratio 0.0 ambiguous for zero-volatility returns

**File:** `backtest/engine.py` — Lines 441–445 — Can't distinguish "no returns" from "flat positive returns".

### BUG-102: Alpaca missing credentials silently skipped per fetch

**File:** `data/sources/alpaca_source.py` — Lines 44–46 — Session runs with degraded data, no clear indication.

---

## PREVIOUSLY FIXED (BUG-14 through BUG-43)

All items from the 2026-03-26 audit have been fixed. See `DONE.md` for details.
