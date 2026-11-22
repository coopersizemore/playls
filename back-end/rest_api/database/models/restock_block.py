"""Songs a user asked PlayLS to stop suggesting ("Stop suggesting" in Restock).

Blocked songs never appear in the Bring back, PlayLS picks or For you decks (score 0),
but stay in rotation History. Manual Search and History's "Add back" still work.
Deleting the row ("Resume suggesting" in Settings) undoes it.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from rest_api.clock import utcnow
from rest_api.database.config import Base


class RestockBlockDB(Base):
    __tablename__ = "restock_block"
    __table_args__ = (UniqueConstraint("user_id", "track_id", name="uq_restock_block_user_track"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(String(64), nullable=False)
    # Display metadata for the Settings list
    title = Column(String(300), nullable=False)
    artists = Column(String(500), nullable=True)
    image_url = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
