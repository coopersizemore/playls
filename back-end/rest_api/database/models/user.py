"""User model. Rows hold Spotify tokens, so never return them from a route."""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from rest_api.clock import utcnow
from rest_api.database.config import Base
from rest_api.database.encryption import EncryptedText


class UserDB(Base):
    __tablename__ = "users"  # "user" is a reserved word in Postgres

    id = Column(Integer, primary_key=True)
    # Music provider the account logs in with (only "spotify" today; Apple is a maybe-later)
    provider = Column(String(20), nullable=False, default="spotify", server_default="spotify")
    spotify_id = Column(String(64), unique=True, index=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    # Spotify tokens, encrypted at rest
    access_token = Column(EncryptedText, nullable=True)
    refresh_token = Column(EncryptedText, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)  # naive UTC
    created_at = Column(DateTime, nullable=False, default=utcnow)

    rotations = relationship(
        "RotationDB", back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
