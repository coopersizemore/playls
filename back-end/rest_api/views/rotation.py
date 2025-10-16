from fastapi import APIRouter, HTTPException, Depends
from rest_api.database.config import get_db

router = APIRouter(prefix="/rotation", tags=["rotation"])

@router.get("/{rotation_id}")
async def get_rotation(rotation_id: int, db=Depends(get_db)):
    pass

@router.post("/")
async def create_rotation(db=Depends(get_db)):
    pass

@router.delete("/{rotation_id}")
async def delete_rotation(rotation_id: int, db=Depends(get_db)):
    pass

@router.put("/{rotation_id}")   
async def update_rotation(rotation_id: int, db=Depends(get_db)):
    pass

