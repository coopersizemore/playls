"""Per-rotation sync claim (a short lease), so two requests can't sync one rotation at once.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rotation", sa.Column("sync_claimed_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("rotation", "sync_claimed_until")
