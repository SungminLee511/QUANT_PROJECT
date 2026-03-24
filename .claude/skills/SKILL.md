# Quant Trading System Skill

> **MAINTENANCE:** This file is a living document. When you modify code in this project, update the relevant section here in the **same commit**. Added a module? Update the file tree. Changed a config key? Update the config section. New gotcha? Add it.

**Trigger:** Use this skill when the user asks about automated trading infrastructure — market data ingestion, strategy engine, risk management, order execution, portfolio tracking, monitoring dashboard, Telegram bot, or Docker deployment for Binance (crypto) and Alpaca (US equities).

**Project Root:** `/home/PROJECT/QUANT_PROJECT/`
**Origin:** Custom-built modular trading platform — infrastructure only, strategy is a swappable component.
**Conda Env:** N/A — runs in Docker containers (Python 3.12)

---

## File Tree

```
QUANT_PROJECT/
├── README.md                          # Architecture overview & quick start
├── instructions_for_claude_code.md    # [DELETED] Original build spec (now in git history)
├── Dockerfile                         # Single image, command varies per service
├── docker-compose.yml                 # Full stack: Redis, Postgres/TimescaleDB, 4 app services
├── requirements.txt                   # All Python dependencies
├── pyproject.toml                     # Project metadata, pytest config
├── .env.example                       # Template for API keys & secrets
│
├── config/
│   ├── default.yaml                   # Base config (all defaults)
│   ├── dev.yaml                       # Dev overrides (testnet/paper, debug logging)
│   └── prod.yaml                      # Prod overrides (real trading, INFO logging)
│
├── shared/                            # Cross-service utilities
│   ├── enums.py                       # Exchange, Side, Signal, OrderStatus, AssetType, OrderType
│   ├── schemas.py                     # Pydantic v2: MarketTick, OHLCVBar, TradeSignal, OrderRequest, OrderUpdate, etc.
│   ├── config.py                      # YAML + env var hierarchical config loader (QT_ prefix)
│   └── redis_client.py               # Async Redis: pub/sub, flags, connection pooling
│
├── data/                              # Market data ingestion (Phase 2)
│   ├── base_feed.py                   # Abstract BaseFeed (connect/disconnect/subscribe)
│   ├── normalizer.py                  # Exchange-specific → MarketTick/OHLCVBar conversion
│   ├── binance_feed.py               # Binance WebSocket trades + klines (python-binance)
│   ├── alpaca_feed.py                # Alpaca StockDataStream trades + bars (alpaca-py)
│   └── manager.py                     # Feed lifecycle: retry, signal handling, graceful shutdown
│
├── strategy/                          # Strategy engine (Phase 3)
│   ├── base.py                        # Abstract BaseStrategy (on_tick/on_bar/on_start/on_stop)
│   ├── engine.py                      # Dynamic strategy loading, Redis consumer, signal dispatch
│   └── examples/
│       └── momentum.py               # Placeholder: rolling-window momentum (for pipeline testing)
│
├── risk/                              # Risk management (Phase 4)
│   ├── limits.py                      # Position size, max positions, drawdown, daily loss, kill switch checks
│   ├── kill_switch.py                # Redis-backed emergency halt (activate/deactivate/state)
│   └── manager.py                     # Signal consumer → sequential risk pipeline → OrderRequest emitter
│
├── execution/                         # Order execution (Phase 5)
│   ├── order.py                       # Order state machine (PENDING→PLACED→PARTIAL→FILLED, etc.)
│   ├── base_adapter.py               # Abstract exchange adapter interface
│   ├── binance_adapter.py            # Binance: order placement, retry, balance/position queries
│   ├── alpaca_adapter.py             # Alpaca: order placement, retry, position queries
│   └── router.py                      # Routes OrderRequests to adapters, DB persistence, fill polling
│
├── portfolio/                         # Portfolio tracking (Phase 6)
│   ├── tracker.py                     # Position management, equity snapshots, Redis state publishing
│   ├── pnl.py                        # Realized/unrealized P&L, win rate, daily metrics
│   └── reconciler.py                 # Periodic exchange reconciliation with drift detection
│
├── monitoring/                        # Dashboard & alerts (Phase 7)
│   ├── dashboard.py                   # FastAPI: REST API + Jinja2 dashboard, kill switch toggle
│   ├── telegram_bot.py               # /status, /pnl, /positions, /kill, /resume + alert listener
│   ├── logger.py                      # structlog: JSON (prod) or console (dev) output
│   └── templates/
│       └── dashboard.html            # Dark-theme dashboard with Chart.js equity curve
│
├── db/                                # Database layer
│   ├── models.py                      # SQLAlchemy 2.0: Trade, Position, Order, EquitySnapshot, AlertLog
│   ├── session.py                     # Async session factory (asyncpg), init_db(), get_session()
│   └── migrations/
│       └── env.py                    # Alembic placeholder
│
├── scripts/                           # Service entry points (Phase 8)
│   ├── run_data.py                    # Data feed service
│   ├── run_strategy.py               # Strategy engine service
│   ├── run_execution.py              # Risk + order router + portfolio (single process)
│   ├── run_monitor.py                # Dashboard + Telegram bot
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

## Config System (3-Level Merge)

1. `config/default.yaml` — base defaults
2. `config/{QT_ENV}.yaml` — environment overrides (dev/prod)
3. `QT_*` environment variables — highest priority

**Key env var mappings:**

| Env Variable | Config Path |
|---|---|
| `QT_ENV` | `app.env` |
| `QT_REDIS_HOST` | `redis.host` |
| `QT_BINANCE_API_KEY` | `binance.api_key` |
| `QT_ALPACA_API_KEY` | `alpaca.api_key` |
| `QT_TELEGRAM_BOT_TOKEN` | `monitoring.telegram.bot_token` |
| `QT_DATABASE_HOST` | `database.host` |
| `QT_DB_PASSWORD` | `database.password` |

---

## Redis Channels

| Channel | Publisher | Subscriber | Message Type |
|---|---|---|---|
| `market:ticks` | data feeds | strategy engine | `MarketTick` / `OHLCVBar` |
| `strategy:signals` | strategy engine | risk manager | `TradeSignal` |
| `execution:orders` | risk manager | order router | `OrderRequest` |
| `execution:updates` | order router | portfolio tracker | `OrderUpdate` |
| `monitoring:alerts` | risk manager | Telegram bot | `AlertMessage` |

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
- **Binance adapter** needs symbol for `cancel_order` and `get_order_status` — use `get_order_status_for_symbol()`.
- **Alpaca** only streams during market hours (9:30 AM – 4:00 PM ET). Feed handles this gracefully.
- **Order state machine** enforces valid transitions — invalid ones raise `InvalidTransitionError`.
- **Dashboard has no auth in v1** — keep behind firewall/VPN in production.
- **Telegram bot** validates `chat_id` before accepting commands.
- **All Redis messages** are JSON-serialized Pydantic models (`.model_dump_json()` / `.model_validate_json()`).
