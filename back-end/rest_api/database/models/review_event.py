"""Append-only log of review decisions (feeds History, and Phase 2 "bring back")."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from rest_api.clock import utcnow
from rest_api.database.config import Base

KEEP = "keep"
SUPER_KEEP = "super_keep"  # comes due at the super keep length (default 3) x the interval
SKIP = "skip"
REMOVE = "remove"
UNDO = "undo"
# Recorded by auto rotations (not user decisions: they never count toward the daily limit
# and can't be undone)
ROTATED_OUT = "rotated_out"
AUTO_ADDED = "auto_added"
SYSTEM_ACTIONS = (ROTATED_OUT, AUTO_ADDED)
ACTIONS = (KEEP, SUPER_KEEP, SKIP, REMOVE, UNDO, ROTATED_OUT, AUTO_ADDED)
KEEP_ACTIONS = (KEEP, SUPER_KEEP)


class ReviewEventDB(Base):
    __tablename__ = "review_event"
    __table_args__ = (CheckConstraint(f"action IN {ACTIONS}", name="ck_review_event_action"),)

    id = Column(Integer, primary_key=True)
    rotation_track_id = Column(
        Integer, ForeignKey("rotation_track.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action = Column(String(12), nullable=False)
    # keeps only: the track's keep state before this keep, restored if the keep is undone
    previous_last_kept_at = Column(DateTime, nullable=True)
    previous_keep_multiplier = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)

    track = relationship("RotationTrackDB", back_populates="events")
