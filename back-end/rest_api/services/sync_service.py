"""Keep a rotation's rows in line with its Spotify playlist (Spotify is the source of truth).

flush_pending_removals: push swiped-away tracks to Spotify (batched).
sync_rotation:          flush, then re-read the playlist if its snapshot changed and diff.
"""
import logging
from datetime import datetime, timedelta

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


def _mark_removed(track: RotationTrackDB, removed_by: str) -> None:
    track.status = REMOVED
    track.removed_at = utcnow()
    track.removed_by = removed_by


async def flush_pending_removals(db: Session, rotation: RotationDB, user: UserDB) -> int:
    """Remove pending tracks from the Spotify playlist. Returns how many were removed.

    On a Spotify failure the tracks stay pending (the next flush or sync retries them)
    and the error propagates.
    """
    pending = (
        db.query(RotationTrackDB)
        .filter(RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.status == PENDING_REMOVAL)
        .all()
    )
    if not pending:
        return 0
    # Removing by URI drops every copy of the track (accepted; see DESIGN.md)
    await SpotifyService.remove_items_from_playlist(rotation.playlist_id, [t.uri for t in pending], user, db)
    for track in pending:
        _mark_removed(track, REMOVED_BY_USER)
    db.commit()
    return len(pending)


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
    """Flush pending removals, then re-read the playlist if it changed. Returns True if re-read."""
    await flush_pending_removals(db, rotation, user)
    if not force and recently_synced(rotation):
        return False

    meta = await SpotifyService.get_playlist(rotation.playlist_id, user, db, fields="snapshot_id,images")
    snapshot_id = meta.get("snapshot_id")
    if "images" in meta:
        rotation.image_url = playlist_image(meta)
    if not force and snapshot_id and snapshot_id == rotation.snapshot_id:
        rotation.last_synced_at = utcnow()
        db.commit()
        return False

    # A change landing between these two reads is harmless: the stored snapshot
    # then won't match next time, which triggers another full read
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
        after = await SpotifyService.get_playlist(rotation.playlist_id, user, db, fields="snapshot_id")
        if after.get("snapshot_id") != snapshot_id:
            logger.info("Playlist %s changed during the read; applying additions only", rotation.playlist_id)
            apply_playlist_snapshot(db, rotation, present, rotation.snapshot_id, partial=True)
            return True
    apply_playlist_snapshot(db, rotation, present, snapshot_id)
    return True
