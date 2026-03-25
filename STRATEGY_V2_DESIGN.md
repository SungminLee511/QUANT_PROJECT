# Strategy System V2 — Design Document

> **Purpose:** Replace the old tick-by-tick BaseStrategy system with a data-config-driven, tensor-based, multi-stock strategy system.

---

## Overview

The new system has **three user-facing steps** per session, all configured in the Strategy Editor page (tabbed UI):

1. **Data Config** (UI form) — choose scrape resolution, select data fields, set lookback per field
2. **Custom Data Functions** (code editor tab) — optional user Python functions for extra data
3. **Strategy Function** (code editor tab) — a `main(data)` function that returns portfolio weights

---

## 1. Data Config

### Scrape Resolution Options

| Resolution | Crypto | Stocks | Implementation |
|---|---|---|---|
| 1min | Yes | Yes | Binance kline WS / yfinance poll |
| 5min | Yes | Yes | Aggregate from 1min or direct |
| 15min | Yes | Yes | Aggregate or direct |
| 30min | Yes | Yes | Aggregate or direct |
| 60min | Yes | Yes | Aggregate or direct |
| 1day | Yes (UTC close) | Yes (5 min before market close) | Daily candle |

### Strategy Execution Multiplier

- User sets an integer `N` (default 1)
- Strategy runs every `N` scrapes
- Effective strategy resolution = scrape_resolution × N
- Example: scrape=1min, N=5 → strategy runs every 5 minutes

### Available Built-in Data Fields

| Field Name | Description | Source |
|---|---|---|
| `price` | Close/last price | Both |
| `open` | Open price of bar | Both |
| `high` | High of bar | Both |
| `low` | Low of bar | Both |
| `volume` | Trade volume | Both |
| `vwap` | Volume-weighted avg price | Both |
| `bid` | Best bid price | Binance only |
| `ask` | Best ask price | Binance only |
| `spread` | ask - bid | Binance only |
| `num_trades` | Number of trades in bar | Binance only |

### Per-Field Lookback

Each selected data field has a user-configured lookback integer:
- Example: `price: 20`, `volume: 10`
- This means the strategy receives `price` as `[N, 20]` and `volume` as `[N, 10]`

### UI Design

```
┌─ Data Configuration ──────────────────────────────────┐
│ Scrape Resolution: [1min ▾]                           │
│ Strategy Runs Every: [1 ▾] scrapes (= 1min)          │
│                                                        │
│ Data Fields:                                           │
│ ☑ price    Lookback: [20]                             │
│ ☑ volume   Lookback: [10]                             │
│ ☐ open     Lookback: [__]                             │
│ ☐ high     Lookback: [__]                             │
│ ☐ low      Lookback: [__]                             │
│ ☑ vwap     Lookback: [5 ]                             │
│ ☐ bid      Lookback: [__]  (crypto only)              │
│ ☐ ask      Lookback: [__]  (crypto only)              │
│ ☐ spread   Lookback: [__]  (crypto only)              │
│ ☐ num_trades Lookback:[__] (crypto only)              │
│                                                        │
│ Custom Data:                                           │
│ [+ Add Custom Per-Stock Data]                          │
│ [+ Add Custom Global Data]                             │
│                                                        │
│ USER_CUSTOM_DATA_1: "put_call_ratio" Lookback: [5]    │
│ USER_CUSTOM_GLOBAL_DATA_1: "vix" Lookback: [10]       │
└────────────────────────────────────────────────────────┘
```

---

## 2. Custom Data Functions

### Per-Stock Custom Data

```python
# Tab: "Custom Data"
# Each custom data block is a named function

# ── USER_CUSTOM_DATA_1: "put_call_ratio" ──
def fetch(tickers: list[str]) -> np.ndarray:
    """
    Called every scrape interval.
    Must return np.ndarray of shape [N] where N = len(tickers).
    Each element is a float for that ticker.
    """
    import requests
    result = []
    for ticker in tickers:
        # user's custom logic
        ratio = ...
        result.append(ratio)
    return np.array(result, dtype=np.float64)
```

### Global Custom Data

```python
# ── USER_CUSTOM_GLOBAL_DATA_1: "vix" ──
def fetch() -> float:
    """
    Called every scrape interval.
    Returns a single float scalar.
    """
    import requests
    # user's custom logic
    return 18.5
```

### Validator for Custom Data Functions

Separate from strategy validator. **Allows:**
- `requests`, `urllib`, `json`, `re`, `time`, `datetime`
- `numpy`, `pandas`
- All safe stdlib (`math`, `statistics`, `collections`, etc.)

**Still blocks:**
- `subprocess`, `os.system`, `eval`, `exec`, `__import__`
- File writes (`open(..., 'w')`)
- `sys.exit`, `importlib`

### Storage

Custom data functions stored in DB as JSON:
```json
{
  "custom_data": [
    {"name": "put_call_ratio", "type": "per_stock", "code": "def fetch(tickers):\n  ..."},
  ],
  "custom_global_data": [
    {"name": "vix", "type": "global", "code": "def fetch():\n  ..."}
  ]
}
```

---

## 3. Strategy Main Function

### Interface

```python
import numpy as np

def main(data: dict[str, np.ndarray]) -> np.ndarray:
    """
    Args:
        data: Dictionary of data arrays. Keys are configured field names.
              Built-in fields: data["price"] shape [N, lookback_price]
                               data["volume"] shape [N, lookback_volume]
              Custom per-stock: data["put_call_ratio"] shape [N, lookback]
              Custom global:   data["vix"] shape [1, lookback] (broadcast-ready)
              Special keys:
                data["tickers"] — list[str] of length N (ticker names, for reference)

    Returns:
        np.ndarray of shape [N] — portfolio weights per stock.
        Positive = long, negative = short.
        Will be normalized so sum(|weights|) = 1.
        Example: [0.3, -0.2, 0.5] → normalized to [0.3, -0.2, 0.5] (already sums to 1.0)
        Example: [0.6, -0.4, 1.0] → normalized to [0.3, -0.2, 0.5]
    """
    prices = data["price"]      # [N, 20]
    volumes = data["volume"]    # [N, 10]

    # Simple example: momentum — long stocks above their mean, short below
    mean_prices = prices.mean(axis=1)     # [N]
    current_prices = prices[:, -1]        # [N]
    deviation = (current_prices - mean_prices) / mean_prices  # [N]

    return deviation  # will be normalized automatically
```

### Output Normalization

After `main()` returns weights `w` of shape `[N]`:

```python
w = main(data)
w = np.array(w, dtype=np.float64)

# Normalize so sum(|w|) = 1
abs_sum = np.sum(np.abs(w))
if abs_sum > 0:
    w = w / abs_sum
else:
    w = np.zeros(N)  # all zero = hold everything flat
```

This means:
- User doesn't need to worry about normalization
- If user already normalizes, output is unchanged
- Weights represent fraction of total portfolio value per stock

### Strategy Validator

Same restrictions as current (no network, no os, no file I/O). **Allows:**
- `numpy`, `math`, `statistics`, `collections`, `itertools`, `functools`
- `datetime`, `decimal`, `typing`, `logging`

**Checks:**
- Must define a `def main(data):` function (not a class)
- `data` parameter name enforced
- Return type must be array-like
- Validate that accessed `data[key]` keys match configured fields
- Validate no out-of-bounds indexing beyond declared lookbacks (best-effort via AST)

---

## 4. Data Collection Layer

### New Module: `data/collector.py`

Replaces the old `BaseFeed` / `BinanceSimFeed` / `YFinanceFeed` system.

```python
class DataCollector:
    """
    Collects configured data fields at configured resolution.
    Maintains a rolling buffer per field per session.
    Triggers strategy execution every N scrapes.
    """

    def __init__(self, session_id, symbols, data_config, redis):
        self.session_id = session_id
        self.symbols = symbols               # list[str], length N
        self.resolution = data_config["resolution"]  # "1min", "5min", etc.
        self.fields = data_config["fields"]  # {"price": 20, "volume": 10, ...}
        self.exec_every_n = data_config.get("exec_every_n", 1)
        self.custom_data = data_config.get("custom_data", [])
        self.custom_global_data = data_config.get("custom_global_data", [])

        # Rolling buffers: field_name -> np.ndarray of shape [N, max_lookback]
        # Stored as deques or circular buffers
        self.buffers = {}
        self.scrape_count = 0

    async def start(self):
        """Start the collection loop."""
        ...

    async def _collect_once(self):
        """
        1. Fetch built-in data (price, volume, etc.) for all symbols
        2. Fetch custom data (run user functions in executor)
        3. Append to rolling buffers
        4. Increment scrape_count
        5. If scrape_count % exec_every_n == 0 → trigger strategy
        """
        ...

    def get_data_snapshot(self) -> dict[str, np.ndarray]:
        """
        Slice buffers to configured lookbacks.
        Returns dict ready to pass to main().
        """
        result = {}
        for field, lookback in self.fields.items():
            result[field] = self.buffers[field][:, -lookback:]  # [N, lookback]
        result["tickers"] = self.symbols
        return result
```

### Data Sources

| Resolution | Crypto Source | Stock Source |
|---|---|---|
| 1min–60min | Binance kline WebSocket (public, no key) | yfinance polling or Alpaca bars |
| 1day | Binance daily kline | yfinance daily (polled 5 min before close) |

For simulation: same data sources (both use public data).

### Rolling Buffer Design

```python
# Per field, maintain a numpy array of shape [N, buffer_size]
# buffer_size = max(all lookbacks for this field) + some padding
# New data appended by rolling left:
#   buffer[:, :-1] = buffer[:, 1:]
#   buffer[:, -1] = new_values
```

---

## 5. Strategy Execution Layer

### New Module: `strategy/executor.py`

Replaces the old `StrategyEngine` / `BaseStrategy` system.

```python
class StrategyExecutor:
    """
    Receives data snapshots from DataCollector.
    Runs user's main() function.
    Normalizes output weights.
    Converts weight changes to orders.
    """

    def __init__(self, session_id, strategy_code, symbols, redis, config):
        self.session_id = session_id
        self.symbols = symbols
        self.strategy_code = strategy_code
        self._compiled_main = None  # compiled main() function

    def load_strategy(self, code: str):
        """Compile user code and extract main() function."""
        namespace = {"np": numpy, "numpy": numpy, "math": math, ...}
        exec(code, namespace)
        self._compiled_main = namespace["main"]

    async def execute(self, data: dict[str, np.ndarray]) -> np.ndarray:
        """
        1. Call main(data)
        2. Validate output shape [N]
        3. Normalize: w = w / sum(|w|)
        4. Return normalized weights
        """
        raw_weights = self._compiled_main(data)
        raw_weights = np.array(raw_weights, dtype=np.float64)
        assert raw_weights.shape == (len(self.symbols),)

        abs_sum = np.sum(np.abs(raw_weights))
        if abs_sum > 0:
            return raw_weights / abs_sum
        return np.zeros(len(self.symbols))
```

### Weight-to-Order Conversion

```python
class WeightRebalancer:
    """Converts target weights to buy/sell orders."""

    def rebalance(self, target_weights, current_positions, total_equity, prices):
        """
        target_weights: [N] normalized weights (sum |w| = 1)
        current_positions: dict[symbol -> quantity]
        total_equity: float (cash + positions value)
        prices: [N] current prices

        Returns: list of OrderRequest (symbol, side, quantity)
        """
        orders = []
        for i, symbol in enumerate(self.symbols):
            target_value = target_weights[i] * total_equity  # can be negative (short)
            current_qty = current_positions.get(symbol, 0)
            current_value = current_qty * prices[i]
            diff_value = target_value - current_value

            if abs(diff_value) < min_order_threshold:
                continue

            qty = abs(diff_value) / prices[i]
            side = "BUY" if diff_value > 0 else "SELL"
            orders.append(OrderRequest(symbol=symbol, side=side, quantity=qty))

        return orders
```

---

## 6. Pipeline Flow (per session)

```
┌──────────────────────────────────────────────────────────────┐
│                     Session Pipeline                          │
│                                                               │
│  ┌─────────────┐    every resolution     ┌──────────────┐    │
│  │ DataCollector│──── (1min/5min/...) ───→│ Rolling      │    │
│  │             │     collect built-in +   │ Buffers      │    │
│  │  - Binance  │     custom data          │ [N, T] each  │    │
│  │  - yfinance │                          └──────┬───────┘    │
│  └─────────────┘                                 │            │
│                                    every N scrapes│            │
│                                                  ▼            │
│                                    ┌──────────────────┐       │
│                                    │ StrategyExecutor  │       │
│                                    │  main(data) →     │       │
│                                    │  weights [N]      │       │
│                                    └────────┬─────────┘       │
│                                             │                 │
│                                    normalize│sum(|w|)=1       │
│                                             ▼                 │
│                                    ┌──────────────────┐       │
│                                    │ WeightRebalancer  │       │
│                                    │  target - current │       │
│                                    │  → OrderRequests  │       │
│                                    └────────┬─────────┘       │
│                                             │                 │
│                                             ▼                 │
│                                    ┌──────────────────┐       │
│                                    │ OrderRouter       │       │
│                                    │ (existing, mostly │       │
│                                    │  unchanged)       │       │
│                                    └────────┬─────────┘       │
│                                             │                 │
│                                             ▼                 │
│                                    ┌──────────────────┐       │
│                                    │ PortfolioTracker  │       │
│                                    │ (existing, mostly │       │
│                                    │  unchanged)       │       │
│                                    └──────────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

---

## 7. UI Changes — Strategy Editor Page

### Tab Layout

```
┌─────────────────────────────────────────────────────────┐
│ Strategy Editor           Session: Test (Binance Sim)    │
│                                                          │
│ ┌──────────┬──────────────┬───────────┐                  │
│ │ Data     │ Custom Data  │ Strategy  │  ← tabs          │
│ │ Config   │ Functions    │ Code      │                   │
│ └──────────┴──────────────┴───────────┘                  │
│                                                          │
│ [Tab content here]                                       │
│                                                          │
│ [Validate]  [Deploy]                                     │
└─────────────────────────────────────────────────────────┘
```

**Tab 1: Data Config**
- Scrape resolution dropdown
- Strategy execution multiplier
- Checkbox + lookback input per data field
- Add/remove custom data fields
- Shows crypto-only fields based on session type

**Tab 2: Custom Data Functions**
- One CodeMirror editor per custom data function
- Each has a name, type (per-stock / global), and code
- Add/remove buttons
- Separate validate button per function

**Tab 3: Strategy Code**
- Single CodeMirror editor for the `main(data)` function
- Reference panel showing available data keys and their shapes
- Validate checks: `main` exists, data key access matches config, no forbidden calls

### Deploy Action

Deploy saves all three tabs together:
1. Data config → `TradingSession.data_config` (JSON)
2. Custom data functions → `TradingSession.custom_data_code` (JSON)
3. Strategy code → `TradingSession.strategy_code` (text)

Hot-reload restarts the DataCollector with new config and reloads strategy.

---

## 8. DB Schema Changes

### TradingSession Model — New/Modified Fields

```python
class TradingSession(Base):
    # ... existing fields ...

    # V2 strategy fields (replace old strategy_code / strategy_class)
    data_config = Column(Text, nullable=True)       # JSON: resolution, fields, lookbacks, exec_every_n
    custom_data_code = Column(Text, nullable=True)   # JSON: list of custom data functions
    strategy_code = Column(Text, nullable=True)      # Python source: main(data) function

    # Remove (deprecated):
    # strategy_class — no longer needed (no class, just main())
```

### data_config JSON Schema

```json
{
  "resolution": "1min",
  "exec_every_n": 5,
  "fields": {
    "price": {"enabled": true, "lookback": 20},
    "volume": {"enabled": true, "lookback": 10},
    "open": {"enabled": false, "lookback": 0},
    "high": {"enabled": false, "lookback": 0},
    "low": {"enabled": false, "lookback": 0},
    "vwap": {"enabled": true, "lookback": 5},
    "bid": {"enabled": false, "lookback": 0},
    "ask": {"enabled": false, "lookback": 0},
    "spread": {"enabled": false, "lookback": 0},
    "num_trades": {"enabled": false, "lookback": 0}
  },
  "custom_data": [
    {"name": "put_call_ratio", "type": "per_stock", "lookback": 5}
  ],
  "custom_global_data": [
    {"name": "vix", "type": "global", "lookback": 10}
  ]
}
```

---

## 9. Files to Create / Modify / Delete

### New Files

| File | Purpose |
|---|---|
| `data/collector.py` | DataCollector — unified data collection with rolling buffers |
| `strategy/executor.py` | StrategyExecutor — runs main(), normalizes weights |
| `strategy/rebalancer.py` | WeightRebalancer — converts weights to orders |
| `strategy/validator_v2.py` | New validator for main() function (replaces class-based checks) |
| `strategy/custom_validator.py` | Validator for custom data functions (allows network) |
| `strategy/examples/momentum_v2.py` | Default strategy using new interface |

### Modified Files

| File | Changes |
|---|---|
| `session/manager.py` | Pipeline construction uses DataCollector + StrategyExecutor + WeightRebalancer instead of old Feed + StrategyEngine + RiskManager chain |
| `monitoring/editor.py` | Tabbed UI: data config, custom data, strategy code. New API endpoints for save/load/validate each section |
| `monitoring/templates/editor.html` | Complete rewrite: 3 tabs, data config form, multiple code editors |
| `db/models.py` | Add `data_config`, `custom_data_code` columns to TradingSession |
| `shared/enums.py` | Add `DataResolution` enum |
| `monitoring/backtest.py` | Update to use new strategy interface |
| `backtest/engine.py` | Update to use DataCollector + StrategyExecutor pattern |
| `monitoring/sessions.py` | Session creation includes data_config defaults |

### Deprecated / Removed Files

| File | Action |
|---|---|
| `strategy/base.py` | **DELETE** — no more BaseStrategy class |
| `strategy/engine.py` | **DELETE** — replaced by executor.py |
| `strategy/validator.py` | **DELETE** — replaced by validator_v2.py |
| `strategy/examples/momentum.py` | **DELETE** — replaced by momentum_v2.py |
| `data/base_feed.py` | **DELETE** — replaced by collector.py |
| `data/binance_feed.py` | **DELETE** — replaced by collector.py |
| `data/binance_sim_feed.py` | **DELETE** — replaced by collector.py |
| `data/alpaca_feed.py` | **DELETE** — replaced by collector.py |
| `data/yfinance_feed.py` | **DELETE** — replaced by collector.py |
| `data/manager.py` | **DELETE** — replaced by collector.py |
| `data/normalizer.py` | **KEEP partially** — may reuse binance message parsing |
| `risk/manager.py` | **MODIFY** — risk checks now operate on weights, not individual signals |
| `risk/limits.py` | **MODIFY** — adapt to weight-based system |

---

## 10. Default Strategy (momentum_v2.py)

```python
"""Default momentum strategy — long stocks above rolling mean, short below."""
import numpy as np


def main(data: dict) -> np.ndarray:
    """
    Simple momentum: deviation from rolling mean price.
    Positive deviation → long, negative → short.

    Required data config:
        price: lookback >= 2
    """
    prices = data["price"]              # [N, lookback]
    current = prices[:, -1]             # [N]
    mean = prices.mean(axis=1)          # [N]
    deviation = (current - mean) / mean # [N]
    return deviation                    # auto-normalized to sum(|w|) = 1
```

---

## 11. Risk Management Changes

The risk system needs adaptation for weight-based orders:

| Current | V2 |
|---|---|
| Per-signal risk checks | Per-rebalance risk checks |
| Max position size % | Max single-stock weight % (inherent in normalization) |
| Max positions count | All N stocks can have positions (by design) |
| Kill switch | Still works — blocks all order execution |
| Drawdown limit | Still works — monitors equity |
| Daily loss limit | Still works — monitors equity |

Key change: risk checks happen **after** weight normalization but **before** order generation. If risk is breached (drawdown, daily loss), kill switch activates and rebalancer outputs zero weights (flatten all positions).

---

## 12. Migration / Backward Compatibility

- Existing sessions in DB will have `data_config = NULL` and old-style `strategy_code`
- On upgrade: old sessions won't start (incompatible strategy format)
- User must recreate sessions with new config
- This is acceptable since the user said "get rid of the old system"

---

## 13. Implementation Order

### Phase 1: Core Backend
1. `shared/enums.py` — add DataResolution enum
2. `db/models.py` — add data_config, custom_data_code columns
3. `data/collector.py` — DataCollector with rolling buffers
4. `strategy/executor.py` — StrategyExecutor (run main, normalize)
5. `strategy/rebalancer.py` — WeightRebalancer (weights → orders)
6. `strategy/validator_v2.py` — new validator for main()
7. `strategy/custom_validator.py` — validator for custom data functions
8. `strategy/examples/momentum_v2.py` — default strategy

### Phase 2: Pipeline Integration
9. `session/manager.py` — rewire pipeline construction
10. `risk/manager.py` + `risk/limits.py` — adapt to weight-based system
11. Delete deprecated files

### Phase 3: UI
12. `monitoring/editor.py` — new API endpoints for tabbed editor
13. `monitoring/templates/editor.html` — complete rewrite with 3 tabs
14. `monitoring/sessions.py` — data_config in session creation
15. `monitoring/templates/base.html` — update create session modal

### Phase 4: Backtest
16. `backtest/engine.py` — update to use new data + strategy system
17. `monitoring/backtest.py` + `backtest.html` — update UI

### Phase 5: Tests
18. Update all tests to match new interface
19. Add tests for DataCollector, StrategyExecutor, WeightRebalancer, validators

---

## 14. Open Questions (Resolved)

| Question | Decision |
|---|---|
| Tick-based resolution? | No — pure time-based only |
| Signal type? | Continuous weights, sum(\|w\|) = 1 |
| Shorting? | Yes — negative weights = short. User provides API keys |
| torch vs numpy? | numpy |
| Custom data network access? | Yes — separate validator allows requests/urllib |
| Old system? | Delete entirely |
| 1-per-day crypto? | Just use normal daily candle (no "5 min before close") |
