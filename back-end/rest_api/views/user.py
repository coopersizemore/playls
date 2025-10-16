from fastapi import APIRouter, HTTPException, Depends
from rest_api.database.config import get_db
from rest_api.database.models import User

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/")
async def get_users(db=Depends(get_db)):
    pass

@router.get("/{user_id}")
async def get_user(user_id: int, db=Depends(get_db)):
    pass

@router.post("/")
async def create_user(user: User, db=Depends(get_db)):
    pass

@router.put("/{user_id}")
async def update_user(user_id: int, user: User, db=Depends(get_db)):
    pass

@router.delete("/{user_id}")
async def delete_user(user_id: int, db=Depends(get_db)):
    pass

@router.get("/{user_id}/rotations")
async def get_user_rotations(user_id: int, db=Depends(get_db)):
    pass