# Database Guide — Quant Trading System

A beginner-friendly walkthrough of how the database layer works in this project.

---

## 1. What's a Database and Why Do You Need One?

Your trading system generates **data that needs to survive restarts**: sessions, trades, orders, positions, equity history. If you stored this only in Python variables (RAM), everything disappears when the container stops. A **database** is just a program that writes structured data to disk and lets you query it later.

This project uses **PostgreSQL** (Postgres) — the most popular open-source relational database. Think of it like a spreadsheet app that runs as a server process.

---

## 2. Tables = Spreadsheets

The database `quant_trader` has **6 tables** (defined in `db/models.py`). Each table is like an Excel sheet:

```
trading_sessions    ← One row per session you create in the UI
├── trades          ← Every buy/sell fill
├── positions       ← Current holdings per session+symbol
├── orders          ← Every order placed (pending, filled, cancelled...)
├── equity_snapshots ← Periodic snapshots of total portfolio value (for the chart)
└── alert_logs      ← Risk alerts, errors, etc.
```

Each row in `trades`, `positions`, etc. has a `session_id` column that **links it back** to which trading session it belongs to. This is a **foreign key** — it's like saying "this trade belongs to session X."

---

## 3. The Stack: Postgres → SQLAlchemy → Your Python Code

```
Your Python code
      ↓
  SQLAlchemy  (ORM — translates Python objects ↔ SQL queries)
      ↓
    asyncpg   (network driver — talks TCP to Postgres)
      ↓
  PostgreSQL  (the actual database server, running in Docker)
      ↓
  pg_data volume  (files on disk that survive container restarts)
```

### What each layer does:

- **PostgreSQL** — the server. Runs in its own Docker container. Stores data in files at `/var/lib/postgresql/data` (mapped to the `pg_data` Docker volume).

- **asyncpg** — a Python library that speaks the Postgres wire protocol. It's "async" meaning it doesn't block your event loop while waiting for DB responses (important since the whole app is async).

- **SQLAlchemy** — the **ORM** (Object-Relational Mapper). Instead of writing raw SQL like `SELECT * FROM trades WHERE session_id='abc'`, you write Python:

```python
# This Python...
session.query(Trade).filter(Trade.session_id == "abc").all()

# ...gets translated to this SQL automatically:
# SELECT * FROM trades WHERE session_id = 'abc'
```

Each table is defined as a **Python class** in `db/models.py`:

```python
class Trade(Base):
    __tablename__ = "trades"         # ← actual table name in Postgres
    id = mapped_column(Integer, primary_key=True)  # ← auto-incrementing row ID
    session_id = mapped_column(String(36), ForeignKey("trading_sessions.id"))
    symbol = mapped_column(String(20))
    price = mapped_column(Float)
    # ... etc
```

When your code does `trade = Trade(symbol="BTCUSDT", price=67000, ...)` and commits it, SQLAlchemy generates an `INSERT INTO trades ...` SQL statement and sends it via asyncpg.

---

## 4. The Connection: `db/session.py`

This file manages **how the app connects** to Postgres:

```python
# 1. Build the URL (where to connect)
"postgresql+asyncpg://quant:changeme@postgres:5432/quant_trader"
#    ↑driver          ↑user ↑password  ↑host   ↑port ↑database name

# 2. Create an "engine" (connection pool)
_engine = create_async_engine(url, pool_size=10)
#         ↑ This holds 10 TCP connections to Postgres, reuses them

# 3. Create a "session factory" (hands out DB sessions)
_session_factory = async_sessionmaker(_engine)
```

When any part of the app needs to talk to the DB:

```python
async with get_session() as session:
    # session = one database transaction
    trade = Trade(symbol="BTCUSDT", ...)
    session.add(trade)        # stage the insert
    # auto-commits when exiting the `async with` block
    # auto-rollbacks on exception (undo everything if error)
```

---

## 5. TimescaleDB: What and Why?

**TimescaleDB** is a Postgres **extension** (plugin) that optimizes time-series data — data where every row has a timestamp and you mostly query by time range ("show me equity snapshots from the last 24h").

Regular Postgres would work, but gets slow with millions of time-series rows. TimescaleDB automatically partitions the data into time-based chunks. You use it the same way (normal SQL), it's just faster for time queries.

That's why `db/init.sql` runs:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
```

This "activates" TimescaleDB inside the Postgres database.

---

## 6. Alembic: Schema Migration

Here's the problem Alembic solves:

> You have a running database with real data. Now you want to add a column to the `orders` table. You can't just delete everything and recreate — you'd lose all your trading history.

**Alembic** tracks schema changes as numbered "migration" files. Each one says "do this change" (upgrade) and "undo it" (downgrade):

```
alembic/versions/
└── 001_initial_schema.py    ← "create all 6 tables from scratch"
    (future: 002_add_column_x.py, 003_rename_table_y.py, ...)
```

Alembic keeps a special table in the database called `alembic_version` that stores which migration number it's currently at. When you run:

```bash
alembic upgrade head
```

It checks: "DB is at version 0 (empty), latest migration is 001" → runs 001 → DB is now at version 001. Next time you run it: "DB is at 001, latest is 001" → nothing to do.

### Why do we need BOTH Alembic AND `create_all()`?

- **Alembic** = the primary, production-grade way. Handles incremental changes.
- **`Base.metadata.create_all()`** (in `db/session.py`) = safety net. If Alembic state is somehow messed up, this creates any missing tables. It's idempotent (safe to run twice — skips existing tables).

---

## 7. The Boot Sequence (What Happens on `docker-compose up`)

```
1. Postgres starts → creates empty quant_trader database
                   → runs db/init.sql (enables TimescaleDB) [first time only]
                   → passes healthcheck (pg_isready)

2. db-init starts  → waits for Postgres to accept real connections (asyncpg check)
                   → runs alembic upgrade head → creates all tables
                   → exits successfully

3. Redis starts    → passes healthcheck (redis-cli ping)

4. Engine starts   → (only after db-init completed AND redis healthy)
                   → FastAPI lifespan calls init_db() (safety net create_all)
                   → connects to Redis
                   → auto-restarts previously active sessions
                   → serves web UI on :8080
```

---

## 8. The Docker Volume: Why Data Survives (or Doesn't)

```
docker-compose down          → stops containers, data SURVIVES (pg_data volume kept)
docker-compose down -v       → stops containers, DELETES volumes (data GONE)
docker-compose up            → if pg_data exists: Postgres loads existing data
                             → if pg_data empty: fresh database, init.sql runs,
                               then db-init runs Alembic migrations
```

This is what was broken before the bug fixes: there was no Alembic step, so after a volume wipe, Postgres started empty and the app crashed trying to query non-existent tables.

---

## 9. Quick Reference

| Concept | Analogy |
|---------|---------|
| PostgreSQL | The spreadsheet application |
| `quant_trader` database | One workbook (file) |
| Tables (trades, orders...) | Sheets within the workbook |
| Rows | Individual records (one trade, one order) |
| SQLAlchemy | Your Python assistant that writes SQL for you |
| asyncpg | The USB cable between Python and Postgres |
| psycopg2 | A second USB cable (synchronous, used only by Alembic) |
| Alembic | Version control for table structure (like git for schema) |
| `pg_data` volume | The hard drive where the workbook is saved |
| TimescaleDB | A turbo plugin for time-stamped data |

---

## 10. Key Files

| File | Purpose |
|------|---------|
| `db/models.py` | Defines all 6 tables as Python classes |
| `db/session.py` | Connection pool, `init_db()`, `get_session()`, `close_db()` |
| `db/init.sql` | Enables TimescaleDB extension on first boot |
| `alembic.ini` | Alembic config (connection string, logging) |
| `alembic/env.py` | Migration runner (resolves DB host/password from env vars) |
| `alembic/versions/` | Migration files (001_initial_schema.py, etc.) |
| `docker-compose.yml` | Defines the `db-init` service that runs migrations on boot |
