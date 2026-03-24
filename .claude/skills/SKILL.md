# Quant Trading System Skill

> **MAINTENANCE:** This file is a living document. When you modify code in this project, update the relevant section here in the **same commit**. Added a module? Update the file tree. Changed a config key? Update the config section. New gotcha? Add it.

**Trigger:** Use this skill when the user asks about automated trading infrastructure — market data ingestion, strategy engine, risk management, order execution, portfolio tracking, web dashboard, strategy code editor, session management, simulation mode, or Docker deployment for Binance (crypto) and Alpaca (US equities).

**Project Root:** `/home/PROJECT/QUANT_PROJECT/`
**Origin:** Custom-built modular trading platform — infrastructure only, strategy is a swappable component via web editor.
**Conda Env:** N/A — runs in Docker containers (Python 3.12)
**Branch:** `feature/multi-session` (multi-session + simulation mode)

---

## Architecture Overview

The system supports **multiple concurrent trading sessions**, each running an independent pipeline:
```
data feed → strategy engine → risk manager → order router → portfolio tracker
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

---

## File Tree

```
QUANT_PROJECT/
├── README.md                          # Architecture overview & quick start
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
│   ├── enums.py                       # Exchange, Side, Signal, OrderStatus, AssetType, OrderType, SessionType
│   ├── schemas.py                     # Pydantic v2: MarketTick, OHLCVBar, TradeSignal, OrderRequest, OrderUpdate, etc.
│   ├── config.py                      # YAML + env var hierarchical config loader (QT_ prefix)
│   └── redis_client.py               # Async Redis: pub/sub, flags, connection pooling, session_channel() helper
│
├── session/                           # Multi-session orchestration
│   ├── __init__.py
│   ├── manager.py                     # SessionManager: create/start/stop/delete sessions, pipeline lifecycle
│   └── schemas.py                     # SessionCreate, SessionUpdate Pydantic models
│
├── data/                              # Market data ingestion
│   ├── base_feed.py                   # Abstract BaseFeed (connect/disconnect/subscribe)
│   ├── normalizer.py                  # Exchange-specific → MarketTick/OHLCVBar conversion
│   ├── binance_feed.py               # Binance WebSocket trades + klines (python-binance, needs API key)
│   ├── binance_sim_feed.py           # Binance public WebSocket (no API key, session-aware)
│   ├── alpaca_feed.py                # Alpaca StockDataStream trades + bars (alpaca-py)
│   ├── yfinance_feed.py             # yfinance polling feed for stocks (session-aware, ~2s interval)
│   └── manager.py                     # Feed lifecycle: retry, signal handling, graceful shutdown
│
├── strategy/                          # Strategy engine
│   ├── base.py                        # Abstract BaseStrategy (on_tick/on_bar/on_start/on_stop)
│   ├── engine.py                      # Dynamic strategy loading, Redis consumer, signal dispatch
│   ├── validator.py                   # AST-based validation of user strategy code (enforces interface)
│   ├── user_strategies/              # Directory for user-uploaded strategies (gitignored)
│   │   └── .gitkeep
│   └── examples/
│       └── momentum.py               # Default: rolling-window momentum (loaded in editor on first use)
│
├── risk/                              # Risk management
│   ├── limits.py                      # Position size, max positions, drawdown, daily loss, kill switch checks
│   ├── kill_switch.py                # Redis-backed emergency halt (activate/deactivate/state)
│   └── manager.py                     # Signal consumer → sequential risk pipeline → OrderRequest emitter
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
├── monitoring/                        # Web interface (ALL user interaction happens here)
│   ├── app.py                         # FastAPI app factory, lifespan auto-restarts active sessions
│   ├── auth.py                        # Session-based login/logout (cookie auth, no heavy deps)
│   ├── dashboard.py                   # Dashboard API: positions, P&L, orders, equity history, kill switch
│   ├── editor.py                      # Strategy editor API: load/save/validate/deploy (per-session or global)
│   ├── settings.py                    # Settings API: global API key management, .env read/write
│   ├── sessions.py                    # Sessions REST API: CRUD + start/stop endpoints
│   ├── logger.py                      # structlog: JSON (prod) or console (dev) output
│   └── templates/
│       ├── base.html                 # Shared layout: nav bar + session sidebar + create modal + toast
│       ├── login.html                # Login page (simple form)
│       ├── dashboard.html            # Main dashboard (extends base.html): equity curve, positions, orders
│       ├── editor.html               # Code editor (extends base.html): CodeMirror, per-session deploy
│       └── settings.html             # Global API keys (extends base.html): Binance/Alpaca config
│
├── db/                                # Database layer
│   ├── models.py                      # SQLAlchemy 2.0: TradingSession, Trade, Position, Order, EquitySnapshot, AlertLog
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
└── tests/                             # Unit tests (37 tests)
    ├── conftest.py                    # Shared fixtures (mock Redis, sample data)
    ├── test_data/test_normalizer.py   # Binance trade/kline normalization
    ├── test_strategy/test_engine.py   # Momentum strategy buy/sell/hold signals
    ├── test_risk/test_manager.py      # All risk limit checks
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
| `/editor` | Strategy Editor | In-browser Python editor — per-session strategy storage via DB |
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

### Strategy Editor

- **CodeMirror** (via CDN) — syntax-highlighted Python editor
- Pre-loaded with default momentum strategy on first visit
- **Validate** button: sends code to backend, runs AST checks, returns errors
- **Deploy** button: saves to DB (per-session) or filesystem (global), triggers hot-reload
- Editor shows validation feedback inline (green = OK, red = errors)
- Session label shows which session's strategy is being edited

---

## Session Manager (session/manager.py)

Central orchestrator for all trading sessions.

### Key Classes

| Class | Purpose |
|---|---|
| `SessionPipeline` | Holds all runtime state for one session (tasks, feed, engine, risk, router, tracker) |
| `SessionManager` | CRUD + start/stop lifecycle, pipeline construction, auto-restart on crash |

### Pipeline Construction

When a session starts, `SessionManager._start_pipeline()`:
1. Creates session-specific config with namespaced Redis channels
2. Creates the appropriate data feed (BinanceSimFeed / YFinanceFeed / etc.)
3. Creates StrategyEngine, RiskManager, OrderRouter, PortfolioTracker
4. For simulation: creates SimulationAdapter + price listener task
5. Launches all components as asyncio tasks with `_run_with_restart()` (max 3 retries)

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
| `TradingSession` | id (UUID), name, session_type, is_simulation, status, config_json, starting_budget, strategy_code, strategy_class | **New** — central session record |
| `Trade` | id, session_id (FK), symbol, side, quantity, price, ... | session_id added |
| `Position` | id, session_id (FK), symbol, quantity, entry_price, ... | session_id added |
| `Order` | id, session_id (FK), symbol, side, quantity, status, exchange, ... | session_id added |
| `EquitySnapshot` | id, session_id (FK), timestamp, total_equity, cash, positions_value | session_id added |
| `AlertLog` | id, session_id (FK), level, message, source, ... | session_id added |

All `session_id` fields are nullable (backward compat with pre-session data).

---

## Strategy Code Contract (ENFORCED)

User-submitted strategy code **must** follow this interface. `strategy/validator.py` checks via AST parsing before allowing deploy.

### Required

| Rule | Detail |
|---|---|
| Must define exactly one class | That subclasses `BaseStrategy` |
| Must implement `on_tick` | Signature: `async def on_tick(self, tick: MarketTick) -> TradeSignal \| None` |
| Must implement `on_bar` | Signature: `async def on_bar(self, bar: OHLCVBar) -> TradeSignal \| None` |
| Return type | `TradeSignal` or `None` only |
| Parameter names | `tick` for on_tick, `bar` for on_bar (enforced) |

### Allowed Imports (Whitelist)

```
math, statistics, collections, itertools, functools, datetime, decimal,
numpy, pandas,
shared.enums (Exchange, Side, Signal, OrderStatus, AssetType, OrderType),
shared.schemas (MarketTick, OHLCVBar, TradeSignal),
strategy.base (BaseStrategy)
```

### Forbidden

- `os`, `sys`, `subprocess`, `importlib`, `eval`, `exec`, `open`, `__import__`
- Any network/file I/O
- Module-level side effects

### Default Strategy (Pre-loaded in Editor)

The momentum strategy from `strategy/examples/momentum.py` — rolling window of N prices, buy if above avg by threshold%, sell if below.

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

---

## Risk Checks (Sequential)

1. **Kill switch** — Redis flag (session-scoped: `session:{id}:risk:kill_switch`)
2. **Drawdown** — peak-to-trough (default 5%)
3. **Daily loss** — from day start equity (default 3%)
4. **Max positions** — total open (default 10)
5. **Position size** — per-position % of equity (default 10%)

Auto-activates kill switch on drawdown or daily loss breach.

---

## Docker Services

| Service | Command | Ports | Depends On |
|---|---|---|---|
| `redis` | Redis 7 Alpine | 6379 | — |
| `postgres` | TimescaleDB pg16 | 5432 | — |
| `engine` | `python -m scripts.run_monitor` | 8080 | redis, postgres |

**Note:** Previously 4 separate app services (data-feed, strategy, execution, monitor). Now consolidated into single `engine` service — `SessionManager` orchestrates all trading pipelines as asyncio tasks within one process.

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

`SessionType` has properties: `.is_simulation` (bool), `.exchange` (Exchange enum).

---

## Gotchas & Notes

- **Never commit `.env`** — it's gitignored. Use `.env.example` as template.
- **Telegram bot removed in v2** — all interaction is through the web UI.
- **Strategy validator** uses AST parsing, not `exec()` — code is never executed during validation.
- **User strategies** are saved to `strategy/user_strategies/` which is gitignored (user code stays local).
- **Per-session strategies** are stored in DB (`TradingSession.strategy_code`), not filesystem.
- **Hot-reload** works by publishing a reload signal to Redis; the strategy engine picks it up and re-imports.
- **Binance adapter** needs symbol for `cancel_order` and `get_order_status` — use `get_order_status_for_symbol()`.
- **Alpaca** only streams during market hours (9:30 AM – 4:00 PM ET). Feed handles this gracefully.
- **Order state machine** enforces valid transitions — invalid ones raise `InvalidTransitionError`.
- **Auth is simple** — in-memory sessions, single user. Not for public-facing deployment.
- **All Redis messages** are JSON-serialized Pydantic models (`.model_dump_json()` / `.model_validate_json()`).
- **API keys not encrypted** in DB — `TradingSession.config_json` stores plaintext (personal system, not public-facing).
- **Session auto-restart** — on container boot, `app.py` lifespan queries DB for `status='active'` sessions and restarts them.
- **SimulationAdapter clips orders** — if buy exceeds available cash, quantity is reduced to max affordable (no rejection).
- **`_run_with_restart`** — each session component auto-retries up to 3 times with 5s delay; sets session status to `error` on exhaust.
- **Legacy scripts** (`run_data.py`, `run_strategy.py`, `run_execution.py`) still exist but are unused — `run_monitor.py` is the sole entry point.
