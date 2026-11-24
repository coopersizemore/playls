"""The per-rotation sync claim, storing our own writes' snapshots, and Spotify 429 handling."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from conftest import spotify_item, track_object
from rest_api.clock import utcnow
from rest_api.database.models import RotationDB, RotationTrackDB
from rest_api.services import sync_service
from rest_api.services.auth_service import AuthService
from rest_api.services.spotify import spotify_service
from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService
from test_auto_rotation import create_auto, stock_signals
from test_rotation_flow import make_rotation


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(sync_service, "SYNC_CLAIM_WAIT_SECONDS", 0.0)


def claim_elsewhere(db, rid, seconds=60):
    rotation = db.get(RotationDB, rid)
    rotation.sync_claimed_until = utcnow() + timedelta(seconds=seconds)
    db.commit()


def spotify_calls(spotify, kind):
    return sum(1 for c in spotify.calls if c[0] == kind)


# ---------- the sync claim ----------

def test_claim_is_released_after_a_sync(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    client.get(f"/api/rotation/{rid}")
    db.expire_all()
    assert db.get(RotationDB, rid).sync_claimed_until is None


def test_claim_is_released_when_spotify_fails(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    spotify.fail = True
    assert client.get(f"/api/rotation/{rid}").json()["sync_ok"] is False
    db.expire_all()
    assert db.get(RotationDB, rid).sync_claimed_until is None


def test_sync_held_elsewhere_reads_what_is_stored(client, spotify, db, no_wait):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    claim_elsewhere(db, rid)
    spotify.playlists["p1"]["items"].append(spotify_item("b", 0))
    spotify.touch("p1")
    before = len(spotify.calls)
    r = client.get(f"/api/rotation/{rid}").json()
    assert r["sync_ok"] is True and r["active_count"] == 1  # the other request is syncing it
    assert len(spotify.calls) == before


def test_expired_claim_is_taken_over(client, spotify, db, no_wait):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    claim_elsewhere(db, rid, seconds=-1)
    spotify.playlists["p1"]["items"].append(spotify_item("b", 0))
    spotify.touch("p1")
    assert client.get(f"/api/rotation/{rid}").json()["active_count"] == 2


def test_waits_for_a_claim_that_ends(client, spotify, db, monkeypatch):
    monkeypatch.setattr(sync_service, "SYNC_CLAIM_WAIT_SECONDS", 3.0)
    monkeypatch.setattr(sync_service, "SYNC_CLAIM_POLL_SECONDS", 0.05)
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    claim_elsewhere(db, rid, seconds=0.3)
    spotify.playlists["p1"]["items"].append(spotify_item("b", 0))
    spotify.touch("p1")
    assert client.get(f"/api/rotation/{rid}").json()["active_count"] == 2


def test_flush_held_elsewhere_leaves_removals_pending(client, spotify, db, no_wait):
    rid = make_rotation(client, spotify, [spotify_item(t, 60) for t in ("a", "b")], grace=False)["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    claim_elsewhere(db, rid)
    assert client.post(f"/api/rotation/{rid}/flush").json() == {"removed": 0, "pending": 1}
    assert spotify_calls(spotify, "remove") == 0

    claim_elsewhere(db, rid, seconds=-1)  # that request finished (or died)
    client.get(f"/api/rotation/{rid}")
    assert spotify_calls(spotify, "remove") == 1


def test_restock_add_held_elsewhere_is_a_409(client, spotify, db, no_wait):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    spotify.catalog["n1"] = track_object("n1")
    claim_elsewhere(db, rid)
    r = client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "n1", "source": "search"})
    assert r.status_code == 409
    assert spotify_calls(spotify, "add") == 0


def test_auto_flush_refills_under_the_same_claim(client, spotify, db):
    stock_signals(spotify, 120)
    rid = create_auto(client, target_size=30)["id"]
    some = db.query(RotationTrackDB).filter_by(rotation_id=rid, status="active").first().track_id
    client.post(f"/api/rotation/{rid}/review", json={"track_id": some, "action": "remove"})
    assert client.post(f"/api/rotation/{rid}/flush").json()["removed"] == 1
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, status="active").count() == 30


# ---------- storing our own writes' snapshots ----------

def test_flush_onto_unchanged_playlist_skips_the_next_reread(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item(t, 60) for t in ("a", "b", "c")], grace=False)["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    client.post(f"/api/rotation/{rid}/flush")
    reads = spotify_calls(spotify, "get_items")
    r = client.get(f"/api/rotation/{rid}").json()
    assert spotify_calls(spotify, "get_items") == reads
    assert r["active_count"] == 2


def test_flush_after_an_outside_change_still_rereads(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item(t, 60) for t in ("a", "b", "c")], grace=False)["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    # Changed in Spotify since the last sync: the flush mustn't claim the new snapshot as ours
    spotify.playlists["p1"]["items"].append(spotify_item("d", 0))
    spotify.touch("p1")
    client.post(f"/api/rotation/{rid}/flush")
    reads = spotify_calls(spotify, "get_items")
    r = client.get(f"/api/rotation/{rid}").json()
    assert spotify_calls(spotify, "get_items") == reads + 1
    assert r["active_count"] == 3  # b, c, d


def test_sync_flush_onto_unchanged_playlist_skips_the_reread(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item(t, 60) for t in ("a", "b")], grace=False)["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    reads = spotify_calls(spotify, "get_items")
    client.get(f"/api/rotation/{rid}")  # flushes as part of the sync
    client.get(f"/api/rotation/{rid}")
    assert spotify_calls(spotify, "remove") == 1
    assert spotify_calls(spotify, "get_items") == reads


def test_restock_add_skips_the_next_reread(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    spotify.catalog["n1"] = track_object("n1")
    assert client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "n1", "source": "search"}).status_code == 201
    reads = spotify_calls(spotify, "get_items")
    assert client.get(f"/api/rotation/{rid}").json()["active_count"] == 2
    assert spotify_calls(spotify, "get_items") == reads


def test_auto_fill_skips_the_next_reread(client, spotify):
    stock_signals(spotify, 120)
    rid = create_auto(client, target_size=30)["id"]
    reads = spotify_calls(spotify, "get_items")
    assert client.get(f"/api/rotation/{rid}").json()["active_count"] == 30
    assert spotify_calls(spotify, "get_items") == reads


# ---------- 429s ----------

def fake_spotify_http(monkeypatch, responses):
    """make_spotify_request against canned responses; returns (requests seen, waits slept)."""
    seen, waits = [], []
    queue = list(responses)

    def handler(request):
        seen.append(request)
        return queue.pop(0)

    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    async def token(user, db, force_refresh=False):
        return "tok"

    real_sleep = asyncio.sleep

    async def sleep(seconds):
        waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(spotify_service, "_client", client)
    monkeypatch.setattr(AuthService, "ensure_valid_spotify_token", staticmethod(token))
    monkeypatch.setattr(spotify_service.asyncio, "sleep", sleep)
    return seen, waits


def call():
    return asyncio.run(SpotifyService.make_spotify_request("/me", SimpleNamespace(access_token="tok"), None))


def test_short_429_is_retried(monkeypatch):
    seen, waits = fake_spotify_http(monkeypatch, [
        httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={"ok": True}),
    ])
    assert call() == {"ok": True}
    assert len(seen) == 2 and waits == [2.0]


def test_long_429_fails_with_retry_after(monkeypatch):
    seen, waits = fake_spotify_http(monkeypatch, [httpx.Response(429, headers={"Retry-After": "30"})])
    with pytest.raises(SpotifyAPIError) as e:
        call()
    assert len(seen) == 1 and waits == []
    assert e.value.status_code == 429 and e.value.headers == {"Retry-After": "30"}


def test_quota_429_is_not_retried(monkeypatch):
    seen, waits = fake_spotify_http(monkeypatch, [
        httpx.Response(429, headers={"Retry-After": "1"},
                       json={"error": {"status": 429, "message": "Quota exceeded", "reason": "QUOTA_EXCEEDED"}}),
    ])
    with pytest.raises(SpotifyAPIError) as e:
        call()
    assert len(seen) == 1 and waits == []
    assert "quota" in e.value.detail


def test_429_retries_are_capped(monkeypatch):
    seen, waits = fake_spotify_http(monkeypatch, [httpx.Response(429, headers={"Retry-After": "1"})] * 5)
    with pytest.raises(SpotifyAPIError):
        call()
    assert len(seen) == spotify_service.RATE_LIMIT_RETRIES + 1
