# Fix Plan — Execution Order

> Work through items top-to-bottom. Move each to `DONE.md` after fix + push.

## Phase 1: Showstoppers (can't trade without these)
1. **BUG-2** — OrderRequest metadata crash (every rebalance fails)
2. **BUG-3** — Position size risk check is a no-op
3. **ARCH-1** — DB password URL encoding (breaks on special chars)

## Phase 2: Correctness (wrong behavior)
4. **BUG-4** — Router false "FILLED" logs
5. **BUG-5** — Backtest missing `close` mapping
6. **BUG-6** — Reconciler broken in multi-session
7. **ERR-1** — Risk manager silent stale data
8. **CONC-1** — SimAdapter race condition

## Phase 3: Code health (clean up dead weight)
9. **CQ-1** — Duplicate ValidationResult
10. **CQ-3** — Dead code custom_data.py
11. **CQ-4** — Type hint fix
12. **CQ-5** — Remove dead RiskManager class
13. **ERR-2** — Silent exception swallowing
14. **ERR-3** — get_session_info DB error
15. **ERR-4** — yfinance fast_info defensive check

## Phase 4: Performance
16. **PERF-1** — yfinance N+1 calls
17. **PERF-2** — Binance N+1 order book
18. **PERF-3** — Eager DB relationship loading
19. **PERF-4** — Auth session cleanup
20. **PERF-5** — Log buffer cleanup

## Phase 5: Security (personal system, lower urgency)
21. **SEC-5** — API keys unmasked in response
22. **SEC-6** — Arbitrary kwargs on update
23. **SEC-7** — Timing-safe password compare
24. **SEC-3** — Hash passwords
25. **SEC-4** — Secure cookie flag
26. **SEC-1/SEC-2** — Sandbox hardening (big effort, low ROI for personal use)

## Phase 6: Architecture (scaling prep, lowest priority)
27. **ARCH-3** — CSRF
28. **ARCH-4** — Per-session Redis
29. **ARCH-5** — Rate limiting
30. **ARCH-6** — Backtest thread pool
31. **ARCH-7** — Multi-worker globals
32. **CONC-2/3/4** — SSE queues, Redis reconnect, iteration safety
