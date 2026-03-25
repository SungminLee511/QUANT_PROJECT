# QUANT_PROJECT Bug Fix Guide

> **Reference:** This document catalogs known bugs, root causes, and fixes for the Quant Trading Platform. Ordered by severity (most critical first).

**Repository:** https://github.com/SungminLee511/QUANT_PROJECT

**Stack:** Dockerized platform — Binance + Alpaca, PostgreSQL/TimescaleDB, Redis, SQLAlchemy (async via asyncpg), Alembic, FastAPI.

**Core symptom:** After restarting Docker containers, the database is broken and requires manual reinstallation.

---

## BUG 1: No database schema initialization on startup (CRITICAL — root cause of restart failures)

### Problem

In `docker-compose.yml`, application services (`data-feed`, `strategy`, `execution`, `monitor`) start as soon as Postgres passes a healthcheck (`pg_isready`). But `pg_isready` only confirms that Postgres is *accepting TCP connections* — it does **NOT** mean the application's tables, hypertables, or extensions exist.

There is no step anywhere in the Docker workflow that runs `alembic upgrade head` or `Base.metadata.create_all()`. So:

- On first launch after `docker-compose up`, the `quant_trader` database is empty — no tables.
- After a `docker-compose down && docker-compose up`, if the `pg_data` volume was removed (or corrupted by a bad shutdown), the same problem occurs.
- All four app services crash immediately with SQLAlchemy errors like `relation "orders" does not exist`.

### Fix

Create a dedicated `db-init` service in `docker-compose.yml` that runs Alembic migrations before any app service starts. All app services must depend on this init service completing successfully.

**Step 1:** Add this service to `docker-compose.yml`, right after the `postgres` service:

```yaml
  db-init:
    build: .
    command: >
      bash -c "
        echo 'Waiting for database to be fully ready...' &&
        python -c \"
import time, subprocess, sys
for i in range(30):
    try:
        import asyncpg, asyncio
        async def check():
            conn = await asyncpg.connect(
                host='postgres', port=5432,
                user='quant', password='${QT_DB_PASSWORD:-changeme}',
                database='quant_trader'
            )
            await conn.close()
        asyncio.run(check())
        print('Database is ready')
        break
    except Exception as e:
        print(f'Attempt {i+1}/30: {e}')
        time.sleep(2)
else:
    print('Database not ready after 60s')
    sys.exit(1)
        \" &&
        echo 'Running Alembic migrations...' &&
        alembic upgrade head &&
        echo 'Database initialization complete'
      "
    env_file: .env
    environment:
      QT_ENV: prod
      QT_REDIS_HOST: redis
      QT_DATABASE_HOST: postgres
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"
```

**Step 2:** Update ALL app services to depend on `db-init` completing:

```yaml
  data-feed:
    # ... existing config ...
    depends_on:
      redis:
        condition: service_healthy
      db-init:
        condition: service_completed_successfully

  strategy:
    # ... existing config ...
    depends_on:
      redis:
        condition: service_healthy
      db-init:
        condition: service_completed_successfully

  execution:
    # ... existing config ...
    depends_on:
      redis:
        condition: service_healthy
      db-init:
        condition: service_completed_successfully

  monitor:
    # ... existing config ...
    depends_on:
      redis:
        condition: service_healthy
      db-init:
        condition: service_completed_successfully
```

**Step 3:** If there is no Alembic setup yet (check for `alembic.ini` and `alembic/` directory), create one:

```bash
alembic init alembic
```

Then edit `alembic.ini` to set:

```ini
sqlalchemy.url = postgresql+asyncpg://quant:%(QT_DB_PASSWORD)s@%(QT_DATABASE_HOST)s:5432/quant_trader
```

And edit `alembic/env.py` to:

1. Import all your models (so metadata is populated)
2. Set `target_metadata = Base.metadata` (where `Base` is your SQLAlchemy declarative base from `db/models.py`)
3. Handle async engine properly (use `run_async_migrations` pattern for asyncpg)

If Alembic is already configured but has no migration files, generate the initial migration:

```bash
alembic revision --autogenerate -m "initial schema"
```

**Step 4:** As a fallback, also add `Base.metadata.create_all()` to the application startup code (likely in `db/session.py` or wherever the engine is created). This is a safety net — Alembic is the primary mechanism, but `create_all` ensures tables exist even if Alembic state is inconsistent:

```python
# In db/session.py or similar
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

Call this function at the start of each service's `main()` / entry point.

---

## BUG 2: TimescaleDB extension never created (CRITICAL — causes hypertable failures)

### Problem

The project uses `timescale/timescaledb:latest-pg16` as the Postgres image, which means it intends to use TimescaleDB hypertables for time-series data (equity curves, OHLCV bars, etc.). However, the TimescaleDB extension must be explicitly created with:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

Without this, any `SELECT create_hypertable(...)` call in migrations or application code will fail with `function create_hypertable does not exist`.

### Fix

Create a SQL init script that the Postgres container runs on first startup.

**Step 1:** Create `db/init.sql`:

```sql
-- This runs automatically on first database creation
-- (via docker-entrypoint-initdb.d)
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
```

**Step 2:** Mount it in the `postgres` service in `docker-compose.yml`:

```yaml
  postgres:
    image: timescale/timescaledb:2.17.2-pg16  # also pin version, see BUG 4
    environment:
      POSTGRES_DB: quant_trader
      POSTGRES_USER: quant
      POSTGRES_PASSWORD: ${QT_DB_PASSWORD:-changeme}
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quant"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**Important note:** `docker-entrypoint-initdb.d` scripts only run when the database is created for the first time (empty `pg_data` volume). If the volume already exists with data, these scripts are skipped. So also add `CREATE EXTENSION IF NOT EXISTS timescaledb;` to the Alembic initial migration as a safety measure.

---

## BUG 3: data-feed and strategy services don't depend on Postgres (HIGH)

### Problem

In `docker-compose.yml`:

- `data-feed` depends only on `redis` (healthy)
- `strategy` depends on `redis` (healthy) and `data-feed` (started)

Neither depends on `postgres`. If these services write anything to the database (positions, signals, market data snapshots), they will crash if Postgres isn't ready. Even if they primarily use Redis pub/sub, any DB write path will fail.

### Fix

After implementing BUG 1's fix, both services will depend on `db-init` which transitively depends on Postgres. This is the correct solution — see BUG 1 Step 2 above.

If for some reason you don't implement the `db-init` service, at minimum add:

```yaml
  data-feed:
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy

  strategy:
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      data-feed:
        condition: service_started
```

---

## BUG 4: `latest` tag on TimescaleDB image (HIGH — causes silent breakage)

### Problem

```yaml
image: timescale/timescaledb:latest-pg16
```

Using `latest` means `docker-compose pull` or rebuilding can silently upgrade TimescaleDB. If the new version has a different on-disk format or requires a data migration, the existing `pg_data` volume becomes incompatible. Postgres will fail to start or the extension will fail to load, and you'd have to wipe the volume and reinstall.

### Fix

Pin to a specific version. Check the latest stable release at https://github.com/timescale/timescaledb/releases and use it explicitly:

```yaml
image: timescale/timescaledb:2.17.2-pg16
```

Update the version intentionally when needed, not silently via `latest`.

---

## BUG 5: Missing psycopg2 / synchronous DB driver (MEDIUM)

### Problem

`requirements.txt` includes `asyncpg` for async SQLAlchemy access, but does **NOT** include `psycopg2` or `psycopg2-binary`. Alembic's default `env.py` uses a synchronous connection to run migrations. Without a sync driver, `alembic upgrade head` will fail with:

```
ModuleNotFoundError: No module named 'psycopg2'
```

The Dockerfile does install `libpq-dev` and `gcc` (which are needed to compile psycopg2 from source), but the pip package itself is missing.

### Fix

Add `psycopg2-binary` to `requirements.txt`:

```
# Database
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
psycopg2-binary>=2.9
alembic>=1.13
```

Alternatively, configure Alembic's `env.py` to use the async engine with asyncpg. But adding `psycopg2-binary` is simpler and avoids complicating the migration setup.

If using the async approach instead, modify `alembic/env.py` to use async migrations:

```python
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config

def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
    )
    async def do_run():
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()
    asyncio.run(do_run())
```

But this is more fragile. Prefer `psycopg2-binary`.

---

## BUG 6: No Redis persistence configuration (MEDIUM)

### Problem

Redis is configured with a volume mount (`redis_data:/data`), which suggests the intent is to persist data. However, without explicitly enabling persistence, Redis defaults to RDB snapshots every few minutes at best. On an unclean shutdown (Docker kill, power loss), you lose recent data.

For a trading system, this means losing cached market state, active signal queues, and any pub/sub channel state.

### Fix

Add the `--appendonly yes` flag to the Redis service command:

```yaml
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

This enables AOF (Append Only File) persistence, which logs every write operation and replays them on restart. Combined with the existing volume mount, Redis data will survive container restarts.

---

## BUG 7: Alembic connection string may not resolve env vars (MEDIUM)

### Problem

If `alembic.ini` contains a hardcoded connection string like:

```ini
sqlalchemy.url = postgresql://quant:changeme@localhost:5432/quant_trader
```

Then inside Docker containers, where Postgres is at hostname `postgres` (not `localhost`), migrations will fail. The password also needs to come from the environment variable.

### Fix

In `alembic/env.py`, override the URL from environment variables:

```python
import os

def run_migrations_online():
    host = os.environ.get("QT_DATABASE_HOST", "localhost")
    password = os.environ.get("QT_DB_PASSWORD", "changeme")
    url = f"postgresql://quant:{password}@{host}:5432/quant_trader"

    connectable = create_engine(url)
    # ... rest of migration logic
```

This ensures the Alembic connection works both locally (`localhost`) and inside Docker (`postgres`).

---

## BUG 8: No graceful shutdown handling (LOW)

### Problem

The Dockerfile's default CMD and docker-compose commands start Python processes directly. When Docker sends SIGTERM to stop a container, Python processes may not handle it gracefully, leading to:

- Incomplete database transactions
- Orphaned exchange connections (open orders left hanging)
- Corrupted Redis state

### Fix

Ensure each service's entry point script (`scripts/run_data.py`, `scripts/run_strategy.py`, etc.) registers signal handlers:

```python
import signal
import asyncio

async def shutdown(sig, loop):
    """Graceful shutdown on SIGTERM/SIGINT."""
    print(f"Received {sig.name}, shutting down...")
    # Close exchange connections
    # Commit/rollback pending DB transactions
    # Flush Redis
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

loop = asyncio.get_event_loop()
for sig in (signal.SIGTERM, signal.SIGINT):
    loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop)))
```

Also add `stop_grace_period` to docker-compose services so Docker waits before force-killing:

```yaml
  execution:
    # ... existing config ...
    stop_grace_period: 30s  # Give 30s to close orders gracefully
```

---

## Complete Fixed docker-compose.yml

Here is the full corrected file incorporating all fixes above. Replace the existing `docker-compose.yml` with this:

```yaml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
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
    image: timescale/timescaledb:2.17.2-pg16
    environment:
      POSTGRES_DB: quant_trader
      POSTGRES_USER: quant
      POSTGRES_PASSWORD: ${QT_DB_PASSWORD:-changeme}
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quant -d quant_trader"]
      interval: 10s
      timeout: 5s
      retries: 5

  db-init:
    build: .
    command: >
      bash -c "
        echo 'Waiting for database...' &&
        sleep 5 &&
        alembic upgrade head &&
        echo 'Database ready'
      "
    env_file: .env
    environment:
      QT_ENV: prod
      QT_REDIS_HOST: redis
      QT_DATABASE_HOST: postgres
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

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
      db-init:
        condition: service_completed_successfully
    restart: unless-stopped
    stop_grace_period: 10s

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
      db-init:
        condition: service_completed_successfully
      data-feed:
        condition: service_started
    restart: unless-stopped
    stop_grace_period: 10s

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
      db-init:
        condition: service_completed_successfully
    restart: unless-stopped
    stop_grace_period: 30s

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
      db-init:
        condition: service_completed_successfully
    restart: unless-stopped
    stop_grace_period: 10s

volumes:
  redis_data:
  pg_data:
```

---

## New File: db/init.sql

Create this file:

```sql
-- Runs on first Postgres initialization only (empty pg_data volume)
-- Enables TimescaleDB extension for hypertable support
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
```

---

## Updated requirements.txt

Add `psycopg2-binary` to the Database section:

```
# Database
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
psycopg2-binary>=2.9
alembic>=1.13
```

---

## Checklist

After applying all fixes, verify with this sequence:

1. `docker-compose down -v` (wipe all volumes for a clean test)
2. `docker-compose build --no-cache`
3. `docker-compose up -d`
4. `docker-compose logs db-init` — should show "Database ready"
5. `docker-compose logs data-feed` — should start without DB errors
6. `docker-compose ps` — all services should be "Up"
7. `docker-compose restart` — all services should come back cleanly
8. `docker-compose down && docker-compose up -d` — should work without reinstalling anything

If step 4 fails with Alembic errors, check:

- `alembic.ini` exists and has the correct connection string
- `alembic/env.py` imports all models and sets `target_metadata`
- There is at least one migration in `alembic/versions/`
- `QT_DATABASE_HOST` and `QT_DB_PASSWORD` are properly passed to the `db-init` container
