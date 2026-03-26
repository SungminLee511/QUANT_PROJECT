# Fix Plan — Execution Order

> Work through items top-to-bottom. Move each to `DONE.md` after fix + push.

## ~~Round 1 (ALL COMPLETE — items 1-32, see DONE.md)~~

---

## Round 2 — Full Audit (2026-03-26)

### Phase 1: Data Correctness (wrong data → wrong trades)
1. **BUG-14** — `close` field returns yesterday's close across all sources
2. **BUG-15** — Validator ALLOWED_IMPORTS doesn't match executor whitelist
3. **BUG-16** — Partial fill double-counting in PortfolioTracker

### Phase 2: Order/Execution Integrity
4. **BUG-17** — `_persist_order` queries by `external_id=None` (corrupts DB)
5. **BUG-20** — Binance `cancel_order` missing required symbol param
6. **BUG-21** — Alpaca adapter blocks event loop with sync HTTP
7. **BUG-26** — `avg_price` never persisted to DB
8. **BUG-27** — `PnLCalculator.record_close` never called (P&L always 0)

### Phase 3: Session Lifecycle & Infrastructure
9. **BUG-18** — Pipeline leak on `start_session` failure
10. **BUG-19** — `update_session` ignores strategy/data config fields
11. **BUG-22** — Stale PubSub object on Redis reconnect

### Phase 4: Backtest Correctness
12. **BUG-23** — `float("inf")` profit factor breaks JSON
13. **BUG-24** — `day_change_pct` never computed in backtest
14. **BUG-25** — Missing data filled with 0.0 instead of NaN

### Phase 5: Security & Validation
15. **BUG-29** — Custom validator missing `open` in FORBIDDEN_NAMES
16. **BUG-30** — `check_position_size` approves on zero equity

### Phase 6: Config & Minor
17. **BUG-28** — Default strategy file `read_text()` unguarded
18. **BUG-31** — Non-numeric port env var silently passes through
