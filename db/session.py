"""Async DB session factory using SQLAlchemy 2.0 + asyncpg."""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base

_engine = None
_session_factory = None


def _build_url(config: dict) -> str:
    db = config.get("database", {})
    user = db.get("user", "quant")
    password = db.get("password", "changeme")
    host = db.get("host", "localhost")
    port = db.get("port", 5432)
    name = db.get("name", "quant_trader")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


def init_engine(config: dict):
    """Create the async engine and session factory. Call once at startup."""
    global _engine, _session_factory
    url = _build_url(config)
    _engine = create_async_engine(
        url,
        pool_size=10,
        max_overflow=20,
        echo=config.get("app", {}).get("env") == "dev",
    )
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables. Call once at startup after init_engine()."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session():
    """Yield an async DB session. Always use with `async with`."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db():
    """Dispose engine. Call on shutdown."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None
