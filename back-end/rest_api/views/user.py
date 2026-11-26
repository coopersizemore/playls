from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from ..clock import to_naive_utc
from ..database.config import get_db
from ..database.models.user import DEMO, UserDB
from ..models.restock import BlockedSongOut
from ..models.rotation import RotationOut
from ..models.user import ImportIn, ImportOut, ListeningStatusOut, SettingsOut, SettingsUpdate
from ..services import listening_service as listening
from ..services import preferences as prefs
from ..services import restock_service as restock
from ..services import telemetry
from ..services.auth_service import AuthService
from ..services.db import rotation_service as rs
from ..services.db import user_service as us

# Users are created by the Spotify login callback; these routes only act on the
# authenticated user. Profile info lives at /auth/me.
router = APIRouter(prefix="/user", tags=["user"])


@router.get("/me/rotations", response_model=list[RotationOut])
async def get_current_user_rotations(
    sync: bool = Query(True, description="Sync each rotation with Spotify first (cheap when unchanged)"),
    tz_offset: int = Query(0, ge=-840, le=840, description="JS Date.getTimezoneOffset() of the client"),
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """The current user's rotations with due counts and today's review allowance."""
    return await rs.list_rotation_summaries(db, current_user, sync=sync, tz_offset_minutes=tz_offset)


def _settings_out(user: UserDB) -> SettingsOut:
    return SettingsOut(
        review_limit=user.review_limit, analytics_consent=user.analytics_consent,
        listening_enabled=listening.enabled(user), **prefs.account_settings(user),
    )


@router.get("/me/settings", response_model=SettingsOut)
async def get_settings(current_user: UserDB = Depends(AuthService.get_current_user_from_token)):
    return _settings_out(current_user)


@router.put("/me/settings", response_model=SettingsOut)
async def update_settings(
    data: SettingsUpdate,
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """Change only the settings sent. review_limit: 1-1000, or null for no limit.
    analytics_consent: true / false (false also deletes recorded usage data; null is ignored).
    For the others, null puts the setting back to its default."""
    if current_user.provider == DEMO and data.analytics_consent:
        raise HTTPException(status_code=400, detail="The demo doesn't record usage data")
    for name in data.model_fields_set - {"analytics_consent", "listening_enabled"}:
        setattr(current_user, name, getattr(data, name))
    db.commit()
    if "listening_enabled" in data.model_fields_set and data.listening_enabled is not None:
        listening.set_enabled(db, current_user, data.listening_enabled)
    if "analytics_consent" in data.model_fields_set and data.analytics_consent is not None:
        telemetry.set_consent(db, current_user, data.analytics_consent)
    return _settings_out(current_user)


@router.post("/me/listening/capture")
async def capture_listening(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """Save the latest plays (called when the app opens; at most every 15 minutes per user).
    Best effort: Spotify trouble returns {"added": 0}, never an error."""
    return {"added": await listening.safe_capture(db, current_user)}


@router.get("/me/listening", response_model=ListeningStatusOut)
async def listening_status(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    return listening.status(db, current_user)


@router.post("/me/listening/import", response_model=ImportOut)
async def import_listening(
    data: ImportIn,
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """Add plays from Spotify's Extended Streaming History export (up to 5,000 rows per
    request; the browser reads the files and sends them in chunks)."""
    if current_user.provider == DEMO:
        raise HTTPException(status_code=400, detail="The demo can't import listening history")
    if not listening.enabled(current_user):
        raise HTTPException(status_code=409, detail="Turn on listening history first")
    rows = [
        listening.ImportRow(
            ts=to_naive_utc(r.ts), ms_played=r.ms_played, uri=r.uri, track=r.track, artist=r.artist,
            album=r.album, reason_end=r.reason_end, skipped=r.skipped,
        )
        for r in data.rows
    ]
    return listening.import_plays(db, current_user, rows)


@router.post("/me/telemetry/session-end", status_code=204)
async def telemetry_session_end(
    data: telemetry.SessionEndIn,
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """End of a Review or Restock visit (sent with keepalive as the page closes). Recorded only
    with analytics consent."""
    telemetry.record_session_end(db, current_user, data)


@router.get("/me/blocked-songs", response_model=list[BlockedSongOut])
async def get_blocked_songs(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token), db: Session = Depends(get_db)
):
    """Songs the user asked PlayLS to stop suggesting."""
    return restock.list_blocks(db, current_user)


@router.delete("/me/blocked-songs/{track_id}", status_code=204)
async def unblock_song(
    track_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9]+$"),
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """Resume suggesting a song."""
    if not restock.unblock(db, current_user, track_id):
        raise HTTPException(status_code=404, detail="That song isn't blocked")


@router.delete("/me")
async def delete_current_user(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """Delete the current user's account, rotations and stored Spotify tokens"""
    us.delete_user(db, current_user.id)
    return {"message": "User deleted successfully"}
