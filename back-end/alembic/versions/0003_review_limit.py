"""Per-user daily review limit (NULL = no limit).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing users get the default of 50
    op.add_column("users", sa.Column("review_limit", sa.Integer(), nullable=True, server_default="50"))
    op.create_check_constraint(
        "ck_users_review_limit_range", "users", "review_limit IS NULL OR (review_limit BETWEEN 1 AND 1000)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_review_limit_range", "users", type_="check")
    op.drop_column("users", "review_limit")
