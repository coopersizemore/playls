from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database.config import get_db
from ..database.models.user import UserDB
from ..models.rotation import RotationOut
from ..services.auth_service import AuthService
from ..services.db import rotation_service as rs
from ..services.db import user_service as us

# Users are created by the Spotify login callback; these routes only act on the
# authenticated user. Profile info lives at /auth/me.
router = APIRouter(prefix="/user", tags=["user"])


@router.get("/me/rotations", response_model=list[RotationOut])
async def get_current_user_rotations(
    sync: bool = Query(True, description="Sync each rotation with Spotify first (cheap when unchanged)"),
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """The current user's rotations with due counts."""
    return await rs.list_rotation_summaries(db, current_user, sync=sync)


@router.delete("/me")
async def delete_current_user(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """Delete the current user's account, rotations and stored Spotify tokens"""
    us.delete_user(db, current_user.id)
    return {"message": "User deleted successfully"}
