"""Initial schema — all tables from db/models.py.

Also ensures TimescaleDB extension exists (safety net for BUG 2).

Revision ID: 001
Revises: None
Create Date: 2026-03-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure TimescaleDB extension (safety net — also in db/init.sql)
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # -- trading_sessions --
    op.create_table(
        "trading_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("session_type", sa.String(20), nullable=False),
        sa.Column("is_simulation", sa.Boolean(), default=False),
        sa.Column("config_json", sa.Text(), default="{}"),
        sa.Column("starting_budget", sa.Float(), nullable=True),
        sa.Column("strategy_code", sa.Text(), nullable=True),
        sa.Column("strategy_class", sa.String(128), nullable=True),
        sa.Column("status", sa.String(20), default="stopped"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # -- trades --
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("trading_sessions.id"), nullable=False, index=True),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("fees", sa.Float(), default=0.0),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_index("ix_trades_session_symbol_timestamp", "trades", ["session_id", "symbol", "timestamp"])

    # -- positions --
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("trading_sessions.id"), nullable=False, index=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Float(), default=0.0),
        sa.Column("avg_entry_price", sa.Float(), default=0.0),
        sa.Column("current_price", sa.Float(), default=0.0),
        sa.Column("unrealized_pnl", sa.Float(), default=0.0),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_position_session_symbol", "positions", ["session_id", "symbol"])

    # -- orders --
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("trading_sessions.id"), nullable=False, index=True),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("filled_quantity", sa.Float(), default=0.0),
        sa.Column("order_type", sa.String(10), nullable=False, default="market"),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_session_symbol_created", "orders", ["session_id", "symbol", "created_at"])

    # -- equity_snapshots --
    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("trading_sessions.id"), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("total_equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("positions_value", sa.Float(), nullable=False),
    )

    # -- alert_logs --
    op.create_table(
        "alert_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("trading_sessions.id"), nullable=True, index=True),
        sa.Column("level", sa.String(20), nullable=False, default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("alert_logs")
    op.drop_table("equity_snapshots")
    op.drop_table("orders")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("trading_sessions")
    op.execute("DROP EXTENSION IF EXISTS timescaledb CASCADE")
