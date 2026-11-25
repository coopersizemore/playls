"""Listening history: plays, gaps, top tracks, and the settings that use them.

- play_event: one row per play, captured from recently-played (source 'api') or imported
  from Spotify's Extended Streaming History export (source 'import').
- listening_gap: spans where plays were probably missed (more than 50 between captures).
- top_track: the latest top-tracks snapshot per time range.
- users / rotation: listening settings (NULL = default; see services/preferences.py).
- rotation_track.listening_holds: times an auto rotation let a heavily played song stay.
- restock_feedback.source gains 'rediscover'.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("play_event", "listening_gap", "top_track")


def upgrade() -> None:
    op.create_table(
        "play_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("track_id", sa.String(64), nullable=False),
        sa.Column("song_key", sa.String(400), nullable=True),
        sa.Column("uri", sa.String(128), nullable=True),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("artists", sa.String(500), nullable=True),
        sa.Column("album", sa.String(300), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("played_at", sa.DateTime(), nullable=False),
        sa.Column("context_type", sa.String(20), nullable=True),
        sa.Column("context_uri", sa.String(200), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="api"),
        sa.Column("ms_played", sa.Integer(), nullable=True),
        sa.Column("skipped", sa.Boolean(), nullable=True),
        sa.Column("reason_end", sa.String(20), nullable=True),
        sa.CheckConstraint("source IN ('api', 'import')", name="ck_play_event_source"),
        sa.UniqueConstraint("user_id", "played_at", name="uq_play_event_user_played_at"),
    )
    op.create_index("ix_play_event_user_song", "play_event", ["user_id", "song_key", "played_at"])
    op.create_index("ix_play_event_user_track", "play_event", ["user_id", "track_id", "played_at"])
    op.create_index("ix_play_event_user_context", "play_event", ["user_id", "context_uri", "played_at"])

    op.create_table(
        "listening_gap",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gap_start", sa.DateTime(), nullable=False),
        sa.Column("gap_end", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_listening_gap_user", "listening_gap", ["user_id", "gap_end"])

    op.create_table(
        "top_track",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("time_range", sa.String(12), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.String(64), nullable=False),
        sa.Column("song_key", sa.String(400), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_top_track_user_range", "top_track", ["user_id", "time_range"])

    for table in NEW_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')

    op.add_column("users", sa.Column("listening_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("listening_since", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("listening_cursor", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("listening_captured_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("top_tracks_captured_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("heavy_listening_review", sa.String(12), nullable=True))

    op.add_column("rotation", sa.Column("heavy_listening_review", sa.String(12), nullable=True))
    op.add_column("rotation", sa.Column("listening_hold_rotations", sa.Integer(), nullable=True))
    op.add_column("rotation", sa.Column("listening_protect_top_percent", sa.Integer(), nullable=True))

    op.add_column(
        "rotation_track", sa.Column("listening_holds", sa.Integer(), nullable=False, server_default="0")
    )

    op.drop_constraint("ck_restock_feedback_source", "restock_feedback", type_="check")
    op.create_check_constraint(
        "ck_restock_feedback_source", "restock_feedback",
        "source IN ('bring_back', 'picks', 'suggested', 'search', 'rediscover')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM restock_feedback WHERE source = 'rediscover'")
    op.drop_constraint("ck_restock_feedback_source", "restock_feedback", type_="check")
    op.create_check_constraint(
        "ck_restock_feedback_source", "restock_feedback",
        "source IN ('bring_back', 'picks', 'suggested', 'search')",
    )
    op.drop_column("rotation_track", "listening_holds")
    for column in ("listening_protect_top_percent", "listening_hold_rotations", "heavy_listening_review"):
        op.drop_column("rotation", column)
    for column in (
        "heavy_listening_review", "top_tracks_captured_at", "listening_captured_at", "listening_cursor",
        "listening_since", "listening_enabled",
    ):
        op.drop_column("users", column)
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
