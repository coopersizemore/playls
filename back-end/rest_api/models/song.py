from pydantic import BaseModel
from datetime import datetime

class Song(BaseModel):
    id: str | None = None
    title: str
    artist: str
    album: str
    duration_ms: int
    added_at: datetime
    removed_at: datetime | None = None
    is_removed: bool = False
    reviewed_at: datetime | None = None
    is_reviewed: bool = False
