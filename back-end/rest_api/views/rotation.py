from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..clock import utcnow
from ..database.config import get_db
from ..database.models.analytics_event import REVIEW
from ..database.models.user import UserDB
from ..models.rotation import (
    FlushOut,
    HistoryEventOut,
    ListeningDigestOut,
    QueueOut,
    RemoveUnplayableOut,
    ReviewIn,
    RotationCreate,
    RotationOut,
    RotationUpdate,
    TrackOut,
    UnplayableOut,
)
from ..services import listening_reports, telemetry
from ..services.auth_service import AuthService
from ..services.db import rotation_service as rs
from ..services.sync_service import flush_pending_removals, sync_claim, sync_rotation

# Every rotation route requires a logged-in user
router = APIRouter(
    prefix="/rotation",
    tags=["rotation"],
    dependencies=[Depends(AuthService.get_current_user_from_token)],
)

current_user_dep = Depends(AuthService.get_current_user_from_token)


@router.post("/", response_model=RotationOut, status_code=201)
async def create_rotation(data: RotationCreate, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    rotation, sync_ok = await rs.create_rotation(db, data, user)
    return rs.summarize_one(db, rotation, sync_ok)


@router.get("/{rotation_id}", response_model=RotationOut)
async def get_rotation(
    rotation_id: int,
    sync: bool = Query(True, description="Sync with Spotify first"),
    tz_offset: int = Query(0, ge=-840, le=840, description="JS Date.getTimezoneOffset() of the client"),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    sync_ok = await rs.try_sync(db, rotation, user) if sync else True
    return rs.summarize_one(db, rotation, sync_ok, tz_offset)


@router.put("/{rotation_id}", response_model=RotationOut)
async def update_rotation(
    rotation_id: int, data: RotationUpdate, db: Session = Depends(get_db), user: UserDB = current_user_dep
):
    rotation = await rs.update_rotation(db, rs.get_owned_or_404(db, rotation_id, user), data, user)
    return rs.summarize_one(db, rotation)


@router.delete("/{rotation_id}")
async def delete_rotation(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    rs.delete_rotation(db, rs.get_owned_or_404(db, rotation_id, user))
    return {"message": "Rotation deleted"}


@router.get("/{rotation_id}/queue", response_model=QueueOut)
async def get_queue(
    rotation_id: int,
    tz_offset: int = Query(0, ge=-840, le=840, description="JS Date.getTimezoneOffset() of the client"),
    more: bool = Query(False, description="Serve another batch after today's limit is used up"),
    all: bool = Query(False, description="Every song in the rotation, soonest due first, no limit"),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    """Today's batch of due songs (most overdue first, capped by the daily review limit).
    Syncs with Spotify first (best effort)."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    await rs.try_sync(db, rotation, user)
    if all:
        return rs.all_songs_queue(db, rotation, tz_offset)
    return rs.due_queue(db, rotation, tz_offset, more)


@router.post("/{rotation_id}/reset-due", response_model=RotationOut)
async def reset_due_dates(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Mark every song as not due: each comes due one interval from now."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    rs.reset_due_dates(db, rotation)
    return rs.summarize_one(db, rotation)


@router.get("/{rotation_id}/unplayable", response_model=UnplayableOut)
async def get_unplayable(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Songs still in the playlist but unavailable on Spotify. Re-reads the whole playlist
    first, since availability can change without the playlist changing."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    async with sync_claim(db, rotation) as held:
        if held:
            await sync_rotation(db, rotation, user, force=True)
        # else another request is syncing it right now; list what's stored
    return UnplayableOut(tracks=rs.unplayable_tracks(db, rotation))


@router.post("/{rotation_id}/remove-unplayable", response_model=RemoveUnplayableOut)
async def remove_unplayable(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Remove every unavailable song from the rotation and the Spotify playlist now."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    removed = rs.queue_unplayable_removals(db, rotation)
    flushed = True
    async with sync_claim(db, rotation) as held:
        if not held:
            flushed = False  # stays pending; the sync holding the claim, or the next one, flushes it
        else:
            try:
                await flush_pending_removals(db, rotation, user)
            except Exception:
                db.rollback()
                flushed = False  # stays pending; the next sync retries
    return RemoveUnplayableOut(removed=removed, flushed=flushed)


@router.get("/{rotation_id}/tracks", response_model=list[TrackOut])
async def get_tracks(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Every track currently in rotation (active, then pending removal), with due dates."""
    return rs.all_tracks(db, rs.get_owned_or_404(db, rotation_id, user))


@router.post("/{rotation_id}/review", response_model=TrackOut)
async def review_track(
    rotation_id: int, data: ReviewIn, db: Session = Depends(get_db), user: UserDB = current_user_dep
):
    """Record one swipe (keep / skip / remove / undo). Removals are applied on flush."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    song = None
    if telemetry.enabled(user) and data.telemetry and data.action != "undo":
        # The song's state before the decision changes it (for remove-rate-by-age stats)
        song = telemetry.song_context(rs.find_track(db, rotation, data.track_id), rotation, utcnow())
    result = rs.apply_review(db, rotation, data.track_id, data.action)
    telemetry.record_decision(db, user, rotation, REVIEW, data.action, data.telemetry, song=song)
    return result


@router.post("/{rotation_id}/flush", response_model=FlushOut)
async def flush_removals(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Apply pending removals to the Spotify playlist (called when leaving Review)."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    removed = 0
    async with sync_claim(db, rotation) as held:
        # Not held: another request is syncing it, and the removals stay pending for it (or the next sync)
        if held:
            removed = await flush_pending_removals(db, rotation, user)
            if removed and rotation.kind == "auto":
                await rs.try_maintain(db, rotation, user)  # refill the slots that were just freed
    return FlushOut(removed=removed, pending=rs.summarize_one(db, rotation).pending_removal_count)


@router.get("/{rotation_id}/history", response_model=list[HistoryEventOut])
async def get_history(
    rotation_id: int,
    response: Response,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    filter: Literal["all", "removed", "kept", "skipped", "rotated", "reviews"] = Query(
        "all", description="Which events: a History tab, or 'reviews' (keeps, skips and removals only)"
    ),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    """Newest first. X-Total-Count gives how many events match the filter (for paging)."""
    events, total = rs.history(db, rs.get_owned_or_404(db, rotation_id, user), limit, offset, filter)
    response.headers["X-Total-Count"] = str(total)
    return events


@router.get("/{rotation_id}/listening", response_model=ListeningDigestOut)
async def get_listening(
    rotation_id: int,
    days: int = Query(30, ge=1, le=365),
    tz_offset: int = Query(0, ge=-840, le=840, description="JS Date.getTimezoneOffset() of the client"),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    """Daily listening for this rotation (the user's local days, newest first), from the
    stored listening history: plays from its playlist, and plays of its songs elsewhere."""
    return listening_reports.digest(db, rs.get_owned_or_404(db, rotation_id, user), days, tz_offset)
