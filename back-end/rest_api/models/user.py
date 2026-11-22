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


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Songs offered for review per rotation per day; null = no limit
    review_limit: int | None = Field(..., ge=1, le=1000)
