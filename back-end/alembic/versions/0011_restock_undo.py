"""Remember a song's row state before a restock add, so the add can be undone.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("restock_feedback", sa.Column("previous_state", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("restock_feedback", "previous_state")
