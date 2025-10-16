"""Database models using SQLAlchemy."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from rest_api.database.config import Base

class Rotation(Base):
    """Rotation model for storing playlist rotations."""
    
    __tablename__ = "rotation"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    playlist_id = Column(String(50), nullable=False)
    rotation_interval = Column(Integer, default=10)
    created_at = Column(DateTime, server_default=func.now())
    last_rotated_at = Column(DateTime, nullable=True)
    
    # Foreign keys
    owner_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    
    # Relationships
    owner = relationship("User", back_populates="rotation")
    songs = relationship("Song", back_populates="rotation")