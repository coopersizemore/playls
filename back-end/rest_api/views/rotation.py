from fastapi import APIRouter, HTTPException, Depends
from ..database.config import get_db
from ..database.models.user import UserDB
from ..models.rotation import Rotation
from ..models.song import Song
from ..services.auth_service import AuthService

from ..services.db import rotation_service as rs

# Every rotation route requires a logged-in user
router = APIRouter(
    prefix="/rotation",
    tags=["rotation"],
    dependencies=[Depends(AuthService.get_current_user_from_token)],
)

current_user_dep = Depends(AuthService.get_current_user_from_token)

def _get_owned_or_404(db, rotation_id: int, user: UserDB):
    # 404 (not 403) for other users' rotations so ids don't leak
    rotation = rs.get_owned_rotation(db, rotation_id, user.id)
    if not rotation:
        raise HTTPException(status_code=404, detail="Rotation not found")
    return rotation

@router.get("/{rotation_id}")
async def get_rotation(rotation_id: int, db=Depends(get_db), current_user: UserDB = current_user_dep):
    return _get_owned_or_404(db, rotation_id, current_user)

@router.post("/")
async def create_rotation(rotation: Rotation, db=Depends(get_db), current_user: UserDB = current_user_dep):
    rotation = await rs.create_rotation(db, rotation=rotation, owner=current_user)
    if not rotation:
        raise HTTPException(status_code=500, detail="Failed to create rotation")
    return rotation

@router.put("/{rotation_id}")
async def update_rotation(
    rotation_id: int, rotation: Rotation, db=Depends(get_db), current_user: UserDB = current_user_dep
):
    existing = _get_owned_or_404(db, rotation_id, current_user)
    return rs.update_rotation(db, existing, rotation)

@router.delete("/{rotation_id}")
async def delete_rotation(rotation_id: int, db=Depends(get_db), current_user: UserDB = current_user_dep):
    existing = _get_owned_or_404(db, rotation_id, current_user)
    rs.delete_rotation(db, existing)
    return {"message": "Rotation deleted successfully"}

@router.get("/{rotation_id}/rotate")
async def rotate_playlist(rotation_id: int, db=Depends(get_db)):
    pass

@router.get("/{rotation_id}/songs")
async def get_rotation_songs(rotation_id: int, db=Depends(get_db)):
    pass

@router.post("/{rotation_id}/song")
async def add_song_to_rotation(rotation_id: int, song: Song, db=Depends(get_db)):
    pass

@router.delete("/{rotation_id}/song/{song_id}")
async def remove_song_from_rotation(rotation_id: int, song_id: str, db=Depends(get_db)):
    pass
