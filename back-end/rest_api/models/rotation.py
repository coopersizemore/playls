from pydantic import BaseModel 
from datetime import datetime

class Rotation(BaseModel):
    id: int
    name: str
    description: str | None = None
    playlist_id: str
    rotation_interval: int # in days
    created_at: datetime
    last_rotated_at: datetime | None = None
    songs_to_review: list[str] = []
    removed_songs: list[str] = []
    