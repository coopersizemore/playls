from pydantic import BaseModel
from datetime import datetime


class User(BaseModel):
    """Internal: used by the OAuth callback to create a user row. Never returned to clients."""

    spotify_id: str
    display_name: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
