# Fix Plan — Execution Order

> Work through items top-to-bottom. Move each to `DONE.md` after fix + push.

## ~~Round 1 (ALL COMPLETE — items 1-32, see DONE.md)~~

---

## ~~Round 2 — ALL COMPLETE (BUG-14 through BUG-31)~~

---

## ~~Round 3 — ALL COMPLETE (BUG-32 through BUG-43)~~

---

## Round 4 — Features

> Build order: Calendar first (correctness fix), then Vol Target (risk), then Tx Cost (accuracy).
> Detailed implementation plans in separate files.

### Feature 1: Market Calendar + Session Scheduling — HIGH
**Plan:** [`FEATURE_MARKET_CALENDAR.md`](FEATURE_MARKET_CALENDAR.md)

### Feature 2: Volatility Targeting Risk Overlay — HIGH
**Plan:** [`FEATURE_VOL_TARGET.md`](FEATURE_VOL_TARGET.md)

### Feature 3: Transaction Cost Model — MEDIUM
**Plan:** [`FEATURE_TX_COST.md`](FEATURE_TX_COST.md)

### Feature 4: Strategy Mode — Long/Short Support — HIGH
**Plan:** [`FEATURE_STRATEGY_MODE.md`](FEATURE_STRATEGY_MODE.md)

---

## Round 5 — Full Audit (2026-03-27)

> 59 new issues found across all modules. Organized by fix priority.
> Detailed issues in category files below.

### TODO File Summary

| File | Contents | Critical | High | Medium | Low |
|------|----------|----------|------|--------|-----|
| [`BUGS.md`](BUGS.md) | Logic errors, crashes, edge cases | 10 | 16 | 13 | 12 |
| [`SECURITY.md`](SECURITY.md) | XSS, input validation, auth gaps | 1 | 3 | 4 | 3 |
| [`CONCURRENCY.md`](CONCURRENCY.md) | Race conditions, task lifecycle | 0 | 2 | 5 | 0 |
| [`PERFORMANCE.md`](PERFORMANCE.md) | Error handling, retries, timeouts | 0 | 0 | 8 | 2 |
| [`CODE_QUALITY.md`](CODE_QUALITY.md) | Validation, schema, observability | 0 | 0 | 6 | 5 |

### Phase 1: Critical Crashes (fix first — these can crash the server)

| # | ID | File | Issue |
|---|-----|------|-------|
| 1 | BUG-44 | `shared/redis_client.py` | Redis client null dereference on disconnect |
| 2 | BUG-45 | `db/session.py` | DB engine null reference in `init_db()` |
| 3 | BUG-48 | `session/manager.py` | Unguarded index access in `_run_strategy_cycle()` |
| 4 | BUG-49 | `session/manager.py` | `del _pipelines[sid]` KeyError on double stop |
| 5 | BUG-51 | `data/sources/binance_source.py` | Unchecked kline array indexing |
| 6 | BUG-52 | `data/sources/binance_source.py` | Empty orderbook crash |
| 7 | BUG-63 | `shared/redis_client.py` | `get_flag()` crashes on malformed JSON |

### Phase 2: Data Correctness (wrong data → wrong trades)

| # | ID | File | Issue |
|---|-----|------|-------|
| 8 | BUG-46 | `shared/market_calendar.py` | Holidays missing for 2028+ |
| 9 | BUG-47 | `backtest/engine.py` | Early bars silently skipped |
| 10 | BUG-50 | `strategy/examples/momentum_v2.py` | NaN propagation zeros all weights |
| 11 | BUG-80 | all sources | Missing data → 0.0 instead of NaN |
| 12 | BUG-82 | `data/sources/alpaca_source.py` | Malformed bars → silent zeros |
| 13 | BUG-87 | `data/sources/yfinance_source.py` | Unsupported resolution defaults to 1d |
| 14 | BUG-66 | `data/sources/binance_source.py` | VWAP division by zero |
| 15 | BUG-67 | `data/sources/yfinance_source.py` | Percent-change division by zero |

### Phase 3: Execution & Portfolio Integrity

| # | ID | File | Issue |
|---|-----|------|-------|
| 16 | BUG-53 | `strategy/rebalancer.py` | Zero price silently skipped |
| 17 | BUG-54 | `strategy/rebalancer.py` | Negative equity not validated |
| 18 | BUG-55 | `execution/router.py` | Premature unfilled OrderUpdate |
| 19 | BUG-57 | `execution/binance_adapter.py` | Silent cancel failure |
| 20 | BUG-60 | `execution/alpaca_adapter.py` | `filled_avg_price=None` → 0 |
| 21 | BUG-61 | `portfolio/tracker.py` | Short positions excluded from equity |
| 22 | BUG-62 | `portfolio/tracker.py` | DB commit not explicitly awaited |
| 23 | CONC-5 | `session/manager.py` | Unguarded sim_adapter._positions access |

### Phase 4: Security

| # | ID | File | Issue |
|---|-----|------|-------|
| 24 | SEC-3 | `monitoring/templates/logs.html` | XSS — unescaped source/symbol |
| 25 | SEC-4 | `monitoring/templates/dashboard.html` | XSS — unescaped table fields |
| 26 | SEC-5 | `monitoring/templates/editor.html` | XSS via innerHTML |
| 27 | SEC-6 | `monitoring/dashboard.py` | No session ownership validation |

### Phase 5: Resilience & Error Handling

| # | ID | File | Issue |
|---|-----|------|-------|
| 28 | BUG-65 | `data/collector.py` | Backfill failure silently ignored |
| 29 | BUG-81 | `data/sources/binance_source.py` | Thread exceptions swallowed |
| 30 | BUG-86 | all sources | No retry/rate-limit handling |
| 31 | ERR-2 | `session/manager.py` | JSON deserialization unguarded |
| 32 | ERR-3 | `session/manager.py` | Strategy load failure not caught |
| 33 | CONC-6 | `session/manager.py` | Task cancellation swallows all exceptions |

### Phase 6: Concurrency & Lifecycle

| # | ID | File | Issue |
|---|-----|------|-------|
| 34 | BUG-73 | `risk/kill_switch.py` | Kill switch state lost on Redis restart |
| 35 | BUG-85 | `shared/redis_client.py` | Listener task not cancelled on reconnect |
| 36 | CONC-7 | `risk/kill_switch.py` | Check-then-act race |
| 37 | CONC-10 | `session/manager.py` | 30s sleep delays shutdown |
| 38 | CONC-11 | `portfolio/tracker.py` | Position update + persist not atomic |

### Phase 7: Schema, Validation & Code Quality (low urgency)

| # | ID | File | Issue |
|---|-----|------|-------|
| 39 | BUG-64 | `db/models.py` | `avg_price` nullable vs typed float |
| 40 | BUG-83 | `shared/schemas.py` | LIMIT order price not validated |
| 41 | BUG-84 | `db/models.py` | Missing unique constraint on trades |
| 42 | VAL-1 | `session/manager.py` | No symbol list validation |
| 43 | ARCH-8 | multiple | Multiple sources of truth for portfolio |
| 44+ | Various | Various | Remaining LOW items (see individual files) |
