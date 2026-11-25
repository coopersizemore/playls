from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """Internal: used by the OAuth callback to create a user row. Never returned to clients."""

    spotify_id: str
    display_name: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None


class SettingsOut(BaseModel):
    review_limit: int | None  # None = no limit
    analytics_consent: bool | None  # None = not asked yet
    # Reviewing
    super_keep_multiplier: int  # a super keep waits this many intervals
    skip_hold_days: int  # 1 = a skipped song is back tomorrow
    review_order: str  # listening | overdue | oldest | shuffle
    heavy_listening_review: str  # inform | less_often | never
    default_interval_hours: int  # starting interval for new (manual) rotations
    # Restocking
    deck_size: int
    discovery_percent: int  # For you: share of "new to you" songs
    not_now_percent: int  # weight left after a fresh Not now (lower = stronger)
    bring_back_recovery_days: int
    # Listening history on (off deletes it)
    listening_enabled: bool = True


class SettingsUpdate(BaseModel):
    """Only the fields sent are changed. review_limit: null = no limit."""
    model_config = ConfigDict(extra="forbid")

    # Songs offered for review per rotation per day; null = no limit
    review_limit: int | None = Field(None, ge=1, le=1000)
    # Usage analytics opt-in; false also deletes what was recorded
    analytics_consent: bool | None = None
    super_keep_multiplier: Literal[2, 3, 5] | None = None
    skip_hold_days: Literal[1, 3, 7] | None = None
    review_order: Literal["listening", "overdue", "oldest", "shuffle"] | None = None
    heavy_listening_review: Literal["inform", "less_often", "never"] | None = None
    default_interval_hours: int | None = Field(None, ge=1, le=365 * 24)
    deck_size: Literal[10, 20, 30, 50] | None = None
    discovery_percent: Literal[15, 33, 60] | None = None
    not_now_percent: Literal[75, 50, 25] | None = None
    bring_back_recovery_days: Literal[30, 90, 180] | None = None
    # false also deletes the stored listening history (null is ignored)
    listening_enabled: bool | None = None


class ListeningStatusOut(BaseModel):
    enabled: bool
    since: datetime | None  # earliest moment the history covers
    last_captured_at: datetime | None
    plays: int
    has_import: bool
    missing_scopes: list[str]


class ImportPlayIn(BaseModel):
    """One row of Spotify's Extended Streaming History export, trimmed in the browser."""
    model_config = ConfigDict(extra="forbid")

    ts: datetime
    ms_played: int = Field(..., ge=0, le=24 * 3600 * 1000)
    uri: str = Field(..., min_length=15, max_length=128, pattern=r"^spotify:track:[A-Za-z0-9]+$")
    track: str | None = Field(None, max_length=300)
    artist: str | None = Field(None, max_length=500)
    album: str | None = Field(None, max_length=300)
    reason_end: str | None = Field(None, max_length=40)
    skipped: bool | None = None


MAX_IMPORT_ROWS = 5000


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ImportPlayIn] = Field(..., max_length=MAX_IMPORT_ROWS)


class ImportOut(BaseModel):
    received: int
    added: int
    duplicates: int
