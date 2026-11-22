"""API schemas for rotations, their tracks, reviews and history."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_INTERVAL_HOURS = 365 * 24
DEFAULT_INTERVAL_HOURS = 30 * 24


class RotationCreate(BaseModel):
    """Wrap an existing playlist (playlist_id set) or create a new one (playlist_id omitted)."""

    model_config = ConfigDict(extra="forbid")  # owner_id/id/etc. can never be supplied

    playlist_id: str | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=300)
    interval_hours: int = Field(DEFAULT_INTERVAL_HOURS, ge=1, le=MAX_INTERVAL_HOURS)
    # Off: songs already in the playlist are due from their own added_at (immediately if unknown)
    grace_period: bool = True

    @model_validator(mode="after")
    def _name_required_for_new_playlist(self):
        if not self.playlist_id and not self.name:
            raise ValueError("name is required when creating a new playlist")
        return self


class RotationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=300)
    interval_hours: int | None = Field(None, ge=1, le=MAX_INTERVAL_HOURS)
    grace_period: bool | None = None


class RotationOut(BaseModel):
    id: int
    provider: str
    playlist_id: str
    name: str
    description: str | None
    interval_hours: int
    grace_period: bool
    created_at: datetime
    last_synced_at: datetime | None
    active_count: int
    due_count: int
    pending_removal_count: int
    next_due_at: datetime | None
    # Daily review limit (per rotation, resets at the user's local midnight)
    daily_limit: int | None  # None = no limit
    reviewed_today: int
    ready_today: int  # due songs offered today (not skipped today, within the limit)
    # False when the last sync attempt with Spotify failed (counts may be stale)
    sync_ok: bool = True


class TrackOut(BaseModel):
    track_id: str
    uri: str
    title: str
    artists: str | None
    album: str | None
    image_url: str | None
    duration_ms: int | None
    added_at: datetime | None  # None when Spotify didn't report it
    last_kept_at: datetime | None
    status: str
    due_at: datetime | None  # None unless active


class QueueOut(BaseModel):
    tracks: list[TrackOut]  # this batch, most overdue first
    due_count: int  # everything currently due, including songs skipped today
    daily_limit: int | None
    reviewed_today: int
    # Due songs left after this batch (excludes songs skipped today; they return tomorrow)
    remaining_after_batch: int
    # True when today's allowance is used up and more songs are due ("review more" offer)
    limit_reached: bool


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(..., min_length=1, max_length=64)
    action: Literal["keep", "skip", "remove", "undo"]


class FlushOut(BaseModel):
    removed: int
    pending: int


class HistoryEventOut(BaseModel):
    action: str
    created_at: datetime
    track: TrackOut
