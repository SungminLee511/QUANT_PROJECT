"""Add kill_switch_events table for persistent kill switch state.

Fixes BUG-73: kill switch state lost on Redis restart.

Revision ID: 004
Revises: 003
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "kill_switch_events" not in inspector.get_table_names():
        op.create_table(
            "kill_switch_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.String(36), nullable=False, index=True),
            sa.Column("active", sa.Boolean, nullable=False),
            sa.Column("reason", sa.Text, nullable=False, server_default=""),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
                index=True,
            ),
        )


def downgrade() -> None:
    op.drop_table("kill_switch_events")
