from pydantic import BaseModel
from datetime import datetime

class User(BaseModel):
    id: int
    spotify_id: str
    display_name: str | None = None
    email: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    created_at: datetime | None = None