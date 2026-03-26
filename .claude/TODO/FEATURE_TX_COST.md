# Feature: Transaction Cost Model

> **Priority:** MEDIUM — Without this, backtests overstate returns and the rebalancer churns on tiny adjustments that cost more than they're worth.

---

## Problem

Three gaps:

1. **Backtest overstates returns:** No commission or slippage applied. A strategy that trades every bar looks profitable in backtest but bleeds fees in reality.
2. **Sim adapter overstates returns:** Same issue for paper trading. SimulationAdapter adds/deducts exact `price * qty` with zero friction.
3. **Rebalancer churns:** The skip threshold is a flat `$1.00`. A rebalance of $5 on a 10bps-fee asset costs $0.005 — fine. But a rebalance of $5 with 10bps slippage on an illiquid asset costs more. No cost-awareness in the decision.

---

## Design

### Cost Components

| Component | What it models | Typical values |
|-----------|---------------|----------------|
| **Commission** | Exchange fee per trade | Binance: 10bps (0.1%), Alpaca: 0 (commission-free) |
| **Slippage** | Market impact + bid-ask spread | 1-10bps for liquid assets, more for illiquid |

Both are applied as a percentage of trade value: `cost = trade_value * (commission_rate + slippage_bps / 10000)`.

### Where Costs Are Applied

| Context | Where | What changes |
|---------|-------|-------------|
| **Backtest** | `_VirtualPortfolio.rebalance()` | Cash adjusted by `cost` after each trade |
| **Sim Adapter** | `SimulationAdapter.place_order()` | Cash adjusted by `cost` after each fill |
| **Rebalancer** | `WeightRebalancer.rebalance()` | Skip threshold becomes cost-aware |
| **Metrics** | `_compute_metrics()` + `PortfolioTracker` | Total fees tracked and reported |

---

## Implementation Plan

### Step 1: Config

**`config/default.yaml` — Add:**
```yaml
costs:
  enabled: true
  # Per-exchange fee rates (fraction, not bps)
  binance:
    commission: 0.001       # 10 bps maker/taker
    slippage_bps: 2         # 2 bps estimated slippage
  alpaca:
    commission: 0.0         # commission-free
    slippage_bps: 3         # 3 bps estimated slippage
  # Used when exchange-specific config not found
  default:
    commission: 0.001
    slippage_bps: 5
  # Minimum trade value after accounting for costs
  # (replaces the hardcoded $1.00 MIN_ORDER_VALUE)
  min_net_value: 2.0
```

### Step 2: `shared/cost_model.py` (NEW FILE)

Simple, pure functions. No async, no state.

```python
"""Transaction cost model — commission + slippage estimation."""

from shared.enums import Exchange


def get_cost_rates(config: dict, exchange: Exchange) -> tuple[float, float]:
    """Get (commission_rate, slippage_rate) for an exchange.

    Both are fractions (e.g., 0.001 = 10bps).

    Returns:
        (commission_rate, slippage_rate)
    """
    costs_cfg = config.get("costs", {})
    if not costs_cfg.get("enabled", False):
        return 0.0, 0.0

    exchange_cfg = costs_cfg.get(exchange.value, costs_cfg.get("default", {}))
    commission = exchange_cfg.get("commission", 0.001)
    slippage_bps = exchange_cfg.get("slippage_bps", 5)
    return commission, slippage_bps / 10000


def estimate_trade_cost(trade_value: float, commission_rate: float, slippage_rate: float) -> float:
    """Estimate total cost for a trade.

    Args:
        trade_value: absolute dollar value of the trade.
        commission_rate: fraction (e.g., 0.001).
        slippage_rate: fraction (e.g., 0.0005).

    Returns:
        Estimated cost in dollars.
    """
    return abs(trade_value) * (commission_rate + slippage_rate)


def apply_cost_to_fill(
    cash_delta: float,
    trade_value: float,
    commission_rate: float,
    slippage_rate: float,
) -> tuple[float, float]:
    """Adjust a cash change for transaction costs.

    Args:
        cash_delta: raw cash change (negative for buy, positive for sell).
        trade_value: absolute value of the trade.
        commission_rate: fraction.
        slippage_rate: fraction.

    Returns:
        (adjusted_cash_delta, fee_amount)
    """
    fee = estimate_trade_cost(trade_value, commission_rate, slippage_rate)
    # Fees always reduce cash regardless of buy/sell
    return cash_delta - fee, fee
```

### Step 3: SimulationAdapter Integration

**`execution/sim_adapter.py`:**

**Constructor change (line 23):**
```python
def __init__(
    self, session_id, starting_budget, exchange, redis,
    commission_rate: float = 0.0,    # NEW
    slippage_rate: float = 0.0,      # NEW
):
    ...
    self._commission_rate = commission_rate
    self._slippage_rate = slippage_rate
    self._total_fees = 0.0
```

**BUY path (line 88-98) — change:**
```python
# Current:
self._cash -= cost

# New:
from shared.cost_model import apply_cost_to_fill
adjusted_delta, fee = apply_cost_to_fill(-cost, cost, self._commission_rate, self._slippage_rate)
self._cash += adjusted_delta  # adjusted_delta is negative (buy cost + fee)
self._total_fees += fee
```

**SELL path (line 100-110) — change:**
```python
# Current:
self._cash += sell_qty * price

# New:
sell_value = sell_qty * price
adjusted_delta, fee = apply_cost_to_fill(sell_value, sell_value, self._commission_rate, self._slippage_rate)
self._cash += adjusted_delta  # sell_value minus fee
self._total_fees += fee
```

**Store fee in order record (line 114-119):**
```python
self._orders[order_id] = {
    ...,
    "fee": fee,  # NEW — track per-order fee
}
```

**`get_balances()` — include total fees:**
```python
return {
    ...,
    "total_fees": self._total_fees,
}
```

### Step 4: SimAdapter Instantiation

**`session/manager.py` — `_start_pipeline()` (line ~338):**

Current:
```python
sim_adapter = SimulationAdapter(
    session_id=sid,
    starting_budget=starting_budget,
    exchange=exchange,
    redis=self._redis,
)
```

New:
```python
from shared.cost_model import get_cost_rates
commission_rate, slippage_rate = get_cost_rates(self._config, exchange)
sim_adapter = SimulationAdapter(
    session_id=sid,
    starting_budget=starting_budget,
    exchange=exchange,
    redis=self._redis,
    commission_rate=commission_rate,
    slippage_rate=slippage_rate,
)
```

### Step 5: Rebalancer Cost-Aware Skip

**`strategy/rebalancer.py`:**

**Constructor change:**
```python
def __init__(self, session_id, symbols, exchange,
             strategy_id="v2",
             min_net_value: float = 1.0,       # NEW
             commission_rate: float = 0.0,      # NEW
             slippage_rate: float = 0.0):       # NEW
    ...
    self._min_net_value = min_net_value
    self._commission_rate = commission_rate
    self._slippage_rate = slippage_rate
```

**Skip logic (line 76) — change:**
```python
# Current:
if abs(diff_value) < MIN_ORDER_VALUE:
    continue

# New:
from shared.cost_model import estimate_trade_cost
estimated_cost = estimate_trade_cost(
    abs(diff_value), self._commission_rate, self._slippage_rate
)
net_value = abs(diff_value) - estimated_cost
if net_value < self._min_net_value:
    continue  # not worth trading after costs
```

**Rebalancer instantiation in `session/manager.py` `_start_pipeline()` (line ~333):**
```python
costs_cfg = self._config.get("costs", {})
min_net_value = costs_cfg.get("min_net_value", 2.0)
commission_rate, slippage_rate = get_cost_rates(self._config, exchange)
rebalancer = WeightRebalancer(
    sid, symbols, exchange,
    min_net_value=min_net_value,
    commission_rate=commission_rate,
    slippage_rate=slippage_rate,
)
```

### Step 6: Backtest Integration

**`backtest/engine.py` — `_VirtualPortfolio`:**

**Constructor change (line 89):**
```python
def __init__(self, starting_cash, symbols,
             commission_rate: float = 0.0,
             slippage_rate: float = 0.0):
    ...
    self._commission_rate = commission_rate
    self._slippage_rate = slippage_rate
    self.total_fees = 0.0
```

**BUY path (line ~135):**
```python
# Current:
self.cash -= qty * price

# New:
from shared.cost_model import apply_cost_to_fill
trade_value = qty * price
adjusted_delta, fee = apply_cost_to_fill(-trade_value, trade_value, self._commission_rate, self._slippage_rate)
self.cash += adjusted_delta
self.total_fees += fee
```

**SELL path (line ~150):**
```python
# Current:
self.cash += qty * price

# New:
trade_value = qty * price
adjusted_delta, fee = apply_cost_to_fill(trade_value, trade_value, self._commission_rate, self._slippage_rate)
self.cash += adjusted_delta
self.total_fees += fee
```

**`BacktestTrade` dataclass (line 26) — Add:**
```python
fee: float = 0.0
```

**`run_backtest()` signature (line 372):**
```python
def run_backtest(
    ...,
    commission_rate: float = 0.001,   # NEW
    slippage_bps: float = 5.0,        # NEW
) -> BacktestResult:
```

Pass to `_VirtualPortfolio`:
```python
portfolio = _VirtualPortfolio(
    starting_cash, symbols,
    commission_rate=commission_rate,
    slippage_rate=slippage_bps / 10000,
)
```

**`BacktestMetrics` — Add:**
```python
total_fees: float = 0.0
fees_pct: float = 0.0  # total_fees / starting_cash * 100
```

**`_compute_metrics()` — populate:**
```python
metrics.total_fees = round(portfolio.total_fees, 2)
metrics.fees_pct = round(portfolio.total_fees / starting_cash * 100, 2)
```

### Step 7: API

**`monitoring/backtest.py`:**
- Accept `commission_rate` and `slippage_bps` in backtest request body (with defaults from config)
- Pass to `run_backtest()`

**No session API changes needed** — costs come from global config, not per-session.

---

## File Changes Summary

| File | Change |
|------|--------|
| `shared/cost_model.py` | **NEW** — `get_cost_rates`, `estimate_trade_cost`, `apply_cost_to_fill` |
| `config/default.yaml` | Add `costs:` section |
| `execution/sim_adapter.py` | Accept cost rates in constructor, apply fees to BUY/SELL cash changes |
| `session/manager.py` | Pass cost rates when creating SimAdapter and Rebalancer |
| `strategy/rebalancer.py` | Accept cost rates, cost-aware skip threshold |
| `backtest/engine.py` | Accept cost rates, apply fees in `_VirtualPortfolio`, new metrics fields |
| `monitoring/backtest.py` | Accept cost params in backtest API request |

---

## Testing Plan

1. **Unit test `cost_model.py`:**
   - `get_cost_rates` returns correct per-exchange rates
   - `estimate_trade_cost` arithmetic
   - `apply_cost_to_fill` reduces cash for both buys and sells
2. **SimAdapter test:** Buy $1000 of BTC with 10bps commission → cash should decrease by $1001 (not $1000)
3. **Rebalancer skip test:** $3 rebalance with $2 estimated cost and `min_net_value=2.0` → skipped ($1 net < $2 threshold)
4. **Backtest test:** Run strategy with 0 fees vs 100bps fees → verify final equity differs by roughly `n_trades * avg_trade_value * 0.01`
5. **Metrics test:** Verify `total_fees` and `fees_pct` are populated correctly
