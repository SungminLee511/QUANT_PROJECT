# Quant Trading System — Claude Code Build Instructions

## Overview

Build a Python-based automated trading system that runs 24/7, trading crypto on Binance and US equities on Alpaca. The system is dockerized, uses Redis for inter-service messaging, PostgreSQL for persistence, and is designed for easy migration from a self-hosted server to AWS.

**Key constraints:**

- Latency tolerance: sub-minute (no HFT optimizations needed)
- Single strategy at launch, but architecture must support multiple strategies later
- The strategy algorithm itself is a placeholder — focus is on the infrastructure
- All services must run as separate containers via Docker Compose
- Full monitoring: web dashboard, Telegram alerts, kill switch, trade logging

-----

## Tech Stack

|Component       |Technology                    |
|----------------|------------------------------|
|Language        |Python 3.12+                  |
|Async framework |asyncio                       |
|Crypto exchange |Binance (via `python-binance`)|
|Equities broker |Alpaca (via `alpaca-py`)      |
|Message bus     |Redis 7+ (pub/sub + key-value)|
|Database        |PostgreSQL 16 + TimescaleDB   |
|ORM / DB access |SQLAlchemy 2.0 + asyncpg      |
|Web dashboard   |FastAPI + Jinja2 templates    |
|Alerts          |python-telegram-bot           |
|Config          |YAML (PyYAML) + env vars      |
|Containerization|Docker + Docker Compose       |
|Logging         |structlog (JSON output)       |
|Testing         |pytest + pytest-asyncio       |

-----

## Project Structure

Create exactly this directory layout:

```
quant-trader/
├── config/
│   ├── default.yaml          # Base configuration (all defaults)
│   ├── dev.yaml              # Dev overrides (paper trading, debug logging)
│   └── prod.yaml             # Prod overrides (real trading, reduced logging)
├── data/
│   ├── __init__.py
│   ├── base_feed.py          # Abstract base class for data feeds
│   ├── binance_feed.py       # Binance WebSocket + REST data feed
│   ├── alpaca_feed.py        # Alpaca streaming data feed
│   ├── normalizer.py         # Unified data schema (MarketTick, OHLCV)
│   └── manager.py            # Data feed lifecycle manager
├── strategy/
│   ├── __init__.py
│   ├── base.py               # BaseStrategy abstract class
│   ├── engine.py             # Strategy event loop & signal dispatch
│   └── examples/
│       ├── __init__.py
│       └── momentum.py       # Example momentum strategy (placeholder)
├── risk/
│   ├── __init__.py
│   ├── manager.py            # Pre-trade risk check pipeline
│   ├── limits.py             # Limit definitions (position, drawdown, daily loss)
│   └── kill_switch.py        # Emergency halt (Redis-backed state)
├── execution/
│   ├── __init__.py
│   ├── router.py             # Routes orders to correct exchange adapter
│   ├── base_adapter.py       # Abstract exchange adapter interface
│   ├── binance_adapter.py    # Binance order placement & tracking
│   ├── alpaca_adapter.py     # Alpaca order placement & tracking
│   └── order.py              # Order model & state machine
├── portfolio/
│   ├── __init__.py
│   ├── tracker.py            # Position & balance management
│   ├── pnl.py                # P&L calculation (realized + unrealized)
│   └── reconciler.py         # Sync local state with exchange balances
├── monitoring/
│   ├── __init__.py
│   ├── dashboard.py          # FastAPI web dashboard
│   ├── telegram_bot.py       # Telegram alert bot & kill switch control
│   ├── logger.py             # structlog configuration
│   └── templates/
│       └── dashboard.html    # Dashboard HTML template
├── db/
│   ├── __init__.py
│   ├── models.py             # SQLAlchemy ORM models
│   ├── session.py            # Async DB session factory
│   └── migrations/           # Alembic migrations directory
│       └── env.py
├── shared/
│   ├── __init__.py
│   ├── redis_client.py       # Redis connection + pub/sub helpers
│   ├── config.py             # Config loading (YAML + env merge)
│   ├── enums.py              # Shared enums (Side, OrderStatus, Exchange, etc.)
│   └── schemas.py            # Pydantic models for inter-service messages
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # Shared fixtures (mock Redis, mock DB, etc.)
│   ├── test_data/
│   │   └── test_normalizer.py
│   ├── test_strategy/
│   │   └── test_engine.py
│   ├── test_risk/
│   │   └── test_manager.py
│   ├── test_execution/
│   │   └── test_router.py
│   └── test_portfolio/
│       └── test_pnl.py
├── scripts/
│   ├── run_data.py           # Entry point: data service
│   ├── run_strategy.py       # Entry point: strategy engine
│   ├── run_execution.py      # Entry point: execution + risk + portfolio
│   ├── run_monitor.py        # Entry point: dashboard + telegram bot
│   └── run_all.py            # Dev helper: runs all services in one process
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── pyproject.toml
```

-----

## Implementation Details — Build In This Order

### Phase 1: Foundation (shared/, config/, db/)

#### 1.1 — shared/enums.py

Define enums used everywhere:

```python
from enum import Enum

class Exchange(str, Enum):
    BINANCE = "binance"
    ALPACA = "alpaca"

class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class OrderStatus(str, Enum):
    PENDING = "pending"
    PLACED = "placed"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"

class AssetType(str, Enum):
    CRYPTO = "crypto"
    EQUITY = "equity"
```

#### 1.2 — shared/schemas.py

Use Pydantic v2 models for all inter-service messages. Every message that goes through Redis must be serializable via `.model_dump_json()` and deserializable via `.model_validate_json()`.

Key schemas to define:

- `MarketTick` — symbol, price, volume, timestamp, exchange
- `OHLCVBar` — symbol, open, high, low, close, volume, interval, timestamp, exchange
- `TradeSignal` — symbol, signal (BUY/SELL/HOLD), strength (float 0-1), strategy_id, timestamp, metadata (dict)
- `OrderRequest` — symbol, side, quantity, order_type (market/limit), price (optional), exchange, strategy_id
- `OrderUpdate` — order_id, status, filled_qty, avg_price, timestamp, exchange
- `RiskCheckResult` — approved (bool), reason (str), original_signal (TradeSignal)

#### 1.3 — shared/config.py

Implement hierarchical config loading:

1. Load `config/default.yaml` as base
1. Merge environment-specific YAML (dev/prod) on top using `QT_ENV` env var
1. Override any value with env vars prefixed with `QT_` (e.g., `QT_REDIS_HOST` overrides `redis.host`)
1. Return a frozen dataclass or Pydantic Settings object

Config structure in YAML:

```yaml
# config/default.yaml
app:
  name: "quant-trader"
  env: "dev"
  log_level: "INFO"

redis:
  host: "localhost"
  port: 6379
  db: 0
  channels:
    market_data: "market:ticks"
    signals: "strategy:signals"
    orders: "execution:orders"
    order_updates: "execution:updates"
    alerts: "monitoring:alerts"

database:
  host: "localhost"
  port: 5432
  name: "quant_trader"
  user: "quant"
  password: "changeme"

binance:
  api_key: ""       # Override via QT_BINANCE_API_KEY
  api_secret: ""    # Override via QT_BINANCE_API_SECRET
  testnet: true     # Use testnet in dev
  symbols:
    - "BTCUSDT"
    - "ETHUSDT"

alpaca:
  api_key: ""       # Override via QT_ALPACA_API_KEY
  api_secret: ""    # Override via QT_ALPACA_API_SECRET
  paper: true       # Use paper trading in dev
  base_url: "https://paper-api.alpaca.markets"
  symbols:
    - "AAPL"
    - "SPY"

strategy:
  id: "momentum_v1"
  module: "strategy.examples.momentum"
  class_name: "MomentumStrategy"
  params: {}        # Strategy-specific params

risk:
  max_position_pct: 0.10       # Max 10% of portfolio per position
  max_drawdown_pct: 0.05       # Halt at 5% drawdown
  max_daily_loss_pct: 0.03     # Halt at 3% daily loss
  max_open_positions: 10
  kill_switch_key: "risk:kill_switch"

portfolio:
  base_currency: "USDT"
  reconcile_interval_sec: 60

monitoring:
  dashboard:
    host: "0.0.0.0"
    port: 8080
  telegram:
    bot_token: ""   # Override via QT_TELEGRAM_BOT_TOKEN
    chat_id: ""     # Override via QT_TELEGRAM_CHAT_ID
    enabled: false
```

#### 1.4 — shared/redis_client.py

Create a Redis helper class:

- Async Redis connection using `redis.asyncio`
- `publish(channel, message)` — serialize Pydantic model and publish
- `subscribe(channel, callback)` — subscribe and deserialize messages into Pydantic models
- `get_flag(key)` / `set_flag(key, value)` — for kill switch and state flags
- Connection pooling and auto-reconnect

#### 1.5 — db/models.py

Define SQLAlchemy 2.0 ORM models:

- `Trade` — id, order_id, symbol, side, quantity, price, exchange, strategy_id, timestamp, fees
- `Position` — id, symbol, exchange, quantity, avg_entry_price, current_price, unrealized_pnl, updated_at
- `Order` — id, external_id, symbol, side, quantity, filled_quantity, order_type, status, exchange, strategy_id, created_at, updated_at
- `EquitySnapshot` — id, timestamp, total_equity, cash, positions_value (for P&L charting)
- `AlertLog` — id, level, message, source, timestamp

Use TimescaleDB hypertable for `EquitySnapshot` (create via raw SQL migration).

#### 1.6 — db/session.py

Async session factory using `create_async_engine` with asyncpg. Provide:

- `get_session()` async context manager
- `init_db()` — creates tables on startup
- Connection pool settings from config

#### 1.7 — monitoring/logger.py

Configure structlog for JSON output:

- Timestamp, log level, service name, and message in every log line
- Bind context (e.g., symbol, order_id) per-logger
- Console renderer for dev, JSON for prod
- Log to stdout (Docker captures it)

-----

### Phase 2: Market Data (data/)

#### 2.1 — data/base_feed.py

Abstract base class:

```python
from abc import ABC, abstractmethod

class BaseFeed(ABC):
    @abstractmethod
    async def connect(self): ...

    @abstractmethod
    async def disconnect(self): ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]): ...
```

#### 2.2 — data/normalizer.py

Functions to convert exchange-specific data into `MarketTick` and `OHLCVBar` Pydantic models. Each exchange returns data in different formats — this module normalizes them.

#### 2.3 — data/binance_feed.py

Implement `BaseFeed` for Binance:

- Use `python-binance` `AsyncClient` and `BinanceSocketManager`
- Subscribe to trade streams and kline (candlestick) streams
- On each message, normalize to `MarketTick` / `OHLCVBar` and publish to Redis channel `market:ticks`
- Handle reconnection on WebSocket drop (built into python-binance, but add logging)
- Respect rate limits

#### 2.4 — data/alpaca_feed.py

Implement `BaseFeed` for Alpaca:

- Use `alpaca-py` `StockDataStream`
- Subscribe to trade and bar updates for configured symbols
- Normalize and publish to the same Redis channel `market:ticks`
- Note: Alpaca only streams during market hours (9:30 AM – 4:00 PM ET). The feed should handle this gracefully — log when market is closed, don’t error out
- Handle extended hours data if configured

#### 2.5 — data/manager.py

Data feed lifecycle manager:

- Instantiates correct feed(s) based on config
- Starts all feeds concurrently using `asyncio.gather()`
- Handles graceful shutdown on SIGTERM/SIGINT
- Restart logic: if a feed dies, wait 5 seconds, try again, max 5 retries

-----

### Phase 3: Strategy Engine (strategy/)

#### 3.1 — strategy/base.py

```python
from abc import ABC, abstractmethod
from shared.schemas import MarketTick, OHLCVBar, TradeSignal

class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, params: dict):
        self.strategy_id = strategy_id
        self.params = params

    @abstractmethod
    async def on_tick(self, tick: MarketTick) -> TradeSignal | None:
        """Process a single tick. Return a signal or None."""
        ...

    @abstractmethod
    async def on_bar(self, bar: OHLCVBar) -> TradeSignal | None:
        """Process a completed OHLCV bar. Return a signal or None."""
        ...

    async def on_start(self):
        """Called once when the strategy starts. Override for initialization."""
        pass

    async def on_stop(self):
        """Called on shutdown. Override for cleanup."""
        pass
```

#### 3.2 — strategy/examples/momentum.py

A dead-simple placeholder strategy:

- Track a rolling window of N prices (e.g., 20)
- If current price > average of window by X%, emit BUY signal
- If current price < average of window by X%, emit SELL signal
- Otherwise emit HOLD (or return None)
- This is deliberately naive — it exists to test the pipeline, not to make money

#### 3.3 — strategy/engine.py

The strategy event loop:

- On startup, dynamically import the strategy class from config (`strategy.module` + `strategy.class_name`)
- Subscribe to Redis channel `market:ticks`
- For each incoming message, deserialize and call `strategy.on_tick()` or `strategy.on_bar()`
- If the strategy returns a non-None signal that is not HOLD, publish `TradeSignal` to Redis channel `strategy:signals`
- Support future multi-strategy by making the engine a list of strategies (but launch with one)

-----

### Phase 4: Risk Management (risk/)

#### 4.1 — risk/limits.py

Define risk limit checks as individual functions or classes:

- `check_position_size(signal, portfolio_state, config)` → bool + reason
- `check_max_positions(signal, portfolio_state, config)` → bool + reason
- `check_drawdown(equity_history, config)` → bool + reason
- `check_daily_loss(today_pnl, config)` → bool + reason
- `check_kill_switch(redis_client)` → bool + reason

Each check returns a `(approved: bool, reason: str)` tuple.

#### 4.2 — risk/kill_switch.py

Redis-backed kill switch:

- `is_active()` — check Redis key `risk:kill_switch`, returns bool
- `activate(reason: str)` — set flag to “active” with reason and timestamp
- `deactivate()` — clear the flag
- When active, ALL signals are rejected
- Can be triggered manually (via Telegram bot or dashboard) or automatically (by risk limit breach)

#### 4.3 — risk/manager.py

Risk check pipeline:

- Subscribe to Redis channel `strategy:signals`
- For each `TradeSignal`, run it through ALL risk checks sequentially
- If all pass, publish an `OrderRequest` to Redis channel `execution:orders`
- If any fail, log the rejection with reason, publish alert to `monitoring:alerts`
- The risk manager MUST be stateful — it needs to know current positions, equity, etc. It should query the portfolio tracker or maintain a local cache

-----

### Phase 5: Order Execution (execution/)

#### 5.1 — execution/order.py

Order state machine:

- Define `Order` dataclass with status transitions
- Valid transitions: PENDING → PLACED → PARTIAL → FILLED, PENDING → REJECTED, PLACED → CANCELLED, any → FAILED
- Reject invalid transitions with clear error messages

#### 5.2 — execution/base_adapter.py

Abstract exchange adapter:

```python
from abc import ABC, abstractmethod

class BaseExchangeAdapter(ABC):
    @abstractmethod
    async def place_order(self, order_request: OrderRequest) -> str:
        """Place an order. Returns external order ID."""
        ...

    @abstractmethod
    async def cancel_order(self, external_order_id: str) -> bool:
        ...

    @abstractmethod
    async def get_order_status(self, external_order_id: str) -> OrderUpdate:
        ...

    @abstractmethod
    async def get_balances(self) -> dict:
        ...

    @abstractmethod
    async def get_positions(self) -> list:
        ...
```

#### 5.3 — execution/binance_adapter.py

Implement `BaseExchangeAdapter` for Binance:

- Use `python-binance` `AsyncClient`
- Map `OrderRequest` to Binance’s order params
- Handle Binance-specific quirks: lot size filters, price precision, min notional
- Poll order status for fills (or use user data stream WebSocket)
- Retry on transient errors (HTTP 5xx, rate limits) with exponential backoff

#### 5.4 — execution/alpaca_adapter.py

Implement `BaseExchangeAdapter` for Alpaca:

- Use `alpaca-py` `TradingClient`
- Map `OrderRequest` to Alpaca’s order params
- Handle Alpaca-specific rules: PDT rule awareness (log warning), fractional shares, market hours
- Alpaca supports WebSocket for order updates — use it

#### 5.5 — execution/router.py

Order router:

- Subscribe to Redis channel `execution:orders`
- For each `OrderRequest`, determine which adapter to use based on `exchange` field
- Call `adapter.place_order()` and persist the `Order` to PostgreSQL
- Start tracking the order for fill updates
- On fill/update, publish `OrderUpdate` to Redis channel `execution:updates` and persist to DB
- Run a periodic loop (every 10s) to poll open order statuses as a safety net

-----

### Phase 6: Portfolio Tracking (portfolio/)

#### 6.1 — portfolio/tracker.py

Central position and balance tracker:

- Subscribe to Redis channel `execution:updates`
- On each `OrderUpdate` with status FILLED or PARTIAL, update local position state
- Maintain a dict of `{symbol: Position}` in memory + persist to DB
- Provide methods: `get_position(symbol)`, `get_all_positions()`, `get_total_equity()`
- Expose current state via Redis keys for other services to read (e.g., risk manager)

#### 6.2 — portfolio/pnl.py

P&L calculation:

- Realized P&L: computed on position close (sell qty * (sell_price - avg_entry_price))
- Unrealized P&L: computed on each tick (current_price - avg_entry_price) * position_qty
- Daily P&L: sum of realized + change in unrealized since market open
- Aggregate metrics: total P&L, win rate, average win/loss, Sharpe ratio (if enough data)
- Store `EquitySnapshot` to DB every 60 seconds for charting

#### 6.3 — portfolio/reconciler.py

Exchange reconciliation:

- Every N seconds (configurable, default 60), query actual balances and positions from Binance and Alpaca
- Compare with local state
- If drift detected (e.g., manual trade on exchange, fill we missed), log a warning and update local state
- This is a safety net — the normal flow keeps state via order updates

-----

### Phase 7: Monitoring (monitoring/)

#### 7.1 — monitoring/dashboard.py

FastAPI web dashboard:

- `GET /` — main dashboard page (Jinja2 template)
- `GET /api/positions` — JSON of current positions
- `GET /api/pnl` — JSON of P&L metrics
- `GET /api/orders` — recent orders (last 100)
- `GET /api/equity-history` — equity snapshots for charting
- `GET /api/status` — system health (service uptime, last tick time, kill switch state)
- `POST /api/kill-switch` — toggle kill switch on/off
- Serve on port 8080
- The HTML template should use a lightweight JS charting library (Chart.js via CDN) for equity curves
- Auto-refresh every 10 seconds via JavaScript
- IMPORTANT: Keep the dashboard simple. Server-rendered HTML, no React, no build step

#### 7.2 — monitoring/telegram_bot.py

Telegram bot for alerts and control:

- On trade execution: send message with symbol, side, qty, price, P&L
- On risk event: send warning with reason
- On error: send error message with service name and details
- Commands:
  - `/status` — current positions, equity, system health
  - `/pnl` — today’s P&L summary
  - `/kill` — activate kill switch
  - `/resume` — deactivate kill switch
  - `/positions` — list open positions
- Subscribe to Redis channel `monitoring:alerts` for incoming alerts
- Only send to configured `chat_id` (do not accept commands from unknown users)
- Must be disableable via config (`monitoring.telegram.enabled`)

#### 7.3 — monitoring/logger.py

Already described in Phase 1. Ensure all services use the same logger config. Every service should log:

- Startup and shutdown events
- Every trade signal, risk decision, and order event
- Errors with full tracebacks
- Performance metrics (tick processing time, order round-trip time)

-----

### Phase 8: Entry Points & Docker (scripts/, Docker)

#### 8.1 — Entry point scripts

Each script in `scripts/` is a standalone entry point:

```python
# scripts/run_data.py
import asyncio
from shared.config import load_config
from monitoring.logger import setup_logging
from data.manager import DataFeedManager

async def main():
    config = load_config()
    setup_logging(config)
    manager = DataFeedManager(config)
    await manager.run()

if __name__ == "__main__":
    asyncio.run(main())
```

Create similar entry points for:

- `run_data.py` — starts data feed manager
- `run_strategy.py` — starts strategy engine
- `run_execution.py` — starts risk manager + order router + portfolio tracker (these are tightly coupled, run in one process)
- `run_monitor.py` — starts FastAPI dashboard + Telegram bot

Also create `run_all.py` for development — runs all services in a single process using `asyncio.gather()`. This is convenient but not used in production.

#### 8.2 — Dockerfile

Single Dockerfile for all Python services (which service runs is determined by the command):

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command (overridden per service in docker-compose)
CMD ["python", "-m", "scripts.run_all"]
```

#### 8.3 — docker-compose.yml

```yaml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: quant_trader
      POSTGRES_USER: quant
      POSTGRES_PASSWORD: ${QT_DB_PASSWORD:-changeme}
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quant"]
      interval: 10s
      timeout: 5s
      retries: 5

  data-feed:
    build: .
    command: python -m scripts.run_data
    env_file: .env
    environment:
      QT_ENV: prod
      QT_REDIS_HOST: redis
      QT_DATABASE_HOST: postgres
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  strategy:
    build: .
    command: python -m scripts.run_strategy
    env_file: .env
    environment:
      QT_ENV: prod
      QT_REDIS_HOST: redis
      QT_DATABASE_HOST: postgres
    depends_on:
      redis:
        condition: service_healthy
      data-feed:
        condition: service_started
    restart: unless-stopped

  execution:
    build: .
    command: python -m scripts.run_execution
    env_file: .env
    environment:
      QT_ENV: prod
      QT_REDIS_HOST: redis
      QT_DATABASE_HOST: postgres
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    restart: unless-stopped

  monitor:
    build: .
    command: python -m scripts.run_monitor
    env_file: .env
    environment:
      QT_ENV: prod
      QT_REDIS_HOST: redis
      QT_DATABASE_HOST: postgres
    ports:
      - "8080:8080"
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  redis_data:
  pg_data:
```

#### 8.4 — requirements.txt

```
# Async
asyncio-mqtt>=2.0
redis[hiredis]>=5.0

# Exchanges
python-binance>=1.0.19
alpaca-py>=0.21

# Database
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
alembic>=1.13

# Web & API
fastapi>=0.109
uvicorn[standard]>=0.27
jinja2>=3.1

# Alerts
python-telegram-bot>=21.0

# Data & Config
pydantic>=2.5
pydantic-settings>=2.1
pyyaml>=6.0
pandas>=2.1
numpy>=1.26

# Logging
structlog>=24.1

# Testing
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=4.1

# Utilities
python-dotenv>=1.0
```

#### 8.5 — .env.example

```bash
# Environment
QT_ENV=dev

# Binance
QT_BINANCE_API_KEY=your_binance_api_key
QT_BINANCE_API_SECRET=your_binance_api_secret

# Alpaca
QT_ALPACA_API_KEY=your_alpaca_api_key
QT_ALPACA_API_SECRET=your_alpaca_api_secret

# Telegram (optional)
QT_TELEGRAM_BOT_TOKEN=your_telegram_bot_token
QT_TELEGRAM_CHAT_ID=your_telegram_chat_id

# Database
QT_DB_PASSWORD=changeme

# Redis (only override if not using Docker)
# QT_REDIS_HOST=localhost
# QT_REDIS_PORT=6379
```

#### 8.6 — .gitignore

```
__pycache__/
*.pyc
*.pyo
.env
*.egg-info/
dist/
build/
.pytest_cache/
.mypy_cache/
.venv/
venv/
*.log
```

-----

## Implementation Guidelines

### Error Handling

- Every service must handle exceptions gracefully — never crash silently
- Use try/except around all exchange API calls, with structured logging
- On transient errors (network, rate limit), retry with exponential backoff (base 2s, max 60s, max 5 retries)
- On fatal errors (invalid API key, account frozen), log and halt the service — don’t retry
- All services must handle SIGTERM/SIGINT for graceful shutdown (cancel tasks, close connections)

### Async Patterns

- Use `asyncio` throughout. No threading, no multiprocessing within a service
- Each service has one `async def main()` as its event loop
- Use `asyncio.TaskGroup` (Python 3.11+) or `asyncio.gather()` for concurrent operations
- Always use `async with` for database sessions and Redis connections

### Redis Message Format

- All messages on Redis pub/sub are JSON-serialized Pydantic models
- Channel names are defined in config, not hardcoded
- Messages include a `timestamp` and `source` field for debugging

### Database Patterns

- Use SQLAlchemy 2.0 async style with `AsyncSession`
- Always use `async with get_session() as session:` — never leave sessions open
- Bulk inserts for high-frequency data (batch equity snapshots)
- Index on: `Order.symbol`, `Order.created_at`, `Trade.symbol`, `Trade.timestamp`, `EquitySnapshot.timestamp`

### Testing Strategy

- Unit tests: test each component in isolation with mocked Redis and DB
- Integration tests: test the full pipeline with real Redis and PostgreSQL (use docker-compose for test infra)
- Never test against real exchanges — use mocks or testnet/paper accounts
- Test the risk manager thoroughly — this is the safety-critical component

### Security

- NEVER commit API keys or secrets to git
- All secrets via environment variables
- The `.env` file must be in `.gitignore`
- The Telegram bot must validate `chat_id` before accepting commands
- The dashboard should be behind a firewall or VPN in production (no auth built-in for v1)

### AWS Migration Path

When ready to migrate from self-hosted to AWS:

- Each docker-compose service maps to an ECS Fargate task
- Redis → ElastiCache
- PostgreSQL → RDS (with TimescaleDB extension or use TimeStream)
- Dashboard → behind ALB with Cognito auth
- Secrets → AWS Secrets Manager (replace env vars)
- Logs → CloudWatch (structlog JSON works natively)
- No code changes needed — only infrastructure config

-----

## Build Order Checklist

Build and test in this exact order. Each phase should be working before moving to the next.

1. [ ] **Foundation** — config loading, Redis client, DB models, logger
1. [ ] **Market Data** — Binance + Alpaca feeds publishing to Redis (test with `redis-cli subscribe`)
1. [ ] **Strategy Engine** — consuming ticks, running placeholder strategy, publishing signals
1. [ ] **Risk Manager** — consuming signals, applying checks, forwarding approved orders
1. [ ] **Execution** — consuming order requests, placing orders on testnet/paper, tracking fills
1. [ ] **Portfolio** — tracking positions from fill updates, computing P&L, reconciliation
1. [ ] **Monitoring** — dashboard showing live data, Telegram bot sending alerts
1. [ ] **Docker** — everything running in docker-compose, test full pipeline end-to-end
1. [ ] **Testing** — unit tests for all modules, integration test for full pipeline