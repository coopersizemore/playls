"""Example database usage in FastAPI routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from rest_api.database.config import get_db
from rest_api.database.services import UserService, RotationService
from rest_api.database.models import User, Rotation
from typing import List

# Create router for database examples
db_router = APIRouter(prefix="/db", tags=["database"])


@db_router.get("/users/{spotify_id}")
async def get_user(spotify_id: str, db: Session = Depends(get_db)):
    """Get user by Spotify ID."""
    user = UserService.get_user_by_spotify_id(db, spotify_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": user.id,
        "spotify_id": user.spotify_id,
        "display_name": user.display_name,
        "email": user.email,
        "is_active": user.is_active,
        "created_at": user.created_at
    }


@db_router.post("/users")
async def create_user(
    spotify_id: str, 
    display_name: str = None, 
    email: str = None,
    db: Session = Depends(get_db)
):
    """Create a new user."""
    # Check if user already exists
    existing_user = UserService.get_user_by_spotify_id(db, spotify_id)
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    
    user = UserService.create_user(db, spotify_id, display_name, email)
    return {
        "id": user.id,
        "spotify_id": user.spotify_id,
        "display_name": user.display_name,
        "email": user.email,
        "created_at": user.created_at
    }


@db_router.get("/users/{user_id}/rotations")
async def get_user_rotations(user_id: int, db: Session = Depends(get_db)):
    """Get all rotations for a user."""
    rotations = RotationService.get_user_rotations(db, user_id)
    return [
        {
            "id": rotation.id,
            "name": rotation.name,
            "description": rotation.description,
            "source_playlist_id": rotation.source_playlist_id,
            "target_playlist_id": rotation.target_playlist_id,
            "rotation_size": rotation.rotation_size,
            "is_active": rotation.is_active,
            "created_at": rotation.created_at
        }
        for rotation in rotations
    ]


# To use this router in your main app.py, add:
# from rest_api.database.example_routes import db_router
# app.include_router(db_router)