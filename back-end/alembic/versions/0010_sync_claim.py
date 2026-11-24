"""Per-rotation sync claim (a short lease), so two requests can't sync one rotation at once.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rotation", sa.Column("sync_claimed_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("rotation", "sync_claimed_until")
