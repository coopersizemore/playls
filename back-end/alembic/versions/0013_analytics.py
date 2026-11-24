"""Usage analytics (opt-in) and app health for the admin dashboard.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("analytics_consent", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("analytics_consent_at", sa.DateTime(), nullable=True))

    op.create_table(
        "analytics_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rotation_id", sa.Integer(), sa.ForeignKey("rotation.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rotation_kind", sa.String(10), nullable=True),
        sa.Column("surface", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(12), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("decision_ms", sa.Integer(), nullable=True),
        sa.Column("session_elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("input", sa.String(8), nullable=True),
        sa.Column("revisit", sa.Boolean(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("song_age_days", sa.Integer(), nullable=True),
        sa.Column("overdue_days", sa.Integer(), nullable=True),
        sa.Column("local_hour", sa.Integer(), nullable=True),
        sa.Column("local_weekday", sa.Integer(), nullable=True),
        sa.Column("ended", sa.String(12), nullable=True),
        sa.Column("decisions", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("surface IN ('review', 'restock')", name="ck_analytics_event_surface"),
        sa.CheckConstraint("kind IN ('decision', 'undo', 'session_end')", name="ck_analytics_event_kind"),
    )
    op.create_index("ix_analytics_event_user_created", "analytics_event", ["user_id", "created_at"])
    op.create_index("ix_analytics_event_created_at", "analytics_event", ["created_at"])
    op.create_index("ix_analytics_event_session_id", "analytics_event", ["session_id"])

    op.create_table(
        "health_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("route", sa.String(120), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("spotify_ms", sa.Integer(), nullable=False),
        sa.Column("spotify_calls", sa.Integer(), nullable=False),
        sa.Column("db_ms", sa.Integer(), nullable=False),
        sa.Column("db_queries", sa.Integer(), nullable=False),
        sa.Column("db_connects", sa.Integer(), nullable=False),
        sa.Column("sampled", sa.Boolean(), nullable=False),
        sa.Column("counters", sa.Text(), nullable=True),
    )
    op.create_index("ix_health_event_created_at", "health_event", ["created_at"])

    # Block Supabase's Data API; the app reaches these tables only through its own connection
    for table in ("analytics_event", "health_event"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_health_event_created_at", table_name="health_event")
    op.drop_table("health_event")
    op.drop_index("ix_analytics_event_session_id", table_name="analytics_event")
    op.drop_index("ix_analytics_event_created_at", table_name="analytics_event")
    op.drop_index("ix_analytics_event_user_created", table_name="analytics_event")
    op.drop_table("analytics_event")
    op.drop_column("users", "analytics_consent_at")
    op.drop_column("users", "analytics_consent")
