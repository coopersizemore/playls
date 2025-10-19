import sqlalchemy.orm as orm
from rest_api.database.models.rotation import RotationDB
from rest_api.models.rotation import Rotation
from rest_api.database.models.user import UserDB
from rest_api.models.user import User

def get_all_users(db: orm.Session) -> list[UserDB]:
    return db.query(UserDB).all()

def get_user(db: orm.Session, user_id: int) -> User | None:
    return db.query(UserDB).filter(UserDB.id == user_id).first()

def create_user(db: orm.Session, user: User) -> UserDB:
    new_user = UserDB(**user.model_dump())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

def update_user(db: orm.Session, user_id: int, user: User) -> UserDB:
    existing_user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not existing_user:
        return None
    for key, value in user.model_dump().items():
        setattr(existing_user, key, value)
    db.commit()
    db.refresh(existing_user)
    return existing_user

def delete_user(db: orm.Session, user_id: int) -> bool:
    existing_user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not existing_user:
        return False
    db.delete(existing_user)
    db.commit()
    return True

def get_user_rotations(db: orm.Session, user_id: int) -> list[RotationDB]:
    rotations = db.query(RotationDB).filter(RotationDB.user_id == user_id).all()
    if not rotations:
        return None
    return rotations

def get_user_by_spotify_id(db: orm.Session, spotify_id: str) -> UserDB | None:
    """Get user by Spotify ID"""
    return db.query(UserDB).filter(UserDB.spotify_id == spotify_id).first()

def update_user_tokens(
    db: orm.Session, 
    user_id: int, 
    access_token: str, 
    refresh_token: str = None, 
    token_expires_at = None
) -> UserDB | None:
    """Update user's Spotify tokens"""
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        return None
    
    user.access_token = access_token
    if refresh_token:
        user.refresh_token = refresh_token
    if token_expires_at:
        user.token_expires_at = token_expires_at
    
    db.commit()
    db.refresh(user)
    return user

