"""Demo mode: per-IP cap on demo accounts.

Stores a keyed hash of the IP that started each demo account (never the IP itself), so
one client can't take every DEMO_MAX_ACTIVE slot. NULL for everyone else.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("demo_client_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "demo_client_hash")
