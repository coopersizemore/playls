"""Restock: curated picks, restock feedback, suggestion cache, granted scopes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("curated_pick", "restock_feedback", "suggestion_cache")


def upgrade() -> None:
    op.add_column("users", sa.Column("granted_scopes", sa.Text(), nullable=True))

    op.create_table(
        "curated_pick",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("track_id", sa.String(64), nullable=False),
        sa.Column("uri", sa.String(128), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("artists", sa.String(500)),
        sa.Column("album", sa.String(300)),
        sa.Column("image_url", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("note", sa.String(300)),
        sa.Column("starts_at", sa.DateTime()),
        sa.Column("ends_at", sa.DateTime()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_curated_pick_track_id", "curated_pick", ["track_id"])

    op.create_table(
        "restock_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rotation_id", sa.Integer(), sa.ForeignKey("rotation.id", ondelete="SET NULL")),
        sa.Column("track_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("action IN ('add', 'skip')", name="ck_restock_feedback_action"),
        sa.CheckConstraint(
            "source IN ('bring_back', 'picks', 'suggested', 'search')", name="ck_restock_feedback_source"
        ),
    )
    op.create_index("ix_restock_feedback_user_track", "restock_feedback", ["user_id", "track_id"])

    op.create_table(
        "suggestion_cache",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    for table in NEW_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    op.drop_column("users", "granted_scopes")
