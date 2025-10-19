from pydantic import BaseModel 
from datetime import datetime

class Rotation(BaseModel):
    id: int | None = None
    name: str
    description: str | None = None
    playlist_id: str | None = None
    rotation_interval: int # in days
    created_at: datetime
    last_rotated_at: datetime | None = None
    owner_id: int
    