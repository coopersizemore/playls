"""What the user did with a restock suggestion. "skip" (Not now) lowers that song's weight."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String
from rest_api.clock import utcnow
from rest_api.database.config import Base

ADD = "add"
SKIP = "skip"

BRING_BACK = "bring_back"
PICKS = "picks"
SUGGESTED = "suggested"
SEARCH = "search"
SOURCES = (BRING_BACK, PICKS, SUGGESTED, SEARCH)


class RestockFeedbackDB(Base):
    __tablename__ = "restock_feedback"
    __table_args__ = (
        CheckConstraint(f"action IN ('{ADD}', '{SKIP}')", name="ck_restock_feedback_action"),
        CheckConstraint(f"source IN {SOURCES}", name="ck_restock_feedback_source"),
        Index("ix_restock_feedback_user_track", "user_id", "track_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rotation_id = Column(Integer, ForeignKey("rotation.id", ondelete="SET NULL"), nullable=True)
    track_id = Column(String(64), nullable=False)
    source = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
