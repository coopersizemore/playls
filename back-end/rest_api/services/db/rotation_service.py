"""Rotation CRUD, the due queue, review decisions and history."""
import logging
from collections import defaultdict
from typing import Iterable

import sqlalchemy.orm as orm
from fastapi import HTTPException

from rest_api.clock import utcnow
from rest_api.database.models.review_event import KEEP, KEEP_ACTIONS, REMOVE, SKIP, SUPER_KEEP, UNDO, ReviewEventDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.rotation_track import ACTIVE, PENDING_REMOVAL, RotationTrackDB
from rest_api.database.models.user import UserDB
from rest_api.models.rotation import (
    HistoryEventOut,
    QueueOut,
    RotationCreate,
    RotationOut,
    RotationUpdate,
    TrackOut,
)
from rest_api.services import rotation_logic as logic
from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService as ss
from rest_api.services.sync_service import sync_rotation

logger = logging.getLogger(__name__)

SUPER_KEEP_MULTIPLIER = 3

PLAYLIST_META_FIELDS = "id,name,description,snapshot_id,collaborative,owner(id),images"


# ---------- reads / serialization ----------

def get_owned_rotation(db: orm.Session, rotation_id: int, owner_id: int) -> RotationDB | None:
    return db.query(RotationDB).filter(RotationDB.id == rotation_id, RotationDB.owner_id == owner_id).first()


def get_user_rotations(db: orm.Session, owner_id: int) -> list[RotationDB]:
    return db.query(RotationDB).filter(RotationDB.owner_id == owner_id).order_by(RotationDB.created_at).all()


def _live_tracks(db: orm.Session, rotation_ids: Iterable[int]) -> dict[int, list[RotationTrackDB]]:
    ids = list(rotation_ids)
    by_rotation: dict[int, list[RotationTrackDB]] = defaultdict(list)
    if not ids:
        return by_rotation
    rows = db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id.in_(ids),
        RotationTrackDB.status.in_((ACTIVE, PENDING_REMOVAL)),
    )
    for row in rows:
        by_rotation[row.rotation_id].append(row)
    return by_rotation


class DailyActivity:
    """Today's review activity for one rotation (since the user's local midnight)."""

    def __init__(self):
        self.reviewed = 0  # keep + skip + remove, minus undos
        self.skipped_track_ids: set[int] = set()  # rotation_track ids skipped today


def _todays_activity(db: orm.Session, rotation_ids: Iterable[int], since) -> dict[int, DailyActivity]:
    ids = list(rotation_ids)
    activity: dict[int, DailyActivity] = defaultdict(DailyActivity)
    if not ids:
        return activity
    rows = (
        db.query(RotationTrackDB.rotation_id, ReviewEventDB.rotation_track_id, ReviewEventDB.action)
        .join(RotationTrackDB, ReviewEventDB.rotation_track_id == RotationTrackDB.id)
        .filter(RotationTrackDB.rotation_id.in_(ids), ReviewEventDB.created_at >= since)
    )
    for rotation_id, track_row_id, action in rows:
        day = activity[rotation_id]
        day.reviewed += -1 if action == UNDO else 1
        if action == SKIP:
            day.skipped_track_ids.add(track_row_id)
    for day in activity.values():
        day.reviewed = max(0, day.reviewed)
    return activity


def _eligible_due(rotation: RotationDB, tracks: list[RotationTrackDB], day: DailyActivity, now) -> list:
    """Due active tracks that weren't skipped today, most overdue first."""
    due = [
        t for t in tracks
        if t.status == ACTIVE and logic.is_due(t, rotation, now) and t.id not in day.skipped_track_ids
    ]
    return logic.sort_queue(due, rotation)


def summarize(
    rotation: RotationDB,
    tracks: list[RotationTrackDB],
    sync_ok: bool = True,
    day: DailyActivity | None = None,
) -> RotationOut:
    now = utcnow()
    day = day or DailyActivity()
    limit = rotation.owner.review_limit
    active = [t for t in tracks if t.status == ACTIVE]
    due_dates = [logic.due_at(t, rotation) for t in active]
    upcoming = [d for d in due_dates if d > now]
    eligible = len(_eligible_due(rotation, tracks, day, now))
    return RotationOut(
        id=rotation.id,
        provider=rotation.provider,
        playlist_id=rotation.playlist_id,
        name=rotation.name,
        description=rotation.description,
        image_url=rotation.image_url,
        interval_hours=rotation.interval_hours,
        grace_period=rotation.grace_period,
        created_at=rotation.created_at,
        last_synced_at=rotation.last_synced_at,
        active_count=len(active),
        due_count=sum(1 for d in due_dates if d <= now),
        pending_removal_count=sum(1 for t in tracks if t.status == PENDING_REMOVAL),
        next_due_at=min(upcoming) if upcoming else None,
        daily_limit=limit,
        reviewed_today=day.reviewed,
        ready_today=logic.todays_batch_size(limit, day.reviewed, eligible, more=False),
        sync_ok=sync_ok,
    )


def summarize_one(
    db: orm.Session, rotation: RotationDB, sync_ok: bool = True, tz_offset_minutes: int = 0
) -> RotationOut:
    since = logic.local_day_start(utcnow(), tz_offset_minutes)
    day = _todays_activity(db, [rotation.id], since)[rotation.id]
    return summarize(rotation, _live_tracks(db, [rotation.id])[rotation.id], sync_ok, day)


def track_out(track: RotationTrackDB, rotation: RotationDB) -> TrackOut:
    return TrackOut(
        track_id=track.track_id,
        uri=track.uri,
        title=track.title,
        artists=track.artists,
        album=track.album,
        image_url=track.image_url,
        duration_ms=track.duration_ms,
        is_playable=track.is_playable,
        added_at=track.added_at,
        last_kept_at=track.last_kept_at,
        keep_multiplier=track.keep_multiplier or 1,
        status=track.status,
        due_at=logic.due_at(track, rotation),
    )


# ---------- sync wrappers ----------

async def try_sync(db: orm.Session, rotation: RotationDB, user: UserDB, force: bool = False) -> bool:
    """Sync, but don't fail the request if Spotify is unavailable. Returns sync_ok."""
    try:
        await sync_rotation(db, rotation, user, force=force)
        return True
    except Exception:
        # Spotify errors, timeouts, or a concurrent sync inserting the same rows
        db.rollback()
        logger.warning("Sync failed for rotation %s", rotation.id, exc_info=True)
        return False


async def list_rotation_summaries(
    db: orm.Session, user: UserDB, sync: bool = True, tz_offset_minutes: int = 0
) -> list[RotationOut]:
    rotations = get_user_rotations(db, user.id)
    sync_ok = {r.id: (await try_sync(db, r, user)) if sync else True for r in rotations}
    ids = [r.id for r in rotations]
    tracks = _live_tracks(db, ids)
    activity = _todays_activity(db, ids, logic.local_day_start(utcnow(), tz_offset_minutes))
    return [summarize(r, tracks[r.id], sync_ok[r.id], activity[r.id]) for r in rotations]


# ---------- create / update / delete ----------

async def create_rotation(db: orm.Session, data: RotationCreate, owner: UserDB) -> tuple[RotationDB, bool]:
    """Wrap an owned/collaborative playlist, or create a new private one. Returns (rotation, sync_ok)."""
    if data.playlist_id:
        if db.query(RotationDB).filter(
            RotationDB.owner_id == owner.id, RotationDB.playlist_id == data.playlist_id
        ).first():
            raise HTTPException(status_code=409, detail="This playlist already has a rotation")
        try:
            playlist = await ss.get_playlist(data.playlist_id, owner, db, fields=PLAYLIST_META_FIELDS)
        except SpotifyAPIError as e:
            if e.upstream_status in (403, 404):
                raise HTTPException(status_code=404, detail="Playlist not found")
            raise
        owns = (playlist.get("owner") or {}).get("id") == owner.spotify_id
        if not owns and not playlist.get("collaborative"):
            raise HTTPException(
                status_code=400, detail="You can only rotate playlists you own or collaborate on"
            )
        name = data.name or playlist.get("name") or "Rotation"
        description = data.description if data.description is not None else (playlist.get("description") or None)
        playlist_id = data.playlist_id
    else:
        playlist = await ss.create_playlist(data.name, owner, db, description=data.description, public=False)
        name, description, playlist_id = data.name, data.description, playlist["id"]

    rotation = RotationDB(
        owner_id=owner.id,
        playlist_id=playlist_id,
        name=name[:100],
        description=description,
        image_url=logic.playlist_image(playlist),
        interval_hours=data.interval_hours,
        grace_period=data.grace_period,
        created_at=utcnow(),
    )
    db.add(rotation)
    db.commit()
    db.refresh(rotation)
    # Initial import (grace_period decides when songs already in the playlist come due)
    sync_ok = await try_sync(db, rotation, owner, force=True)
    return rotation, sync_ok


def update_rotation(db: orm.Session, rotation: RotationDB, data: RotationUpdate) -> RotationDB:
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in ("name", "interval_hours", "grace_period") and value is None:
            continue  # not nullable
        setattr(rotation, key, value)
    db.commit()
    db.refresh(rotation)
    return rotation


def delete_rotation(db: orm.Session, rotation: RotationDB) -> None:
    """Deletes the rotation and its history; the Spotify playlist is left untouched."""
    db.delete(rotation)
    db.commit()


# ---------- queue / review / history ----------

def _tracks(db: orm.Session, rotation: RotationDB, statuses: tuple[str, ...]) -> list[RotationTrackDB]:
    return db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.status.in_(statuses)
    ).all()


def all_songs_queue(db: orm.Session, rotation: RotationDB, tz_offset_minutes: int = 0) -> QueueOut:
    """Every active song, soonest due first (overdue ones first), ignoring the daily limit."""
    now = utcnow()
    day = _todays_activity(db, [rotation.id], logic.local_day_start(now, tz_offset_minutes))[rotation.id]
    active = logic.sort_queue(_tracks(db, rotation, (ACTIVE,)), rotation)
    return QueueOut(
        tracks=[track_out(t, rotation) for t in active],
        due_count=sum(1 for t in active if logic.is_due(t, rotation, now)),
        daily_limit=None,
        reviewed_today=day.reviewed,
        remaining_after_batch=0,
        limit_reached=False,
    )


def reset_due_dates(db: orm.Session, rotation: RotationDB) -> int:
    """Treat every active song as just reviewed: each comes due one interval from now.

    Not recorded as keeps (no review events), so it doesn't touch History or the daily limit.
    """
    now = utcnow()
    tracks = _tracks(db, rotation, (ACTIVE,))
    for track in tracks:
        track.last_kept_at = now
        track.keep_multiplier = 1
    db.commit()
    return len(tracks)


def unplayable_tracks(db: orm.Session, rotation: RotationDB) -> list[TrackOut]:
    rows = db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id == rotation.id,
        RotationTrackDB.status == ACTIVE,
        RotationTrackDB.is_playable.is_(False),
    ).order_by(RotationTrackDB.title)
    return [track_out(t, rotation) for t in rows]


def queue_unplayable_removals(db: orm.Session, rotation: RotationDB) -> int:
    """Mark every unavailable active song for removal (pushed to Spotify by the caller's flush).

    A cleanup, not a review: no review events, so it doesn't use up the daily limit.
    """
    rows = db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id == rotation.id,
        RotationTrackDB.status == ACTIVE,
        RotationTrackDB.is_playable.is_(False),
    ).all()
    for row in rows:
        row.status = PENDING_REMOVAL
    db.commit()
    return len(rows)


def due_queue(db: orm.Session, rotation: RotationDB, tz_offset_minutes: int = 0, more: bool = False) -> QueueOut:
    """Today's batch of due songs, most overdue first, capped by the owner's daily review limit.

    Songs skipped today are held back until tomorrow. `more` serves another full batch
    after today's allowance is used up.
    """
    now = utcnow()
    limit = rotation.owner.review_limit
    day = _todays_activity(db, [rotation.id], logic.local_day_start(now, tz_offset_minutes))[rotation.id]
    active = _tracks(db, rotation, (ACTIVE,))
    eligible = _eligible_due(rotation, active, day, now)
    size = logic.todays_batch_size(limit, day.reviewed, len(eligible), more)
    return QueueOut(
        tracks=[track_out(t, rotation) for t in eligible[:size]],
        due_count=sum(1 for t in active if logic.is_due(t, rotation, now)),
        daily_limit=limit,
        reviewed_today=day.reviewed,
        remaining_after_batch=len(eligible) - size,
        limit_reached=limit is not None and not more and size < len(eligible),
    )


def all_tracks(db: orm.Session, rotation: RotationDB) -> list[TrackOut]:
    tracks = logic.sort_queue(_tracks(db, rotation, (ACTIVE,)), rotation)
    pending = _tracks(db, rotation, (PENDING_REMOVAL,))
    return [track_out(t, rotation) for t in tracks + pending]


def apply_review(db: orm.Session, rotation: RotationDB, track_id: str, action: str) -> TrackOut:
    """Record one swipe. DB only; removals reach Spotify on flush."""
    track = db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.track_id == track_id
    ).first()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found in this rotation")

    if action == UNDO:
        return _undo_last_review(db, rotation, track)
    if track.status != ACTIVE:
        raise HTTPException(status_code=409, detail="Track is not active in this rotation")

    event = ReviewEventDB(rotation_track_id=track.id, action=action, created_at=utcnow())
    if action in KEEP_ACTIONS:
        # Remember the previous keep state so this keep can be undone
        event.previous_last_kept_at = track.last_kept_at
        event.previous_keep_multiplier = track.keep_multiplier
        track.last_kept_at = utcnow()
        track.keep_multiplier = SUPER_KEEP_MULTIPLIER if action == SUPER_KEEP else 1
    elif action == REMOVE:
        track.status = PENDING_REMOVAL
    # SKIP changes nothing on the track: it stays due and comes back tomorrow

    db.add(event)
    db.commit()
    db.refresh(track)
    return track_out(track, rotation)


def _undo_last_review(db: orm.Session, rotation: RotationDB, track: RotationTrackDB) -> TrackOut:
    """Revert the track's most recent keep / skip / remove, as if it never happened.

    The event is deleted, so it also stops counting toward today's review limit and a
    skipped song is no longer held back until tomorrow. A removal can only be undone
    while it's still pending (before the flush reaches Spotify).
    """
    event = (
        db.query(ReviewEventDB)
        .filter(ReviewEventDB.rotation_track_id == track.id, ReviewEventDB.action != UNDO)
        .order_by(ReviewEventDB.created_at.desc(), ReviewEventDB.id.desc())
        .first()
    )
    if event is None:
        raise HTTPException(status_code=409, detail="Nothing to undo for this song")
    if event.action == REMOVE:
        if track.status != PENDING_REMOVAL:
            raise HTTPException(
                status_code=409,
                detail="That song was already removed from Spotify. Add it back from History or Restock.",
            )
        track.status = ACTIVE
    elif event.action in KEEP_ACTIONS:
        if track.status != ACTIVE:
            raise HTTPException(status_code=409, detail="Track is not active in this rotation")
        track.last_kept_at = event.previous_last_kept_at
        track.keep_multiplier = event.previous_keep_multiplier or 1
    db.delete(event)
    db.commit()
    db.refresh(track)
    return track_out(track, rotation)


def history(db: orm.Session, rotation: RotationDB, limit: int = 100, offset: int = 0) -> list[HistoryEventOut]:
    rows = (
        db.query(ReviewEventDB, RotationTrackDB)
        .join(RotationTrackDB, ReviewEventDB.rotation_track_id == RotationTrackDB.id)
        .filter(RotationTrackDB.rotation_id == rotation.id)
        .order_by(ReviewEventDB.created_at.desc(), ReviewEventDB.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        HistoryEventOut(action=event.action, created_at=event.created_at, track=track_out(track, rotation))
        for event, track in rows
    ]
