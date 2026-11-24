"""Demo accounts: create and seed one, skip its clock ahead, end it, purge old ones.

A demo account is an ordinary users row with provider = 'demo'. Its Spotify calls go to
DemoSpotify (no network), so every rule (due dates, the queue, history, restock, auto
rotations) runs on the real code. Accounts are deleted DEMO_SESSION_HOURS after they're
created (real time), by purge_expired, which runs on every start and in the daily cron.
"""
import logging
import os
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from rest_api.clock import real_utcnow
from rest_api.database.models.review_event import KEEP, REMOVE, SKIP, SUPER_KEEP, ReviewEventDB
from rest_api.database.models.rotation import AUTO, MANUAL, RotationDB
from rest_api.database.models.rotation_track import ACTIVE, REMOVED, REMOVED_BY_USER, RotationTrackDB
from rest_api.database.models.user import DEMO, UserDB
from rest_api.services import health
from rest_api.services.auth_service import DEMO_SESSION_HOURS, REQUESTED_SCOPES
from rest_api.services.rotation_logic import parse_playlist_items

from .catalog import NEW_PLAYLIST_PREFIX, catalog
from .demo_spotify import sample_added_at, snapshot

logger = logging.getLogger(__name__)

# Most demo accounts alive at once; bounds what the public demo can add to the shared database
DEMO_MAX_ACTIVE = int(os.getenv("DEMO_MAX_ACTIVE", "100"))
SKIP_AHEAD_HOURS = 24
MAX_OFFSET_HOURS = 60 * 24

# Seeded manual rotation: weekly, with about this many songs due right away
DAILY_MIX_INTERVAL_HOURS = 7 * 24
DAILY_MIX_SIZE = 40
DUE_NOW = 15
REMOVED_COUNT = 4
UNPLAYABLE_COUNT = 2
# Seeded auto rotation
AUTO_SIZE = 30
AUTO_ROTATE_PERCENT = 20


def expires_at(user: UserDB):
    return user.created_at + timedelta(hours=DEMO_SESSION_HOURS)


def purge_expired(db: Session) -> int:
    """Delete demo accounts older than DEMO_SESSION_HOURS (their rows cascade in the database)."""
    cutoff = real_utcnow() - timedelta(hours=DEMO_SESSION_HOURS)
    n = (
        db.query(UserDB)
        .filter(UserDB.provider == DEMO, UserDB.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    if n:
        health.count("demo.purged", n)
    return n


def active_count(db: Session) -> int:
    return db.query(UserDB).filter(UserDB.provider == DEMO).count()


def start(db: Session) -> UserDB:
    """Create and seed a new demo account. 503 when DEMO_MAX_ACTIVE are already in use."""
    purge_expired(db)
    if active_count(db) >= DEMO_MAX_ACTIVE:
        health.count("demo.full")
        raise HTTPException(status_code=503, detail="The demo is full right now. Try again later.")
    cat = catalog()
    if len(cat.playlists) < 2:
        logger.error("Demo catalog is missing or too small (see scripts/build_demo_catalog.py)")
        raise HTTPException(status_code=503, detail="The demo isn't available right now.")
    now = real_utcnow()
    user = UserDB(
        provider=DEMO,
        spotify_id=f"demo-{secrets.token_urlsafe(12)}",
        display_name="Demo listener",
        created_at=now,
        analytics_consent=False,
        analytics_consent_at=now,
        granted_scopes=" ".join(REQUESTED_SCOPES),
    )
    db.add(user)
    db.flush()
    playlists = list(cat.playlists.values())
    _seed_daily_mix(db, user, playlists[0], now)
    _seed_auto(db, user, playlists[1], now)
    db.commit()
    db.refresh(user)
    health.count("demo.start")
    return user


def _rows_from(playlist_id: str, track_ids: list[str], rotation: RotationDB) -> list[RotationTrackDB]:
    """Rows for catalog tracks, parsed the same way a sync would parse them."""
    entries = [
        {"added_at": sample_added_at(i).isoformat() + "Z", "is_local": False, "item": t}
        for i, t in enumerate(catalog().resolve(track_ids))
    ]
    parsed = parse_playlist_items(entries)
    rows = []
    for t in parsed.values():
        rows.append(RotationTrackDB(
            rotation_id=rotation.id, track_id=t.track_id, uri=t.uri, title=t.title, artists=t.artists,
            album=t.album, image_url=t.image_url, duration_ms=t.duration_ms, is_playable=True,
            added_at=t.added_at, status=ACTIVE, keep_multiplier=1,
        ))
    return rows


def _event(db: Session, row: RotationTrackDB, action: str, at, **kw) -> None:
    db.add(ReviewEventDB(rotation_track_id=row.id, action=action, created_at=at, **kw))


def _seed_daily_mix(db: Session, user: UserDB, playlist: dict, now) -> None:
    """A weekly manual rotation with songs due now, some review history, a few removed songs
    (for Bring back) and a couple of unavailable ones (for Remove unavailable)."""
    track_ids = playlist["track_ids"][:DAILY_MIX_SIZE]
    rotation = RotationDB(
        owner_id=user.id, playlist_id=playlist["id"], name=playlist["name"][:100],
        description=playlist.get("description") or None, kind=MANUAL,
        interval_hours=DAILY_MIX_INTERVAL_HOURS, grace_period=True,
        created_at=now - timedelta(days=90), snapshot_id=snapshot(playlist["id"]), last_synced_at=now,
    )
    db.add(rotation)
    db.flush()
    rows = _rows_from(playlist["id"], track_ids, rotation)
    if rows and rows[0].image_url:
        rotation.image_url = rows[0].image_url
    db.add_all(rows)
    db.flush()
    interval = timedelta(hours=DAILY_MIX_INTERVAL_HOURS)
    removed = rows[len(rows) - REMOVED_COUNT:] if len(rows) > REMOVED_COUNT + DUE_NOW else []
    active = rows[:len(rows) - len(removed)]
    for i, row in enumerate(active):
        if i < DUE_NOW:
            # Kept a while back, now due (some overdue by a few days)
            row.last_kept_at = now - interval - timedelta(days=i % 5, hours=3 * i)
            _event(db, row, KEEP, row.last_kept_at)
        elif i % 7 == 0:
            # Super kept: waits three intervals
            row.keep_multiplier = 3
            row.last_kept_at = now - timedelta(days=4 + i % 9)
            _event(db, row, SUPER_KEEP, row.last_kept_at)
        else:
            row.last_kept_at = now - timedelta(days=1 + i % 6, hours=i)
            _event(db, row, KEEP, row.last_kept_at)
            if i % 3 == 0:
                _event(db, row, KEEP, row.last_kept_at - interval)
        if i % 11 == 5:
            _event(db, row, SKIP, row.last_kept_at - timedelta(days=2))
    for row in active[DUE_NOW - UNPLAYABLE_COUNT:DUE_NOW]:
        row.is_playable = False
    for j, row in enumerate(removed):
        row.status, row.removed_by = REMOVED, REMOVED_BY_USER
        row.removed_at = now - timedelta(days=20 + 15 * j)
        _event(db, row, KEEP, row.removed_at - interval * 2)
        _event(db, row, REMOVE, row.removed_at)


def _seed_auto(db: Session, user: UserDB, playlist: dict, now) -> None:
    """A weekly auto rotation whose next rotation is a couple of days out."""
    playlist_id = NEW_PLAYLIST_PREFIX + secrets.token_hex(6)
    rotation = RotationDB(
        owner_id=user.id, playlist_id=playlist_id, name="Fresh Rotation",
        description="PlayLS swaps a few of these out every week", kind=AUTO,
        interval_hours=7 * 24, grace_period=True, target_size=AUTO_SIZE, rotate_percent=AUTO_ROTATE_PERCENT,
        created_at=now - timedelta(days=40), last_rotated_at=now - timedelta(days=5),
        snapshot_id=snapshot(playlist_id), last_synced_at=now,
    )
    db.add(rotation)
    db.flush()
    rows = _rows_from(playlist_id, playlist["track_ids"][:AUTO_SIZE], rotation)
    for i, row in enumerate(rows):
        row.added_at = now - timedelta(days=5 + 7 * (i % 5), hours=i)
    if rows and rows[0].image_url:
        rotation.image_url = rows[0].image_url
    db.add_all(rows)


def skip_ahead(db: Session, user: UserDB) -> int:
    """Move the account's clock a day forward (songs come due, the daily limit resets)."""
    offset = min((user.demo_clock_offset_hours or 0) + SKIP_AHEAD_HOURS, MAX_OFFSET_HOURS)
    if offset == (user.demo_clock_offset_hours or 0):
        raise HTTPException(status_code=400, detail="The demo can't skip any further ahead")
    user.demo_clock_offset_hours = offset
    db.commit()
    health.count("demo.skip_ahead")
    return offset


def end(db: Session, user: UserDB) -> None:
    db.delete(user)
    db.commit()
