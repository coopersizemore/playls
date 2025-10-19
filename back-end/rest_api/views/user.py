from fastapi import APIRouter, HTTPException, Depends
from ..database.config import get_db
from ..database.models.user import UserDB
from ..models.user import User
from ..services.db import user_service as us
from ..services.auth_service import AuthService

router = APIRouter(prefix="/user", tags=["user"])

@router.get("/")
async def get_users(db=Depends(get_db)):
    users = us.get_all_users(db)
    if not users:
        raise HTTPException(status_code=404, detail="No users found")
    return users

@router.get("/{user_id}")
async def get_user(user_id: int, db=Depends(get_db)):
    user = us.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.post("/")
async def create_user(user: User, db=Depends(get_db)):
    user = us.create_user(db, user=user)
    if not user:
        raise HTTPException(status_code=500, detail="Failed to create user")
    return user

@router.put("/{user_id}")
async def update_user(user_id: int, user: User, db=Depends(get_db)):
    user = us.update_user(db, user_id, user)
    if not user:
        raise HTTPException(status_code=404, detail="No users found")
    return user

@router.delete("/{user_id}")
async def delete_user(user_id: int, db=Depends(get_db)):
    success = us.delete_user(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="No users found")
    return {"message": "User deleted successfully"}

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

@router.get("/{user_id}/rotations")
async def get_user_rotations(
    user_id: int, 
    db=Depends(get_db),
    current_user: UserDB = Depends(AuthService.get_current_user_from_token)
):
    """Get rotations for a specific user (admin access or own rotations)"""
    # Users can only access their own rotations unless they're admin
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    rotations = us.get_user_rotations(db, user_id)
    if not rotations:
        return []
    return rotations