"""Liked Songs rotations: a rotation with playlist_id 'liked' must be manual.

No new columns: a Liked Songs rotation is a manual rotation whose playlist_id is the
sentinel 'liked' (see database/models/rotation.py). Existing rows all satisfy the check.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-24
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_rotation_liked_manual", "rotation", "playlist_id <> 'liked' OR kind = 'manual'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_rotation_liked_manual", "rotation", type_="check")
