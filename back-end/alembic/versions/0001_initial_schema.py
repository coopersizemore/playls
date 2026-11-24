"""Initial schema: users, rotation, rotation_track, review_event.

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("users", "rotation", "rotation_track", "review_event")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False, server_default="spotify"),
        sa.Column("spotify_id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("access_token", sa.Text()),
        sa.Column("refresh_token", sa.Text()),
        sa.Column("token_expires_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_spotify_id", "users", ["spotify_id"], unique=True)

    op.create_table(
        "rotation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False, server_default="spotify"),
        sa.Column("playlist_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(128)),
        sa.Column("last_synced_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "provider", "playlist_id", name="uq_rotation_owner_playlist"),
        sa.CheckConstraint("interval_days > 0", name="ck_rotation_interval_positive"),
    )
    op.create_index("ix_rotation_owner_id", "rotation", ["owner_id"])

    op.create_table(
        "rotation_track",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rotation_id", sa.Integer(), sa.ForeignKey("rotation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("track_id", sa.String(64), nullable=False),
        sa.Column("uri", sa.String(128), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("artists", sa.String(500)),
        sa.Column("album", sa.String(300)),
        sa.Column("image_url", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("last_kept_at", sa.DateTime()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("removed_at", sa.DateTime()),
        sa.Column("removed_by", sa.String(10)),
        sa.UniqueConstraint("rotation_id", "track_id", name="uq_rotation_track"),
        sa.CheckConstraint(
            "status IN ('active', 'pending_removal', 'removed')", name="ck_rotation_track_status"
        ),
        sa.CheckConstraint(
            "removed_by IS NULL OR removed_by IN ('user', 'external')", name="ck_rotation_track_removed_by"
        ),
    )
    op.create_index("ix_rotation_track_rotation_status", "rotation_track", ["rotation_id", "status"])

    op.create_table(
        "review_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rotation_track_id",
            sa.Integer(),
            sa.ForeignKey("rotation_track.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("action IN ('keep', 'skip', 'remove', 'undo')", name="ck_review_event_action"),
    )
    op.create_index("ix_review_event_rotation_track_id", "review_event", ["rotation_track_id"])
    op.create_index("ix_review_event_created_at", "review_event", ["created_at"])

    # RLS on with no policies: blocks Supabase's Data API (anon/authenticated keys).
    # The backend connects as the table owner, which bypasses RLS.
    for table in TABLES + ("alembic_version",):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
