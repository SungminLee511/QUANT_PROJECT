# Quant Trader

An automated trading system for crypto (Binance) and US equities (Alpaca) that runs 24/7 on a self-hosted server, with a clear migration path to AWS.

-----

## What This Is

A modular, containerized trading platform built in Python. You plug in your trading strategy, configure your risk limits, and it handles everything else — data ingestion, order execution, position tracking, P&L reporting, and alerting.

The system is **not** a trading strategy. It’s the infrastructure that runs one. The strategy is a swappable component — you write a Python class that receives market data and returns buy/sell signals. The platform handles the rest.

## Architecture

```
┌─────────────┐   ┌─────────────┐
│ Binance API  │   │  Alpaca API  │
└──────┬───────┘   └──────┬───────┘
       │   WebSocket/REST  │
       └────────┬──────────┘
                │
       ┌────────▼────────┐
       │  Data Service    │  ← Ingests & normalizes market data
       └────────┬────────┘
                │  Redis Pub/Sub
       ┌────────▼────────┐
       │ Strategy Engine  │  ← Your algorithm lives here
       └────────┬────────┘
                │  Signals
       ┌────────▼────────┐     ┌──────────────────┐
       │  Risk Manager    │────►  Order Execution   │
       └─────────────────┘     └────────┬──────────┘
                                        │  Fills
                               ┌────────▼──────────┐
                               │ Portfolio Tracker   │
                               └────────┬──────────┘
                                        │  Metrics
                               ┌────────▼──────────┐
                               │    Monitoring       │
                               │  Dashboard + Alerts │
                               └────────────────────┘
```

Every box is a separate Docker container. They communicate through Redis pub/sub. State is persisted in PostgreSQL (with TimescaleDB for time-series data like equity curves).

## Features

- **Multi-exchange support** — Binance for crypto, Alpaca for equities, unified under one interface
- **Real-time data ingestion** — WebSocket streams for live price data, normalized into a common format
- **Pluggable strategies** — Write a Python class, drop it in, configure via YAML
- **Risk management** — Position limits, drawdown checks, daily loss limits, kill switch
- **Order management** — Smart routing, retry logic, state tracking, exchange reconciliation
- **Portfolio tracking** — Positions, realized/unrealized P&L, equity curve snapshots
- **Web dashboard** — Real-time positions, P&L charts, system health, kill switch toggle
- **Telegram alerts** — Trade notifications, risk warnings, error alerts, remote kill switch
- **Structured logging** — JSON logs from every service for debugging and audit
- **Dockerized** — One command to start everything, designed for AWS migration

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Binance API key (testnet for development)
- Alpaca API key (paper trading for development)
- Telegram bot token (optional, for alerts)

### Setup

1. Clone the repo and create your environment file:

```bash
git clone <repo-url> && cd quant-trader
cp .env.example .env
```

1. Add your API keys to `.env`:

```bash
QT_BINANCE_API_KEY=your_key
QT_BINANCE_API_SECRET=your_secret
QT_ALPACA_API_KEY=your_key
QT_ALPACA_API_SECRET=your_secret
```

1. Start everything:

```bash
docker-compose up -d
```

1. Open the dashboard at `http://localhost:8080`

### Development Mode

To run all services in a single process without Docker (useful for debugging):

```bash
pip install -r requirements.txt
python -m scripts.run_all
```

## Writing a Strategy

Your strategy is a Python class that extends `BaseStrategy`:

```python
from strategy.base import BaseStrategy
from shared.schemas import MarketTick, TradeSignal
from shared.enums import Signal

class MyStrategy(BaseStrategy):
    async def on_tick(self, tick: MarketTick) -> TradeSignal | None:
        # Your logic here
        if should_buy(tick):
            return TradeSignal(
                symbol=tick.symbol,
                signal=Signal.BUY,
                strength=0.8,
                strategy_id=self.strategy_id,
            )
        return None

    async def on_bar(self, bar):
        return None
```

Point to it in your config:

```yaml
strategy:
  id: "my_strategy_v1"
  module: "strategy.my_strategy"
  class_name: "MyStrategy"
  params:
    lookback: 20
    threshold: 0.02
```

Restart the strategy service and it picks up the new strategy.

## Configuration

Config is layered: `config/default.yaml` → `config/{env}.yaml` → environment variables.

Environment variables override everything and use the `QT_` prefix with underscores for nesting:

|Env Variable           |Overrides                      |
|-----------------------|-------------------------------|
|`QT_ENV`               |`app.env`                      |
|`QT_REDIS_HOST`        |`redis.host`                   |
|`QT_BINANCE_API_KEY`   |`binance.api_key`              |
|`QT_ALPACA_API_KEY`    |`alpaca.api_key`               |
|`QT_TELEGRAM_BOT_TOKEN`|`monitoring.telegram.bot_token`|

## Risk Management

Every signal passes through the risk manager before an order is placed. Built-in checks:

|Check           |Default      |Description                         |
|----------------|-------------|------------------------------------|
|Position size   |10% of equity|Max allocation per position         |
|Max positions   |10           |Total open positions allowed        |
|Max drawdown    |5%           |Halt trading on peak-to-trough drop |
|Daily loss limit|3%           |Halt trading on daily loss threshold|
|Kill switch     |Off          |Manual emergency halt               |

The kill switch can be triggered from the web dashboard, Telegram (`/kill`), or automatically when drawdown/daily loss limits are breached.

## Monitoring

### Web Dashboard

Available at `http://localhost:8080` with:

- Live positions and P&L
- Equity curve chart
- Recent orders and trades
- System health indicators
- Kill switch toggle

### Telegram Bot

Commands:

- `/status` — System overview
- `/pnl` — Today’s P&L
- `/positions` — Open positions
- `/kill` — Activate kill switch
- `/resume` — Deactivate kill switch

Automatic alerts for trade executions, risk events, and system errors.

## Project Structure

```
quant-trader/
├── config/            # YAML configs per environment
├── data/              # Market data ingestion (Binance + Alpaca feeds)
├── strategy/          # Strategy engine + implementations
├── risk/              # Risk management & kill switch
├── execution/         # Order routing & exchange adapters
├── portfolio/         # Position tracking & P&L
├── monitoring/        # Dashboard, Telegram bot, logging
├── db/                # SQLAlchemy models & migrations
├── shared/            # Redis client, config loader, schemas, enums
├── scripts/           # Service entry points
├── tests/             # Unit + integration tests
└── docker-compose.yml # Full stack orchestration
```

## AWS Migration

The system is designed to move from a self-hosted server to AWS without code changes:

|Self-Hosted       |AWS Equivalent |
|------------------|---------------|
|Docker Compose    |ECS Fargate    |
|Local Redis       |ElastiCache    |
|Local PostgreSQL  |RDS PostgreSQL |
|`.env` file       |Secrets Manager|
|stdout logs       |CloudWatch Logs|
|Direct port access|ALB + Cognito  |

Each Docker service becomes an ECS task definition. Infrastructure config changes, but application code stays the same.

## Safety Notes

- **Always start with paper/testnet trading.** Binance testnet and Alpaca paper trading are configured by default in dev mode.
- **Never commit API keys.** The `.env` file is gitignored.
- **Test your strategy in backtest mode** before running it live.
- **The risk manager is your safety net.** Configure conservative limits and tighten as you gain confidence.
- **The dashboard has no authentication in v1.** Keep it behind a firewall or VPN when running on a public 