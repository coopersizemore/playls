"""App health for the admin dashboard: one row per (sampled) API request.

No user column, by design: this is operational data (route template, status, timings and
counters such as sync outcomes or Spotify 429s), recorded for everyone regardless of the
analytics consent. Errors, slow requests and requests with counters are always recorded;
other requests are sampled (services/health.py). Kept for 6 months.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from rest_api.clock import utcnow
from rest_api.database.config import Base


class HealthEventDB(Base):
    __tablename__ = "health_event"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    method = Column(String(8), nullable=False)
    route = Column(String(120), nullable=False)  # the route template, e.g. /api/rotation/{rotation_id}
    status = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    spotify_ms = Column(Integer, nullable=False, default=0)
    spotify_calls = Column(Integer, nullable=False, default=0)
    db_ms = Column(Integer, nullable=False, default=0)
    db_queries = Column(Integer, nullable=False, default=0)
    db_connects = Column(Integer, nullable=False, default=0)
    sampled = Column(Boolean, nullable=False)  # True: kept by sampling (counts for latency percentiles)
    counters = Column(Text, nullable=True)  # JSON {name: n}, e.g. {"sync.full_read": 1}
