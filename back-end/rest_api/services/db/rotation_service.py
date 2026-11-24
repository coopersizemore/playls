"""Rotation CRUD, the due queue, review decisions and history."""
import logging
from collections import defaultdict
from typing import Iterable

import sqlalchemy.orm as orm
from fastapi import HTTPException

from rest_api.clock import utcnow
from rest_api.database.models.review_event import (
    KEEP_ACTIONS,
    REMOVE,
    SKIP,
    SUPER_KEEP,
    SYSTEM_ACTIONS,
    UNDO,
    ReviewEventDB,
)
from rest_api.database.models.rotation import AUTO, RotationDB
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
from rest_api.services import auto_rotation_logic as auto
from rest_api.services import rotation_logic as logic
from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService as ss
from rest_api.services.sync_service import sync_claim, sync_rotation

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
        .filter(
            RotationTrackDB.rotation_id.in_(ids),
            ReviewEventDB.created_at >= since,
            ReviewEventDB.action.notin_(SYSTEM_ACTIONS),
        )
    )
    for rotation_id, track_row_id, action in rows:
        day = activity[rotation_id]
        day.reviewed += -1 if action == UNDO else 1
        if action == SKIP:
            day.skipped_track_ids.add(track_row_id)
    for day in activity.values():
        day.reviewed = max(0, day.reviewed)
    return activity


def due_dates(rotation: RotationDB, active: list[RotationTrackDB], now) -> dict[int, object]:
    """When each active track comes due, by row id.

    Manual rotations: the review due date. Auto rotations: when the song is projected to
    rotate out (the next group is "due" for an optional review).
    """
    if rotation.kind == AUTO:
        return auto.leaving_schedule(active, rotation, now)
    return {t.id: logic.due_at(t, rotation) for t in active}


def _due_now(rotation: RotationDB, active: list[RotationTrackDB], now) -> list[RotationTrackDB]:
    """Every active track currently due, in queue order (auto: leaving at the next rotation)."""
    if rotation.kind == AUTO:
        return auto.leaving_next(active, rotation, now)
    return logic.sort_queue([t for t in active if logic.is_due(t, rotation, now)], rotation)


def _sorted_by_due(rotation: RotationDB, active: list[RotationTrackDB], now) -> list[RotationTrackDB]:
    if rotation.kind == AUTO:
        schedule = auto.leaving_schedule(active, rotation, now)
        order = {t.id: i for i, t in enumerate(auto.rotate_out_order(active, rotation, now))}
        return sorted(active, key=lambda t: (schedule[t.id], order[t.id]))
    return logic.sort_queue(active, rotation)


def _eligible_due(rotation: RotationDB, tracks: list[RotationTrackDB], day: DailyActivity, now) -> list:
    """Due active tracks that weren't skipped today, most overdue first."""
    active = [t for t in tracks if t.status == ACTIVE]
    return [t for t in _due_now(rotation, active, now) if t.id not in day.skipped_track_ids]


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
    is_auto = rotation.kind == AUTO
    dates = list(due_dates(rotation, active, now).values())
    due_count = len(_due_now(rotation, active, now)) if is_auto else sum(1 for d in dates if d <= now)
    upcoming = [d for d in dates if d > now] if not is_auto else []
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
        kind=rotation.kind,
        target_size=rotation.target_size,
        rotate_percent=rotation.rotate_percent,
        last_rotated_at=rotation.last_rotated_at,
        next_rotation_at=auto.next_rotation_at(rotation) if is_auto else None,
        created_at=rotation.created_at,
        last_synced_at=rotation.last_synced_at,
        active_count=len(active),
        due_count=due_count,
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


_UNSET = object()


def track_out(track: RotationTrackDB, rotation: RotationDB, due_at=_UNSET) -> TrackOut:
    """`due_at` overrides the computed due date (auto rotations pass the leaving estimate)."""
    if due_at is _UNSET:
        due_at = logic.due_at(track, rotation) if rotation.kind != AUTO else None
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
        due_at=due_at if track.status == ACTIVE else None,
        protected=rotation.kind == AUTO and track.status == ACTIVE and auto.is_protected(track, rotation),
    )


def _tracks_out(tracks: list[RotationTrackDB], rotation: RotationDB, active: list[RotationTrackDB], now) -> list[TrackOut]:
    dates = due_dates(rotation, active, now)
    return [track_out(t, rotation, dates.get(t.id)) for t in tracks]


# ---------- sync wrappers ----------

async def try_sync(db: orm.Session, rotation: RotationDB, user: UserDB, force: bool = False) -> bool:
    """Sync (and, for auto rotations, maintain) under the rotation's sync claim, without
    failing the request if Spotify is unavailable. Returns sync_ok.

    If another request holds the claim past the wait, this reads what's stored and reports
    sync_ok=True: that request is syncing it right now.
    """
    async with sync_claim(db, rotation) as held:
        if not held:
            return True
        try:
            await sync_rotation(db, rotation, user, force=force)
        except Exception:
            # Spotify errors and timeouts
            db.rollback()
            logger.warning("Sync failed for rotation %s", rotation.id, exc_info=True)
            return False
        if rotation.kind == AUTO:
            await try_maintain(db, rotation, user)
        return True


async def try_maintain(db: orm.Session, rotation: RotationDB, user: UserDB) -> bool:
    """Auto rotations: rotate out if due and restock to the target (best effort)."""
    from rest_api.services.auto_restock_service import maintain  # that module imports this one

    async with sync_claim(db, rotation) as held:  # already held when called from try_sync
        if not held:
            return False
        try:
            await maintain(db, rotation, user)
            return True
        except Exception:
            db.rollback()
            logger.warning("Auto restock failed for rotation %s", rotation.id, exc_info=True)
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
    """Wrap an owned/collaborative playlist, or create a new private one. Returns (rotation, sync_ok).

    Auto rotations always start from a new playlist; the initial sync's restock fills it.
    """
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
        kind=data.kind,
        target_size=data.target_size if data.kind == AUTO else None,
        rotate_percent=data.rotate_percent if data.kind == AUTO else None,
        created_at=utcnow(),
    )
    db.add(rotation)
    db.commit()
    db.refresh(rotation)
    # Initial import (grace_period decides when songs already in the playlist come due)
    sync_ok = await try_sync(db, rotation, owner, force=True)
    return rotation, sync_ok


def update_rotation(db: orm.Session, rotation: RotationDB, data: RotationUpdate) -> RotationDB:
    changes = data.model_dump(exclude_unset=True)
    if rotation.kind != AUTO and any(changes.get(k) is not None for k in ("target_size", "rotate_percent")):
        raise HTTPException(status_code=400, detail="Only auto rotations have a target size")
    for key, value in changes.items():
        if key in ("name", "interval_hours", "grace_period", "target_size", "rotate_percent") and value is None:
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
    active = _sorted_by_due(rotation, _tracks(db, rotation, (ACTIVE,)), now)
    return QueueOut(
        tracks=_tracks_out(active, rotation, active, now),
        due_count=len(_due_now(rotation, active, now)),
        daily_limit=None,
        reviewed_today=day.reviewed,
        remaining_after_batch=0,
        limit_reached=False,
    )


def reset_due_dates(db: orm.Session, rotation: RotationDB) -> int:
    """Treat every active song as just reviewed: each comes due one interval from now.

    Not recorded as keeps (no review events), so it doesn't touch History or the daily limit.
    """
    if rotation.kind == AUTO:
        # Every song would be protected and the next rotation would swap nothing out
        raise HTTPException(status_code=400, detail="Auto rotations don't have due dates to reset")
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
    ).order_by(RotationTrackDB.title).all()
    return _tracks_out(rows, rotation, _tracks(db, rotation, (ACTIVE,)), utcnow())


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
        tracks=_tracks_out(eligible[:size], rotation, active, now),
        due_count=len(_due_now(rotation, active, now)),
        daily_limit=limit,
        reviewed_today=day.reviewed,
        remaining_after_batch=len(eligible) - size,
        limit_reached=limit is not None and not more and size < len(eligible),
    )


def all_tracks(db: orm.Session, rotation: RotationDB) -> list[TrackOut]:
    now = utcnow()
    tracks = _sorted_by_due(rotation, _tracks(db, rotation, (ACTIVE,)), now)
    pending = _tracks(db, rotation, (PENDING_REMOVAL,))
    return _tracks_out(tracks + pending, rotation, tracks, now)


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
    return _one_out(db, rotation, track)


def _undo_last_review(db: orm.Session, rotation: RotationDB, track: RotationTrackDB) -> TrackOut:
    """Revert the track's most recent keep / skip / remove, as if it never happened.

    The event is deleted, so it also stops counting toward today's review limit and a
    skipped song is no longer held back until tomorrow. A removal can only be undone
    while it's still pending (before the flush reaches Spotify).
    """
    event = (
        db.query(ReviewEventDB)
        .filter(
            ReviewEventDB.rotation_track_id == track.id,
            ReviewEventDB.action.notin_((UNDO,) + SYSTEM_ACTIONS),
        )
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
    return _one_out(db, rotation, track)


def _one_out(db: orm.Session, rotation: RotationDB, track: RotationTrackDB) -> TrackOut:
    if rotation.kind != AUTO:
        return track_out(track, rotation)
    return _tracks_out([track], rotation, _tracks(db, rotation, (ACTIVE,)), utcnow())[0]


# History tabs -> the actions they show (None = every event, including legacy undo rows)
HISTORY_FILTERS: dict[str, tuple[str, ...] | None] = {
    "all": None,
    "removed": (REMOVE,),
    "kept": tuple(KEEP_ACTIONS),
    "skipped": (SKIP,),
    "rotated": tuple(SYSTEM_ACTIONS),
    "reviews": (*KEEP_ACTIONS, SKIP, REMOVE),  # the user's own decisions (e.g. "last reviewed")
}


def history(
    db: orm.Session, rotation: RotationDB, limit: int = 100, offset: int = 0, filter: str = "all"
) -> tuple[list[HistoryEventOut], int]:
    """One page of events (newest first) and how many match in total. Filtering happens here,
    not in the client, so older events of one kind aren't hidden behind newer events of another."""
    query = (
        db.query(ReviewEventDB, RotationTrackDB)
        .join(RotationTrackDB, ReviewEventDB.rotation_track_id == RotationTrackDB.id)
        .filter(RotationTrackDB.rotation_id == rotation.id)
    )
    actions = HISTORY_FILTERS[filter]
    if actions is not None:
        query = query.filter(ReviewEventDB.action.in_(actions))
    total = query.count()
    rows = (
        query
        .order_by(ReviewEventDB.created_at.desc(), ReviewEventDB.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    dates = due_dates(rotation, _tracks(db, rotation, (ACTIVE,)), utcnow())
    return [
        HistoryEventOut(
            action=event.action, created_at=event.created_at, track=track_out(track, rotation, dates.get(track.id))
        )
        for event, track in rows
    ], total
