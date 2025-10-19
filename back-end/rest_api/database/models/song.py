"""Database models using SQLAlchemy."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from rest_api.database.config import Base

class SongDB(Base):
    __tablename__ = "song"

    id = Column(String(50), primary_key=True, index=True)
    title = Column(String(100), index=True)
    artist = Column(String(100), index=True)
    album = Column(String(100), index=True)
    duration_ms = Column(Integer)
    added_at = Column(DateTime, default=func.now())
    removed_at = Column(DateTime, default=None)
    is_removed = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, default=None)
    is_reviewed = Column(Boolean, default=False)

    # Foreign keys
    rotation_id = Column(Integer, ForeignKey("rotation.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("user.id"), nullable=False)

    # Relationships
    rotation = relationship("RotationDB", back_populates="song")
    owner = relationship("UserDB", back_populates="song")