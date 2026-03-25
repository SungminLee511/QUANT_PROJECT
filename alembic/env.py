"""Alembic migration environment for Quant Trading System.

Uses synchronous psycopg2 driver for migrations (simpler and more reliable
than async approach). Connection URL is resolved from QT_* environment
variables so it works both locally (localhost) and inside Docker (postgres).
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so metadata is populated
from db.models import Base  # noqa: F401

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Build connection URL from environment variables (BUG 7 fix)."""
    host = os.environ.get("QT_DATABASE_HOST", "localhost")
    password = os.environ.get("QT_DB_PASSWORD", "changeme")
    user = os.environ.get("QT_DB_USER", "quant")
    port = os.environ.get("QT_DB_PORT", "5432")
    db_name = os.environ.get("QT_DB_NAME", "quant_trader")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
