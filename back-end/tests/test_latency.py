"""Latency work: Server-Timing, concurrent playlist pages, the token-refresh guard,
the mid-read snapshot check, and skipping recent syncs of manual rotations."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from conftest import spotify_item
from rest_api import request_context
from rest_api.clock import utcnow
from rest_api.database.models import RotationDB, RotationTrackDB
from rest_api.services import sync_service
from rest_api.services.auth_service import AuthService
from rest_api.services.spotify import spotify_service
from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService
from test_auto_rotation import create_auto, stock_signals
from test_rotation_flow import make_rotation

SHOWN_LONG_AGO = {"X-Visible-For": str(10 * 60 * 1000)}  # app shown 10 minutes ago
JUST_SHOWN = {"X-Visible-For": "0"}


def playlist_calls(spotify):
    return sum(1 for c in spotify.calls if c[0] == "get_playlist")


def test_server_timing_header(client):
    r = client.get("/api")
    timing = r.headers["server-timing"]
    assert "total;dur=" in timing and "spotify;dur=" in timing and "db;dur=" in timing


# ---------- concurrent playlist pages ----------

def fake_pages(monkeypatch, total, fail_at=None):
    offsets = []

    async def page(playlist_id, user, db, limit=50, offset=0):
        offsets.append(offset)
        await asyncio.sleep(0)
        if offset == fail_at:
            raise SpotifyAPIError(429)
        items = [{"n": i} for i in range(offset, min(offset + limit, total))]
        return {"items": items, "total": total, "next": "more" if offset + limit < total else None}

    monkeypatch.setattr(SpotifyService, "get_playlist_items_page", staticmethod(page))
    return offsets


def test_all_pages_fetched_in_order(monkeypatch):
    offsets = fake_pages(monkeypatch, total=170)
    items = asyncio.run(SpotifyService.get_all_playlist_items("p", None, None))
    assert [i["n"] for i in items] == list(range(170))
    assert sorted(offsets) == [0, 50, 100, 150]


def test_single_page_playlist(monkeypatch):
    offsets = fake_pages(monkeypatch, total=12)
    assert len(asyncio.run(SpotifyService.get_all_playlist_items("p", None, None))) == 12
    assert offsets == [0]


def test_failed_page_raises_the_spotify_error(monkeypatch):
    fake_pages(monkeypatch, total=300, fail_at=100)
    with pytest.raises(SpotifyAPIError) as e:
        asyncio.run(SpotifyService.get_all_playlist_items("p", None, None))
    assert e.value.upstream_status == 429


def test_concurrent_401s_refresh_the_token_once(monkeypatch):
    refreshes = []
    user = SimpleNamespace(access_token="old")

    async def refresh(u, db, force_refresh=False):
        refreshes.append(1)
        await asyncio.sleep(0)
        u.access_token = "new"
        return "new"

    monkeypatch.setattr(AuthService, "ensure_valid_spotify_token", staticmethod(refresh))

    async def run():
        token = request_context._current.set(request_context.RequestContext())
        try:
            return await asyncio.gather(*(spotify_service._refresh_after_401(user, None, "old") for _ in range(3)))
        finally:
            request_context._current.reset(token)

    assert asyncio.run(run()) == ["new", "new", "new"]
    assert len(refreshes) == 1


# ---------- the playlist changing during a read ----------

def test_change_during_read_marks_nothing_removed(client, spotify, db, monkeypatch):
    rot = make_rotation(client, spotify, [spotify_item(t, 5) for t in ("a", "b", "c")])
    rid = rot["id"]
    stored_snapshot = db.get(RotationDB, rid).snapshot_id

    # Someone adds "d" in Spotify, so the next sync does a full read. During that read,
    # "c" is removed, which shifts pages: the read misses "b" (still in the playlist).
    spotify.playlists["p1"]["items"].append(spotify_item("d", 0))
    spotify.touch("p1")
    real_read = spotify.get_all_playlist_items

    async def shifted_read(playlist_id, user, db_):
        items = await real_read(playlist_id, user, db_)
        p = spotify.playlists["p1"]
        p["items"] = [i for i in p["items"] if i["item"]["id"] != "c"]
        spotify.touch("p1")
        return [i for i in items if i["item"]["id"] != "b"]

    monkeypatch.setattr(SpotifyService, "get_all_playlist_items", staticmethod(shifted_read))
    assert client.get(f"/api/rotation/{rid}").json()["sync_ok"] is True

    status = {t.track_id: t.status for t in db.query(RotationTrackDB).filter_by(rotation_id=rid)}
    assert status == {"a": "active", "b": "active", "c": "active", "d": "active"}  # nothing removed
    # The old snapshot is kept, so the next sync reads the playlist again
    assert db.get(RotationDB, rid).snapshot_id == stored_snapshot

    monkeypatch.setattr(SpotifyService, "get_all_playlist_items", staticmethod(real_read))
    client.get(f"/api/rotation/{rid}")
    status = {t.track_id: t.status for t in db.query(RotationTrackDB).filter_by(rotation_id=rid)}
    assert status == {"a": "active", "b": "active", "c": "removed", "d": "active"}


# ---------- skipping recent syncs (manual rotations) ----------

def test_recent_sync_is_reused_for_manual_rotations(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    before = playlist_calls(spotify)
    client.get(f"/api/rotation/{rid}", headers=SHOWN_LONG_AGO)
    client.get(f"/api/rotation/{rid}/queue", headers=SHOWN_LONG_AGO)
    assert playlist_calls(spotify) == before


def test_returning_to_the_app_always_resyncs(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    # Added in Spotify while PlayLS was in the background
    spotify.playlists["p1"]["items"].append(spotify_item("b", 0))
    spotify.touch("p1")
    r = client.get(f"/api/rotation/{rid}", headers=JUST_SHOWN).json()
    assert r["active_count"] == 2


def test_requests_without_the_hint_always_sync(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    before = playlist_calls(spotify)
    client.get(f"/api/rotation/{rid}")
    assert playlist_calls(spotify) == before + 1


def test_old_sync_is_not_reused(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    rotation = db.get(RotationDB, rid)
    rotation.last_synced_at = utcnow() - timedelta(seconds=sync_service.FRESH_SYNC_SECONDS + 5)
    db.commit()
    before = playlist_calls(spotify)
    client.get(f"/api/rotation/{rid}", headers=SHOWN_LONG_AGO)
    assert playlist_calls(spotify) == before + 1


def test_pending_removals_still_flush_when_the_sync_is_skipped(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item(t, 60) for t in ("a", "b")], grace=False)["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    client.get(f"/api/rotation/{rid}", headers=SHOWN_LONG_AGO)
    assert any(c[0] == "remove" for c in spotify.calls)


def test_auto_rotations_always_sync(client, spotify):
    stock_signals(spotify, 80)
    rid = create_auto(client, target_size=30)["id"]
    before = playlist_calls(spotify)
    client.get(f"/api/rotation/{rid}", headers=SHOWN_LONG_AGO)
    assert playlist_calls(spotify) > before
