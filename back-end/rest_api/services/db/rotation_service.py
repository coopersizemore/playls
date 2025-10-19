import sqlalchemy.orm as orm
from rest_api.database.models.rotation import RotationDB
from rest_api.models.rotation import Rotation

def get_rotation(db: orm.Session, rotation_id: int) -> Rotation | None:
    return db.query(RotationDB).filter(RotationDB.id == rotation_id).first()

def create_rotation(db: orm.Session, rotation: Rotation) -> RotationDB:
    new_rotation = RotationDB(**rotation.model_dump())
    db.add(new_rotation)
    db.commit()
    db.refresh(new_rotation)
    return new_rotation

def update_rotation(db: orm.Session, rotation_id: int, rotation: Rotation) -> RotationDB | None:
    existing_rotation = db.query(RotationDB).filter(RotationDB.id == rotation_id).first()
    if not existing_rotation:
        return None
    for key, value in rotation.model_dump().items():
        setattr(existing_rotation, key, value)
    db.commit()
    db.refresh(existing_rotation)
    return existing_rotation

def delete_rotation(db: orm.Session, rotation_id: int) -> bool:
    existing_rotation = db.query(RotationDB).filter(RotationDB.id == rotation_id).first()
    if not existing_rotation:
        return False
    db.delete(existing_rotation)
    db.commit()
    return True