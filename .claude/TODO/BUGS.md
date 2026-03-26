# Bugs — Open Issues

> Full audit: 2026-03-26. Covers all directories (data, strategy, execution, portfolio, session, monitoring, shared, db, backtest).

---

## ~~BUG-14: `close` field returns yesterday's close across all sources — FIXED~~

---

## ~~BUG-15: Validator ALLOWED_IMPORTS doesn't match executor _IMPORT_WHITELIST — FIXED~~

---

## ~~BUG-16: Partial fill double-counting in PortfolioTracker — FIXED~~

---

## ~~BUG-17: `_persist_order` queries by `external_id=None` for failed orders — FIXED~~

---

## ~~BUG-18: Pipeline leak on `start_session` failure — FIXED~~

---

## ~~BUG-19: `update_session` silently ignores `strategy_code`, `data_config`, `custom_data_code` — FIXED~~

---

## ~~BUG-20: Binance `cancel_order` missing required `symbol` parameter — FIXED~~

---

## ~~BUG-21: Alpaca adapter blocks event loop with synchronous HTTP calls — FIXED~~

---

## ~~BUG-22: Stale PubSub object reused after Redis connection failure — FIXED~~

---

## ~~BUG-23: `float("inf")` profit factor breaks JSON serialization — FIXED~~

---

## ~~BUG-24: Backtest `day_change_pct` field never computed — FIXED~~

---

## ~~BUG-25: Backtest fills missing data with 0.0 instead of NaN — FIXED~~

---

## ~~BUG-26: `avg_price` never persisted to DB on order updates — FIXED (with BUG-17)~~

---

## ~~BUG-27: `PnLCalculator.record_close` never called — realized P&L always 0 — FIXED~~

---

## ~~BUG-28: Default strategy file `read_text()` unguarded — FIXED~~

---

## ~~BUG-29: Custom data validator missing `open` in FORBIDDEN_NAMES — FIXED~~

---

## ~~BUG-30: `check_position_size` approves on zero/negative equity — FIXED~~

---

## ~~BUG-31: Non-numeric port env var silently passes through as string — FIXED~~

---

## ~~BUG-32: Infinite recursion in `_read_default_strategy()` — FIXED~~

---

## ~~BUG-33: `day_change_pct` backfilled as repeated constant in `yfinance_source.fetch_history` — FIXED~~

---

## ~~BUG-34: Backtest rebalance processes buys before sells, causing cash starvation — FIXED~~

---

## ~~BUG-35: Equity endpoint crashes — `_Proxy` blocks private attribute access — FIXED~~

---

## ~~BUG-36: PortfolioTracker zeroes out short positions immediately — FIXED~~

---

## ~~BUG-37: PortfolioTracker corrupts P&L and avg_entry_price on short trades — FIXED~~

---

## ~~BUG-38: SimulationAdapter.get_positions() hides short positions — FIXED~~

---

## ~~BUG-39: SimulationAdapter short cover path skips cash sufficiency check — FIXED~~

---

## ~~BUG-40: Backtest _compute_metrics ignores short round-trips in win/loss analysis — FIXED~~

---

## ~~BUG-41: validator_v2 crashes on malformed custom_data entries — FIXED~~

---

## BUG-42: Binance day_change_pct inconsistent between live and historical

- **Severity:** MEDIUM
- **File:** `data/sources/binance_source.py` lines 84 vs 232-236
- **Description:** Live `fetch()` returns Binance's `priceChangePercent` (24hr rolling change). Historical `fetch_history()` computes `(close-open)/open*100` (intra-bar change). Strategy sees a discontinuity at the backfill-to-live boundary. yfinance_source uses bar-over-bar close change — yet another definition.
- **Fix:** Align historical to bar-over-bar close change to match yfinance behavior.
