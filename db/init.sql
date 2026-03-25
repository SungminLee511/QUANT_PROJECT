-- Runs on first Postgres initialization only (empty pg_data volume).
-- Enables TimescaleDB extension for hypertable support.
-- Also added as safety net in Alembic migration 001.
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
