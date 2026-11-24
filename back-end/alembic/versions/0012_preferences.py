"""Tweakable behavior: account-wide defaults on users, per-rotation overrides on rotation.

Every column is nullable and NULL means "the built-in default" (users) or "use the account
setting" (rotation), so existing rows behave exactly as before. Allowed values are
enforced by the API schemas; the services fall back to defaults for anything unexpected.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_COLUMNS = [
    ("super_keep_multiplier", sa.Integer()),
    ("skip_hold_days", sa.Integer()),
    ("review_order", sa.String(20)),
    ("default_interval_hours", sa.Integer()),
    ("deck_size", sa.Integer()),
    ("discovery_percent", sa.Integer()),
    ("not_now_percent", sa.Integer()),
    ("bring_back_recovery_days", sa.Integer()),
]

ROTATION_COLUMNS = [
    ("super_keep_multiplier", sa.Integer()),
    ("skip_hold_days", sa.Integer()),
    ("review_order", sa.String(20)),
    ("review_limit", sa.Integer()),  # 0 = no limit
    ("return_cooldown_days", sa.Integer()),  # auto only
    ("pick_percent", sa.Integer()),  # auto only
    ("bring_back_percent", sa.Integer()),  # auto only
]


def upgrade() -> None:
    for name, type_ in USER_COLUMNS:
        op.add_column("users", sa.Column(name, type_, nullable=True))
    for name, type_ in ROTATION_COLUMNS:
        op.add_column("rotation", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(ROTATION_COLUMNS):
        op.drop_column("rotation", name)
    for name, _ in reversed(USER_COLUMNS):
        op.drop_column("users", name)
