# Feature: Strategy Mode Selector (Long-Only vs Long-Short)

> **Priority:** HIGH — Fundamental change to how the platform interprets strategy output. Currently the system force-normalizes `sum(|w|) = 1` and caps sells to holdings, making true shorting and cash-holding impossible.

---

## Problem

Today, `executor.execute()` divides all weights by `sum(|w|)`, forcing full capital deployment at all times. The rebalancer then caps sell quantities to current holdings, preventing short positions. This means:

1. **No cash allocation** — The strategy can't say "I only want 30% exposure, hold 70% cash." Weights always sum to 1.
2. **No short selling** — Even if the strategy returns negative weights, the rebalancer won't sell beyond what's owned.
3. **One-size-fits-all normalization** — A momentum strategy wanting to short losers gets the same treatment as a passive long-only allocation.

---

## Design

### New Toggle: `strategy_mode`

Added to `data_config` (alongside `resolution`, `exec_every_n`, `schedule_mode`):

```json
{
  "resolution": "1min",
  "exec_every_n": 1,
  "schedule_mode": "always_on",
  "strategy_mode": "rebalance",
  "short_loss_limit_pct": 1.0,
  ...
}
```

- `strategy_mode` — Two values:
  - `"rebalance"` (default) — Long-only. Weights clamped to `[0, 1]`, sum capped at 1.
  - `"long_short"` — Long and short. Weights in `[-1, 1]`, `sum(|w|)` capped at 1.
- `short_loss_limit_pct` — Only relevant when `strategy_mode == "long_short"`. Default `1.0` (100%). Kill switch fires when any single short position's unrealized loss reaches this % of its entry notional. User-configurable via slider in the Data Config panel (e.g., 0.5 = 50%, 1.0 = 100%, 2.0 = 200%).

### Weight Normalization Rules

#### `rebalance` mode (Long-Only)
```
1. Clamp all negative weights to 0
2. Clamp all weights > 1 to 1
3. If sum(w) > 1: scale down proportionally → w = w / sum(w)
4. If sum(w) <= 1: keep as-is (remainder = cash)
```

Example:
- `main()` returns `[0.3, 0.5, -0.1, 0.1]`
- After clamp negatives: `[0.3, 0.5, 0.0, 0.1]`
- `sum = 0.9 ≤ 1` → keep as-is. 10% held as cash.

Example (over-allocated):
- `main()` returns `[0.6, 0.5, 0.3]`
- `sum = 1.4 > 1` → scale: `[0.429, 0.357, 0.214]`

#### `long_short` mode
```
1. Clamp all weights to [-1, 1]
2. If sum(|w|) > 1: scale down proportionally → w = w / sum(|w|)
3. If sum(|w|) <= 1: keep as-is (remainder = cash)
```

Example:
- `main()` returns `[0.4, -0.3, 0.2]`
- `sum(|w|) = 0.9 ≤ 1` → keep as-is. 10% cash buffer.
- Asset 1: long 40% of equity
- Asset 2: short 30% of equity
- Asset 3: long 20% of equity
- Cash: 10%

Example (over-allocated):
- `main()` returns `[0.5, -0.5, 0.3]`
- `sum(|w|) = 1.3 > 1` → scale: `[0.385, -0.385, 0.231]`

---

## Implementation Plan

### Step 1: Modify `strategy/executor.py` — `execute()`

**Current** (lines ~75-82):
```python
# NORMALIZATION: sum(|w|) = 1
abs_sum = np.sum(np.abs(weights))
if abs_sum > 0:
    weights = weights / abs_sum
else:
    weights = np.zeros(n)
```

**New:**
```python
# Normalize based on strategy mode
if self._strategy_mode == "rebalance":
    # Long-only: clamp negatives, cap sum at 1
    weights = np.clip(weights, 0.0, 1.0)
    weight_sum = np.sum(weights)
    if weight_sum > 1.0:
        weights = weights / weight_sum
else:  # "long_short"
    # Allow negatives, cap sum(|w|) at 1
    weights = np.clip(weights, -1.0, 1.0)
    abs_sum = np.sum(np.abs(weights))
    if abs_sum > 1.0:
        weights = weights / abs_sum
```

**Constructor change:**
```python
def __init__(self, source: str, symbols: list[str], strategy_mode: str = "rebalance"):
    self._strategy_mode = strategy_mode
    ...
```

### Step 2: Modify `strategy/rebalancer.py` — `rebalance()`

**Current** (sell cap logic):
```python
# Cap sell quantity to current position (no naked shorting on SimAdapter)
if side == Side.SELL:
    qty = min(qty, max(current_qty, 0.0))
    if qty * price < MIN_ORDER_VALUE:
        continue
```

**New:**
```python
if side == Side.SELL:
    if self._strategy_mode == "rebalance":
        # Long-only: can't sell more than owned
        qty = min(qty, max(current_qty, 0.0))
        if qty * price < MIN_ORDER_VALUE:
            continue
    # long_short: allow selling beyond holdings (opens short position)
    # Broker handles short mechanics (margin, borrow, etc.)
```

**Constructor change:**
```python
def __init__(self, symbols, exchange, strategy_id, session_id, strategy_mode="rebalance"):
    self._strategy_mode = strategy_mode
    ...
```

### Step 3: Modify `backtest/engine.py` — Portfolio rebalance

The backtest `Portfolio.rebalance()` also caps sells to current holdings. Needs the same mode-aware logic:

**Current:**
```python
# Sell: only what we own
qty = min(qty, max(current_qty, 0.0))
```

**New for `long_short`:**
```python
if self._strategy_mode == "long_short":
    # Allow negative positions (short)
    # qty is the absolute diff; position can go negative
    pass  # No cap — let position go negative
else:
    qty = min(qty, max(current_qty, 0.0))
```

**Short position P&L tracking:**
In backtest, when position is negative (short):
- Selling at price P₁ and buying back at P₂: profit = qty × (P₁ - P₂)
- Equity = cash + sum(position[i] × price[i])
  - For short positions, `position[i] < 0`, so `position[i] × price[i] < 0` (correct: shorts reduce equity when price rises)
- This already works mathematically if we allow negative positions!

### Step 4: Modify `session/manager.py`

**`DEFAULT_DATA_CONFIG`** — Add default:
```python
DEFAULT_DATA_CONFIG = {
    "resolution": "1min",
    "exec_every_n": 1,
    "schedule_mode": "always_on",
    "strategy_mode": "rebalance",    # NEW
    ...
}
```

**`start_session()` / `_start_pipeline()`** — Pass `strategy_mode` to executor and rebalancer:
```python
strategy_mode = data_config.get("strategy_mode", "rebalance")

pipeline.executor = StrategyExecutor(
    source=strategy_source,
    symbols=symbols,
    strategy_mode=strategy_mode,     # NEW
)

pipeline.rebalancer = Rebalancer(
    symbols=symbols,
    exchange=exchange,
    strategy_id=strategy_id,
    session_id=sid,
    strategy_mode=strategy_mode,     # NEW
)
```

### Step 5: Modify `backtest/engine.py` — `run_backtest()`

Pass `strategy_mode` through to executor and portfolio:

```python
def run_backtest(
    ...,
    strategy_mode: str = "rebalance",   # NEW
) -> BacktestResult:
    ...
    executor = StrategyExecutor(source, symbols, strategy_mode=strategy_mode)
    portfolio = Portfolio(symbols, initial_capital, strategy_mode=strategy_mode)
```

### Step 6: Modify `monitoring/backtest.py` — API

Accept `strategy_mode` in backtest request body, pass to `run_backtest()`:

```python
class BacktestRequest(BaseModel):
    ...
    strategy_mode: str = "rebalance"   # NEW

@router.post("/api/backtest")
async def run_backtest_endpoint(req: BacktestRequest):
    ...
    result = run_backtest(
        ...,
        strategy_mode=req.strategy_mode,
    )
```

### Step 7: Modify `monitoring/editor.py` — Frontend Config Panel

The Data Config tab (where `resolution`, `exec_every_n`, `schedule_mode` live) gets a new `strategy_mode` dropdown:

```python
# In the data config form builder:
# Add strategy_mode select alongside existing toggles
strategy_mode_options = ["rebalance", "long_short"]
```

### Step 8: Short Position Kill Switch — `risk/limits.py`

When `long_short` mode is active, a per-position kill switch protects against unbounded short losses.

**Config** (in `data_config`, visible only when `strategy_mode == "long_short"`):
```json
{
  "strategy_mode": "long_short",
  "short_loss_limit_pct": 1.0
}
```

- `short_loss_limit_pct`: default `1.0` (100%). Kill switch fires when any single short position's unrealized loss reaches this percentage of its entry notional.
- Example at 1.0 (100%): Short 10 shares at $100 (notional = $1,000). Price hits $200 → loss = $1,000 = 100% of notional → **KILL**.
- Example at 0.5 (50%): Same short. Price hits $150 → loss = $500 = 50% of notional → **KILL**.

**New function in `risk/limits.py`:**
```python
def check_short_loss(
    positions: dict[str, float],       # symbol → qty (negative = short)
    current_prices: dict[str, float],  # symbol → current price
    entry_prices: dict[str, float],    # symbol → price when position was opened
    short_loss_limit_pct: float = 1.0,
) -> tuple[bool, str]:
    """Check if any short position has exceeded its loss limit.

    Returns:
        (True, "") if OK, (False, reason) if kill switch should fire.
    """
    for symbol, qty in positions.items():
        if qty >= 0:
            continue  # Only check shorts

        entry_price = entry_prices.get(symbol)
        current_price = current_prices.get(symbol)
        if entry_price is None or current_price is None or entry_price <= 0:
            continue

        notional = abs(qty) * entry_price
        unrealized_loss = abs(qty) * (current_price - entry_price)  # positive when price rose

        if unrealized_loss <= 0:
            continue  # Short is profitable, no concern

        if unrealized_loss >= notional * short_loss_limit_pct:
            return False, (
                f"Short {symbol}: loss ${unrealized_loss:.0f} "
                f">= {short_loss_limit_pct*100:.0f}% of notional ${notional:.0f} "
                f"(entry={entry_price:.2f}, now={current_price:.2f})"
            )

    return True, ""
```

**Entry price tracking — Live (`session/manager.py`):**

The pipeline needs to track entry prices for short positions. Add to `SessionPipeline`:
```python
@dataclass
class SessionPipeline:
    ...
    short_entry_prices: dict[str, float] = field(default_factory=dict)
```

In `_run_strategy_cycle()`, after orders are filled:
- When a new short position opens (position goes from ≥0 to <0), record `entry_price = current_price`
- When a short position is fully covered (position goes from <0 to ≥0), remove the entry record
- When a short position increases, update entry price as weighted average

Call `check_short_loss()` alongside existing `check_portfolio_risk()`:
```python
# In _run_strategy_cycle(), after risk check:
if strategy_mode == "long_short":
    short_ok, short_reason = check_short_loss(
        positions=current_positions,
        current_prices=prices_dict,
        entry_prices=pipeline.short_entry_prices,
        short_loss_limit_pct=data_config.get("short_loss_limit_pct", 1.0),
    )
    if not short_ok:
        await kill_switch.activate(short_reason)
        weights = np.zeros(len(pipeline.executor.symbols))
```

**Entry price tracking — Backtest (`backtest/engine.py`):**

Same logic in `Portfolio`:
```python
class Portfolio:
    def __init__(self, ...):
        ...
        self.short_entry_prices: dict[str, float] = {}

    def rebalance(self, target_weights, date_str):
        ...
        # After updating position:
        if old_qty >= 0 and new_qty < 0:
            # Opened short
            self.short_entry_prices[symbol] = price
        elif old_qty < 0 and new_qty >= 0:
            # Covered short
            self.short_entry_prices.pop(symbol, None)
```

In backtest loop, call `check_short_loss()` each bar. If triggered → flatten everything, stop.

### Step 9: Backtest Metrics — Short Tracking

Add short-specific metrics to `BacktestMetrics`:

```python
@dataclass
class BacktestMetrics:
    ...
    short_count: int = 0           # Number of short trades
    gross_exposure_avg: float = 0  # Average sum(|w|) — shows leverage usage
```

In the backtest loop, track:
- Count trades where side == SELL and resulting position < 0
- Track `sum(|w|)` each bar and average it

---

## File Changes Summary

| File | Change |
|------|--------|
| `strategy/executor.py` | Mode-aware normalization in `execute()`, new `strategy_mode` param |
| `strategy/rebalancer.py` | Mode-aware sell cap in `rebalance()`, new `strategy_mode` param |
| `backtest/engine.py` | Allow negative positions in portfolio, pass `strategy_mode` through, short entry tracking, kill switch check, add short metrics |
| `session/manager.py` | Add `strategy_mode` + `short_loss_limit_pct` to `DEFAULT_DATA_CONFIG`, pass to executor + rebalancer, short entry price tracking, call `check_short_loss()` |
| `risk/limits.py` | New `check_short_loss()` function for per-position short loss kill switch |
| `monitoring/backtest.py` | Accept `strategy_mode` + `short_loss_limit_pct` in backtest request |
| `monitoring/editor.py` | Add `strategy_mode` dropdown + conditional `short_loss_limit_pct` slider to Data Config panel |

---

## Testing Plan

### Unit Tests (`tests/test_strategy/test_executor.py`)

1. **`rebalance` mode — clamp negatives:** `main()` returns `[0.5, -0.3, 0.2]` → executor returns `[0.5, 0.0, 0.2]` (negative clamped, sum=0.7 ≤ 1, kept as-is)
2. **`rebalance` mode — cap sum:** `main()` returns `[0.6, 0.5, 0.3]` → executor scales to sum=1: `[0.429, 0.357, 0.214]`
3. **`rebalance` mode — cash holding:** `main()` returns `[0.3, 0.2]` → `[0.3, 0.2]` (sum=0.5, 50% cash)
4. **`long_short` mode — keep negatives:** `main()` returns `[0.4, -0.3, 0.2]` → `[0.4, -0.3, 0.2]` (sum|w|=0.9 ≤ 1)
5. **`long_short` mode — cap abs sum:** `main()` returns `[0.5, -0.5, 0.3]` → scaled to sum|w|=1
6. **`long_short` mode — cash holding:** `main()` returns `[0.3, -0.2]` → `[0.3, -0.2]` (sum|w|=0.5, 50% cash)

### Unit Tests (`tests/test_strategy/test_rebalancer.py`)

7. **`rebalance` mode — sell capped:** Can't sell more than owned (existing behavior preserved)
8. **`long_short` mode — short opens:** Weight = -0.3, no current position → SELL order created (opens short)
9. **`long_short` mode — increase short:** Weight = -0.5, current position = -10 shares → additional SELL order

### Unit Tests — Short Kill Switch (`tests/test_risk/test_limits.py`)

10. **No shorts → OK:** All positions positive, `check_short_loss()` returns `(True, "")`
11. **Short profitable → OK:** Short at $100, now $80 → no loss → `(True, "")`
12. **Short loss under limit → OK:** Short at $100, now $140 → loss=40% < 100% → `(True, "")`
13. **Short loss at limit → KILL:** Short at $100, now $200 → loss=100% = limit → `(False, reason)`
14. **Short loss over limit → KILL:** Short at $100, now $250 → loss=150% > 100% → `(False, reason)`
15. **Custom limit 50% → KILL at 50%:** `short_loss_limit_pct=0.5`, short at $100, now $150 → `(False, reason)`
16. **Multiple shorts, one bad → KILL:** Two shorts, one profitable one at limit → `(False, reason)` for the bad one

### Backtest Tests (`tests/test_backtest/`)

17. **Long-only backtest:** `rebalance` mode, strategy returns negatives → ignored, results same as all-positive
18. **Long-short backtest:** Negative position tracked, equity correct: `cash + sum(pos * price)` where pos can be negative
19. **Short P&L:** Short at $100, price drops to $90 → profit = qty × $10
20. **Short P&L loss:** Short at $100, price rises to $110 → loss = qty × $10
21. **Cash allocation:** Weights sum to 0.6 → 40% stays cash, equity = cash + positions
22. **Short kill switch in backtest:** Short position hits limit → backtest stops, all positions flattened

---

## Edge Cases & Gotchas

1. **Binance doesn't support shorting** — For crypto sessions on Binance, `long_short` mode should be rejected at session creation or automatically fall back to `rebalance`. Add validation in `start_session()`.

2. **Margin requirements** — Real short selling requires margin. The platform doesn't model margin. For live trading, the broker (Alpaca) handles margin. For backtest, we assume unlimited shorting ability (no margin call simulation). Document this limitation.

3. **Short + liquidation interaction** — When `schedule_mode = "market_hours_liquidate"`, the liquidation logic zeros all positions. For shorts, "zero" means buy-to-cover. The existing liquidation code (`_liquidate_session`) already generates zero-weight rebalance orders, which should work — but needs testing.

4. **Kill switch + shorts** — When risk limits trigger, weights go to zero. The rebalancer must close both long AND short positions. Current kill switch logic sets `weights = np.zeros(N)` which should work if the rebalancer correctly handles covering shorts.

5. **Division by zero** — If all weights are zero after clamping (e.g., `rebalance` mode and strategy returns all negatives), return zero weights (100% cash). Already handled.

6. **Backward compatibility** — Default is `"rebalance"`, which matches the existing long-only behavior. Existing sessions/strategies unaffected.
