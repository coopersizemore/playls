from fastapi import APIRouter, Depends
from ..database.config import get_db
from ..database.models.user import UserDB
from ..services.db import user_service as us
from ..services.auth_service import AuthService

# Users are created by the Spotify login callback; these routes only act on the
# authenticated user. Profile info lives at /auth/me.
router = APIRouter(prefix="/user", tags=["user"])

@router.get("/me/rotations")
async def get_current_user_rotations(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db=Depends(get_db)
):
    """Get rotations for the current authenticated user"""
    rotations = us.get_user_rotations(db, current_user.id)
    if not rotations:
        return []
    return rotations

@router.delete("/me")
async def delete_current_user(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db=Depends(get_db)
):
    """Delete the current user's account, rotations and stored Spotify tokens"""
    us.delete_user(db, current_user.id)
    return {"message": "User deleted successfully"}
