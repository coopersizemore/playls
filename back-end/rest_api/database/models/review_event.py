"""Append-only log of review decisions (feeds History, and Phase 2 "bring back")."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from rest_api.clock import utcnow
from rest_api.database.config import Base

KEEP = "keep"
SKIP = "skip"
REMOVE = "remove"
UNDO = "undo"
ACTIONS = (KEEP, SKIP, REMOVE, UNDO)


class ReviewEventDB(Base):
    __tablename__ = "review_event"
    __table_args__ = (CheckConstraint(f"action IN {ACTIONS}", name="ck_review_event_action"),)

    id = Column(Integer, primary_key=True)
    rotation_track_id = Column(
        Integer, ForeignKey("rotation_track.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action = Column(String(10), nullable=False)
    # keep only: last_kept_at before this keep, restored if the keep is undone
    previous_last_kept_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)

    track = relationship("RotationTrackDB", back_populates="events")
