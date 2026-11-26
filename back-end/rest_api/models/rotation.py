"""API schemas for rotations, their tracks, reviews and history."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rest_api.services.auto_rotation_logic import (
    DEFAULT_INTERVAL_HOURS as AUTO_DEFAULT_INTERVAL_HOURS,
)
from rest_api.services.auto_rotation_logic import (
    DEFAULT_ROTATE_PERCENT,
    DEFAULT_TARGET_SIZE,
)

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
    # "auto": a new playlist PlayLS keeps at target_size, swapping out rotate_percent of it
    # every interval_hours (default weekly)
    kind: Literal["manual", "auto"] = "manual"
    target_size: Literal[30, 50, 100, 200] | None = None
    rotate_percent: int | None = Field(None, ge=5, le=100)
    # Wrap the user's Liked Songs instead of a playlist: removing a song unlikes it
    liked_songs: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.liked_songs:
            if self.playlist_id:
                raise ValueError("liked_songs and playlist_id can't both be set")
            if self.kind != "manual":
                raise ValueError("a Liked Songs rotation can't be an auto rotation")
            return self
        if not self.playlist_id and not self.name:
            raise ValueError("name is required when creating a new playlist")
        if self.kind == "auto":
            if self.playlist_id:
                raise ValueError("auto rotations always start from a new playlist")
            if self.target_size is None:
                self.target_size = DEFAULT_TARGET_SIZE
            if self.rotate_percent is None:
                self.rotate_percent = DEFAULT_ROTATE_PERCENT
            if "interval_hours" not in self.model_fields_set:
                self.interval_hours = AUTO_DEFAULT_INTERVAL_HOURS
        elif self.target_size is not None or self.rotate_percent is not None:
            raise ValueError("target_size and rotate_percent are only for auto rotations")
        return self


class RotationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=300)
    interval_hours: int | None = Field(None, ge=1, le=MAX_INTERVAL_HOURS)
    grace_period: bool | None = None
    target_size: Literal[30, 50, 100, 200] | None = None  # auto rotations only
    rotate_percent: int | None = Field(None, ge=5, le=100)
    # Overrides of the account settings; null = use the account setting
    super_keep_multiplier: Literal[2, 3, 5] | None = None
    skip_hold_days: Literal[1, 3, 7] | None = None
    review_order: Literal["listening", "overdue", "oldest", "shuffle"] | None = None
    heavy_listening_review: Literal["inform", "less_often", "never"] | None = None
    review_limit: int | None = Field(None, ge=0, le=1000)  # 0 = no limit for this rotation
    # Auto rotations only; null = the default
    return_cooldown_days: Literal[14, 28, 56] | None = None
    pick_percent: Literal[0, 10, 25] | None = None
    bring_back_percent: Literal[0, 20, 40] | None = None
    listening_hold_rotations: Literal[1, 2, 3] | None = None
    listening_protect_top_percent: Literal[0, 10, 25] | None = None


class RotationOverrides(BaseModel):
    """A rotation's own settings as stored (null = uses the account setting or default)."""
    super_keep_multiplier: int | None = None
    skip_hold_days: int | None = None
    review_order: str | None = None
    heavy_listening_review: str | None = None
    review_limit: int | None = None  # 0 = no limit
    return_cooldown_days: int | None = None
    pick_percent: int | None = None
    bring_back_percent: int | None = None


class RotationListeningOut(BaseModel):
    """This rotation's listening over its window (listening history)."""
    window_days: int
    plays_here: int  # plays from this playlist
    top_song: str | None = None  # the rotation's most played song (title)
    top_song_plays: int = 0


class RotationOut(BaseModel):
    id: int
    provider: str
    playlist_id: str
    name: str
    description: str | None
    image_url: str | None  # playlist cover
    interval_hours: int
    grace_period: bool
    kind: str = "manual"  # "auto": PlayLS rotates out and restocks on its own
    is_liked: bool = False  # wraps the user's Liked Songs: removing a song unlikes it
    target_size: int | None = None
    rotate_percent: int | None = None
    last_rotated_at: datetime | None = None
    next_rotation_at: datetime | None = None  # auto only
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
    # Settings in effect for this rotation (its override, else the account setting)
    super_keep_multiplier: int = 3
    skip_hold_days: int = 1
    review_order: str = "listening"
    heavy_listening_review: str = "inform"
    overrides: RotationOverrides = RotationOverrides()
    listening: RotationListeningOut | None = None  # None: listening history off


class ListeningOut(BaseModel):
    """A song's listening over the rotation's window (see services/listening_logic.py)."""
    window_days: int
    plays: int  # from anywhere
    plays_here: int  # from this rotation's playlist
    last_played_at: datetime | None = None
    # Current top tracks: time range (short_term | medium_term | long_term) -> rank (0 = #1)
    top_rank: dict[str, int] = {}
    heavy: bool = False  # "you listen to this a lot"
    few_plays: bool = False  # confidently not played lately
    held: bool = False  # left out of reviews while heavily played (heavy_listening_review = never)
    # Imported history only: starts in the window and how many were skipped
    starts: int = 0
    skips: int = 0


class TrackOut(BaseModel):
    track_id: str
    uri: str
    title: str
    artists: str | None
    album: str | None
    image_url: str | None
    duration_ms: int | None
    is_playable: bool = True  # False: in the playlist but unavailable on Spotify
    added_at: datetime | None  # None when Spotify didn't report it
    last_kept_at: datetime | None
    keep_multiplier: int = 1  # 3 after a super keep
    status: str
    # None unless active. Auto rotations: when the song is expected to rotate out
    due_at: datetime | None
    protected: bool = False  # auto: kept since the last rotation, so it stays for the next one
    # Filled in by GET /rotation/{id}/tracks only (0 / None elsewhere)
    times_kept: int = 0  # keeps + super keeps over the song's whole time in the rotation
    last_reviewed_at: datetime | None = None  # latest keep, super keep, skip or remove
    listening: ListeningOut | None = None  # None: no listening history to show


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
    action: Literal["keep", "super_keep", "skip", "remove", "undo"]
    # Optional client timing for usage analytics; parsed leniently (bad values are dropped)
    telemetry: Any = None


class UnplayableOut(BaseModel):
    tracks: list[TrackOut]  # active songs Spotify reports as unavailable


class RemoveUnplayableOut(BaseModel):
    removed: int
    flushed: bool  # False: Spotify couldn't be reached; removals are retried on the next sync


class FlushOut(BaseModel):
    removed: int
    pending: int


class HistoryEventOut(BaseModel):
    action: str
    created_at: datetime
    track: TrackOut
    # Keeps and removals, when listening history covers it: plays of the song (anywhere) in
    # the `plays_window_hours` before the event, and (removals) since
    plays_before: int | None = None
    plays_window_hours: int | None = None
    plays_since: int | None = None


class ListeningSongOut(BaseModel):
    track_id: str
    title: str | None
    artists: str | None
    image_url: str | None
    plays: int
    plays_here: int


class ListeningDayOut(BaseModel):
    """One day (the user's local date) of this rotation's listening."""
    date: str  # YYYY-MM-DD
    plays_here: int  # plays from this playlist
    plays_elsewhere: int  # plays of its songs from anywhere else
    songs: list[ListeningSongOut]


class ListeningDigestOut(BaseModel):
    since: datetime | None  # earliest moment the listening history covers
    days: list[ListeningDayOut]  # newest first, days with plays only
