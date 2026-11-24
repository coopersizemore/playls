"""PlayLS picks: songs hand-curated by an admin (ADMIN_SPOTIFY_IDS), shared by all users."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from rest_api.clock import utcnow
from rest_api.database.config import Base


class CuratedPickDB(Base):
    __tablename__ = "curated_pick"

    id = Column(Integer, primary_key=True)
    track_id = Column(String(64), nullable=False, index=True)
    uri = Column(String(128), nullable=False)
    title = Column(String(300), nullable=False)
    artists = Column(String(500), nullable=True)
    album = Column(String(300), nullable=True)
    image_url = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    note = Column(String(300), nullable=True)  # e.g. "Pick of the week"
    # Optional active window (naive UTC); NULL = open-ended
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
