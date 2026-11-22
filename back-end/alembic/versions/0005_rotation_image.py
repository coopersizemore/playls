"""Playlist cover on rotations.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Filled in by the next sync of each rotation
    op.add_column("rotation", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rotation", "image_url")
