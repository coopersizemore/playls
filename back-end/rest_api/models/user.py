from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


class User(BaseModel):
    """Internal: used by the OAuth callback to create a user row. Never returned to clients."""

    spotify_id: str
    display_name: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None


class SettingsOut(BaseModel):
    review_limit: int | None  # None = no limit
    # Reviewing
    super_keep_multiplier: int  # a super keep waits this many intervals
    skip_hold_days: int  # 1 = a skipped song is back tomorrow
    review_order: str  # overdue | oldest | shuffle
    default_interval_hours: int  # starting interval for new (manual) rotations
    # Restocking
    deck_size: int
    discovery_percent: int  # For you: share of "new to you" songs
    not_now_percent: int  # weight left after a fresh Not now (lower = stronger)
    bring_back_recovery_days: int


class SettingsUpdate(BaseModel):
    """Only the fields sent are changed. review_limit: null = no limit."""
    model_config = ConfigDict(extra="forbid")

    # Songs offered for review per rotation per day; null = no limit
    review_limit: int | None = Field(None, ge=1, le=1000)
    super_keep_multiplier: Literal[2, 3, 5] | None = None
    skip_hold_days: Literal[1, 3, 7] | None = None
    review_order: Literal["overdue", "oldest", "shuffle"] | None = None
    default_interval_hours: int | None = Field(None, ge=1, le=365 * 24)
    deck_size: Literal[10, 20, 30, 50] | None = None
    discovery_percent: Literal[15, 33, 60] | None = None
    not_now_percent: Literal[75, 50, 25] | None = None
    bring_back_recovery_days: Literal[30, 90, 180] | None = None
