import sqlalchemy.orm as orm

from rest_api.database.models.user import UserDB
from rest_api.models.user import User


def create_user(db: orm.Session, user: User) -> UserDB:
    new_user = UserDB(**user.model_dump())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


def delete_user(db: orm.Session, user_id: int) -> bool:
    existing_user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not existing_user:
        return False
    db.delete(existing_user)
    db.commit()
    return True
