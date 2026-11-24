"""Per-user cache of the listening signals behind "Suggested for you" (refreshed every few hours)."""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer

from rest_api.clock import utcnow
from rest_api.database.config import Base


class SuggestionCacheDB(Base):
    __tablename__ = "suggestion_cache"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # {"candidates": {track_id: {...features}}, "missing_scopes": [...]}
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
