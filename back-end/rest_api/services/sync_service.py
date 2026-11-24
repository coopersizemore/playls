"""Keep a rotation's rows in line with its Spotify playlist (Spotify is the source of truth).

sync_claim:             a short per-rotation lease; held around every sync and PlayLS playlist write.
write_adopting_snapshot: run a playlist write and, if the rows matched Spotify just before it,
                        store the write's snapshot (so our own changes don't force a full re-read).
flush_pending_removals: push swiped-away tracks to Spotify (batched).
sync_rotation:          check the snapshot, flush, then re-read the playlist if it changed and diff.
"""
import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from rest_api import request_context
from rest_api.clock import utcnow
from rest_api.database.models.rotation import MANUAL, RotationDB, is_liked
from rest_api.database.models.rotation_track import (
    ACTIVE,
    PENDING_REMOVAL,
    REMOVED,
    REMOVED_BY_EXTERNAL,
    REMOVED_BY_USER,
    RotationTrackDB,
)
from rest_api.database.models.user import UserDB
from rest_api.services import health
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

def _try_claim(db: Session, rotation_id: int) -> datetime | None:
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
async def sync_claim(db: Session, rotation: RotationDB, wait_seconds: float | None = None):
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
    started = time.monotonic()
    deadline = started + wait
    until = _try_claim(db, rotation_id)
    while until is None and time.monotonic() < deadline:
        await asyncio.sleep(SYNC_CLAIM_POLL_SECONDS)
        until = _try_claim(db, rotation_id)
    waited_ms = round((time.monotonic() - started) * 1000)
    if waited_ms >= SYNC_CLAIM_POLL_SECONDS * 1000:
        health.count("claim.waited")
        health.count("claim.wait_ms", waited_ms)
    if until is None:
        logger.info("Rotation %s is being synced by another request; not waiting longer", rotation_id)
        health.count("claim.timeout")
        yield False
        return
    token = _held_claims.set(_held_claims.get() | {rotation_id})
    try:
        yield True
    finally:
        _held_claims.reset(token)
        _release(db, rotation_id, until)


@asynccontextmanager
async def claim_or_409(db: Session, rotation: RotationDB):
    """sync_claim for a user action that can't just fall back to stored data: 409 if it's busy."""
    async with sync_claim(db, rotation) as held:
        if not held:
            raise HTTPException(status_code=409, detail="This playlist is being updated. Try again in a moment.")
        yield


# ---------- writes ----------

async def _current_snapshot(db: Session, rotation: RotationDB, user: UserDB) -> str | None:
    meta = await SpotifyService.get_playlist(rotation.playlist_id, user, db, fields="snapshot_id")
    return meta.get("snapshot_id")


async def write_adopting_snapshot(
    db: Session, rotation: RotationDB, user: UserDB,
    write: Callable[[], Awaitable[str | None]], in_sync: bool | None = None,
) -> str | None:
    """Run a playlist write that returns Spotify's new snapshot_id.

    If the stored snapshot matched Spotify right before the write, the only change since is
    ours, so the new snapshot is stored and the next sync short-circuits instead of re-reading
    the playlist. `in_sync` can be passed when the caller just checked; otherwise this checks
    (one cheap call). The caller commits. A write snapshot that doesn't match what reads report
    would only cost a full re-read next time, never a missed change.

    Liked Songs: library writes return no snapshot, so there's nothing to adopt. The stored
    fingerprint is cleared instead, which makes the next sync read the whole library.
    """
    if is_liked(rotation):
        await write()
        rotation.snapshot_id = None
        return None
    if in_sync is None:
        in_sync = bool(rotation.snapshot_id) and await _current_snapshot(db, rotation, user) == rotation.snapshot_id
    new_snapshot = await write()
    if in_sync and new_snapshot:
        rotation.snapshot_id = new_snapshot
    return new_snapshot


def source_add(db: Session, rotation: RotationDB, user: UserDB, uris: list[str]) -> Awaitable[str | None]:
    """The Spotify call that adds songs to a rotation: a playlist add, or a like for Liked
    Songs. Pass it to write_adopting_snapshot (as a lambda), under sync_claim."""
    if is_liked(rotation):
        return SpotifyService.save_to_library(uris, user, db)
    return SpotifyService.add_items_to_playlist(rotation.playlist_id, uris, user, db)


def source_remove(db: Session, rotation: RotationDB, user: UserDB, uris: list[str]) -> Awaitable[str | None]:
    """The Spotify call that removes songs: a playlist removal, or an unlike for Liked Songs."""
    if is_liked(rotation):
        return SpotifyService.remove_from_library(uris, user, db)
    return SpotifyService.remove_items_from_playlist(rotation.playlist_id, uris, user, db)


def _mark_removed(track: RotationTrackDB, removed_by: str) -> None:
    track.status = REMOVED
    track.removed_at = utcnow()
    track.removed_by = removed_by


async def flush_pending_removals(
    db: Session, rotation: RotationDB, user: UserDB, in_sync: bool | None = None
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
        db, rotation, user, lambda: source_remove(db, rotation, user, uris), in_sync=in_sync,
    )
    for track in pending:
        _mark_removed(track, REMOVED_BY_USER)
    db.commit()
    health.count("sync.flushed_songs", len(pending))
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
    health.count("sync.attempt")
    if is_liked(rotation):
        return await sync_liked(db, rotation, user, force=force)
    if not force and recently_synced(rotation):
        health.count("sync.fresh_skip")
        await flush_pending_removals(db, rotation, user)
        return False

    # The snapshot is checked before the flush, so a flush onto an unchanged playlist can
    # store its own snapshot (write_adopting_snapshot) and skip the re-read
    meta = await SpotifyService.get_playlist(rotation.playlist_id, user, db, fields="snapshot_id,name,images")
    snapshot_id = meta.get("snapshot_id")
    if "images" in meta:
        rotation.image_url = playlist_image(meta)
    # The playlist's name in Spotify wins (renames in PlayLS are pushed to Spotify first)
    name = meta.get("name")
    if isinstance(name, str) and name.strip() and name[:100] != rotation.name:
        rotation.name = name[:100]
    in_sync = bool(snapshot_id) and snapshot_id == rotation.snapshot_id
    flushed = await flush_pending_removals(db, rotation, user, in_sync=in_sync)
    if not force and in_sync:
        health.count("sync.unchanged")
        rotation.last_synced_at = utcnow()
        db.commit()
        return False
    if flushed:
        snapshot_id = await _current_snapshot(db, rotation, user)

    health.count("sync.full_read")
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
    if snapshot_id and await _current_snapshot(db, rotation, user) != snapshot_id:
        logger.info("Playlist %s changed during the read; applying additions only", rotation.playlist_id)
        health.count("sync.partial_read")
        apply_playlist_snapshot(db, rotation, present, rotation.snapshot_id, partial=True)
        return True
    apply_playlist_snapshot(db, rotation, present, snapshot_id)
    return True


# ---------- Liked Songs ----------
#
# The library has no snapshot_id. Liked Songs is ordered newest-liked first, so every like
# lands on page 1 and every unlike lowers the total: (total, page-1 ids) changes on every
# change to its contents. That fingerprint stands in for the snapshot. The UTC date is part
# of it, so the first sync of each day reads the whole library anyway (catching anything
# the shortcut could miss, and refreshing is_playable).

# A full diff that would mark more than this share of active songs (and at least
# LIKED_MASS_REMOVAL_MIN of them) removed in Spotify is distrusted and applied as
# additions only. A false alarm costs nothing (the rows stay active, and unliking a song
# that's already unliked is a no-op); a wrong diff would wipe their kept state.
LIKED_MASS_REMOVAL_SHARE = 0.25
LIKED_MASS_REMOVAL_MIN = 20


def library_fingerprint(page: dict, now: datetime | None = None) -> str | None:
    """Stand-in snapshot for Liked Songs from its first page (None if it has no total)."""
    total = page.get("total")
    if not isinstance(total, int):
        return None
    ids = []
    for entry in page.get("items") or []:
        item = (entry or {}).get("track") or (entry or {}).get("item") or {}
        original = item.get("linked_from") or {}
        ids.append(original.get("id") or item.get("id") or "")
    digest = hashlib.sha1(",".join(ids).encode()).hexdigest()[:16]
    day = (now or utcnow()).strftime("%Y%m%d")
    return f"liked:{day}:{total}:{digest}"


def _would_remove_too_many(db: Session, rotation: RotationDB, present: dict[str, PlaylistTrack]) -> bool:
    active = [
        t.track_id for t in db.query(RotationTrackDB.track_id).filter(
            RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.status == ACTIVE
        )
    ]
    gone = sum(1 for track_id in active if track_id not in present)
    return gone >= LIKED_MASS_REMOVAL_MIN and gone > LIKED_MASS_REMOVAL_SHARE * len(active)


async def sync_liked(db: Session, rotation: RotationDB, user: UserDB, force: bool = False) -> bool:
    """sync_rotation for a Liked Songs rotation. Returns True if the library was re-read.

    Deliberately conservative (it reads more than a playlist sync does):
    - the fingerprint is checked before flushing; a flush (unlikes) clears it, so the
      library is always fully re-read after PlayLS changed it;
    - a full read is trusted only if it returned `total` items, the fingerprint is the same
      afterwards, and it wouldn't mark a large share of the songs removed. Otherwise only
      additions are applied and the old fingerprint is kept, so the next sync reads again.
    """
    if not force and recently_synced(rotation):
        health.count("sync.fresh_skip")
        await flush_pending_removals(db, rotation, user)
        return False

    first = await SpotifyService.get_saved_tracks_page(user, db, offset=0)
    fingerprint = library_fingerprint(first)
    in_sync = fingerprint is not None and fingerprint == rotation.snapshot_id
    flushed = await flush_pending_removals(db, rotation, user)
    if not force and in_sync and not flushed:
        health.count("sync.unchanged")
        rotation.last_synced_at = utcnow()
        db.commit()
        return False
    if flushed:
        # Our own unlikes changed the library; start the read from a fresh first page
        first = await SpotifyService.get_saved_tracks_page(user, db, offset=0)
        fingerprint = library_fingerprint(first)

    health.count("sync.full_read")
    entries, total = await SpotifyService.get_all_saved_tracks(user, db, first=first)
    present = parse_playlist_items(entries)
    if entries and not present:
        logger.warning("Liked Songs returned %d items but none parsed as tracks; skipping diff", len(entries))
        return False

    reason = None
    if total is None or len(entries) != total:
        reason = "count"
    elif library_fingerprint(await SpotifyService.get_saved_tracks_page(user, db, offset=0)) != fingerprint:
        reason = "changed"
    elif _would_remove_too_many(db, rotation, present):
        reason = "mass_removal"
        logger.warning("Liked Songs sync for rotation %s would remove too many songs; applying additions only",
                       rotation.id)
    if reason:
        logger.info("Liked Songs read for rotation %s not trusted (%s); applying additions only", rotation.id, reason)
        health.count(f"sync.liked_partial_{reason}")
        apply_playlist_snapshot(db, rotation, present, rotation.snapshot_id, partial=True)
        return True
    apply_playlist_snapshot(db, rotation, present, fingerprint)
    return True
