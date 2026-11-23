from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database.config import get_db
from ..database.models.user import UserDB
from ..models.rotation import (
    FlushOut,
    HistoryEventOut,
    QueueOut,
    RemoveUnplayableOut,
    UnplayableOut,
    ReviewIn,
    RotationCreate,
    RotationOut,
    RotationUpdate,
    TrackOut,
)
from ..services.auth_service import AuthService
from ..services.db import rotation_service as rs
from ..services.sync_service import flush_pending_removals, sync_rotation

# Every rotation route requires a logged-in user
router = APIRouter(
    prefix="/rotation",
    tags=["rotation"],
    dependencies=[Depends(AuthService.get_current_user_from_token)],
)

current_user_dep = Depends(AuthService.get_current_user_from_token)


def _get_owned_or_404(db: Session, rotation_id: int, user: UserDB):
    # 404 (not 403) for other users' rotations so ids don't leak
    rotation = rs.get_owned_rotation(db, rotation_id, user.id)
    if not rotation:
        raise HTTPException(status_code=404, detail="Rotation not found")
    return rotation


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
    rotation = _get_owned_or_404(db, rotation_id, user)
    sync_ok = await rs.try_sync(db, rotation, user) if sync else True
    return rs.summarize_one(db, rotation, sync_ok, tz_offset)


@router.put("/{rotation_id}", response_model=RotationOut)
async def update_rotation(
    rotation_id: int, data: RotationUpdate, db: Session = Depends(get_db), user: UserDB = current_user_dep
):
    rotation = rs.update_rotation(db, _get_owned_or_404(db, rotation_id, user), data)
    return rs.summarize_one(db, rotation)


@router.delete("/{rotation_id}")
async def delete_rotation(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    rs.delete_rotation(db, _get_owned_or_404(db, rotation_id, user))
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
    rotation = _get_owned_or_404(db, rotation_id, user)
    await rs.try_sync(db, rotation, user)
    if all:
        return rs.all_songs_queue(db, rotation, tz_offset)
    return rs.due_queue(db, rotation, tz_offset, more)


@router.post("/{rotation_id}/reset-due", response_model=RotationOut)
async def reset_due_dates(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Mark every song as not due: each comes due one interval from now."""
    rotation = _get_owned_or_404(db, rotation_id, user)
    rs.reset_due_dates(db, rotation)
    return rs.summarize_one(db, rotation)


@router.get("/{rotation_id}/unplayable", response_model=UnplayableOut)
async def get_unplayable(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Songs still in the playlist but unavailable on Spotify. Re-reads the whole playlist
    first, since availability can change without the playlist changing."""
    rotation = _get_owned_or_404(db, rotation_id, user)
    await sync_rotation(db, rotation, user, force=True)
    return UnplayableOut(tracks=rs.unplayable_tracks(db, rotation))


@router.post("/{rotation_id}/remove-unplayable", response_model=RemoveUnplayableOut)
async def remove_unplayable(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Remove every unavailable song from the rotation and the Spotify playlist now."""
    rotation = _get_owned_or_404(db, rotation_id, user)
    removed = rs.queue_unplayable_removals(db, rotation)
    flushed = True
    try:
        await flush_pending_removals(db, rotation, user)
    except Exception:
        db.rollback()
        flushed = False  # stays pending; the next sync retries
    return RemoveUnplayableOut(removed=removed, flushed=flushed)


@router.get("/{rotation_id}/tracks", response_model=list[TrackOut])
async def get_tracks(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Every track currently in rotation (active, then pending removal), with due dates."""
    return rs.all_tracks(db, _get_owned_or_404(db, rotation_id, user))


@router.post("/{rotation_id}/review", response_model=TrackOut)
async def review_track(
    rotation_id: int, data: ReviewIn, db: Session = Depends(get_db), user: UserDB = current_user_dep
):
    """Record one swipe (keep / skip / remove / undo). Removals are applied on flush."""
    return rs.apply_review(db, _get_owned_or_404(db, rotation_id, user), data.track_id, data.action)


@router.post("/{rotation_id}/flush", response_model=FlushOut)
async def flush_removals(rotation_id: int, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Apply pending removals to the Spotify playlist (called when leaving Review)."""
    rotation = _get_owned_or_404(db, rotation_id, user)
    removed = await flush_pending_removals(db, rotation, user)
    if removed and rotation.kind == "auto":
        await rs.try_maintain(db, rotation, user)  # refill the slots that were just freed
    return FlushOut(removed=removed, pending=rs.summarize_one(db, rotation).pending_removal_count)


@router.get("/{rotation_id}/history", response_model=list[HistoryEventOut])
async def get_history(
    rotation_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    return rs.history(db, _get_owned_or_404(db, rotation_id, user), limit, offset)
