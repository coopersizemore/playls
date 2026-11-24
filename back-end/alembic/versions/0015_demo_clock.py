"""Demo mode: per-account clock offset for "Skip ahead a day".

Demo accounts are ordinary users rows with provider = 'demo' (no new table). This adds
the hours their requests run ahead of real time; NULL for everyone else.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("demo_clock_offset_hours", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "demo_clock_offset_hours")
