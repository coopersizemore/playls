"""User model. Rows hold Spotify tokens, so never return them from a route."""
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from rest_api.clock import utcnow
from rest_api.database.config import Base
from rest_api.database.encryption import EncryptedText

DEFAULT_REVIEW_LIMIT = 50
MAX_REVIEW_LIMIT = 1000


class UserDB(Base):
    __tablename__ = "users"  # "user" is a reserved word in Postgres
    __table_args__ = (
        CheckConstraint(
            f"review_limit IS NULL OR (review_limit BETWEEN 1 AND {MAX_REVIEW_LIMIT})",
            name="ck_users_review_limit_range",
        ),
    )

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
    # Max songs offered for review per rotation per day; NULL = no limit
    review_limit = Column(
        Integer, nullable=True, default=DEFAULT_REVIEW_LIMIT, server_default=str(DEFAULT_REVIEW_LIMIT)
    )

    # Account-wide preferences (0012). NULL = the built-in default; see services/preferences.py
    super_keep_multiplier = Column(Integer, nullable=True)
    skip_hold_days = Column(Integer, nullable=True)
    review_order = Column(String(20), nullable=True)
    default_interval_hours = Column(Integer, nullable=True)
    deck_size = Column(Integer, nullable=True)
    discovery_percent = Column(Integer, nullable=True)
    not_now_percent = Column(Integer, nullable=True)
    bring_back_recovery_days = Column(Integer, nullable=True)

    # Usage analytics opt-in (0013): NULL = not asked yet, then True / False (changeable in Settings)
    analytics_consent = Column(Boolean, nullable=True)
    analytics_consent_at = Column(DateTime, nullable=True)

    # Space-separated OAuth scopes granted at the last login (to detect missing ones)
    granted_scopes = Column(Text, nullable=True)

    rotations = relationship(
        "RotationDB", back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
