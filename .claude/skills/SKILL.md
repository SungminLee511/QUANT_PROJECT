# Quant Trading System Skill

> **MAINTENANCE:** This file is a living document. When you modify code in this project, update the relevant section here in the **same commit**. Added a module? Update the file tree. Changed a config key? Update the config section. New gotcha? Add it.

**Trigger:** Use this skill when the user asks about automated trading infrastructure — market data ingestion, strategy engine, risk management, order execution, portfolio tracking, web dashboard, strategy code editor, or Docker deployment for Binance (crypto) and Alpaca (US equities).

**Project Root:** `/home/PROJECT/QUANT_PROJECT/`
**Origin:** Custom-built modular trading platform — infrastructure only, strategy is a swappable component via web editor.
**Conda Env:** N/A — runs in Docker containers (Python 3.12)

---

## File Tree

```
QUANT_PROJECT/
├── README.md                          # Architecture overview & quick start
├── Dockerfile                         # Single image, command varies per service
├── docker-compose.yml                 # Full stack: Redis, Postgres/TimescaleDB, 4 app services
├── requirements.txt                   # All Python dependencies
├── pyproject.toml                     # Project metadata, pytest config
├── .env.example                       # Template for API keys & secrets
│
├── config/
│   ├── default.yaml                   # Base config (all defaults, incl. auth credentials)
│   ├── dev.yaml                       # Dev overrides (testnet/paper, debug logging)
│   └── prod.yaml                      # Prod overrides (real trading, INFO logging)
│
├── shared/                            # Cross-service utilities
│   ├── enums.py                       # Exchange, Side, Signal, OrderStatus, AssetType, OrderType
│   ├── schemas.py                     # Pydantic v2: MarketTick, OHLCVBar, TradeSignal, OrderRequest, OrderUpdate, etc.
│   ├── config.py                      # YAML + env var hierarchical config loader (QT_ prefix)
│   └── redis_client.py               # Async Redis: pub/sub, flags, connection pooling
│
├── data/                              # Market data ingestion
│   ├── base_feed.py                   # Abstract BaseFeed (connect/disconnect/subscribe)
│   ├── normalizer.py                  # Exchange-specific → MarketTick/OHLCVBar conversion
│   ├── binance_feed.py               # Binance WebSocket trades + klines (python-binance)
│   ├── alpaca_feed.py                # Alpaca StockDataStream trades + bars (alpaca-py)
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
│   └── router.py                      # Routes OrderRequests to adapters, DB persistence, fill polling
│
├── portfolio/                         # Portfolio tracking
│   ├── tracker.py                     # Position management, equity snapshots, Redis state publishing
│   ├── pnl.py                        # Realized/unrealized P&L, win rate, daily metrics
│   └── reconciler.py                 # Periodic exchange reconciliation with drift detection
│
├── monitoring/                        # Web interface (ALL user interaction happens here)
│   ├── app.py                         # FastAPI app factory, mounts auth + dashboard + editor + settings
│   ├── auth.py                        # Session-based login/logout (cookie auth, no heavy deps)
│   ├── dashboard.py                   # Dashboard API: positions, P&L, orders, equity history, kill switch
│   ├── editor.py                      # Strategy editor API: load/save/validate/deploy user code
│   ├── settings.py                    # Settings API: API key management, .env read/write, masked display
│   ├── logger.py                      # structlog: JSON (prod) or console (dev) output
│   └── templates/
│       ├── login.html                # Login page (simple form)
│       ├── dashboard.html            # Main dashboard: equity curve, positions, orders, kill switch
│       ├── editor.html               # Code editor: CodeMirror (CDN), validate button, deploy button
│       └── settings.html             # API key config: Binance/Alpaca keys, testnet/paper toggles
│
├── db/                                # Database layer
│   ├── models.py                      # SQLAlchemy 2.0: Trade, Position, Order, EquitySnapshot, AlertLog
│   ├── session.py                     # Async session factory (asyncpg), init_db(), get_session()
│   └── migrations/
│       └── env.py                    # Alembic placeholder
│
├── scripts/                           # Service entry points
│   ├── run_data.py                    # Data feed service
│   ├── run_strategy.py               # Strategy engine service
│   ├── run_execution.py              # Risk + order router + portfolio (single process)
│   ├── run_monitor.py                # Web UI (dashboard + editor)
│   └── run_all.py                    # Dev helper: all services in one process
│
└── tests/                             # Unit tests
    ├── conftest.py                    # Shared fixtures (mock Redis, sample data)
    ├── test_data/test_normalizer.py   # Binance trade/kline normalization
    ├── test_strategy/test_engine.py   # Momentum strategy buy/sell/hold signals
    ├── test_risk/test_manager.py      # All risk limit checks
    ├── test_execution/test_router.py  # Order state machine transitions
    └── test_portfolio/test_pnl.py     # P&L calculator, win rate
```

---

## Web Interface (port 8080)

All user interaction is through the web UI. No Telegram bot, no CLI commands needed.

### Authentication

- **Simple session auth** — cookie-based, no external deps
- Default credentials: `admin` / `admin1234` (configurable in `default.yaml` → `auth`)
- Login required for all pages except `/login`
- Session stored server-side (in-memory dict, keyed by random token cookie)

### Pages

| Route | Page | Description |
|---|---|---|
| `/login` | Login | Username + password form |
| `/` | Dashboard | Equity curve, positions, orders, P&L, kill switch, system status |
| `/editor` | Strategy Editor | In-browser Python editor with validate & deploy |
| `/settings` | Settings | API key management (Binance/Alpaca), testnet/paper toggles, saved to `.env` |

### Dashboard Features

- Real-time equity curve (Chart.js via CDN)
- Open positions table with unrealized P&L
- Recent orders (last 100)
- Daily P&L metric card
- Kill switch toggle button
- Auto-refresh every 10 seconds

### Strategy Editor

- **CodeMirror** (via CDN) — syntax-highlighted Python editor
- Pre-loaded with default momentum strategy on first visit
- **Validate** button: sends code to backend, runs AST checks, returns errors
- **Deploy** button: saves to `strategy/user_strategies/`, triggers hot-reload of strategy engine
- Editor shows validation feedback inline (green = OK, red = errors)

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

| Channel | Publisher | Subscriber | Message Type |
|---|---|---|---|
| `market:ticks` | data feeds | strategy engine | `MarketTick` / `OHLCVBar` |
| `strategy:signals` | strategy engine | risk manager | `TradeSignal` |
| `execution:orders` | risk manager | order router | `OrderRequest` |
| `execution:updates` | order router | portfolio tracker | `OrderUpdate` |
| `monitoring:alerts` | risk manager | dashboard (shown in UI) | `AlertMessage` |

---

## Risk Checks (Sequential)

1. **Kill switch** — Redis flag `risk:kill_switch`
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
| `data-feed` | `run_data` | — | redis |
| `strategy` | `run_strategy` | — | redis, data-feed |
| `execution` | `run_execution` | — | redis, postgres |
| `monitor` | `run_monitor` | 8080 | redis, postgres |

---

## Gotchas & Notes

- **Never commit `.env`** — it's gitignored. Use `.env.example` as template.
- **Telegram bot removed in v2** — all interaction is through the web UI.
- **Strategy validator** uses AST parsing, not `exec()` — code is never executed during validation.
- **User strategies** are saved to `strategy/user_strategies/` which is gitignored (user code stays local).
- **Hot-reload** works by publishing a reload signal to Redis; the strategy engine picks it up and re-imports.
- **Binance adapter** needs symbol for `cancel_order` and `get_order_status` — use `get_order_status_for_symbol()`.
- **Alpaca** only streams during market hours (9:30 AM – 4:00 PM ET). Feed handles this gracefully.
- **Order state machine** enforces valid transitions — invalid ones raise `InvalidTransitionError`.
- **Auth is simple** — in-memory sessions, single user. Not for public-facing deployment.
- **All Redis messages** are JSON-serialized Pydantic models (`.model_dump_json()` / `.model_validate_json()`).
