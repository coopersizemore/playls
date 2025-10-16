"""Database service layer for user and rotation operations."""
from sqlalchemy.orm import Session
from rest_api.database.models import User, Rotation
from typing import Optional, List


class UserService:
    """Service class for user database operations."""
    
    @staticmethod
    def create_user(db: Session, spotify_id: str, display_name: str = None, email: str = None) -> User:
        """Create a new user."""
        db_user = User(
            spotify_id=spotify_id,
            display_name=display_name,
            email=email
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    
    @staticmethod
    def get_user_by_spotify_id(db: Session, spotify_id: str) -> Optional[User]:
        """Get user by Spotify ID."""
        return db.query(User).filter(User.spotify_id == spotify_id).first()
    
    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        """Get user by ID."""
        return db.query(User).filter(User.id == user_id).first()
    
    @staticmethod
    def update_user_tokens(db: Session, user_id: int, access_token: str, refresh_token: str = None) -> User:
        """Update user tokens."""
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.access_token = access_token
            if refresh_token:
                user.refresh_token = refresh_token
            db.commit()
            db.refresh(user)
        return user


class RotationService:
    """Service class for rotation database operations."""
    
    @staticmethod
    def create_rotation(
        db: Session, 
        owner_id: int, 
        name: str, 
        source_playlist_id: str, 
        target_playlist_id: str,
        description: str = None,
        rotation_size: int = 10
    ) -> Rotation:
        """Create a new rotation."""
        db_rotation = Rotation(
            owner_id=owner_id,
            name=name,
            description=description,
            source_playlist_id=source_playlist_id,
            target_playlist_id=target_playlist_id,
            rotation_size=rotation_size
        )
        db.add(db_rotation)
        db.commit()
        db.refresh(db_rotation)
        return db_rotation
    
    @staticmethod
    def get_user_rotations(db: Session, user_id: int) -> List[Rotation]:
        """Get all rotations for a user."""
        return db.query(Rotation).filter(Rotation.owner_id == user_id).all()
    
    @staticmethod
    def get_rotation_by_id(db: Session, rotation_id: int) -> Optional[Rotation]:
        """Get rotation by ID."""
        return db.query(Rotation).filter(Rotation.id == rotation_id).first()
    
    @staticmethod
    def delete_rotation(db: Session, rotation_id: int) -> bool:
        """Delete a rotation."""
        rotation = db.query(Rotation).filter(Rotation.id == rotation_id).first()
        if rotation:
            db.delete(rotation)
            db.commit()
            return True
        return False