# Feature: Transaction Cost Model — COMPLETED

> **Status:** ✅ DONE
> **Priority:** MEDIUM

---

## Summary

Simplified commission model (no slippage) with two modes:

### Sim + Backtest: `commission_pct` data_config toggle
- New `commission_pct` field in `data_config` (default: 0, choices: 0, 0.1, 0.3, 0.5, 1%)
- Applied as `fee = trade_value × (commission_pct / 100)` on every fill
- Fee deducted from cash on both buy and sell
- Tracked as `total_fees` in both SimulationAdapter and BacktestMetrics

### Real Sessions: Broker equity comparison
- New `GET /{session_id}/equity` endpoint
- Sim sessions: returns equity, cash, positions_value, total_fees from SimAdapter
- Real sessions: returns broker_equity (from adapter), computed_equity (from Redis), estimated_fees (difference)
- No commission modeling for real — actual fees are revealed by the equity gap

---

## Files Changed

| File | Change |
|------|--------|
| `backtest/engine.py` | `BacktestTrade.fee`, `BacktestMetrics.total_fees/fees_pct`, `_VirtualPortfolio` commission support |
| `execution/sim_adapter.py` | `commission_pct` constructor param, fee deduction on fills, `total_fees` in balances |
| `session/manager.py` | Passes `commission_pct` from data_config to SimulationAdapter |
| `monitoring/backtest.py` | Extracts `commission_pct` from request, passes to `run_backtest_async()` |
| `monitoring/sessions.py` | New `GET /{session_id}/equity` endpoint |

---

## Design Decisions

1. **No slippage modeling** — slippage is just a worse fill price, not a separate cash deduction. Real sessions get actual fill prices from broker.
2. **No per-exchange hardcoded rates** — user picks commission % via toggle, since Alpaca is free and Binance charges ~0.1%.
3. **No cost-aware rebalancer skip** — deemed unnecessary for now; the flat $1 MIN_ORDER_VALUE is sufficient.
4. **No `shared/cost_model.py`** — the logic is simple enough to inline (one multiplication).
