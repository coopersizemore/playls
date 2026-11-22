"""SQLAlchemy models.

Every model is imported here so all of them are registered with the mapper
before any relationship() string (e.g. "RotationTrackDB") is resolved. Importing
any `rest_api.database.models.*` module runs this first. New models must be added here.
"""
from rest_api.database.models.user import UserDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.rotation_track import RotationTrackDB
from rest_api.database.models.review_event import ReviewEventDB

__all__ = ["UserDB", "RotationDB", "RotationTrackDB", "ReviewEventDB"]
