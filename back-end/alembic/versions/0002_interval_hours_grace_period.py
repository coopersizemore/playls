"""Interval in hours, optional grace period, nullable added_at.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rotations keep their behavior: grace period on, same interval
    op.add_column(
        "rotation", sa.Column("grace_period", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("rotation", sa.Column("interval_hours", sa.Integer(), nullable=True))
    op.execute("UPDATE rotation SET interval_hours = interval_days * 24")
    op.alter_column("rotation", "interval_hours", nullable=False)
    op.drop_constraint("ck_rotation_interval_positive", "rotation", type_="check")
    op.drop_column("rotation", "interval_days")
    op.create_check_constraint("ck_rotation_interval_hours_positive", "rotation", "interval_hours > 0")

    # NULL now means "Spotify didn't report when this was added"
    op.alter_column("rotation_track", "added_at", existing_type=sa.DateTime(), nullable=True)


def downgrade() -> None:
    op.execute(
        "UPDATE rotation_track t SET added_at = r.created_at FROM rotation r "
        "WHERE t.rotation_id = r.id AND t.added_at IS NULL"
    )
    op.alter_column("rotation_track", "added_at", existing_type=sa.DateTime(), nullable=False)

    op.add_column("rotation", sa.Column("interval_days", sa.Integer(), nullable=True))
    # Round sub-day intervals up to a whole day
    op.execute("UPDATE rotation SET interval_days = GREATEST(1, CEIL(interval_hours / 24.0))")
    op.alter_column("rotation", "interval_days", nullable=False)
    op.drop_constraint("ck_rotation_interval_hours_positive", "rotation", type_="check")
    op.drop_column("rotation", "interval_hours")
    op.create_check_constraint("ck_rotation_interval_positive", "rotation", "interval_days > 0")
    op.drop_column("rotation", "grace_period")
