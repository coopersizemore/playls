"""Demo mode: demo accounts run the real rules against DemoSpotify, never the network."""
import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from rest_api import clock, request_context
from rest_api.app import app
from rest_api.database.config import get_db
from rest_api.database.models import RotationDB, RotationTrackDB, UserDB
from rest_api.services import analytics_service
from rest_api.services.auth_service import DEMO_SESSION_COOKIE, SESSION_COOKIE, AuthService
from rest_api.services.demo import catalog as demo_catalog_module
from rest_api.services.demo import demo_service

from helpers import DEMO_HEADERS, demo_catalog, review, start_demo


@pytest.fixture
def no_network(monkeypatch):
    async def refuse(self, request, **kw):
        raise AssertionError(f"demo reached the network: {request.url}")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)


@pytest.fixture
def demo(db, no_network):
    """A TestClient in demo mode (real auth dependency, demo header on every request)."""
    demo_catalog_module.set_catalog(demo_catalog())
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app, headers=DEMO_HEADERS)
    finally:
        app.dependency_overrides.clear()
        demo_catalog_module.set_catalog(None)


def _demo_user(db):
    return db.query(UserDB).filter(UserDB.provider == "demo").one()


def _rotations(demo):
    r = demo.get("/api/user/me/rotations")
    assert r.status_code == 200, r.text
    return {x["name"]: x for x in r.json()}


# ---------- accounts ----------

def test_start_creates_and_seeds_a_demo_account(demo, db):
    state = start_demo(demo)
    assert state["clock_offset_hours"] == 0
    me = demo.get("/api/auth/me").json()
    assert me["is_demo"] is True and me["is_admin"] is False and me["missing_scopes"] == []
    assert me["analytics_consent"] is False and me["demo_expires_at"]
    rotations = _rotations(demo)
    assert set(rotations) == {"Daily Mix", "Fresh Rotation"}
    mix = rotations["Daily Mix"]
    assert mix["sync_ok"] is True
    assert mix["due_count"] >= 10
    assert rotations["Fresh Rotation"]["active_count"] == 30


def test_rename_sticks_in_the_demo(demo, db):
    start_demo(demo)
    rid = _rotations(demo)["Daily Mix"]["id"]
    assert demo.put(f"/api/rotation/{rid}", json={"name": "My Mix"}).status_code == 200
    assert demo.get(f"/api/rotation/{rid}").json()["name"] == "My Mix"  # sync doesn't undo it


def test_start_again_reuses_the_account(demo, db):
    start_demo(demo)
    start_demo(demo)
    assert db.query(UserDB).filter(UserDB.provider == "demo").count() == 1


def test_demo_is_capped(demo, db, monkeypatch):
    monkeypatch.setattr(demo_service, "DEMO_MAX_ACTIVE", 1)
    start_demo(demo)
    other = TestClient(app, headers=DEMO_HEADERS)
    r = other.post("/api/demo/start")
    assert r.status_code == 503


def test_demo_is_capped_per_ip(demo, db, monkeypatch):
    monkeypatch.setattr(demo_service, "DEMO_MAX_PER_CLIENT", 2)
    same_ip = {**DEMO_HEADERS, "X-Real-IP": "203.0.113.7"}
    for _ in range(2):
        assert TestClient(app, headers=same_ip).post("/api/demo/start").status_code == 200
    r = TestClient(app, headers=same_ip).post("/api/demo/start")
    assert r.status_code == 403 and "demos" in r.json()["detail"]
    other_ip = {**DEMO_HEADERS, "X-Real-IP": "198.51.100.1"}
    assert TestClient(app, headers=other_ip).post("/api/demo/start").status_code == 200
    # The IP itself is never stored
    hashes = {u.demo_client_hash for u in db.query(UserDB).filter(UserDB.provider == "demo")}
    assert len(hashes) == 2 and all(h and "203.0.113.7" not in h for h in hashes)
    # Ending a demo frees that IP's slot
    db.delete(db.query(UserDB).filter(UserDB.demo_client_hash == demo_service.client_hash("203.0.113.7")).first())
    db.commit()
    assert TestClient(app, headers=same_ip).post("/api/demo/start").status_code == 200


def test_start_needs_the_csrf_header(demo):
    r = demo.post("/api/demo/start", headers={"X-Requested-With": ""})
    assert r.status_code == 403


def test_expired_accounts_are_purged(demo, db):
    start_demo(demo)
    user = _demo_user(db)
    user.created_at -= timedelta(hours=25)
    db.commit()
    assert demo_service.purge_expired(db) == 1
    db.expire_all()
    assert db.query(UserDB).count() == 0
    assert db.query(RotationDB).count() == 0 and db.query(RotationTrackDB).count() == 0


def test_end_deletes_the_account(demo, db):
    start_demo(demo)
    assert demo.post("/api/demo/end").status_code == 200
    db.expire_all()
    assert db.query(UserDB).filter(UserDB.provider == "demo").count() == 0
    assert demo.get("/api/auth/me").status_code == 401


# ---------- isolation ----------

def test_demo_cookie_needs_the_demo_header(demo):
    start_demo(demo)
    r = demo.get("/api/auth/me", headers={"X-PlayLS-Demo": ""})
    assert r.status_code == 401


def test_demo_token_in_the_real_cookie_is_rejected(demo, db):
    start_demo(demo)
    token = demo.cookies.get(DEMO_SESSION_COOKIE)
    real = TestClient(app, cookies={SESSION_COOKIE: token})
    assert real.get("/api/auth/me").status_code == 401


def test_real_session_cannot_use_demo_mode(demo, db, user):
    token = AuthService.create_access_token({"sub": str(user.id)})
    c = TestClient(app, headers=DEMO_HEADERS, cookies={SESSION_COOKIE: token, DEMO_SESSION_COOKIE: token})
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/demo/skip-ahead").status_code == 401


def test_demo_routes_are_demo_only(db, user, no_network):
    token = AuthService.create_access_token({"sub": str(user.id)})
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app, headers={"X-Requested-With": "x"}, cookies={SESSION_COOKIE: token})
        assert c.get("/api/auth/me").json()["is_demo"] is False
        assert c.post("/api/demo/skip-ahead").status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------- the loop, with no network ----------

def test_review_flush_and_history(demo, db):
    start_demo(demo)
    rid = _rotations(demo)["Daily Mix"]["id"]
    queue = demo.get(f"/api/rotation/{rid}/queue").json()
    first, second = queue["tracks"][0]["track_id"], queue["tracks"][1]["track_id"]
    assert review(demo, rid, first, "keep").status_code == 200
    assert review(demo, rid, second, "remove").status_code == 200
    assert demo.post(f"/api/rotation/{rid}/flush").status_code == 200
    row = db.query(RotationTrackDB).filter_by(rotation_id=rid, track_id=second).one()
    assert row.status == "removed"
    # The next sync still agrees with the rows (nothing re-added, nothing else removed)
    active_before = db.query(RotationTrackDB).filter_by(rotation_id=rid, status="active").count()
    assert demo.get(f"/api/rotation/{rid}").json()["sync_ok"] is True
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, status="active").count() == active_before
    history = demo.get(f"/api/rotation/{rid}/history", params={"filter": "reviews"}).json()
    assert {e["action"] for e in history[:2]} == {"keep", "remove"}


def test_unplayable_and_remove_unplayable(demo, db):
    start_demo(demo)
    rid = _rotations(demo)["Daily Mix"]["id"]
    unplayable = demo.get(f"/api/rotation/{rid}/unplayable").json()
    assert len(unplayable["tracks"] if isinstance(unplayable, dict) else unplayable) == 2
    assert demo.post(f"/api/rotation/{rid}/remove-unplayable").status_code == 200
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, is_playable=False, status="active").count() == 0


def test_restock_add_undo_and_search(demo, db):
    start_demo(demo)
    rid = _rotations(demo)["Daily Mix"]["id"]
    deck = demo.get(f"/api/rotation/{rid}/restock/deck/suggested").json()
    assert deck["items"] and deck["missing_scopes"] == []
    track_id = deck["items"][0]["track_id"]
    r = demo.post(f"/api/rotation/{rid}/restock/add", json={"track_id": track_id, "source": "suggested"})
    assert r.status_code == 201, r.text
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, track_id=track_id, status="active").count() == 1
    r = demo.post(f"/api/rotation/{rid}/restock/undo", json={"track_id": track_id, "source": "suggested"})
    assert r.status_code == 200, r.text
    bring_back = demo.get(f"/api/rotation/{rid}/restock/deck/bring_back").json()
    assert bring_back["items"]
    found = demo.get(f"/api/rotation/{rid}/restock/search", params={"q": "demo song 85"}).json()
    assert [i["track_id"] for i in found["items"]] == ["d085"]
    assert demo.get("/api/spotify/search", params={"q": "Band 3"}).status_code == 200


def test_create_and_wrap_rotations(demo, db):
    start_demo(demo)
    playlists = demo.get("/api/spotify/playlists").json()
    by_id = {p["id"]: p for p in (playlists["items"] if isinstance(playlists, dict) else playlists)}
    assert by_id["demo-sample-1"]["rotation_id"] is not None
    assert by_id["demo-sample-3"]["rotatable"] is True
    r = demo.post("/api/rotation/", json={"playlist_id": "demo-sample-3", "interval_hours": 168, "grace_period": True})
    assert r.status_code == 201, r.text
    assert r.json()["active_count"] == 10
    r = demo.post("/api/rotation/", json={"name": "Mine", "interval_hours": 168, "grace_period": True})
    assert r.status_code == 201 and r.json()["active_count"] == 0
    r = demo.post("/api/rotation/", json={"kind": "auto", "name": "Auto", "interval_hours": 168,
                                           "grace_period": True, "target_size": 30})
    assert r.status_code == 201, r.text
    assert r.json()["active_count"] > 0  # restocked from the catalog
    # Real Spotify playlists can't be wrapped from the demo
    r = demo.post("/api/rotation/", json={"playlist_id": "37i9dQZF1DXcBWIGoYBM5M", "interval_hours": 168,
                                           "grace_period": True})
    assert r.status_code == 404


# ---------- skip ahead ----------

def test_skip_ahead_brings_songs_due_and_resets_the_daily_limit(demo, db):
    start_demo(demo)
    user = _demo_user(db)
    user.review_limit = 1
    db.commit()
    rid = _rotations(demo)["Daily Mix"]["id"]
    queue = demo.get(f"/api/rotation/{rid}/queue").json()
    due_before = queue["due_count"]
    assert review(demo, rid, queue["tracks"][0]["track_id"], "keep").status_code == 200
    assert demo.get(f"/api/rotation/{rid}/queue").json()["limit_reached"] is True
    for _ in range(3):
        assert demo.post("/api/demo/skip-ahead").status_code == 200
    queue = demo.get(f"/api/rotation/{rid}/queue").json()
    # A new day: one more song on offer, and more songs due than before
    assert queue["reviewed_today"] == 0 and len(queue["tracks"]) == 1
    assert queue["due_count"] > due_before - 1
    assert demo.get("/api/auth/me").status_code == 200  # the session isn't tied to the skipped clock


def test_skip_ahead_runs_the_auto_rotation(demo, db):
    start_demo(demo)
    rid = _rotations(demo)["Fresh Rotation"]["id"]
    for _ in range(3):
        demo.post("/api/demo/skip-ahead")
    assert demo.get(f"/api/rotation/{rid}").json()["sync_ok"] is True
    db.expire_all()
    rotated = db.query(RotationTrackDB).filter_by(rotation_id=rid, removed_by="rotation").count()
    assert rotated > 0
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, status="active").count() == 30


def test_utcnow_follows_the_request_offset():
    ctx = request_context.RequestContext(clock_offset_hours=48)
    token = request_context._current.set(ctx)
    try:
        assert clock.utcnow() - clock.real_utcnow() >= timedelta(hours=47, minutes=59)
    finally:
        request_context._current.reset(token)
    assert abs(clock.utcnow() - clock.real_utcnow()) < timedelta(seconds=5)


# ---------- cut features ----------

def test_no_liked_songs_or_analytics_in_the_demo(demo):
    start_demo(demo)
    r = demo.post("/api/rotation/", json={"liked_songs": True, "interval_hours": 168, "grace_period": True})
    assert r.status_code == 400
    assert demo.put("/api/user/me/settings", json={"analytics_consent": True}).status_code == 400
    assert demo.put("/api/user/me/settings", json={"review_limit": 10}).status_code == 200


def test_cron_skips_and_purges_demo_accounts(demo, db, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    start_demo(demo)
    r = demo.get("/api/cron/auto-restock", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json().get("rotations", 0) == 0 and r.json()["demo_purged"] == 0


def test_admin_stats_exclude_demo_accounts(demo, db, user, monkeypatch):
    start_demo(demo)
    seen = {}

    def capture(events, previous, health_rows, users, rotations, *rest):
        seen["users"], seen["rotations"] = users, rotations
        return {}

    monkeypatch.setattr(analytics_service, "build_stats", capture)
    analytics_service.load_stats(db, user, 30)
    assert [u.id for u in seen["users"]] == [user.id]
    assert seen["rotations"] == []


def test_demo_spotify_never_falls_through(db):
    """A method that isn't routed must fail closed for a demo account."""
    from rest_api.services.spotify.spotify_service import SpotifyService

    u = UserDB(provider="demo", spotify_id="demo-x", display_name="d")
    with pytest.raises(RuntimeError):
        asyncio.run(SpotifyService.make_spotify_request("/me", u, db))


# ---------- listening history ----------

def test_demo_has_listening_history_and_never_captures(demo, db):
    start_demo(demo)
    status = demo.get("/api/user/me/listening").json()
    assert status["enabled"] is True and status["plays"] > 50 and status["since"]
    assert demo.post("/api/user/me/listening/capture").json() == {"added": 0}
    r = demo.post("/api/user/me/listening/import", json={"rows": []})
    assert r.status_code == 400
