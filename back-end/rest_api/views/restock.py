from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database.config import get_db
from ..database.models.analytics_event import RESTOCK
from ..database.models.user import UserDB
from ..models.restock import BlockedSongOut, DeckOut, DeckSource, RestockActionIn, SearchOut
from ..models.rotation import TrackOut
from ..services import restock_service as restock
from ..services import telemetry
from ..services.auth_service import AuthService
from ..services.db import rotation_service as rs
from ..services.sync_service import claim_or_409

# Restocking a rotation. Every route requires a logged-in user who owns the rotation.
router = APIRouter(
    prefix="/rotation/{rotation_id}/restock",
    tags=["restock"],
    dependencies=[Depends(AuthService.get_current_user_from_token)],
)

current_user_dep = Depends(AuthService.get_current_user_from_token)


def _record(db: Session, user: UserDB, rotation, action: str, data: RestockActionIn) -> None:
    telemetry.record_decision(db, user, rotation, RESTOCK, action, data.telemetry, source=data.source)
TZ = Query(0, ge=-840, le=840, description="JS Date.getTimezoneOffset() of the client")


@router.get("/deck/{source}", response_model=DeckOut)
async def get_deck(
    rotation_id: int,
    source: DeckSource,
    tz_offset: int = TZ,
    refresh: bool = Query(False, description="suggested only: re-read listening data from Spotify"),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    """A ranked deck of up to 30 songs from one source (bring_back, picks, suggested)."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    if source == "bring_back":
        return restock.bring_back_deck(db, rotation, user, tz_offset)
    if source == "picks":
        return restock.picks_deck(db, rotation, user, tz_offset)
    return await restock.suggested_deck(db, rotation, user, tz_offset, refresh)


@router.get("/search", response_model=SearchOut)
async def search(
    rotation_id: int,
    q: str = Query(..., min_length=1, max_length=200),
    offset: int = Query(0, ge=0, le=1000),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    """Spotify track search (10 per page), flagged with what's already in the rotation."""
    return await restock.search(db, rs.get_owned_or_404(db, rotation_id, user), user, q, offset)


@router.post("/add", response_model=TrackOut, status_code=201)
async def add(rotation_id: int, data: RestockActionIn, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Add a song to the rotation's Spotify playlist now."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    async with claim_or_409(db, rotation):
        result = await restock.add_to_rotation(db, rotation, user, data.track_id, data.source)
    _record(db, user, rotation, "add", data)
    return result


@router.post("/undo")
async def undo(rotation_id: int, data: RestockActionIn, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """Undo the latest Add or Not now on a song (an add is taken back out of the playlist).
    Returns {"undone": "add" | "skip"}."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    async with claim_or_409(db, rotation):
        undone = await restock.undo_last(db, rotation, user, data.track_id)
    _record(db, user, rotation, "undo", data)
    return {"undone": undone}


@router.post("/skip", status_code=204)
async def skip(rotation_id: int, data: RestockActionIn, db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """"Not now": hidden for the rest of today, and weighted lower from then on."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    restock.record_skip(db, rotation, user, data.track_id, data.source)
    _record(db, user, rotation, "not_now", data)


@router.post("/block", response_model=BlockedSongOut, status_code=201)
async def block(
    rotation_id: int, data: RestockActionIn, db: Session = Depends(get_db), user: UserDB = current_user_dep
):
    """"Stop suggesting": the song never appears in a restock deck again (it stays in History).
    Undo with DELETE /api/user/me/blocked-songs/{track_id}."""
    rotation = rs.get_owned_or_404(db, rotation_id, user)
    result = await restock.block_suggestions(db, rotation, user, data.track_id)
    _record(db, user, rotation, "block", data)
    return result
