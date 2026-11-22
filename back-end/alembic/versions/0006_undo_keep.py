"""Remember last_kept_at before each keep so keeps can be undone.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("review_event", sa.Column("previous_last_kept_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_event", "previous_last_kept_at")
