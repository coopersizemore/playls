"""Listening history (0017): plays, capture gaps and the latest top-tracks snapshot.

Captured by services/listening_service.py (daily cron, app open, login) or imported from
Spotify's Extended Streaming History export. Per user, cascade-deleted with the account,
deleted when the user turns listening history off, and purged after RETENTION_DAYS.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from rest_api.database.config import Base

API = "api"  # captured from GET /me/player/recently-played
IMPORT = "import"  # from the user's Extended Streaming History export

TIME_RANGES = ("short_term", "medium_term", "long_term")


class PlayEventDB(Base):
    __tablename__ = "play_event"
    __table_args__ = (
        CheckConstraint(f"source IN ('{API}', '{IMPORT}')", name="ck_play_event_source"),
        UniqueConstraint("user_id", "played_at", name="uq_play_event_user_played_at"),
        Index("ix_play_event_user_song", "user_id", "song_key", "played_at"),
        Index("ix_play_event_user_track", "user_id", "track_id", "played_at"),
        Index("ix_play_event_user_context", "user_id", "context_uri", "played_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # The id Spotify reports for the play (may be a relinked id; match on song_key too)
    track_id = Column(String(64), nullable=False)
    song_key = Column(String(400), nullable=True)  # restock_logic.song_key(title, artists)
    uri = Column(String(128), nullable=True)
    title = Column(String(300), nullable=True)
    artists = Column(String(500), nullable=True)
    album = Column(String(300), nullable=True)
    image_url = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    played_at = Column(DateTime, nullable=False)  # naive UTC
    # Where it was played from: "playlist", "album", "artist", "collection" (Liked Songs)...
    context_type = Column(String(20), nullable=True)
    context_uri = Column(String(200), nullable=True)
    source = Column(String(10), nullable=False, default=API, server_default=API)
    # Imported rows only: how long it played, and whether the user skipped it
    ms_played = Column(Integer, nullable=True)
    skipped = Column(Boolean, nullable=True)
    reason_end = Column(String(20), nullable=True)


class ListeningGapDB(Base):
    """A span where plays were probably missed: a capture found 50 new plays, all newer
    than the last one stored."""

    __tablename__ = "listening_gap"
    __table_args__ = (Index("ix_listening_gap_user", "user_id", "gap_end"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gap_start = Column(DateTime, nullable=False)
    gap_end = Column(DateTime, nullable=False)


class TopTrackDB(Base):
    """The latest GET /me/top/tracks snapshot (replaced on each refresh)."""

    __tablename__ = "top_track"
    __table_args__ = (Index("ix_top_track_user_range", "user_id", "time_range"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    time_range = Column(String(12), nullable=False)
    rank = Column(Integer, nullable=False)  # 0 = top
    track_id = Column(String(64), nullable=False)
    song_key = Column(String(400), nullable=True)
    captured_at = Column(DateTime, nullable=False)
