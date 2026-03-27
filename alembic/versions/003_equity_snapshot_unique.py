"""Add unique constraint on equity_snapshots(session_id, timestamp).

Prevents duplicate snapshots for the same session at the same timestamp.
Fixes BUG-91.

Revision ID: 003
Revises: 002
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_unique_constraints("equity_snapshots")}
    if "uq_equity_session_timestamp" not in existing:
        op.create_unique_constraint(
            "uq_equity_session_timestamp", "equity_snapshots",
            ["session_id", "timestamp"],
        )


def downgrade() -> None:
    op.drop_constraint("uq_equity_session_timestamp", "equity_snapshots", type_="unique")
