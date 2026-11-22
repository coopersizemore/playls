"""SQLAlchemy models.

Every model is imported here so all of them are registered with the mapper
before any relationship() string (e.g. "RotationTrackDB") is resolved. Importing
any `rest_api.database.models.*` module runs this first. New models must be added here.
"""
from rest_api.database.models.user import UserDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.rotation_track import RotationTrackDB
from rest_api.database.models.review_event import ReviewEventDB
from rest_api.database.models.curated_pick import CuratedPickDB
from rest_api.database.models.restock_feedback import RestockFeedbackDB
from rest_api.database.models.suggestion_cache import SuggestionCacheDB

__all__ = [
    "UserDB", "RotationDB", "RotationTrackDB", "ReviewEventDB",
    "CuratedPickDB", "RestockFeedbackDB", "SuggestionCacheDB",
]
