from pydantic import BaseModel
from datetime import datetime

class Song(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    duration_ms: int
    added_at: datetime
    removed_at: datetime | None = None
    reviewed_at: datetime | None = None
    is_removed: bool = False
    is_reviewed: bool = False
    