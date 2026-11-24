"""Keep a rotation's rows in line with its Spotify playlist (Spotify is the source of truth).

sync_claim:             a short per-rotation lease; held around every sync and PlayLS playlist write.
write_adopting_snapshot: run a playlist write and, if the rows matched Spotify just before it,
                        store the write's snapshot (so our own changes don't force a full re-read).
flush_pending_removals: push swiped-away tracks to Spotify (batched).
sync_rotation:          check the snapshot, flush, then re-read the playlist if it changed and diff.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from rest_api import request_context
from rest_api.clock import utcnow
from rest_api.database.models.rotation import MANUAL, RotationDB
from rest_api.database.models.rotation_track import (
    ACTIVE,
    PENDING_REMOVAL,
    REMOVED,
    REMOVED_BY_EXTERNAL,
    REMOVED_BY_USER,
    RotationTrackDB,
)
from rest_api.database.models.user import UserDB
from rest_api.services.rotation_logic import PlaylistTrack, parse_playlist_items, playlist_image
from rest_api.services.spotify.spotify_service import SpotifyService

logger = logging.getLogger(__name__)

# A manual rotation synced this recently (and since the app was last shown) isn't
# checked against Spotify again; see recently_synced.
FRESH_SYNC_SECONDS = 120

# The sync claim: how long a lease lasts (covers a function that dies mid-sync), how long
# a request waits for someone else's, and how often it checks.
SYNC_CLAIM_SECONDS = 60
SYNC_CLAIM_WAIT_SECONDS = 10.0
SYNC_CLAIM_POLL_SECONDS = 0.5

# Rotation ids whose claim the current task holds (so nested claims don't wait on themselves)
_held_claims: ContextVar[frozenset] = ContextVar("playls_held_sync_claims", default=frozenset())


# ---------- the sync claim ----------

def _try_claim(db: Session, rotation_id: int) -> Optional[datetime]:
    now = utcnow()
    until = now + timedelta(seconds=SYNC_CLAIM_SECONDS)
    claimed = db.query(RotationDB).filter(
        RotationDB.id == rotation_id,
        or_(RotationDB.sync_claimed_until.is_(None), RotationDB.sync_claimed_until < now),
    ).update({RotationDB.sync_claimed_until: until}, synchronize_session=False)
    db.commit()
    return until if claimed else None


def _release(db: Session, rotation_id: int, until: datetime) -> None:
    # Only clear our own lease: if it expired and someone else took over, leave theirs
    for attempt in range(2):
        try:
            db.query(RotationDB).filter(
                RotationDB.id == rotation_id, RotationDB.sync_claimed_until == until
            ).update({RotationDB.sync_claimed_until: None}, synchronize_session=False)
            db.commit()
            return
        except Exception:
            db.rollback()  # e.g. the session failed mid-sync; retry on a clean transaction
            if attempt:
                logger.warning("Couldn't release the sync claim on rotation %s; it expires on its own", rotation_id,
                               exc_info=True)


@asynccontextmanager
async def sync_claim(db: Session, rotation: RotationDB, wait_seconds: Optional[float] = None):
    """Hold the rotation's sync lease for the block. Yields True if held, False if another
    request kept it for longer than `wait_seconds` (default SYNC_CLAIM_WAIT_SECONDS).

    Every sync and every PlayLS write to the playlist runs under it, so a sync can't read the
    playlist while another request changes it, and two requests can't restock it at once.
    Re-entrant within one task.
    """
    rotation_id = rotation.id
    if rotation_id in _held_claims.get():
        yield True
        return
    wait = SYNC_CLAIM_WAIT_SECONDS if wait_seconds is None else wait_seconds
    deadline = time.monotonic() + wait
    until = _try_claim(db, rotation_id)
    while until is None and time.monotonic() < deadline:
        await asyncio.sleep(SYNC_CLAIM_POLL_SECONDS)
        until = _try_claim(db, rotation_id)
    if until is None:
        logger.info("Rotation %s is being synced by another request; not waiting longer", rotation_id)
        yield False
        return
    token = _held_claims.set(_held_claims.get() | {rotation_id})
    try:
        yield True
    finally:
        _held_claims.reset(token)
        _release(db, rotation_id, until)


# ---------- writes ----------

async def _current_snapshot(db: Session, rotation: RotationDB, user: UserDB) -> Optional[str]:
    meta = await SpotifyService.get_playlist(rotation.playlist_id, user, db, fields="snapshot_id")
    return meta.get("snapshot_id")


async def write_adopting_snapshot(
    db: Session, rotation: RotationDB, user: UserDB,
    write: Callable[[], Awaitable[Optional[str]]], in_sync: Optional[bool] = None,
) -> Optional[str]:
    """Run a playlist write that returns Spotify's new snapshot_id.

    If the stored snapshot matched Spotify right before the write, the only change since is
    ours, so the new snapshot is stored and the next sync short-circuits instead of re-reading
    the playlist. `in_sync` can be passed when the caller just checked; otherwise this checks
    (one cheap call). The caller commits. A write snapshot that doesn't match what reads report
    would only cost a full re-read next time, never a missed change.
    """
    if in_sync is None:
        in_sync = bool(rotation.snapshot_id) and await _current_snapshot(db, rotation, user) == rotation.snapshot_id
    new_snapshot = await write()
    if in_sync and new_snapshot:
        rotation.snapshot_id = new_snapshot
    return new_snapshot


def _mark_removed(track: RotationTrackDB, removed_by: str) -> None:
    track.status = REMOVED
    track.removed_at = utcnow()
    track.removed_by = removed_by


async def flush_pending_removals(
    db: Session, rotation: RotationDB, user: UserDB, in_sync: Optional[bool] = None
) -> int:
    """Remove pending tracks from the Spotify playlist. Returns how many were removed.

    Call under sync_claim. On a Spotify failure the tracks stay pending (the next flush or
    sync retries them) and the error propagates.
    """
    pending = (
        db.query(RotationTrackDB)
        .filter(RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.status == PENDING_REMOVAL)
        .all()
    )
    if not pending:
        return 0
    # Removing by URI drops every copy of the track (accepted; see DESIGN.md)
    uris = [t.uri for t in pending]
    await write_adopting_snapshot(
        db, rotation, user,
        lambda: SpotifyService.remove_items_from_playlist(rotation.playlist_id, uris, user, db),
        in_sync=in_sync,
    )
    for track in pending:
        _mark_removed(track, REMOVED_BY_USER)
    db.commit()
    return len(pending)


# ---------- sync ----------

def recently_synced(rotation: RotationDB, now: datetime | None = None) -> bool:
    """Manual rotations only: skip the Spotify check if the last sync was under
    FRESH_SYNC_SECONDS ago and happened after the client was last shown.

    "Last shown" comes from the frontend (request_context.visible_since): coming back to
    the app, e.g. from editing the playlist in Spotify, always re-checks. Requests that
    don't send it (cron, tests, other clients) never skip. Auto rotations always sync,
    because their maintenance must run against fresh rows.
    """
    ctx = request_context.current()
    if ctx is None or ctx.visible_since is None:
        return False
    if rotation.kind != MANUAL or rotation.last_synced_at is None:
        return False
    now = now or utcnow()
    return (
        rotation.last_synced_at >= ctx.visible_since
        and now - rotation.last_synced_at < timedelta(seconds=FRESH_SYNC_SECONDS)
    )


def apply_playlist_snapshot(
    db: Session, rotation: RotationDB, present: dict[str, PlaylistTrack], snapshot_id: str | None,
    partial: bool = False,
) -> None:
    """Diff the playlist's current tracks against the rotation's rows (no network).

    partial: the playlist changed while it was being read, so `present` may be missing
    songs that are still there. Only add new songs and refresh metadata; don't mark
    anything removed or bring removed rows back, and keep the old snapshot (and sync
    time) so the next sync reads it again.
    """
    now = utcnow()
    rows = {t.track_id: t for t in db.query(RotationTrackDB).filter(RotationTrackDB.rotation_id == rotation.id)}

    for track_id, track in present.items():
        added_at = track.added_at  # None if Spotify didn't report it
        row = rows.get(track_id)
        if row is None:
            db.add(RotationTrackDB(
                rotation_id=rotation.id,
                track_id=track_id,
                uri=track.uri,
                title=track.title,
                artists=track.artists,
                album=track.album,
                image_url=track.image_url,
                duration_ms=track.duration_ms,
                is_playable=track.is_playable,
                added_at=added_at,
                status=ACTIVE,
            ))
            continue

        # Refresh display metadata from Spotify
        row.uri, row.title, row.artists = track.uri, track.title, track.artists
        row.album, row.image_url, row.duration_ms = track.album, track.image_url, track.duration_ms
        row.is_playable = track.is_playable

        if partial:
            continue
        if row.status == REMOVED:
            # Re-added on Spotify after a removal: start over from the new added_at
            row.status = ACTIVE
            row.added_at = added_at
            row.last_kept_at = None
            row.keep_multiplier = 1
            row.removed_at = None
            row.removed_by = None
        elif row.status == ACTIVE:
            row.added_at = added_at
        # PENDING_REMOVAL: still on Spotify only because the flush hasn't happened; leave it

    if partial:
        db.commit()
        return

    for track_id, row in rows.items():
        if track_id in present:
            continue
        if row.status == ACTIVE:
            _mark_removed(row, REMOVED_BY_EXTERNAL)
        elif row.status == PENDING_REMOVAL:
            # Gone already (e.g. removed in Spotify too); the user's decision stands
            _mark_removed(row, REMOVED_BY_USER)

    rotation.snapshot_id = snapshot_id
    rotation.last_synced_at = now
    db.commit()


async def sync_rotation(db: Session, rotation: RotationDB, user: UserDB, force: bool = False) -> bool:
    """Check the playlist's snapshot, flush pending removals, then re-read the playlist if it
    changed. Returns True if re-read. Call under sync_claim (try_sync does)."""
    if not force and recently_synced(rotation):
        await flush_pending_removals(db, rotation, user)
        return False

    # The snapshot is checked before the flush, so a flush onto an unchanged playlist can
    # store its own snapshot (write_adopting_snapshot) and skip the re-read
    meta = await SpotifyService.get_playlist(rotation.playlist_id, user, db, fields="snapshot_id,images")
    snapshot_id = meta.get("snapshot_id")
    if "images" in meta:
        rotation.image_url = playlist_image(meta)
    in_sync = bool(snapshot_id) and snapshot_id == rotation.snapshot_id
    flushed = await flush_pending_removals(db, rotation, user, in_sync=in_sync)
    if not force and in_sync:
        rotation.last_synced_at = utcnow()
        db.commit()
        return False
    if flushed:
        snapshot_id = await _current_snapshot(db, rotation, user)

    entries = await SpotifyService.get_all_playlist_items(rotation.playlist_id, user, db)
    present = parse_playlist_items(entries)
    if entries and not present:
        # Either the playlist is only local files/episodes, or the response shape changed.
        # Don't diff: that would mark every track as removed externally.
        logger.warning(
            "Playlist %s returned %d items but none parsed as tracks; skipping diff",
            rotation.playlist_id, len(entries),
        )
        return False

    # Pages are read by offset from the live playlist: if it changed mid-read, a removal can
    # shift a song past the pages we'd already read. Re-check before trusting absences.
    if snapshot_id:
        if await _current_snapshot(db, rotation, user) != snapshot_id:
            logger.info("Playlist %s changed during the read; applying additions only", rotation.playlist_id)
            apply_playlist_snapshot(db, rotation, present, rotation.snapshot_id, partial=True)
            return True
    apply_playlist_snapshot(db, rotation, present, snapshot_id)
    return True
