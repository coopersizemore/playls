"""Auto rotations: target size, rotate-out share, and system history events.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rotation", sa.Column("kind", sa.String(10), nullable=False, server_default="manual"))
    op.add_column("rotation", sa.Column("target_size", sa.Integer(), nullable=True))
    op.add_column("rotation", sa.Column("rotate_percent", sa.Integer(), nullable=True))
    op.add_column("rotation", sa.Column("last_rotated_at", sa.DateTime(), nullable=True))
    op.create_check_constraint("ck_rotation_kind", "rotation", "kind IN ('manual', 'auto')")
    op.create_check_constraint(
        "ck_rotation_auto_settings",
        "rotation",
        "kind = 'manual' OR (target_size BETWEEN 1 AND 500 AND rotate_percent BETWEEN 1 AND 100)",
    )

    op.drop_constraint("ck_rotation_track_removed_by", "rotation_track", type_="check")
    op.create_check_constraint(
        "ck_rotation_track_removed_by",
        "rotation_track",
        "removed_by IS NULL OR removed_by IN ('user', 'external', 'rotation')",
    )

    op.drop_constraint("ck_review_event_action", "review_event", type_="check")
    op.create_check_constraint(
        "ck_review_event_action",
        "review_event",
        "action IN ('keep', 'super_keep', 'skip', 'remove', 'undo', 'rotated_out', 'auto_added')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM review_event WHERE action IN ('rotated_out', 'auto_added')")
    op.drop_constraint("ck_review_event_action", "review_event", type_="check")
    op.create_check_constraint(
        "ck_review_event_action", "review_event", "action IN ('keep', 'super_keep', 'skip', 'remove', 'undo')"
    )
    op.execute("UPDATE rotation_track SET removed_by = 'user' WHERE removed_by = 'rotation'")
    op.drop_constraint("ck_rotation_track_removed_by", "rotation_track", type_="check")
    op.create_check_constraint(
        "ck_rotation_track_removed_by", "rotation_track", "removed_by IS NULL OR removed_by IN ('user', 'external')"
    )
    op.drop_constraint("ck_rotation_auto_settings", "rotation", type_="check")
    op.drop_constraint("ck_rotation_kind", "rotation", type_="check")
    op.drop_column("rotation", "last_rotated_at")
    op.drop_column("rotation", "rotate_percent")
    op.drop_column("rotation", "target_size")
    op.drop_column("rotation", "kind")
