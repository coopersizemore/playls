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
from rest_api.services import health  # noqa: E402
from rest_api.services.auth_service import AuthService  # noqa: E402
from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService  # noqa: E402

from helpers import track_object  # noqa: E402


def _no_health_db():
    raise RuntimeError("health recording is off in tests (see the health_db fixture)")


@pytest.fixture(autouse=True)
def _health_writes_off(monkeypatch):
    """The request middleware records app health with its own session; never reach a real DB."""
    monkeypatch.setattr(health, "session_factory", _no_health_db)


@pytest.fixture
def admin(monkeypatch):
    """Make the test user ("me") an admin (ADMIN_SPOTIFY_IDS)."""
    from rest_api.services import auth_service
    monkeypatch.setattr(auth_service, "ADMIN_SPOTIFY_IDS", {"me"})


@pytest.fixture
def health_db(db, monkeypatch):
    """Record app health into the test database, keeping every request (no sampling)."""
    monkeypatch.setattr(health, "session_factory", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(health, "SAMPLE_RATE", 1.0)
    return db


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
        granted_scopes="playlist-read-private playlist-read-collaborative playlist-modify-private "
                       "playlist-modify-public user-top-read user-read-recently-played user-library-read",
    )
    db.add(u)
    db.commit()
    return u


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
            "images": p.get("images", []),
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

    async def rename_playlist(self, playlist_id, name, user, db):
        self.calls.append(("rename", playlist_id, name))
        p = self._get(playlist_id)
        if p["owner"] != self.owner_id:
            raise SpotifyAPIError(403)
        p["name"] = name
        p["version"] += 1  # a details change gives the playlist a new snapshot

    # ---- restock signals ----
    catalog = {}  # track_id -> track object (for get_track / search)
    top = {}  # (type, time_range) -> list of objects
    recent = []  # track objects, most recent first
    liked = []  # (track object, added_at iso)
    search_results = {}  # query -> list of track objects

    async def get_track(self, track_id, user, db):
        self.calls.append(("get_track", track_id))
        if track_id not in self.catalog:
            raise SpotifyAPIError(404)
        return self.catalog[track_id]

    async def get_top_items(self, item_type, user, db, time_range="medium_term", limit=50):
        self.calls.append(("top", item_type, time_range))
        return {"items": self.top.get((item_type, time_range), [])[:limit]}

    async def get_recently_played(self, user, db, limit=50):
        self.calls.append(("recent",))
        return {"items": [{"track": t, "played_at": "2026-11-01T00:00:00Z"} for t in self.recent[:limit]]}

    async def get_saved_tracks(self, user, db, limit=50, offset=0):
        self.calls.append(("liked", offset))
        page = self.liked[offset:offset + limit]
        return {"items": [{"track": t, "added_at": a} for t, a in page], "total": len(self.liked),
                "next": "more" if offset + limit < len(self.liked) else None}

    # ---- Liked Songs as a rotation (the same self.liked list, newest first) ----
    async def get_saved_tracks_page(self, user, db, offset=0, limit=50):
        self.calls.append(("liked_page", offset))
        if self.fail:
            raise SpotifyAPIError(500)
        page = self.liked[offset:offset + limit]
        return {"items": [{"track": t, "added_at": a} for t, a in page], "total": len(self.liked),
                "next": "more" if offset + limit < len(self.liked) else None}

    async def get_all_saved_tracks(self, user, db, first=None):
        self.calls.append(("liked_all",))
        if self.fail:
            raise SpotifyAPIError(500)
        return [{"track": t, "added_at": a} for t, a in self.liked], len(self.liked)

    async def save_to_library(self, uris, user, db):
        self.calls.append(("like", tuple(uris)))
        if self.fail:
            raise SpotifyAPIError(500)
        have = {t["uri"] for t, _ in self.liked}
        for uri in uris:
            if uri not in have:
                track_id = uri.split(":")[-1]
                self.liked.insert(0, (self.catalog.get(track_id) or track_object(track_id),
                                      utcnow().isoformat() + "Z"))

    async def remove_from_library(self, uris, user, db):
        self.calls.append(("unlike", tuple(uris)))
        if self.fail:
            raise SpotifyAPIError(500)
        self.liked[:] = [(t, a) for t, a in self.liked if t["uri"] not in set(uris)]

    async def search(self, query, user, db, search_type="track", limit=10, offset=0):
        self.calls.append(("search", query, offset))
        items = self.search_results.get(query, [])
        more = offset + limit < len(items)
        return {"tracks": {"items": items[offset:offset + limit], "next": "more" if more else None}}

    async def add_items_to_playlist(self, playlist_id, uris, user, db, position=None):
        self.calls.append(("add", playlist_id, tuple(uris)))
        p = self._get(playlist_id)
        for uri in uris:
            track_id = uri.split(":")[-1]
            item = self.catalog.get(track_id) or track_object(track_id)
            p["items"].append({"added_at": utcnow().isoformat() + "Z", "is_local": False, "item": item})
        p["version"] += 1
        return f"{playlist_id}-v{p['version']}"

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
    fake.catalog, fake.top, fake.recent, fake.liked, fake.search_results = {}, {}, [], [], {}
    for name in ("get_playlist", "get_all_playlist_items", "remove_items_from_playlist",
                 "create_playlist", "rename_playlist", "get_user_playlists", "get_track", "get_top_items",
                 "get_recently_played", "get_saved_tracks", "search", "add_items_to_playlist",
                 "get_saved_tracks_page", "get_all_saved_tracks", "save_to_library", "remove_from_library"):
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
