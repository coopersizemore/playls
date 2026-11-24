"""Usage analytics for the admin dashboard (docs/MONITORING_PLAN.md).

Append-only and separate from review_event/restock_feedback, which undo deletes. Written only
for users who opted in (users.analytics_consent); turning consent off deletes a user's rows,
and so does deleting the account (cascade). Kept for 6 months. No track ids: the dashboard
only needs timing and choices.
"""
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String

from rest_api.clock import utcnow
from rest_api.database.config import Base

REVIEW = "review"
RESTOCK = "restock"
SURFACES = (REVIEW, RESTOCK)

DECISION = "decision"
UNDO = "undo"
SESSION_END = "session_end"
KINDS = (DECISION, UNDO, SESSION_END)

INPUTS = ("swipe", "button", "key")
ENDINGS = ("done", "stopped", "left", "exhausted")


class AnalyticsEventDB(Base):
    __tablename__ = "analytics_event"
    __table_args__ = (
        CheckConstraint(f"surface IN {SURFACES}", name="ck_analytics_event_surface"),
        CheckConstraint(f"kind IN {KINDS}", name="ck_analytics_event_kind"),
        Index("ix_analytics_event_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Stats survive deleting a rotation; its kind is copied so they can still be split by kind
    rotation_id = Column(Integer, ForeignKey("rotation.id", ondelete="SET NULL"), nullable=True)
    rotation_kind = Column(String(10), nullable=True)
    surface = Column(String(10), nullable=False)
    kind = Column(String(12), nullable=False)
    session_id = Column(String(36), nullable=True, index=True)  # one per Review / Restock page visit
    action = Column(String(12), nullable=True)  # keep / remove / ... or add / not_now / block
    source = Column(String(20), nullable=True)  # restock source
    decision_ms = Column(Integer, nullable=True)  # card shown -> decision (time hidden excluded)
    session_elapsed_ms = Column(Integer, nullable=True)  # page opened -> this event
    input = Column(String(8), nullable=True)  # swipe | button | key
    revisit = Column(Boolean, nullable=True)  # decided again after going Back
    position = Column(Integer, nullable=True)  # card index in the batch / deck
    # Reviews only, from the song's state just before the decision
    song_age_days = Column(Integer, nullable=True)  # since added, or since last kept
    overdue_days = Column(Integer, nullable=True)  # manual rotations: days past due (0 = just due)
    # The user's local time of day (from the client's timezone offset)
    local_hour = Column(Integer, nullable=True)
    local_weekday = Column(Integer, nullable=True)  # 0 = Monday
    # session_end only
    ended = Column(String(12), nullable=True)
    decisions = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)
