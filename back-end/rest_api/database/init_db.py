"""Database initialization and table creation."""
from rest_api.database.config import engine, Base
from rest_api.database.models.users import User
from rest_api.database.models.rotations import Rotation


def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")


def drop_tables():
    """Drop all database tables."""
    print("Dropping database tables...")
    Base.metadata.drop_all(bind=engine)
    print("Database tables dropped successfully!")


if __name__ == "__main__":
    create_tables()