# Bugs — Open Issues

> Full audit: 2026-03-27. Covers session, execution, strategy, data, portfolio, risk, backtest, DB, shared.

---

## CRITICAL

### ~~BUG-44: Redis client null dereference on early disconnect~~ ✅ FIXED

**Fixed in:** commit 75a49c3. Added null guards on all Redis operations.

---

### ~~BUG-45: DB session null reference in `init_db()`~~ ✅ FIXED

**Fixed in:** commit 756778b. Added null guard on `_engine`.

---

### ~~BUG-46: Market calendar returns invalid results for years beyond 2027~~ ✅ FIXED

**Fixed in:** commit eeacd22. Extended holidays to 2030, added warning for missing years.

---

### ~~BUG-47: Backtest silently skips early bars when lookback isn't filled~~ ✅ FIXED

**Fixed in:** commit 06a35bd. Logs warmup phase when backtest skips early bars.

---

### ~~BUG-48: Unguarded index access in `_run_strategy_cycle()`~~ ✅ FIXED

**Fixed in:** commit 8fa3944. Added array length validation before index access.

---

### ~~BUG-49: Race condition — `del self._pipelines[session_id]` in `stop_session()`~~ ✅ FIXED

**Fixed in:** commit d09c426. Uses `.pop()` consistently instead of `del`.

---

### ~~BUG-50: NaN propagation in `momentum_v2.py` silently zeros out all weights~~ ✅ FIXED

**Fixed in:** commit 6ac3055. Added NaN handling in default momentum strategy.

---

### ~~BUG-51: Binance `fetch_history()` unchecked kline array indexing~~ ✅ FIXED

**Fixed in:** commit cdb01cd. Added kline array length validation.

---

### ~~BUG-52: Binance `_fetch_book()` empty orderbook array crash~~ ✅ FIXED

**Fixed in:** commit cdb01cd. Added proper empty list checks for orderbook data.

---

### ~~BUG-53: Zero/negative prices silently skipped in rebalancer~~ ✅ FIXED

**Fixed in:** commit d91757c. Rebalancer validates equity and prices with logging.

---

## HIGH

### ~~BUG-54: Negative/zero `total_equity` not validated in rebalancer~~ ✅ FIXED

**Fixed in:** commit d91757c. Returns empty orders and logs error for non-positive equity.

---

### ~~BUG-55: Router publishes unfilled OrderUpdate immediately after `place_order`~~ ✅ FIXED

**Fixed in:** commit 488d1df (BUG-58). Added immediate status query after `place_order` (router.py lines 124-138). Market orders that fill instantly are detected before publishing the OrderUpdate.

---

### ~~BUG-56: SimAdapter BUY with zero clipped quantity~~ ✅ FIXED

**Fixed in:** commit 4ae59f1. Rejects dust quantities below 0.0001 threshold.

---

### ~~BUG-57: Binance adapter silent cancel failure~~ ✅ FIXED

**Fixed in:** commit 4351c33. Raises exception instead of returning False.

---

### ~~BUG-58: Router `_persist_order` misuses `external_id` for failed orders~~ ✅ FIXED

**Fixed in:** commit (BUG-58). Added dedicated `order_id` column to Order model + Alembic migration 002. Router now uses `order_id` for lookup and stores `external_id=None` until exchange confirms. Failed orders no longer pollute `external_id`.

---

### ~~BUG-59: Extreme strategy weights overflow to infinity → silent all-zero~~ ✅ FIXED

**Fixed in:** FEATURE_STRATEGY_MODE commit. `np.clip(weights, -1.0, 1.0)` (executor.py line 95/101) applied before any sum/division, preventing overflow. Extreme values clipped to ±1.0 before normalization.

---

### ~~BUG-60: Alpaca adapter `filled_avg_price=None` becomes 0~~ ✅ FIXED

**Fixed in:** commit 6b724dd. Handles None filled_avg_price safely.

---

### ~~BUG-61: Short positions excluded from equity calculation~~ ✅ FIXED

**Fixed in:** commit 0353997. Includes short positions in equity and position queries.

---

### ~~BUG-62: DB commit not explicitly awaited in tracker persistence~~ ✅ FIXED

**Resolution:** `get_session()` context manager (db/session.py line 57) explicitly does `await session.commit()` on normal exit and `await session.rollback()` on exception. All callers use `async with get_session()`, so commit is always awaited. No code change needed — original analysis missed the context manager implementation.

---

### ~~BUG-63: Redis `get_flag()` crashes on malformed JSON~~ ✅ FIXED

**Fixed in:** commit 75a49c3. Added try-except for JSONDecodeError, returns None.

---

### ~~BUG-64: `Order.avg_price` nullable but typed as `float`~~ ✅ FIXED

**Fixed in:** commit ac36890. Changed to `Mapped[float | None]`.

---

### ~~BUG-65: Backfill failure silently ignored — strategy runs on empty buffers~~ ✅ FIXED

**Fixed in:** commit a2c7f71. Tracks and reports backfill failures with proper severity.

---

### ~~BUG-66: Binance VWAP division by zero fallback uses potentially-zero close~~ ✅ FIXED

**Fixed in:** commit cdb01cd. Added chained fallback with warning.

---

### ~~BUG-67: YFinance `_fetch_fast_info_fallback()` percent-change division by zero~~ ✅ FIXED

**Fixed in:** commit 5d18b1e. Uses explicit None check for prev_close.

---

### ~~BUG-68: Position size check uses signal strength instead of actual notional (V1)~~ ✅ FIXED

**Fixed in:** BUG-68 commit. Changed `estimated_value` to `signal.strength * max_pct * total_equity` matching `_signal_to_order()` formula. Previously overestimated by 1/max_pct (10x), wrongly rejecting legitimate signals with strength > 0.10.

---

### ~~BUG-69: Daily loss check mixes realized and unrealized P&L~~ ✅ CLOSED (by design)

**Resolution:** Documented as intentional. Total portfolio drawdown (realized + unrealized) is the standard kill switch metric. Unrealized losses represent real risk exposure. Separating realized-only would require per-fill P&L tracking (feature-level). Added docstring clarification.

---

## MEDIUM

### ~~BUG-70: `avg_entry_price` corruption on short cover~~ ✅ FIXED

**Fixed in:** BUG-36/37 commits. Lines 147-149 zero out both `quantity` and `avg_entry_price` when `abs(pos["quantity"]) <= 0.0001` after short cover. Same guard on SELL side (lines 183-185).

---

### ~~BUG-71: Concurrent position update race in tracker~~ ✅ FIXED

**Fixed in:** CONC-11 commit. `_apply_fill()` runs under `_position_lock` (line 106) and `_persist_position()` is awaited (line 197). Position update + persist is atomic.

---

### ~~BUG-72: Stale price fallback in equity calculations~~ ✅ FIXED

**Fixed in:** commit (BUG-72). Added `_get_price()` helper that logs a one-time warning per symbol when falling back to entry price. Warning clears when fresh price arrives, re-fires if price disappears again.

---

### ~~BUG-73: Kill switch state lost on Redis restart~~ ✅ FIXED

**Fixed in:** BUG-73 commit. Added `KillSwitchEvent` DB model, Alembic migration 004. `KillSwitch.activate()`/`deactivate()` now persist events to DB. `restore_from_db()` called on session startup re-populates Redis if state was lost.

---

### ~~BUG-74: String-based kill switch auto-activation is fragile~~ ✅ FIXED

**Fixed in:** BUG-74 commit. Added `check_id` field to `RiskCheckResult`. `_check_all()` sets structured IDs ("drawdown", "daily_loss", etc.). Kill switch activation now matches on `check_id in {"drawdown", "daily_loss"}` instead of fragile substring search.

---

### ~~BUG-75: Order quantity rounding uses fixed 8 decimals~~ ✅ FIXED

**Fixed in:** BUG-75 commit. Added `round_quantity(qty, exchange)` to `shared/enums.py`. Binance → 6 decimals, Alpaca → 2 decimals. Applied in V1 `_signal_to_order()` and V2 `WeightRebalancer.rebalance()`.

---

### ~~BUG-76: `_signal_to_order()` doesn't validate computed quantity~~ ✅ FIXED

**Fixed in:** commit c2bd2bf (BUG-75). Validates price > 0, equity > 0 before sizing. Rejects dust quantities (<= 0) and caps at 10x intended notional. Returns None with warning log on failure.

---

### ~~BUG-77: Missing portfolio state not detected~~ ✅ FIXED

**Fixed in:** commit (BUG-77). Explicitly checks for `None` return from Redis and logs a one-time warning. Warning clears when state arrives, re-fires if it disappears again.

---

### ~~BUG-78: Custom data shape mismatch in `_append_to_buffer()`~~ ✅ FIXED

**Fixed in:** commit (BUG-78). Added shape validation `values.shape != (expected_rows,)` at top of `_append_to_buffer()`. Mismatched shapes are logged and skipped.

---

### ~~BUG-79: Empty symbol list unchecked in DataCollector~~ ✅ FIXED

**Fixed in:** commit e744e36. Rejects empty symbol list in DataCollector init.

---

### ~~BUG-80: Missing data filled with 0.0 instead of NaN across all sources~~ ✅ FIXED

**Fixed in:** commit (BUG-80). All three sources now use `np.nan` for missing price/OHLC/VWAP fields. Volume and trade counts remain 0 (valid default). Covers initial arrays, per-item parsing, fundamentals, and history.

---

### ~~BUG-81: Binance thread pool exceptions swallowed — partial fills silent~~ ✅ FIXED

**Fixed in:** commit 70bfdf0. Counts and reports failed orderbook fetches.

---

### ~~BUG-82: Alpaca malformed bars silently return zeros~~ ✅ FIXED

**Fixed in:** commit f8e5ee4. Uses NaN instead of 0 for missing OHLC data.

---

### ~~BUG-83: `OrderRequest.price` not validated for LIMIT orders~~ ✅ FIXED

**Fixed in:** commit 91bc29f. Added Pydantic model_validator for LIMIT price.

---

### ~~BUG-84: Trade model missing unique constraint on `(session_id, order_id)`~~ ✅ FIXED

**Fixed in:** commit 2666e5d. Added unique constraint.

---

### ~~BUG-85: Redis listener task not cancelled on reconnect~~ ✅ FIXED

**Fixed in:** commit (BUG-22). `_listen()` recreates PubSub and re-subscribes within the same task loop, so old listener naturally exits. `_listener_task` tracked at instance level and properly awaited in `disconnect()`.

---

### ~~BUG-86: No API retry logic or rate-limit handling across all data sources~~ ✅ FIXED

**Fixed in:** BUG-86 commit. Added `data/sources/retry.py` with `retry_request()` — exponential backoff, 429 Retry-After handling, 5xx retry. Applied to all Alpaca and Binance HTTP calls. yfinance `yf.download()` wrapped with retry-on-empty loop.

---

### ~~BUG-87: Unsupported resolution silently defaults to 1d in yfinance~~ ✅ FIXED

**Fixed in:** commit 1e1d24d. Rejects unsupported resolutions instead of defaulting.

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

### ~~BUG-93: `MarketCalendar` constructor doesn't validate exchange parameter~~ ✅ FIXED

**Fixed in:** commit 917e5c9. Warns on unknown exchange in constructor.

### ~~BUG-94: Pydantic models allow negative prices/volumes/quantities~~ ✅ FIXED

**Fixed in:** commit (BUG-94). Added `Field(gt=0)` for prices, `Field(ge=0)` for volumes/quantities on MarketTick, OHLCVBar, and OrderUpdate.

### ~~BUG-95: Backtest `start_date`/`end_date` empty strings if no data~~ ✅ FIXED

**Fixed in:** commit (BUG-95). Default changed from `""` to `"N/A"`. Single-point curves now set both dates. Empty curves retain `"N/A"`.

### ~~BUG-96: Default strategy path not validated at module load~~ ✅ FIXED

**Fixed in:** BUG-96/97/ERR-5 commit. Logs warning if default strategy file missing.

### ~~BUG-97: No timeout on collector stop in `stop_session()`~~ ✅ FIXED

**Fixed in:** BUG-96/97/ERR-5 commit. Added 10s timeout on collector stop.

### ~~BUG-98: Session status not atomic with pipeline state~~ ✅ FIXED

**Fixed in:** BUG-98/100 commit. Resilient status update with try-except.

### ~~BUG-99: Duplicate symbols in session config not detected~~ ✅ FIXED

**Fixed in:** VAL-1 commit. Symbol list is deduplicated while preserving order in `start_session()`.

### ~~BUG-100: `_publish_log()` silently swallows all errors at debug level~~ ✅ FIXED

**Fixed in:** BUG-98/100 commit. Changed to WARNING level for publish failures.

### ~~BUG-101: Sharpe ratio 0.0 ambiguous for zero-volatility returns~~ ✅ FIXED

**Fixed in:** commit (BUG-101). Default `None` (not computable), `0.0` (zero return), `inf`/`-inf` (zero-vol positive/negative). `to_dict()` converts inf to ∞ for JSON.

### ~~BUG-102: Alpaca missing credentials silently skipped per fetch~~ ✅ FIXED

**Fixed in:** commit (BUG-102). Constructor warns on init. Per-fetch warning fires once then suppresses via `_warned_no_creds` flag.

---

## PREVIOUSLY FIXED (BUG-14 through BUG-43)

All items from the 2026-03-26 audit have been fixed. See `DONE.md` for details.
