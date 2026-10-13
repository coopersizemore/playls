"""Database models using SQLAlchemy."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from rest_api.database.config import Base
from rest_api.database.encryption import EncryptedText

class UserDB(Base):
    """User model for storing user information."""
    
    __tablename__ = "users"  # "user" is a reserved word in Postgres
    
    id = Column(Integer, primary_key=True, index=True)
    spotify_id = Column(String(50), unique=True, index=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    email = Column(String(100), unique=True, index=True, nullable=True)
    # Spotify tokens, encrypted at rest
    access_token = Column(EncryptedText, nullable=True)
    refresh_token = Column(EncryptedText, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    rotations = relationship("RotationDB", back_populates="owner", cascade="all, delete-orphan")