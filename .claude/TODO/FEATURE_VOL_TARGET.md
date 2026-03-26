# Feature: Volatility Targeting Risk Overlay

> **Priority:** HIGH — Biggest bang for buck in risk-adjusted returns. Without this, a strategy allocating 100% to a volatile asset gets wiped out on a bad day.

---

## Problem

Strategy `main(data)` returns raw target weights (e.g., `[0.5, 0.3, 0.2]`). These weights go straight to the rebalancer with no adjustment for how volatile the underlying assets are.

Example: a strategy returns `[0.5, 0.5]` for BTC and ETH. If BTC annualized vol is 80% and ETH is 60%, the portfolio's realized volatility is ~50%+ — way beyond what most risk budgets allow. The strategy has no way to say "I want 10% annualized vol."

---

## Design

### Concept: Volatility Scaling

The vol-targeting overlay sits **between** the strategy output and the rebalancer. It does one thing:

```
scaled_weights = raw_weights * (target_vol / realized_vol)
```

Where:
- `target_vol` — user-configured (e.g., 0.10 = 10% annualized)
- `realized_vol` — computed from recent price returns in the data snapshot
- The scaling is applied to the **gross exposure** (sum of absolute weights), not individual weights

This means: when the market is calm, exposure stays near 100%. When vol spikes, exposure automatically shrinks. When vol is low, exposure can exceed 100% (leverage) — capped by a configurable max.

### Two Modes

| Mode | Formula | Use Case |
|------|---------|----------|
| `portfolio` | Scale all weights uniformly by `target_vol / portfolio_vol` | Simple, treats portfolio as one unit |
| `per_asset` | Scale each weight by `target_vol / asset_vol[i]` then renormalize | Risk parity-like, equalizes vol contribution per asset |

Default: `portfolio` mode (simpler, more common).

---

## Implementation Plan

### Step 1: `risk/vol_target.py` (NEW FILE)

```python
"""Volatility targeting overlay — scales strategy weights to hit a target vol."""

import numpy as np
import logging

logger = logging.getLogger(__name__)


def compute_realized_vol(
    price_buffer: np.ndarray,
    lookback: int = 20,
    annualization: float = 252.0,
) -> np.ndarray:
    """Compute annualized realized volatility per asset from price buffer.

    Args:
        price_buffer: shape (N_symbols, buffer_length) — recent prices per asset.
        lookback: number of recent returns to use.
        annualization: 252 for daily, 252*6.5*60 for 1-min, etc.

    Returns:
        shape (N_symbols,) — annualized vol per asset. NaN if insufficient data.
    """
    n_symbols = price_buffer.shape[0]
    vols = np.full(n_symbols, np.nan)

    for i in range(n_symbols):
        prices = price_buffer[i]
        # Get last `lookback + 1` non-NaN prices
        valid = prices[~np.isnan(prices)]
        if len(valid) < lookback + 1:
            continue
        recent = valid[-(lookback + 1):]
        returns = np.diff(np.log(recent))  # log returns
        vols[i] = np.std(returns) * np.sqrt(annualization)

    return vols


def compute_portfolio_vol(
    weights: np.ndarray,
    price_buffer: np.ndarray,
    lookback: int = 20,
    annualization: float = 252.0,
) -> float:
    """Compute annualized portfolio volatility from weights and price history.

    Uses simple weighted sum of asset vols (ignores correlations for speed).
    For a more accurate version, use covariance matrix.

    Returns:
        Portfolio vol (annualized). NaN if insufficient data.
    """
    asset_vols = compute_realized_vol(price_buffer, lookback, annualization)
    if np.any(np.isnan(asset_vols)):
        return float("nan")
    return float(np.sum(np.abs(weights) * asset_vols))


def scale_weights_for_vol_target(
    weights: np.ndarray,
    price_buffer: np.ndarray,
    target_vol: float,
    mode: str = "portfolio",
    lookback: int = 20,
    annualization: float = 252.0,
    max_leverage: float = 2.0,
    min_scale: float = 0.1,
) -> np.ndarray:
    """Scale strategy weights to target a specific portfolio volatility.

    Args:
        weights: raw strategy output, shape (N,).
        price_buffer: shape (N, buffer_length) — recent prices.
        target_vol: target annualized vol (e.g., 0.10 for 10%).
        mode: "portfolio" (uniform scaling) or "per_asset" (per-asset scaling).
        lookback: lookback window for vol computation.
        annualization: annualization factor (252 for daily bars).
        max_leverage: cap on gross exposure after scaling.
        min_scale: floor on scale factor to avoid near-zero positions.

    Returns:
        Scaled weights, same shape as input.
    """
    if target_vol <= 0:
        return weights  # disabled

    if np.all(weights == 0):
        return weights  # nothing to scale

    if mode == "per_asset":
        asset_vols = compute_realized_vol(price_buffer, lookback, annualization)
        scaled = weights.copy()
        for i in range(len(weights)):
            if weights[i] == 0 or np.isnan(asset_vols[i]) or asset_vols[i] <= 0:
                continue
            scale = target_vol / asset_vols[i]
            scale = max(scale, min_scale)
            scaled[i] = weights[i] * scale
        # Renormalize so gross exposure doesn't exceed max_leverage
        gross = np.sum(np.abs(scaled))
        if gross > max_leverage:
            scaled *= max_leverage / gross
        return scaled

    else:  # "portfolio" mode
        port_vol = compute_portfolio_vol(weights, price_buffer, lookback, annualization)
        if np.isnan(port_vol) or port_vol <= 0:
            logger.warning("Cannot compute portfolio vol — skipping vol targeting")
            return weights
        scale = target_vol / port_vol
        scale = max(scale, min_scale)
        scale = min(scale, max_leverage / max(np.sum(np.abs(weights)), 1e-9))
        return weights * scale
```

### Step 2: Config

**`config/default.yaml` — Add under `risk:`:**
```yaml
risk:
  # ... existing keys ...
  vol_target:
    enabled: false
    target_pct: 0.10          # 10% annualized
    mode: "portfolio"         # "portfolio" or "per_asset"
    lookback: 20              # bars of returns
    max_leverage: 2.0         # max gross exposure after scaling
    min_scale: 0.1            # floor on scale factor
```

### Step 3: Wire into Live Pipeline

**`session/manager.py` — `_run_strategy_cycle()` (between risk check and rebalance):**

Current flow (lines ~520-528):
```python
# 4. Risk check ... (existing)

# 5. Generate rebalancing orders
orders = pipeline.rebalancer.rebalance(...)
```

Insert between steps 4 and 5:
```python
# 4b. Volatility targeting overlay
vol_cfg = self._config.get("risk", {}).get("vol_target", {})
if vol_cfg.get("enabled", False):
    from risk.vol_target import scale_weights_for_vol_target
    # Get price buffer from data_snapshot
    price_buffer = data_snapshot.get("price")  # shape (N, lookback)
    if price_buffer is not None:
        # Determine annualization factor from resolution
        resolution_seconds = pipeline.collector.resolution.seconds if pipeline.collector else 60
        bars_per_year = (252 * 6.5 * 3600) / resolution_seconds  # trading seconds per year
        weights = scale_weights_for_vol_target(
            weights=weights,
            price_buffer=price_buffer,
            target_vol=vol_cfg.get("target_pct", 0.10),
            mode=vol_cfg.get("mode", "portfolio"),
            lookback=vol_cfg.get("lookback", 20),
            annualization=bars_per_year,
            max_leverage=vol_cfg.get("max_leverage", 2.0),
            min_scale=vol_cfg.get("min_scale", 0.1),
        )
        await self._publish_log(
            sid, "vol_target",
            f"Vol-targeted weights: {weights.tolist()}",
            metadata={"scaled_weights": weights.tolist()},
        )
```

### Step 4: Wire into Backtest

**`backtest/engine.py` — in the strategy execution block (line ~540):**

Current:
```python
weights = executor.execute(snapshot)
new_trades = portfolio.rebalance(weights, date_str)
```

New:
```python
weights = executor.execute(snapshot)

# Vol targeting overlay
if vol_target_cfg and vol_target_cfg.get("enabled", False):
    from risk.vol_target import scale_weights_for_vol_target
    price_buf = snapshot.get("price")
    if price_buf is not None:
        weights = scale_weights_for_vol_target(
            weights=weights,
            price_buffer=price_buf,
            target_vol=vol_target_cfg.get("target_pct", 0.10),
            mode=vol_target_cfg.get("mode", "portfolio"),
            lookback=vol_target_cfg.get("lookback", 20),
            annualization=annualization_factor,
            max_leverage=vol_target_cfg.get("max_leverage", 2.0),
        )

new_trades = portfolio.rebalance(weights, date_str)
```

**`run_backtest()` signature change:**
```python
def run_backtest(
    ...,
    vol_target_config: dict | None = None,  # NEW
) -> BacktestResult:
```

**Annualization factor in backtest:** Derived from `interval` parameter:
```python
annualization_map = {
    "1d": 252, "60m": 252 * 6.5, "30m": 252 * 13,
    "15m": 252 * 26, "5m": 252 * 78, "1m": 252 * 390,
}
annualization_factor = annualization_map.get(interval, 252)
```

### Step 5: API

**`monitoring/backtest.py`:**
- Accept `vol_target` dict in backtest request body, pass to `run_backtest()`.

**`monitoring/sessions.py`:**
- No change needed — vol target config comes from `config/default.yaml`, not per-session. (Could make per-session later via `config_json`.)

### Step 6: Backtest Metrics Enhancement

Add to `_compute_metrics()`:
- `annualized_vol` — realized portfolio vol from equity curve
- `sharpe_ratio` — `(annualized_return - risk_free) / annualized_vol`

These exist independently of vol targeting but make the feature testable.

```python
# In _compute_metrics():
if len(equity_values) > 1:
    returns = np.diff(np.log(equity_values))
    ann_vol = np.std(returns) * np.sqrt(252)
    ann_return = (equity_values[-1] / equity_values[0]) ** (252 / len(returns)) - 1
    metrics.annualized_vol = round(ann_vol * 100, 2)
    metrics.sharpe_ratio = round((ann_return - 0.02) / ann_vol, 2) if ann_vol > 0 else 0
```

**`BacktestMetrics` dataclass — Add:**
```python
annualized_vol: float = 0.0
sharpe_ratio: float = 0.0
```

---

## File Changes Summary

| File | Change |
|------|--------|
| `risk/vol_target.py` | **NEW** — `compute_realized_vol`, `compute_portfolio_vol`, `scale_weights_for_vol_target` |
| `config/default.yaml` | Add `risk.vol_target` section |
| `session/manager.py` | Insert vol scaling between risk check and rebalance in `_run_strategy_cycle()` |
| `backtest/engine.py` | Insert vol scaling before `portfolio.rebalance()`, add `vol_target_config` param, add Sharpe/vol metrics |
| `monitoring/backtest.py` | Accept `vol_target` in backtest request body |

---

## Testing Plan

1. **Unit test `compute_realized_vol()`:** Known price series → known vol (e.g., constant prices → 0 vol, geometric Brownian → ~target vol)
2. **Unit test `scale_weights_for_vol_target()`:**
   - High-vol market → weights shrink
   - Low-vol market → weights grow (up to max_leverage)
   - Zero weights → stays zero
   - `per_asset` mode: high-vol asset shrinks more than low-vol
3. **Unit test max_leverage cap:** Ensure gross exposure never exceeds `max_leverage`
4. **Backtest integration:** Run same strategy with and without vol targeting, verify annualized vol is closer to target
5. **Sharpe ratio sanity:** Verify calculation against manual computation
