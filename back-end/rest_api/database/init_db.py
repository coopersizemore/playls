"""Database initialization and table creation.

Usage (from back-end/):
    python -m rest_api.database.init_db           # create missing tables
    python -m rest_api.database.init_db --reset   # DROP everything, then recreate
"""
import sys
from sqlalchemy import text
from rest_api.database.config import engine, Base
from rest_api.database.models.user import UserDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.song import SongDB


def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")


def enable_rls():
    """Enable row level security on every table, with no policies.

    The backend connects as the database owner, which bypasses RLS, so this only
    blocks access through Supabase's public Data API (anon/authenticated keys).
    """
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
    print("Row level security enabled on all tables.")


def drop_tables():
    """Drop all database tables."""
    print("Dropping database tables...")
    Base.metadata.drop_all(bind=engine)
    print("Database tables dropped successfully!")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        drop_tables()
    create_tables()
    enable_rls()
