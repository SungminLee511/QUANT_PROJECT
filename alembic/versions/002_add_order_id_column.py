"""Add order_id column to orders table.

Separates internal UUID (order_id) from exchange order ID (external_id).
Fixes BUG-58: external_id was overloaded to store internal UUID for
orders that never received an exchange ID.

Revision ID: 002
Revises: 001
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("orders")}

    # Add order_id column (internal UUID) — nullable initially for backfill
    if "order_id" not in existing_cols:
        op.add_column("orders", sa.Column("order_id", sa.String(36), nullable=True))

    # avg_price may already exist from create_all safety net
    if "avg_price" not in existing_cols:
        op.add_column("orders", sa.Column("avg_price", sa.Float(), nullable=True))

    # Backfill: copy external_id → order_id for existing rows
    op.execute("UPDATE orders SET order_id = external_id WHERE order_id IS NULL")

    # Now make it NOT NULL
    op.alter_column("orders", "order_id", nullable=False)

    # Add index for fast lookup by internal order_id
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("orders")}
    if "ix_orders_order_id" not in existing_indexes:
        op.create_index("ix_orders_order_id", "orders", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_order_id", table_name="orders")
    op.drop_column("orders", "avg_price")
    op.drop_column("orders", "order_id")
