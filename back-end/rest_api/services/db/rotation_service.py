import sqlalchemy.orm as orm
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.user import UserDB
from rest_api.models.rotation import Rotation
from rest_api.services.spotify.spotify_service import SpotifyService as ss

# Fields the client may never set directly
SERVER_MANAGED_FIELDS = {"id", "owner_id", "created_at"}

def get_owned_rotation(db: orm.Session, rotation_id: int, owner_id: int) -> RotationDB | None:
    return db.query(RotationDB).filter(
        RotationDB.id == rotation_id,
        RotationDB.owner_id == owner_id,
    ).first()

async def create_rotation(db: orm.Session, rotation: Rotation, owner: UserDB) -> RotationDB:
    new_rotation = RotationDB(**rotation.model_dump(exclude=SERVER_MANAGED_FIELDS), owner_id=owner.id)
    # Only create a new Spotify playlist when the rotation isn't wrapping an existing one
    if not new_rotation.playlist_id:
        response = await ss.create_playlist(
            name=new_rotation.name,
            user=owner,
            db=db,
            description=new_rotation.description,
            public=False
        )
        new_rotation.playlist_id = response["id"]
    db.add(new_rotation)
    db.commit()
    db.refresh(new_rotation)

    return new_rotation

def update_rotation(db: orm.Session, existing_rotation: RotationDB, rotation: Rotation) -> RotationDB:
    for key, value in rotation.model_dump(exclude=SERVER_MANAGED_FIELDS).items():
        setattr(existing_rotation, key, value)
    db.commit()
    db.refresh(existing_rotation)
    return existing_rotation

def delete_rotation(db: orm.Session, existing_rotation: RotationDB) -> None:
    db.delete(existing_rotation)
    db.commit()
