"""SQLAlchemy 2.0 ORM models for the trading system."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class TradingSession(Base):
    """A trading session — one per exchange connection (real or simulated)."""
    __tablename__ = "trading_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    session_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SessionType enum value
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}")  # per-session config (API keys, symbols, etc.)
    starting_budget: Mapped[float] = mapped_column(Float, nullable=True)  # sim only
    strategy_code: Mapped[str] = mapped_column(Text, nullable=True)  # user main() function source
    strategy_class: Mapped[str] = mapped_column(String(128), nullable=True)  # deprecated (v1)
    data_config: Mapped[str] = mapped_column(Text, nullable=True)  # JSON: resolution, fields, lookbacks, exec_every_n
    custom_data_code: Mapped[str] = mapped_column(Text, nullable=True)  # JSON: list of custom data functions
    status: Mapped[str] = mapped_column(String(20), default="stopped")  # active, stopped, error
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    # lazy="select" (default) — load on access, not on every session query.
    # Use selectinload() / joinedload() explicitly in queries that need related data.
    trades: Mapped[list["Trade"]] = relationship(back_populates="session", lazy="select")
    positions: Mapped[list["Position"]] = relationship(back_populates="session", lazy="select")
    orders: Mapped[list["Order"]] = relationship(back_populates="session", lazy="select")
    equity_snapshots: Mapped[list["EquitySnapshot"]] = relationship(back_populates="session", lazy="select")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("trading_sessions.id"), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    session: Mapped["TradingSession"] = relationship(back_populates="trades")

    __table_args__ = (
        Index("ix_trades_session_symbol_timestamp", "session_id", "symbol", "timestamp"),
        UniqueConstraint("session_id", "order_id", name="uq_trades_session_order"),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("trading_sessions.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    session: Mapped["TradingSession"] = relationship(back_populates="positions")

    __table_args__ = (
        UniqueConstraint("session_id", "symbol", name="uq_position_session_symbol"),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("trading_sessions.id"), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, comment="Internal UUID")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="Exchange order ID")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_price: Mapped[float | None] = mapped_column(Float, default=0.0, nullable=True)
    order_type: Mapped[str] = mapped_column(String(10), nullable=False, default="market")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    session: Mapped["TradingSession"] = relationship(back_populates="orders")

    __table_args__ = (
        Index("ix_orders_session_symbol_created", "session_id", "symbol", "created_at"),
    )


class EquitySnapshot(Base):
    """Time-series equity snapshots for P&L charting.

    Use TimescaleDB hypertable in production (created via migration).
    """
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("trading_sessions.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    positions_value: Mapped[float] = mapped_column(Float, nullable=False)

    session: Mapped["TradingSession"] = relationship(back_populates="equity_snapshots")

    __table_args__ = (
        UniqueConstraint("session_id", "timestamp", name="uq_equity_session_timestamp"),
    )


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("trading_sessions.id"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
