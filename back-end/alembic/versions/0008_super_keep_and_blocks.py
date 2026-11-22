"""Super keep (keep multiplier) and "stop suggesting" blocks.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rotation_track", sa.Column("keep_multiplier", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("review_event", sa.Column("previous_keep_multiplier", sa.Integer(), nullable=True))
    op.alter_column("review_event", "action", existing_type=sa.String(10), type_=sa.String(12))
    op.drop_constraint("ck_review_event_action", "review_event", type_="check")
    op.create_check_constraint(
        "ck_review_event_action", "review_event", "action IN ('keep', 'super_keep', 'skip', 'remove', 'undo')"
    )

    op.create_table(
        "restock_block",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("track_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("artists", sa.String(500)),
        sa.Column("image_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "track_id", name="uq_restock_block_user_track"),
    )
    op.create_index("ix_restock_block_user_id", "restock_block", ["user_id"])
    op.execute('ALTER TABLE "restock_block" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("restock_block")
    # Super keeps become plain keeps
    op.execute("UPDATE review_event SET action = 'keep' WHERE action = 'super_keep'")
    op.drop_constraint("ck_review_event_action", "review_event", type_="check")
    op.create_check_constraint(
        "ck_review_event_action", "review_event", "action IN ('keep', 'skip', 'remove', 'undo')"
    )
    op.alter_column("review_event", "action", existing_type=sa.String(12), type_=sa.String(10))
    op.drop_column("review_event", "previous_keep_multiplier")
    op.drop_column("rotation_track", "keep_multiplier")
