from fastapi import APIRouter, HTTPException, Depends
from ..database.config import get_db
from ..database.models.rotation import RotationDB
from ..database.models.user import UserDB
from ..database.models.song import SongDB
from ..models.rotation import Rotation
from ..models.user import User
from ..models.song import Song

from ..services.db import rotation_service as rs

router = APIRouter(prefix="/rotation", tags=["rotation"])

@router.get("/{rotation_id}")
async def get_rotation(rotation_id: int, db=Depends(get_db)):
    rotation = rs.get_rotation(db, rotation_id)
    if not rotation:
        raise HTTPException(status_code=404, detail="Rotation not found")
    return rotation

@router.post("")
async def create_rotation(rotation: Rotation, db=Depends(get_db)):
    rotation = rs.create_rotation(db, rotation=rotation)
    if not rotation:
        raise HTTPException(status_code=500, detail="Failed to create rotation")
    return rotation

@router.post("/from_playlist")
async def create_rotation_from_playlist(playlist_id: int, db=Depends(get_db)):
    rotation = rs.create_rotation(db)
    if not rotation:
        raise HTTPException(status_code=500, detail="Failed to create rotation")
    return rotation

@router.put("/{rotation_id}")
async def update_rotation(rotation_id: int, rotation: Rotation, db=Depends(get_db)):
    rotation = rs.update_rotation(db, rotation_id=rotation_id, rotation=rotation)
    if not rotation:
        raise HTTPException(status_code=404, detail="Rotation not found")
    return rotation

@router.delete("/{rotation_id}")
async def delete_rotation(rotation_id: int, db=Depends(get_db)):
    success = rs.delete_rotation(db, rotation_id=rotation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rotation not found")
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