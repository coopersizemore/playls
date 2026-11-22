"""API schemas for restocking (bring back, PlayLS picks, suggestions, search) and pick curation."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DeckSource = Literal["bring_back", "picks", "suggested"]
Source = Literal["bring_back", "picks", "suggested", "search"]


class CandidateOut(BaseModel):
    track_id: str
    uri: str
    title: str
    artists: str | None
    album: str | None
    image_url: str | None
    duration_ms: int | None
    source: Source
    reason: str | None = None  # why it's suggested, e.g. "Removed 4 months ago"
    score: float | None = None  # ranking weight (not shown to users)
    note: str | None = None  # curator's note for PlayLS picks
    in_rotation: bool = False  # search results only


class DeckOut(BaseModel):
    source: DeckSource
    items: list[CandidateOut]
    # Spotify permissions this source needs that the user hasn't granted (reconnect to fix)
    missing_scopes: list[str] = []


class SearchOut(BaseModel):
    items: list[CandidateOut]
    next_offset: int | None


class RestockActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9]+$")
    source: Source


class PickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9]+$")
    note: str | None = Field(None, max_length=300)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class PickOut(BaseModel):
    id: int
    track_id: str
    uri: str
    title: str
    artists: str | None
    album: str | None
    image_url: str | None
    note: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    active: bool
