"""Track availability (still in the playlist but unplayable on Spotify).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Everything starts as playable; the next full read of each playlist corrects it
    op.add_column(
        "rotation_track", sa.Column("is_playable", sa.Boolean(), nullable=False, server_default=sa.true())
    )


def downgrade() -> None:
    op.drop_column("rotation_track", "is_playable")
