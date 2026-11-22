"""One row per (rotation, track). Spotify is the source of truth; sync keeps these in line."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from rest_api.database.config import Base

ACTIVE = "active"
PENDING_REMOVAL = "pending_removal"  # user swiped remove; not yet removed on Spotify
REMOVED = "removed"
STATUSES = (ACTIVE, PENDING_REMOVAL, REMOVED)

REMOVED_BY_USER = "user"
REMOVED_BY_EXTERNAL = "external"  # disappeared from the playlist outside PlayLS


class RotationTrackDB(Base):
    __tablename__ = "rotation_track"
    __table_args__ = (
        # Duplicate copies in a playlist collapse to one row (removal removes every copy)
        UniqueConstraint("rotation_id", "track_id", name="uq_rotation_track"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_rotation_track_status"),
        CheckConstraint(
            f"removed_by IS NULL OR removed_by IN ('{REMOVED_BY_USER}', '{REMOVED_BY_EXTERNAL}')",
            name="ck_rotation_track_removed_by",
        ),
        Index("ix_rotation_track_rotation_status", "rotation_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    rotation_id = Column(Integer, ForeignKey("rotation.id", ondelete="CASCADE"), nullable=False)
    track_id = Column(String(64), nullable=False)  # provider's track id
    uri = Column(String(128), nullable=False)  # provider URI used for removal

    title = Column(String(300), nullable=False)
    artists = Column(String(500), nullable=True)  # comma-separated display string
    album = Column(String(300), nullable=True)
    image_url = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    added_at = Column(DateTime, nullable=False)  # from Spotify (earliest copy), naive UTC
    last_kept_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default=ACTIVE, server_default=ACTIVE)
    removed_at = Column(DateTime, nullable=True)
    removed_by = Column(String(10), nullable=True)

    rotation = relationship("RotationDB", back_populates="tracks")
    events = relationship(
        "ReviewEventDB", back_populates="track", cascade="all, delete-orphan", passive_deletes=True
    )
