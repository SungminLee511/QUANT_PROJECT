# Quant Trading System Skill

> **MAINTENANCE:** This file is a living document. When you modify code in this project, update the relevant section here in the **same commit**. Added a module? Update the file tree. Changed a config key? Update the config section. New gotcha? Add it.

**Trigger:** Use this skill when the user asks about automated trading infrastructure — market data ingestion, strategy engine, risk management, order execution, portfolio tracking, web dashboard, strategy code editor, session management, simulation mode, or Docker deployment for Binance (crypto) and Alpaca (US equities).

**Project Root:** `/home/PROJECT/QUANT_PROJECT/`
**Origin:** Custom-built modular trading platform — infrastructure only, strategy is a swappable component via web editor.
**Conda Env:** `SML_env` — runs natively (Docker doesn't work on this server)
**Branch:** `feature/multi-session` (multi-session + simulation mode)

---

## Architecture Overview (V2 — Weight-Based)

The system uses a **data-config-driven, weight-based strategy model**. Instead of per-tick BUY/SELL/HOLD signals, strategies output **portfolio weights** that are automatically normalized and rebalanced.

### V2 Pipeline (Per Session)
```
DataCollector (rolling numpy buffers, configurable fields & resolution)
  ↓
StrategyExecutor (compiles & runs user's main(data) → weights)
  ↓
WeightRebalancer (diffs target weights vs current positions → OrderRequests)
  ↓
RiskManager (kill switch, drawdown, daily loss checks)
  ↓
OrderRouter + Exchange Adapter (sim or live)
  ↓
PortfolioTracker (positions, P&L, equity snapshots)
```

Sessions are isolated by:
- **DB:** `session_id` foreign key on all trade/order/position/snapshot records
- **Redis:** Namespaced channels (`session:{id}:market:ticks`, etc.)
- **Runtime:** Each session is an asyncio task group managed by `SessionManager`

### Session Types

| Type | Enum Value | Data Feed | Execution | API Keys |
|---|---|---|---|---|
| Binance Simulation | `binance_sim` | Binance public WebSocket (no key) | SimulationAdapter (instant fills) | Not needed |
| Alpaca Simulation | `alpaca_sim` | yfinance polling (~2s) | SimulationAdapter (instant fills) | Not needed |
| Binance Live | `binance` | Binance public WebSocket | BinanceAdapter (real orders) | Required |
| Alpaca Live | `alpaca` | yfinance polling | AlpacaAdapter (real orders) | Required |

### Key V1 → V2 Differences

| Aspect | V1 | V2 |
|--------|----|----|
| **Strategy Interface** | Class-based `BaseStrategy` with `on_tick`/`on_bar` | Function-based `main(data)` |
| **Signal Type** | Per-tick BUY/SELL/HOLD signals | Portfolio weights (continuous, normalized) |
| **Data Access** | Tick-by-tick market ticks | Configurable rolling numpy buffers (per field, per lookback) |
| **Execution Frequency** | Every tick | Configurable (every N scrapes) |
| **Field Configuration** | Fixed in strategy class | User-configured in UI with per-field lookbacks |
| **Custom Data** | Hardcoded in strategy | Modular `fetch()` functions with UI editor |
| **Validation** | Class/method checks | AST-based `main(data)` checks (no execution) |
| **Risk Checks** | Per-signal | Per-rebalance (post-weight-normalization) |
| **UI Editor** | Single code editor | Tabbed editor (Data Config / Custom Data / Strategy Code) |

---

## File Tree

```
QUANT_PROJECT/
├── README.md                          # Architecture overview & quick start
├── STRATEGY_V2_DESIGN.md             # Comprehensive V2 design spec
├── Dockerfile                         # Single image, command varies per service
├── docker-compose.yml                 # Stack: Redis, Postgres/TimescaleDB, 1 engine service
├── requirements.txt                   # All Python dependencies (incl. yfinance, websockets)
├── pyproject.toml                     # Project metadata, pytest config
├── .env.example                       # Template for API keys & secrets
│
├── config/
│   ├── default.yaml                   # Base config (all defaults, incl. auth credentials)
│   ├── dev.yaml                       # Dev overrides (testnet/paper, debug logging)
│   └── prod.yaml                      # Prod overrides (real trading, INFO logging)
│
├── shared/                            # Cross-service utilities
│   ├── enums.py                       # Exchange, Side, Signal, OrderStatus, AssetType, OrderType, SessionType, DataResolution
│   ├── schemas.py                     # Pydantic v2: MarketTick, OHLCVBar, TradeSignal, OrderRequest, OrderUpdate, LogEntry, etc.
│   ├── config.py                      # YAML + env var hierarchical config loader (QT_ prefix)
│   └── redis_client.py               # Async Redis: pub/sub, flags, connection pooling, session_channel() helper
│
├── session/                           # Multi-session orchestration
│   ├── __init__.py
│   ├── manager.py                     # SessionManager: create/start/stop/delete, pipeline lifecycle, on_strategy_trigger callback
│   └── schemas.py                     # SessionCreate, SessionUpdate Pydantic models
│
├── data/                              # Market data ingestion (V2: DataCollector)
│   ├── collector.py                   # V2 DataCollector: per-field source routing, rolling numpy buffers, custom data, strategy trigger
│   ├── normalizer.py                  # Exchange-specific → MarketTick/OHLCVBar conversion
│   ├── custom_data.py                 # Custom data placeholder (expected return format: dict[str, dict])
│   └── sources/                       # Data source registry and per-source fetchers
│       ├── __init__.py                # Field registry (FIELD_REGISTRY, FIELD_MAP), DataSource/FieldSection enums, get_default_source()
│       ├── yfinance_source.py         # YFinanceSource: price, OHLCV, fundamentals (market_cap, pe_ratio, 52w high/low)
│       ├── alpaca_source.py           # AlpacaSource: live quotes (bid/ask/spread), daily bars (OHLCV, VWAP) — requires API key
│       └── binance_source.py          # BinanceSource: 24hr ticker + order book — public API, no key needed
│
├── strategy/                          # V2 Strategy engine (weight-based)
│   ├── executor.py                    # V2 StrategyExecutor: compiles main(data), executes with safe builtins, normalizes weights
│   ├── validator_v2.py                # V2 AST validator: checks main(data) signature, forbidden imports/names, data key cross-check
│   ├── custom_validator.py            # Custom data function validator (allows network imports like requests, urllib)
│   ├── rebalancer.py                  # WeightRebalancer: diffs target weights vs positions → OrderRequests (dust filtering)
│   ├── user_strategies/              # Directory for user-uploaded strategies (gitignored)
│   │   └── .gitkeep
│   └── examples/
│       └── momentum_v2.py            # Default V2: weight-based momentum (deviation from rolling mean)
│
├── risk/                              # Risk management
│   ├── limits.py                      # Position size, max positions, drawdown, daily loss, kill switch checks
│   ├── kill_switch.py                # Redis-backed emergency halt (activate/deactivate/state)
│   └── manager.py                     # Risk pipeline + V2 check_portfolio_risk (called after weight normalization)
│
├── execution/                         # Order execution
│   ├── order.py                       # Order state machine (PENDING→PLACED→PARTIAL→FILLED, etc.)
│   ├── base_adapter.py               # Abstract exchange adapter interface
│   ├── binance_adapter.py            # Binance: order placement, retry, balance/position queries
│   ├── alpaca_adapter.py             # Alpaca: order placement, retry, position queries
│   ├── sim_adapter.py                # SimulationAdapter: instant fills, virtual cash/positions, no API key
│   └── router.py                      # Routes OrderRequests to adapters, DB persistence, fill polling
│
├── portfolio/                         # Portfolio tracking
│   ├── tracker.py                     # Position management, equity snapshots, Redis state publishing
│   ├── pnl.py                        # Realized/unrealized P&L, win rate, daily metrics
│   └── reconciler.py                 # Periodic exchange reconciliation with drift detection
│
├── backtest/                          # V2 Backtesting engine (weight-based)
│   ├── __init__.py
│   └── engine.py                     # V2 engine: yfinance OHLCV → rolling buffers → StrategyExecutor → _VirtualPortfolio rebalance → metrics
│
├── monitoring/                        # Web interface (ALL user interaction happens here)
│   ├── app.py                         # FastAPI app factory, lifespan auto-restarts active sessions
│   ├── auth.py                        # Session-based login/logout (cookie auth, no heavy deps)
│   ├── backtest.py                    # Backtest API: run backtest, load strategy code for backtest page
│   ├── dashboard.py                   # Dashboard API: positions, P&L, orders, equity history, kill switch
│   ├── editor.py                      # V2 Strategy editor API: 3-tab (data config, custom data, strategy code), load/validate/deploy
│   ├── logs.py                        # Logs page: SSE streaming, in-memory ring buffer, per-session log viewer
│   ├── settings.py                    # Settings API: global API key management, .env read/write
│   ├── sessions.py                    # Sessions REST API: CRUD + start/stop endpoints
│   ├── logger.py                      # structlog: JSON (prod) or console (dev) output
│   └── templates/
│       ├── base.html                 # Shared layout: nav bar + session sidebar + create modal + toast
│       ├── login.html                # Login page (simple form)
│       ├── backtest.html             # Backtest page: config form, code editor, equity chart, metrics, trade log
│       ├── overview.html             # Overview page (extends base.html): card grid of all sessions with equity/P&L
│       ├── dashboard.html            # Main dashboard (extends base.html): equity curve, positions, orders
│       ├── editor.html               # V2 Code editor (extends base.html): 3-tab interface (Data Config / Custom Data / Strategy Code)
│       ├── logs.html                 # Logs page (extends base.html): real-time monospace log viewer with SSE
│       └── settings.html             # Global API keys (extends base.html): Binance/Alpaca config
│
├── db/                                # Database layer
│   ├── models.py                      # SQLAlchemy 2.0: TradingSession (V2 fields), Trade, Position, Order, EquitySnapshot, AlertLog
│   ├── session.py                     # Async session factory (asyncpg), init_db(), get_session()
│   └── migrations/
│       └── env.py                    # Alembic placeholder
│
├── scripts/                           # Service entry points
│   ├── run_data.py                    # Data feed service (legacy, unused in multi-session)
│   ├── run_strategy.py               # Strategy engine service (legacy, unused in multi-session)
│   ├── run_execution.py              # Risk + order router + portfolio (legacy, unused in multi-session)
│   ├── run_monitor.py                # Main entry point: Web UI + SessionManager (replaces all above)
│   └── run_all.py                    # Dev helper: all services in one process
│
└── tests/                             # Unit tests (96 tests)
    ├── conftest.py                    # Shared fixtures (mock Redis, sample data)
    ├── test_backtest/test_engine.py   # V2: _VirtualPortfolio rebalancing, rolling buffers, _compute_metrics
    ├── test_data/
    │   ├── test_normalizer.py         # Binance trade/kline normalization
    │   └── test_collector.py          # V2: DataCollector buffers, snapshots, custom data loading
    ├── test_strategy/
    │   ├── test_engine.py             # V2: StrategyExecutor load/execute/normalize, error handling
    │   ├── test_validator_v2.py       # V2: AST validation (main signature, forbidden imports/names)
    │   ├── test_rebalancer.py         # V2: WeightRebalancer buy/sell/mixed/dust/shape
    │   └── test_custom_validator.py   # V2: custom data function validation
    ├── test_risk/test_manager.py      # Risk limit checks + V2 check_portfolio_risk
    ├── test_execution/test_router.py  # Order state machine transitions
    ├── test_portfolio/test_pnl.py     # P&L calculator, win rate
    └── test_session/
        └── test_sim_adapter.py       # SimulationAdapter: buy/sell/clip/error scenarios
```

---

## Web Interface (port 8080)

All user interaction is through the web UI. No Telegram bot, no CLI commands needed.

### Authentication

- **Simple session auth** — cookie-based, no external deps
- Default credentials: `admin` / `admin1234` (configurable in `default.yaml` → `auth`)
- Login required for all pages except `/login`
- Session stored server-side (in-memory dict, keyed by random token cookie)

### Layout (base.html)

All pages (except login) share a common layout:
- **Top nav bar** — page links (Dashboard, Strategy Editor, Settings), user info, logout
- **Left sidebar (260px)** — session list with:
  - "All Sessions" global view
  - Per-session items showing name, SIM/LIVE badge, status dot (running/stopped/error)
  - Inline Start/Stop/Delete controls (shown on active selection)
  - "+" button → Create Session modal
- **Main content area** — page-specific content

### Pages

| Route | Page | Description |
|---|---|---|
| `/login` | Login | Username + password form |
| `/` | Dashboard | Equity curve, positions, orders, P&L, kill switch — scoped by ?session_id |
| `/editor` | Strategy Editor | V2 tabbed editor: Data Config, Custom Data, Strategy Code — per-session via DB |
| `/backtest` | Backtest | Run backtests: config form, CodeMirror editor, equity chart, metrics, trade log |
| `/logs` | Logs | Real-time session activity log: tick evals, signals, risk decisions, order fills, session events |
| `/settings` | Settings | Global API key config (Binance/Alpaca), testnet/paper toggles |

### Session Management UI

- **Create Session Modal** — name, type (4 options), symbols, starting budget, API keys (for live only)
- **Sidebar** — real-time session status, click to scope all data views
- **Start/Stop/Delete** — inline controls per session
- **Session-scoped views** — Dashboard, Editor all filter by selected session (via `?session_id=` query param)
- **Global view** — "All Sessions" shows aggregated data across all sessions

### Dashboard Features

- Real-time equity curve (Chart.js via CDN)
- Open positions table with unrealized P&L
- Recent orders (last 100) — filtered by session if selected
- Daily P&L metric card
- Kill switch toggle button (per-session when scoped)
- Session banner showing current session name
- Auto-refresh every 10 seconds

### Strategy Editor (V2 — 3-Tab Interface)

The editor has **3 tabs**, all deployed together:

**Tab 1: Data Config**
- Scrape resolution dropdown (1min, 5min, 15min, 30min, 60min, 1day)
- Strategy execution multiplier (N) — runs `main(data)` every N scrapes
- Two field sections: **Live Data** (price, bid, ask, spread, num_trades) and **Daily Data** (open, high, low, close, volume, vwap, day_change_pct, market_cap, pe_ratio, week52_high, week52_low)
- Each field has: checkbox (enable/disable), lookback input, per-field **data source** dropdown
- Source options depend on session type: stock sessions show `stockSources` (yfinance, alpaca), crypto sessions show `cryptoSources` (binance)
- Fields with no sources for the current session type are hidden entirely
- Fields with only one source show a static label instead of a dropdown
- Multi-source warning: yellow banner when 2+ different sources are enabled across fields
- Field descriptions shown as subtle gray text on each row
- Uses `FIELD_REGISTRY` array (replaces old `ALL_FIELDS`) with `section`, `stockSources`, `cryptoSources`, `description` per field
- Data config format includes `"source"` key per field: `{"enabled": true, "lookback": 20, "source": "yfinance"}`

**Tab 2: Custom Data Functions**
- Per-function CodeMirror editor
- Each shows name, type (per_stock/global), code
- Validate button per function (AST check — allows network imports)
- Add/remove buttons

**Tab 3: Strategy Code**
- CodeMirror editor for `main(data)` function
- Reference panel showing available data keys and shapes
- Validate button (checks main signature, imports, data key access)
- Pre-loaded with default momentum_v2 strategy on first visit

**Deploy** button saves all three tabs to DB → UI shows "deployed successfully, restart session to apply"

#### Editor API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/editor` | GET | Editor page |
| `/editor/api/load?session_id=...` | GET | Load all three sections (data config, custom data, strategy code) |
| `/editor/api/validate` | POST | Validate strategy code (with data_config context) |
| `/editor/api/validate-custom` | POST | Validate custom data function |
| `/editor/api/deploy?session_id=...` | POST | Save all sections to DB |

---

## Strategy Code Contract (V2 — ENFORCED)

User-submitted strategy code **must** follow this interface. `strategy/validator_v2.py` checks via AST parsing before allowing deploy.

### Required

| Rule | Detail |
|---|---|
| Must define exactly one function | Named `main` |
| Must have exactly one parameter | Named `data` |
| Must not be async | numpy is synchronous |
| Return type | `np.ndarray` of shape `[N_symbols]` (portfolio weights) |

### Input: `data` dict

The `data` argument is a dict with keys matching configured fields:

| Key | Shape | Description |
|---|---|---|
| `"tickers"` | `list[str]` | List of symbol names (order matches array rows) |
| `"price"` | `[N, lookback]` | Close/last price rolling buffer |
| `"open"` | `[N, lookback]` | Open price (if enabled) |
| `"high"` | `[N, lookback]` | High price (if enabled) |
| `"low"` | `[N, lookback]` | Low price (if enabled) |
| `"volume"` | `[N, lookback]` | Trade volume (if enabled) |
| `"vwap"` | `[N, lookback]` | Volume-weighted avg price (if enabled) |
| `"bid"` | `[N, lookback]` | Best bid (crypto only, if enabled) |
| `"ask"` | `[N, lookback]` | Best ask (crypto only, if enabled) |
| `"spread"` | `[N, lookback]` | ask - bid (crypto only, if enabled) |
| `"num_trades"` | `[N, lookback]` | Number of trades (crypto only, if enabled) |
| `"<custom_name>"` | `[N, lookback]` or `[lookback]` | Custom per-stock or global data (if configured) |

### Output: Weight Normalization

- Strategy returns raw weights `[N_symbols]`
- System normalizes: `w = w / sum(|w|)` if non-zero sum
- Positive weights = long, negative weights = short
- Zero weights = no position
- Returns zero weights on error (NaN, Inf, wrong shape)

### Safe Builtins (Whitelisted)

```python
int, float, str, bool, list, dict, tuple, set,
abs, all, any, enumerate, filter, map, max, min,
range, reversed, sorted, sum, zip,
ValueError, TypeError, IndexError, KeyError, ...
```

### Allowed Imports

```
numpy, math, statistics, collections, itertools, functools
```

### Forbidden

- `os`, `sys`, `subprocess`, `importlib`, `eval`, `exec`, `open`, `__import__`, `getattr`, `setattr`
- Any network/file I/O
- Module-level side effects

### Custom Data Function Contract

Custom `fetch()` functions are **more permissive** (network access allowed):

| Type | Signature | Returns |
|---|---|---|
| Per-stock | `def fetch(tickers: list[str]) -> np.ndarray` | Array of shape `[N_symbols]` |
| Global | `def fetch() -> float` | Single scalar |

**Allowed imports for custom data:** `requests`, `urllib`, `json`, `re`, `time`, `datetime`, `numpy`
**Still forbidden:** `subprocess`, `os`, `sys`, `eval`, `exec`, `getattr`, `setattr`

### Default Strategy (Pre-loaded in Editor)

`strategy/examples/momentum_v2.py` — deviation from rolling mean:
```python
def main(data: dict) -> np.ndarray:
    prices = data["price"]              # [N, lookback]
    current = prices[:, -1]             # [N]
    mean = prices.mean(axis=1)          # [N]
    safe_mean = np.where(mean != 0, mean, 1.0)
    deviation = (current - safe_mean) / safe_mean
    return deviation  # auto-normalized to sum(|w|) = 1
```

---

## DataCollector (data/collector.py)

Unified market data collection with rolling numpy buffers.

### Features
- Configurable scrape resolution (1min, 5min, 15min, 30min, 60min, 1day)
- Rolling buffers per field per symbol: shape `[N_symbols, lookback + 10]`
- Buffer append via left-rotation: `buf[:, :-1] = buf[:, 1:]; buf[:, -1] = new`
- Tracks fill level — strategy only triggered when sufficient history exists
- Custom per-stock and global data functions called every scrape
- Strategy trigger callback fires every N scrapes
- **Historical buffer backfill** — on session start, `_backfill_buffers()` pre-fills rolling buffers with historical data so the strategy can fire on the very first live scrape (no warm-up delay)

### Data Sources (per-field routing via `data/sources/`)
- **yfinance:** Price, OHLCV, day_change_pct, fundamentals (market_cap, pe_ratio, 52w high/low). No API key. `fetch_history()` uses `yf.download()` for OHLCV bars; fundamentals repeated as constants.
- **Alpaca:** Live quotes (bid/ask/spread), daily bars (OHLCV, VWAP). Requires API key. `fetch_history()` uses `/v2/stocks/bars` endpoint; bid/ask/spread skipped (no historical quotes).
- **Binance:** 24hr ticker (price, OHLCV, VWAP, num_trades, day_change_pct) + order book (bid/ask/spread). Public API. `fetch_history()` uses `/api/v3/klines` per-symbol; bid/ask/spread skipped.

Each field in data_config specifies its `"source"` (yfinance/alpaca/binance). The collector groups fields by source, fetches from each source once, then merges results into buffers. If `"source"` is omitted, `get_default_source()` picks the first available source for the exchange type.

Field registry (`data/sources/__init__.py`) defines 16 fields with per-exchange availability:
- Live: price, bid, ask, spread, num_trades
- Daily: open, high, low, close, volume, vwap, day_change_pct, market_cap, pe_ratio, week52_high, week52_low

### Data Config Schema (stored in DB as JSON)

```json
{
  "resolution": "1min",
  "exec_every_n": 5,
  "fields": {
    "price": {"enabled": true, "lookback": 20, "source": "yfinance"},
    "volume": {"enabled": true, "lookback": 10, "source": "yfinance"},
    "open": {"enabled": false, "lookback": 0, "source": "yfinance"},
    "high": {"enabled": false, "lookback": 0, "source": "yfinance"},
    "low": {"enabled": false, "lookback": 0, "source": "yfinance"},
    "vwap": {"enabled": true, "lookback": 5, "source": "alpaca"}
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

## WeightRebalancer (strategy/rebalancer.py)

Converts target portfolio weights into concrete buy/sell orders.

### Algorithm
```python
for each symbol i:
    target_value = target_weights[i] * total_equity
    current_value = current_positions[i] * prices[i]
    diff_value = target_value - current_value
    if |diff_value| > MIN_ORDER_VALUE ($1):
        qty = |diff_value| / prices[i]
        side = BUY if diff_value > 0 else SELL
        → generate OrderRequest
```

- Dust order filtering (skips orders < $1 value)
- Stores metadata in OrderRequest: target_weight, target_value, current_value, diff_value

---

## Session Manager (session/manager.py)

Central orchestrator for all trading sessions.

### Key Classes

| Class | Purpose |
|---|---|
| `SessionPipeline` | Holds all runtime state for one session (tasks, collector, executor, rebalancer, router, tracker, sim_adapter) |
| `SessionManager` | CRUD + start/stop lifecycle, pipeline construction, auto-restart on crash |

### Pipeline Construction

When a session starts, `SessionManager._start_pipeline()`:
1. Creates StrategyExecutor with strategy code
2. Creates WeightRebalancer with symbols and exchange
3. Creates OrderRouter (with SimulationAdapter for sim sessions)
4. Creates PortfolioTracker
5. Creates DataCollector with strategy trigger callback
6. Loads custom data functions from DB
7. Launches all components as asyncio tasks with `_run_with_restart()` (max 3 retries, 5s delay)

### Strategy Trigger Callback (`on_strategy_trigger`)

```python
async def on_strategy_trigger(data_snapshot: dict):
    # Called by DataCollector every N scrapes
    # 1. Run strategy: weights = executor.execute(data_snapshot)
    # 2. Generate orders: orders = rebalancer.rebalance(weights, positions, equity, prices)
    # 3. Risk checks: check_portfolio_risk(orders, ...) → may activate kill switch
    # 4. Route orders: order_router.place_orders(orders)
```

### Auto-Restart on Boot

`monitoring/app.py` lifespan handler queries DB for sessions with `status='active'` and calls `start_session()` on each.

---

## Sessions REST API (monitoring/sessions.py)

| Endpoint | Method | Description |
|---|---|---|
| `/api/sessions` | GET | List all sessions (enriched with `is_running`) |
| `/api/sessions` | POST | Create new session (name, type, symbols, budget, keys) |
| `/api/sessions/{id}` | GET | Get single session info |
| `/api/sessions/{id}` | PUT | Update session fields |
| `/api/sessions/{id}` | DELETE | Stop + delete session and all its data |
| `/api/sessions/{id}/start` | POST | Start session pipeline |
| `/api/sessions/{id}/stop` | POST | Stop session pipeline |

---

## Backtesting Engine (V2 — backtest/engine.py)

### Features
- Downloads OHLCV from yfinance
- Builds rolling numpy buffers (same format as live DataCollector)
- Replays bars and calls `main(data)` every N bars
- Rebalances portfolio via weights using `_VirtualPortfolio`
- Pure in-memory — no DB, no Redis

### _VirtualPortfolio
- Tracks cash, positions, equity
- `rebalance(target_weights, date)` → list of `BacktestTrade`
- Computes realized P&L on sells, unrealized on holds

### Output
```python
BacktestResult(
    metrics=BacktestMetrics(...),  # total_return, sharpe, max_drawdown, win_rate, profit_factor, avg_win/loss
    equity_curve=[{date, equity, cash, positions_value}, ...],
    trades=[BacktestTrade(...), ...],
    errors=[],
    success=True
)
```

### Backtest API

| Endpoint | Method | Description |
|---|---|---|
| `/backtest` | GET | Backtest page |
| `/backtest/api/run` | POST | Run backtest (symbols, dates, cash, interval, strategy_code) |
| `/backtest/api/load-code` | GET | Load strategy code for session |

---

## Simulation Mode

### SimulationAdapter (execution/sim_adapter.py)

- Instant fills at last known market price (zero slippage, no partial fills)
- Virtual cash balance (starting_budget) — decremented on buys, incremented on sells
- Virtual position tracking — buys accumulate, sells reduce positions
- Quantity clipping: if order exceeds available cash, clips to max affordable
- Sell validation: cannot sell more than current position
- Publishes `OrderUpdate` fills on session-namespaced Redis channel
- Price updates received from sim price listener (subscribes to session's `market:ticks`)

### BinanceSimFeed (data/binance_sim_feed.py)

- Connects to Binance public WebSocket (`wss://stream.binance.com:9443/ws`)
- No API key required — uses public trade streams
- Publishes `MarketTick` to session-namespaced `market:ticks` channel
- Supports multiple symbols via combined streams

### YFinanceFeed (data/yfinance_feed.py)

- Polls `yfinance` `fast_info['lastPrice']` at configurable interval (default ~2s)
- No API key required
- Generates synthetic `MarketTick` from price snapshots
- Suitable for US stocks (AAPL, MSFT, etc.)

---

## DB Models (db/models.py)

| Model | Key Fields | Notes |
|---|---|---|
| `TradingSession` | id (UUID), name, session_type, is_simulation, status, config_json, starting_budget, strategy_code, data_config, custom_data_code | **V2:** `data_config` (JSON), `custom_data_code` (JSON list of {name, type, code}), `strategy_code` (Python source for `main(data)`) |
| `Trade` | id, session_id (FK), symbol, side, quantity, price, ... | session_id added |
| `Position` | id, session_id (FK), symbol, quantity, entry_price, ... | session_id added, unique per session+symbol |
| `Order` | id, session_id (FK), symbol, side, quantity, status, exchange, ... | session_id added |
| `EquitySnapshot` | id, session_id (FK), timestamp, total_equity, cash, positions_value | session_id added |
| `AlertLog` | id, session_id (FK), level, message, source, ... | session_id added |

All `session_id` fields are nullable (backward compat with pre-session data).

### V2-Specific DB Fields on TradingSession

| Field | Type | Content |
|---|---|---|
| `strategy_code` | Text | Python source: `def main(data): ...` |
| `data_config` | Text | JSON: resolution, fields, lookbacks, exec_every_n, custom_data, custom_global_data |
| `custom_data_code` | Text | JSON list: `[{"name": "...", "type": "per_stock"/"global", "code": "def fetch(...): ..."}]` |

---

## Config System (3-Level Merge)

1. `config/default.yaml` — base defaults
2. `config/{QT_ENV}.yaml` — environment overrides (dev/prod)
3. `QT_*` environment variables — highest priority

### Auth Config (in default.yaml)

```yaml
auth:
  username: "admin"
  password: "admin1234"
  session_ttl_hours: 24
```

**Key env var mappings:**

| Env Variable | Config Path |
|---|---|
| `QT_ENV` | `app.env` |
| `QT_REDIS_HOST` | `redis.host` |
| `QT_BINANCE_API_KEY` | `binance.api_key` |
| `QT_ALPACA_API_KEY` | `alpaca.api_key` |
| `QT_DATABASE_HOST` | `database.host` |
| `QT_DB_PASSWORD` | `database.password` |
| `QT_AUTH_USERNAME` | `auth.username` |
| `QT_AUTH_PASSWORD` | `auth.password` |

---

## Redis Channels

### Global (legacy, used when no session_id)

| Channel | Publisher | Subscriber | Message Type |
|---|---|---|---|
| `market:ticks` | data feeds | strategy engine | `MarketTick` / `OHLCVBar` |
| `strategy:signals` | strategy engine | risk manager | `TradeSignal` |
| `execution:orders` | risk manager | order router | `OrderRequest` |
| `execution:updates` | order router | portfolio tracker | `OrderUpdate` |
| `monitoring:alerts` | risk manager | dashboard (shown in UI) | `AlertMessage` |

### Session-Scoped (via `session_channel()` helper)

Pattern: `session:{session_id}:{channel_name}`

Example for session `abc123`:
- `session:abc123:market:ticks`
- `session:abc123:strategy:signals`
- `session:abc123:execution:orders`
- `session:abc123:execution:updates`
- `session:abc123:risk:kill_switch`
- `session:abc123:portfolio:state`
- `session:abc123:strategy:reload`
- `session:abc123:logs`

---

## Risk Checks (Sequential)

1. **Kill switch** — Redis flag (session-scoped: `session:{id}:risk:kill_switch`)
2. **Drawdown** — peak-to-trough (default 5%)
3. **Daily loss** — from day start equity (default 3%)
4. **Max positions** — total open (default 10)
5. **Position size** — per-position % of equity (default 10%)

Auto-activates kill switch on drawdown or daily loss breach.

**V2 adaptation:** Risk checks run **after** weight normalization but **before** order execution (in `on_strategy_trigger` callback).

---

## Shared Enums (shared/enums.py)

| Enum | Values |
|---|---|
| `Exchange` | BINANCE, ALPACA |
| `Side` | BUY, SELL |
| `Signal` | BUY, SELL, HOLD |
| `OrderStatus` | PENDING, PLACED, PARTIAL, FILLED, CANCELLED, REJECTED, FAILED |
| `AssetType` | CRYPTO, EQUITY |
| `OrderType` | MARKET, LIMIT |
| `SessionType` | BINANCE, ALPACA, BINANCE_SIM, ALPACA_SIM |
| `DataResolution` | MIN_1, MIN_5, MIN_15, MIN_30, MIN_60, DAY_1 |

`SessionType` has properties: `.is_simulation` (bool), `.exchange` (Exchange enum).
`DataResolution` has property: `.seconds` (int).

---

## Running on This Server (Native, No Docker)

Docker does not work on this server (restricted container, no `unshare` permission, `vfs` storage driver). Run all services natively instead.

### Startup Sequence

```bash
# 1. Fix Redis write errors (if needed)
redis-cli CONFIG SET stop-writes-on-bgsave-error no

# 2. Start PostgreSQL (data lives in QUANT_PROJECT/pgdata/)
su postgres -s /bin/bash -c "/usr/lib/postgresql/14/bin/pg_ctl -D /home/PROJECT/QUANT_PROJECT/pgdata -l /home/PROJECT/QUANT_PROJECT/pgdata/logfile start"

# 3. Start the app
cd /home/PROJECT/QUANT_PROJECT
conda run -n SML_env nohup python -u -m scripts.run_monitor > /home/PROJECT/QUANT_PROJECT/app_log.txt 2>&1 &

# 4. Start Cloudflare tunnel for external access
nohup cloudflared tunnel --url http://localhost:8080 > /home/PROJECT/QUANT_PROJECT/cloudflared_log.txt 2>&1 &
# Get the link:
grep "trycloudflare.com" /home/PROJECT/QUANT_PROJECT/cloudflared_log.txt
```

### First-Time Setup (only once)

```bash
# Create postgres user and init DB
useradd -m postgres
mkdir -p /var/run/postgresql && chown postgres:postgres /var/run/postgresql
mkdir -p /home/PROJECT/QUANT_PROJECT/pgdata
chown postgres:postgres /home/PROJECT/QUANT_PROJECT/pgdata
su postgres -s /bin/bash -c "/usr/lib/postgresql/14/bin/initdb -D /home/PROJECT/QUANT_PROJECT/pgdata"

# Create DB and user (matches config/default.yaml)
su postgres -s /bin/bash -c "psql -c \"CREATE USER quant WITH PASSWORD 'changeme';\""
su postgres -s /bin/bash -c "psql -c \"CREATE DATABASE quant_trader OWNER quant;\""

# Install Python deps
conda run -n SML_env pip install -q redis[hiredis] sqlalchemy[asyncio] asyncpg psycopg2-binary fastapi 'uvicorn[standard]' jinja2 python-multipart yfinance pydantic pydantic-settings pyyaml structlog python-dotenv
```

### Shutdown

```bash
pkill -f "scripts.run_monitor"
pkill -f cloudflared
su postgres -s /bin/bash -c "/usr/lib/postgresql/14/bin/pg_ctl -D /home/PROJECT/QUANT_PROJECT/pgdata stop"
```

### Services Summary

| Service | How | Port |
|---|---|---|
| Redis | Already running on server | 6379 |
| PostgreSQL 14 | Manual start (pgdata/ in project root) | 5432 |
| Engine (FastAPI) | `python -m scripts.run_monitor` via conda | 8080 |
| Cloudflare tunnel | `cloudflared tunnel --url http://localhost:8080` | Random `.trycloudflare.com` URL |

**Note:** Previously 4 separate app services (data-feed, strategy, execution, monitor). Now consolidated into single `engine` service — `SessionManager` orchestrates all trading pipelines as asyncio tasks within one process.

---

## Bug Fix Guide

See **[BUG_FIX_GUIDE.md](BUG_FIX_GUIDE.md)** for known bugs, root causes, and step-by-step fixes. Key issues documented:

| Bug | Severity | Summary |
|-----|----------|---------|
| BUG 1: No DB schema init on startup | **CRITICAL** | `pg_isready` ≠ tables exist. No Alembic migration step → all services crash after restart. Fix: `db-init` service in docker-compose. |
| BUG 2: TimescaleDB extension never created | **CRITICAL** | `CREATE EXTENSION timescaledb` never runs → `create_hypertable()` fails. Fix: `db/init.sql` mounted via `docker-entrypoint-initdb.d`. |
| BUG 3: Services don't depend on Postgres | **HIGH** | `data-feed` and `strategy` have no Postgres dependency → DB writes crash. Fix: resolved transitively by BUG 1's `db-init` dependency. |
| BUG 4: `latest` tag on TimescaleDB image | **HIGH** | Silent upgrades can break on-disk format → volume incompatible. Fix: pin to specific version (e.g. `2.17.2-pg16`). |
| BUG 5: Missing psycopg2 sync driver | **MEDIUM** | Alembic needs sync driver but only `asyncpg` installed → `alembic upgrade head` fails. Fix: add `psycopg2-binary` to requirements. |
| BUG 6: No Redis persistence config | **MEDIUM** | No AOF enabled → lose cached state on unclean shutdown. Fix: `redis-server --appendonly yes`. |
| BUG 7: Alembic hardcoded connection string | **MEDIUM** | `localhost` in alembic.ini fails inside Docker (host is `postgres`). Fix: override URL from env vars in `env.py`. |
| BUG 8: No graceful shutdown handling | **LOW** | No SIGTERM handler → incomplete transactions, orphaned connections. Fix: register signal handlers in entry points. |
| ~~BUG 9: No market ticks in V2~~ | **CRITICAL** | DataCollector stored prices in buffers but never published to `market:ticks` → SimAdapter had no prices → every order rejected. **Fixed:** `on_scrape_complete` now publishes `MarketTick` per symbol. |
| ~~BUG 10: Portfolio state missing positions~~ | **HIGH** | `_publish_state_loop` published symbol names only, not quantities → rebalancer always saw empty portfolio. **Fixed:** Added `positions` list with `symbol`, `quantity`, `avg_entry_price`. |
| ~~BUG 11: _run_with_restart can't restart~~ | **HIGH** | Passed coroutine objects (single-use) → retry attempts raised `RuntimeError`. **Fixed:** Changed to accept lambda factory that creates a fresh coroutine per attempt. |
| ~~BUG 12: Failed orders not persisted~~ | **MEDIUM** | `return` in except block skipped `_persist_order()` → failed orders invisible. **Fixed:** Failed orders now persisted with FAILED status + error log. |

---

## Gotchas & Notes

- **Never commit `.env`** — it's gitignored. Use `.env.example` as template.
- **Telegram bot removed in v2** — all interaction is through the web UI.
- **V2 replaces V1 entirely** — old V1 class-based sessions are incompatible.
- **Strategy validator** uses AST parsing, not `exec()` — code is never executed during validation.
- **User strategies** are saved to `strategy/user_strategies/` which is gitignored (user code stays local).
- **Per-session strategies** are stored in DB (`TradingSession.strategy_code`), not filesystem.
- **Hot-reload** works by publishing a reload signal to Redis; requires session restart to apply.
- **Custom data functions can access network** — `requests`, `urllib` are allowed (unlike strategy code).
- **Strategy code is strictly sandboxed** — no network, file I/O, or os.system.
- **Weight normalization** — `sum(|w|) = 1` enforced automatically; strategies return raw weights.
- **Weight-based system runs for all N stocks** — no max positions limit by design (diversification via weights).
- **Rolling numpy buffers** — O(1) append via left-rotation, `np.float64` throughout. Pre-filled via `_backfill_buffers()` on session start.
- **Backfill is best-effort** — if `fetch_history()` fails, logs a warning and falls back to live-fill. Custom data fields are not backfilled (no history available).
- **Binance adapter** needs symbol for `cancel_order` and `get_order_status` — use `get_order_status_for_symbol()`.
- **Alpaca** only streams during market hours (9:30 AM – 4:00 PM ET). Feed handles this gracefully.
- **Order state machine** enforces valid transitions — invalid ones raise `InvalidTransitionError`.
- **Auth is simple** — in-memory sessions, single user. Not for public-facing deployment.
- **All Redis messages** are JSON-serialized Pydantic models (`.model_dump_json()` / `.model_validate_json()`).
- **API keys not encrypted** in DB — `TradingSession.config_json` stores plaintext (personal system, not public-facing).
- **Session auto-restart** — on container boot, `app.py` lifespan queries DB for `status='active'` sessions and restarts them.
- **SimulationAdapter clips orders** — if buy exceeds available cash, quantity is reduced to max affordable (no rejection).
- **`_run_with_restart`** — accepts a lambda factory (not a coroutine object!) so each retry creates a fresh coroutine. Auto-retries up to 3 times with 5s delay; sets session status to `error` on exhaust.
- **Market ticks in V2** — `on_scrape_complete` callback publishes `MarketTick` to `session:{id}:market:ticks` after each data scrape. This feeds SimulationAdapter and PortfolioTracker with prices.
- **Portfolio state includes `positions` list** — `_publish_state_loop` publishes `positions: [{symbol, quantity, avg_entry_price}]` for rebalancer consumption.
- **Legacy scripts** (`run_data.py`, `run_strategy.py`, `run_execution.py`) still exist but are unused — `run_monitor.py` is the sole entry point.
- **Backtesting is lightweight** — pure in-memory (no DB, no Redis), uses same rolling buffer format as live.

---

## TODO

### ~~1. Universe Presets for Session Creation~~ DONE
Dropdown with presets (Mag 7, S&P 500 Top 30, NASDAQ Top 20, Crypto Top 10/20, Sector ETFs, Index ETFs) in `base.html`. Optgroups toggle by session type. Individual ticker input preserved alongside.

### ~~2. Backtesting Engine~~ DONE
V2 weight-based backtesting with `_VirtualPortfolio`, rolling numpy buffers, metrics computation. Full UI with Chart.js equity curve, trade log, and metrics grid.

### ~~3. Custom Data Pipeline + Strategy V2 Design~~ DONE
- V2 strategy engine: `main(data)` → weights, DataCollector with rolling buffers, WeightRebalancer
- Custom data functions: per-stock `fetch(tickers)` and global `fetch()` with network access
- 3-tab editor UI: Data Config, Custom Data, Strategy Code
- AST-based validators for both strategy and custom data code
- Full test coverage (96 tests)
