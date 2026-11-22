"""Shared test setup: hermetic env, in-memory SQLite DB, and a fake Spotify.

Env vars are set before the app is imported. The app's Postgres engine is lazy,
so nothing here connects to Supabase.
"""
import os
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-0123456789")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SPOTIFY_CLIENT_ID", "test_client_id")

from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from rest_api.app import app  # noqa: E402
from rest_api.clock import utcnow  # noqa: E402
from rest_api.database.config import Base, get_db  # noqa: E402
from rest_api.database.models import UserDB  # noqa: E402
from rest_api.services.auth_service import AuthService  # noqa: E402
from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def user(db):
    u = UserDB(
        spotify_id="me",
        display_name="Me",
        access_token="token",
        refresh_token="refresh",
        token_expires_at=utcnow() + timedelta(hours=1),
    )
    db.add(u)
    db.commit()
    return u


def spotify_item(track_id, added_days_ago=None, name=None, local=False, kind="track"):
    """A playlist item entry in the post-Feb-2026 shape."""
    added = None
    if added_days_ago is not None:
        added = (utcnow() - timedelta(days=added_days_ago)).isoformat() + "Z"
    return {
        "added_at": added,
        "is_local": local,
        "item": {
            "id": None if local else track_id,
            "uri": f"spotify:{kind}:{track_id}",
            "type": kind,
            "name": name or f"Song {track_id}",
            "duration_ms": 200000,
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "album": {"name": "Album", "images": [{"url": "big", "width": 640}, {"url": "small", "width": 300}]},
        },
    }


class FakeSpotify:
    """In-memory stand-in for the Spotify endpoints PlayLS uses."""

    def __init__(self, owner_id="me"):
        self.owner_id = owner_id
        self.playlists = {}  # id -> {"name", "owner", "collaborative", "items": [...], "version": int}
        self.calls = []
        self.fail = False

    def add_playlist(self, playlist_id, items, name="Mix", owner=None, collaborative=False):
        self.playlists[playlist_id] = {
            "name": name, "owner": owner or self.owner_id, "collaborative": collaborative,
            "items": list(items), "version": 1,
        }

    def touch(self, playlist_id):
        self.playlists[playlist_id]["version"] += 1

    def _get(self, playlist_id):
        if self.fail:
            raise SpotifyAPIError(500)
        if playlist_id not in self.playlists:
            raise SpotifyAPIError(404)
        return self.playlists[playlist_id]

    async def get_playlist(self, playlist_id, user, db, fields=None):
        self.calls.append(("get_playlist", playlist_id))
        p = self._get(playlist_id)
        return {
            "id": playlist_id, "name": p["name"], "description": "", "collaborative": p["collaborative"],
            "owner": {"id": p["owner"]}, "snapshot_id": f"{playlist_id}-v{p['version']}",
        }

    async def get_all_playlist_items(self, playlist_id, user, db):
        self.calls.append(("get_items", playlist_id))
        return list(self._get(playlist_id)["items"])

    async def remove_items_from_playlist(self, playlist_id, uris, user, db):
        self.calls.append(("remove", playlist_id, tuple(uris)))
        p = self._get(playlist_id)
        p["items"] = [i for i in p["items"] if i["item"]["uri"] not in set(uris)]
        p["version"] += 1
        return f"{playlist_id}-v{p['version']}"

    async def create_playlist(self, name, user, db, description=None, public=False):
        self.calls.append(("create", name))
        new_id = f"new{len(self.playlists)}"
        self.add_playlist(new_id, [], name=name)
        return {"id": new_id, "name": name}

    async def get_user_playlists(self, user, db, limit=20, offset=0):
        items = [
            {"id": pid, "name": p["name"], "owner": {"id": p["owner"]}, "collaborative": p["collaborative"],
             "images": [], "items": {"total": len(p["items"])}}
            for pid, p in self.playlists.items()
        ]
        return {"items": items[offset:offset + limit], "next": None}


@pytest.fixture
def spotify(monkeypatch):
    fake = FakeSpotify()
    for name in ("get_playlist", "get_all_playlist_items", "remove_items_from_playlist",
                 "create_playlist", "get_user_playlists"):
        monkeypatch.setattr(SpotifyService, name, staticmethod(getattr(fake, name)))
    return fake


@pytest.fixture
def client(db, user, spotify):
    """Authenticated client backed by the SQLite session and fake Spotify."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[AuthService.get_current_user_from_token] = lambda: user
    try:
        yield TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"})
    finally:
        app.dependency_overrides.clear()
