"""SQLAlchemy models.

Every model is imported here so all of them are registered with the mapper
before any relationship() string (e.g. "SongDB") is resolved. Importing any
`rest_api.database.models.*` module runs this first.
"""
from rest_api.database.models.user import UserDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.song import SongDB

__all__ = ["UserDB", "RotationDB", "SongDB"]
