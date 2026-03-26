# Quant Trader

An automated trading platform for crypto (Binance) and US equities (Alpaca). Weight-based portfolio strategies, real-time data collection, simulation mode, and a web dashboard — all in one process.

---

## What This Is

A modular trading platform built in Python. You write a `main(data)` function that receives rolling market data and returns portfolio weights. The platform handles data collection, weight normalization, order generation, risk management, and execution.

The system is **not** a trading strategy. It's the infrastructure that runs one. The strategy is a swappable Python function deployed through the web UI.

## Architecture (V2 — Weight-Based)

```
DataCollector (rolling numpy buffers, configurable fields & resolution)
  ↓
StrategyExecutor (compiles & runs user's main(data) → weights)
  ↓
WeightRebalancer (diffs target weights vs current positions → orders)
  ↓
RiskManager (kill switch, drawdown, daily loss checks)
  ↓
OrderRouter + Exchange Adapter (sim or live)
  ↓
PortfolioTracker (positions, P&L, equity snapshots)
```

All components run as asyncio tasks within a single FastAPI process. Sessions are isolated by database foreign keys and Redis-namespaced channels. No Docker required — runs natively with conda.

## Features

- **Multi-exchange** — Binance (crypto) + Alpaca (US equities), unified interface
- **Weight-based strategies** — `main(data) → np.ndarray` of portfolio weights, auto-normalized
- **Configurable data pipeline** — Per-field lookbacks, scrape resolution, multiple data sources per field
- **Custom data functions** — User-written Python with network access (separate from sandboxed strategy code)
- **Simulation mode** — Real market data, virtual execution (no API keys needed)
- **Backtesting** — Historical replay with same rolling buffer format as live
- **Multi-session** — Run multiple independent strategies simultaneously
- **Web dashboard** — Equity curves, positions, orders, kill switch, real-time logs
- **3-tab strategy editor** — Data Config, Custom Data, Strategy Code — all deployed together
- **Risk management** — Kill switch, drawdown limits, daily loss limits
- **Auto-restart** — Sessions resume on server reboot

## Quick Start

**Conda env:** `Quant_env` (Python 3.12, dedicated to this project)

```bash
# 1. Start Redis (if not running) and fix write errors
redis-cli CONFIG SET stop-writes-on-bgsave-error no

# 2. Start PostgreSQL
su postgres -s /bin/bash -c "/usr/lib/postgresql/14/bin/pg_ctl -D /home/PROJECT/QUANT_PROJECT/pgdata -l /home/PROJECT/QUANT_PROJECT/pgdata/logfile start"

# 3. Start the app
conda run -n Quant_env nohup python -u -m scripts.run_monitor > app_log.txt 2>&1 &

# 4. (Optional) Cloudflare tunnel for external access
nohup cloudflared tunnel --url http://localhost:8080 > cloudflared_log.txt 2>&1 &
```

Open the dashboard at `http://localhost:8080`. Default login: `admin` / `admin1234`.

## Writing a Strategy

```python
import numpy as np

def main(data: dict) -> np.ndarray:
    prices = data["price"]           # [N_symbols, lookback]
    current = prices[:, -1]          # [N_symbols]
    mean = prices.mean(axis=1)       # [N_symbols]
    safe_mean = np.where(mean != 0, mean, 1.0)
    deviation = (current - safe_mean) / safe_mean
    return deviation  # auto-normalized to sum(|w|) = 1
```

- **Input:** `data` dict with keys matching your configured fields (numpy arrays of shape `[N_symbols, lookback]`)
- **Output:** `np.ndarray` of shape `[N_symbols]` — positive = long, negative = short, zero = flat
- **Allowed imports:** `numpy`, `math`, `statistics`, `collections`, `itertools`, `functools`
- **Forbidden:** `os`, `sys`, `subprocess`, network I/O, file I/O

## Session Types

| Type | Data Source | Execution | API Keys |
|------|-----------|-----------|----------|
| Binance Simulation | Binance public WebSocket | Virtual (instant fills) | Not needed |
| Alpaca Simulation | yfinance polling (~2s) | Virtual (instant fills) | Not needed |
| Binance Live | Binance public WebSocket | Real Binance orders | Required |
| Alpaca Live | yfinance polling | Real Alpaca orders | Required |

## Project Structure

```
QUANT_PROJECT/
├── config/          # YAML configs (default, dev, prod)
├── shared/          # Enums, schemas, config loader, Redis client
├── session/         # SessionManager — multi-session orchestration
├── data/            # DataCollector + per-source fetchers (yfinance, alpaca, binance)
├── strategy/        # StrategyExecutor, WeightRebalancer, validators, examples
├── risk/            # Kill switch, drawdown, daily loss, position limits
├── execution/       # OrderRouter, exchange adapters (Binance, Alpaca, Simulation)
├── portfolio/       # Position tracking, P&L, equity snapshots, reconciliation
├── backtest/        # V2 backtesting engine (in-memory, no DB)
├── monitoring/      # FastAPI app, auth, dashboard, editor, logs, settings, templates
├── db/              # SQLAlchemy models, async session factory
├── scripts/         # Entry points (run_monitor is the main one)
└── tests/           # 96 unit tests
```

## Configuration

Layered: `config/default.yaml` → `config/{QT_ENV}.yaml` → `QT_*` environment variables.

## Safety Notes

- **Always start with simulation.** No API keys needed, uses real market data with virtual execution.
- **Never commit `.env`** — it's gitignored.
- **Risk manager is your safety net.** Kill switch auto-activates on drawdown/daily loss breach.
- **Strategy code is sandboxed** — no network, no file I/O, no OS access.
- **Custom data functions can access network** — `requests`, `urllib` allowed by design.
