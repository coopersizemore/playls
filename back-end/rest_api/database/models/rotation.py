"""A rotation wraps one playlist the user owns or collaborates on."""
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from rest_api.clock import utcnow
from rest_api.database.config import Base

MANUAL = "manual"  # wraps a playlist; songs come due for review every interval
AUTO = "auto"  # created from scratch; PlayLS rotates songs out and restocks to a target size
KINDS = (MANUAL, AUTO)

# playlist_id of a rotation that wraps the user's Liked Songs (saved tracks) instead of a
# playlist. Real Spotify playlist ids are 22-character base62, so this can't collide, and
# the (owner, provider, playlist_id) unique constraint allows one per user. Code that misses
# the branch calls /playlists/liked and fails loudly (404) rather than touching any rows.
LIKED_SONGS = "liked"


def is_liked(rotation) -> bool:
    return rotation.playlist_id == LIKED_SONGS


class RotationDB(Base):
    __tablename__ = "rotation"
    __table_args__ = (
        UniqueConstraint("owner_id", "provider", "playlist_id", name="uq_rotation_owner_playlist"),
        CheckConstraint("interval_hours > 0", name="ck_rotation_interval_hours_positive"),
        CheckConstraint(f"kind IN {KINDS}", name="ck_rotation_kind"),
        CheckConstraint(
            "kind = 'manual' OR (target_size BETWEEN 1 AND 500 AND rotate_percent BETWEEN 1 AND 100)",
            name="ck_rotation_auto_settings",
        ),
        # A Liked Songs rotation is always manual (auto rotations would unlike on a schedule)
        CheckConstraint(f"playlist_id <> '{LIKED_SONGS}' OR kind = 'manual'", name="ck_rotation_liked_manual"),
    )

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(20), nullable=False, default="spotify", server_default="spotify")
    playlist_id = Column(String(64), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    # Playlist cover from Spotify, refreshed on every sync (mosaic covers change with the contents)
    image_url = Column(Text, nullable=True)
    kind = Column(String(10), nullable=False, default=MANUAL, server_default=MANUAL)
    # Review interval in hours (UI offers hours / days / weeks).
    # Auto rotations: how often a share of the playlist is rotated out and restocked.
    interval_hours = Column(Integer, nullable=False, default=30 * 24)
    # True: songs already in the playlist first come due at creation + interval.
    # False: they come due at their own added_at + interval (immediately if unknown).
    grace_period = Column(Boolean, nullable=False, default=True, server_default="true")

    # Auto rotations only: keep the playlist at target_size songs, swapping out
    # rotate_percent of target_size every interval
    target_size = Column(Integer, nullable=True)
    rotate_percent = Column(Integer, nullable=True)
    last_rotated_at = Column(DateTime, nullable=True)  # NULL: never yet (counts from created_at)
    # Per-rotation overrides of the owner's preferences (0012). NULL = use the account setting
    super_keep_multiplier = Column(Integer, nullable=True)
    skip_hold_days = Column(Integer, nullable=True)
    review_order = Column(String(20), nullable=True)
    review_limit = Column(Integer, nullable=True)  # 0 = no limit
    return_cooldown_days = Column(Integer, nullable=True)  # auto only
    pick_percent = Column(Integer, nullable=True)  # auto only: chance per new slot of a PlayLS pick
    bring_back_percent = Column(Integer, nullable=True)  # auto only: share of new slots that are returns
    # Listening overrides (0017). NULL = the account setting / default (services/preferences.py)
    heavy_listening_review = Column(String(12), nullable=True)  # manual only
    listening_hold_rotations = Column(Integer, nullable=True)  # auto only
    listening_protect_top_percent = Column(Integer, nullable=True)  # auto only
    # Lease held by the request syncing or writing this playlist (sync_service.sync_claim)
    sync_claimed_until = Column(DateTime, nullable=True)

    # Last playlist version we synced; an unchanged snapshot skips re-reading the items
    snapshot_id = Column(String(128), nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    # Also the grace-period anchor for songs already in the playlist (see DESIGN.md)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    owner = relationship("UserDB", back_populates="rotations")
    tracks = relationship(
        "RotationTrackDB", back_populates="rotation", cascade="all, delete-orphan", passive_deletes=True
    )
