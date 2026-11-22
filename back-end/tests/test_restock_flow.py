"""Restock end to end: bring back, picks, suggestions, search, add / Not now, admin curation."""
from datetime import timedelta

import pytest

from rest_api.clock import utcnow
from rest_api.database.models import CuratedPickDB, RestockFeedbackDB, RotationTrackDB
from tests.conftest import spotify_item, track_object


def make_rotation(client, spotify, items, playlist_id="p1"):
    spotify.add_playlist(playlist_id, items)
    r = client.post("/api/rotation/", json={"playlist_id": playlist_id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def remove(client, rid, track_id):
    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": track_id, "action": "remove"}).status_code == 200


def deck(client, rid, source, **params):
    r = client.get(f"/api/rotation/{rid}/restock/deck/{source}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def ids(deck_json):
    return [c["track_id"] for c in deck_json["items"]]


# ---------- bring back ----------

def test_bring_back_offers_removed_songs_with_recovering_weight(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 10), spotify_item("b", 10), spotify_item("c", 10)])
    remove(client, rid, "a")
    remove(client, rid, "b")
    client.post(f"/api/rotation/{rid}/flush")
    # b was removed long ago, a just now
    db.query(RotationTrackDB).filter_by(track_id="b").one().removed_at = utcnow() - timedelta(days=200)
    db.commit()
    d = deck(client, rid, "bring_back")
    assert set(ids(d)) == {"a", "b"}
    weights = {c["track_id"]: c["score"] for c in d["items"]}
    assert weights["b"] == 1.0 and weights["a"] == pytest.approx(0.1, abs=0.01)
    assert d["items"][0]["reason"].startswith("Removed")


def test_not_now_hides_for_today_and_halves_weight(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 10)])
    remove(client, rid, "a")
    client.post(f"/api/rotation/{rid}/flush")
    db.query(RotationTrackDB).filter_by(track_id="a").one().removed_at = utcnow() - timedelta(days=200)
    db.commit()
    assert client.post(f"/api/rotation/{rid}/restock/skip", json={"track_id": "a", "source": "bring_back"}).status_code == 204
    assert ids(deck(client, rid, "bring_back")) == []  # hidden today
    for fb in db.query(RestockFeedbackDB):
        fb.created_at -= timedelta(days=1)
    db.commit()
    [c] = deck(client, rid, "bring_back")["items"]
    assert c["score"] == 0.5


def test_adding_brings_song_back_into_rotation_and_playlist(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 10), spotify_item("b", 10)])
    remove(client, rid, "a")
    client.post(f"/api/rotation/{rid}/flush")
    r = client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "a", "source": "bring_back"})
    assert r.status_code == 201
    assert r.json()["status"] == "active" and r.json()["last_kept_at"] is None
    assert ("add", "p1", ("spotify:track:a",)) in spotify.calls
    assert ("get_track", "a") not in spotify.calls  # metadata came from the DB
    assert ids(deck(client, rid, "bring_back")) == []
    # Already there now
    assert client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "a", "source": "bring_back"}).status_code == 409
    # Next sync agrees with Spotify (no duplicate, still active)
    client.get(f"/api/rotation/{rid}")
    assert db.query(RotationTrackDB).filter_by(track_id="a").one().status == "active"


# ---------- picks + admin ----------

@pytest.fixture
def admin(monkeypatch):
    from rest_api.services import auth_service
    monkeypatch.setattr(auth_service, "ADMIN_SPOTIFY_IDS", {"me"})


def test_admin_routes_hidden_from_non_admins(client):
    assert client.get("/api/admin/picks").status_code == 404
    assert client.get("/api/auth/me").json()["is_admin"] is False


def test_admin_curates_picks_and_users_see_active_ones(client, spotify, db, admin):
    spotify.catalog["pnew"] = track_object("pnew", name="Fresh Pick")
    spotify.catalog["pold"] = track_object("pold")
    spotify.catalog["plater"] = track_object("plater")
    assert client.get("/api/auth/me").json()["is_admin"] is True
    r = client.post("/api/admin/picks", json={"track_id": "pnew", "note": "Pick of the week"})
    assert r.status_code == 201 and r.json()["title"] == "Fresh Pick" and r.json()["active"]
    past = (utcnow() - timedelta(days=10)).isoformat()
    client.post("/api/admin/picks", json={"track_id": "pold", "ends_at": past})
    future = (utcnow() + timedelta(days=10)).isoformat()
    client.post("/api/admin/picks", json={"track_id": "plater", "starts_at": future})
    assert client.post("/api/admin/picks", json={"track_id": "missing"}).status_code == 404
    assert len(client.get("/api/admin/picks").json()) == 3

    rid = make_rotation(client, spotify, [spotify_item("a", 1)])
    d = deck(client, rid, "picks")
    assert ids(d) == ["pnew"] and d["items"][0]["note"] == "Pick of the week"

    client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "pnew", "source": "picks"})
    assert ids(deck(client, rid, "picks")) == []  # in the rotation now

    pick_id = db.query(CuratedPickDB).filter_by(track_id="pold").one().id
    assert client.delete(f"/api/admin/picks/{pick_id}").status_code == 204


# ---------- suggestions ----------

def seed_listening(spotify):
    t = {i: track_object(i, artists=((f"Artist {i}", f"art_{i}"),), album=(f"Album {i}", f"alb_{i}"))
         for i in ("top1", "top2", "liked1", "recent1", "inrot", "favnew", "albnew")}
    spotify.top[("tracks", "short_term")] = [t["top1"], t["inrot"]]
    spotify.top[("tracks", "medium_term")] = [t["top2"], t["top1"]]
    spotify.top[("artists", "medium_term")] = [{"id": "art_top1", "name": "Artist top1"}]
    spotify.recent = [t["recent1"], t["recent1"]]
    spotify.liked = [(t["liked1"], "2026-11-01T00:00:00Z")]
    spotify.search_results['artist:"Artist top1"'] = [t["favnew"], t["top1"]]
    spotify.search_results['album:"Album top1" artist:"Artist top1"'] = [t["albnew"]]
    return t


def test_suggestions_mix_listening_and_discoveries(client, spotify, db):
    seed_listening(spotify)
    rid = make_rotation(client, spotify, [spotify_item("inrot", 1)])
    d = deck(client, rid, "suggested")
    got = {c["track_id"]: c for c in d["items"]}
    assert "inrot" not in got  # already in this rotation
    assert {"top1", "top2", "liked1", "recent1", "favnew", "albnew"} <= set(got)
    assert got["recent1"]["reason"] == "Played 2× recently"
    assert got["favnew"]["reason"] == "More from Artist top1"
    # top1 is also found via the artist search, but it's known, so it ranks on its listening signals
    assert got["top1"]["score"] > got["favnew"]["score"]
    assert d["missing_scopes"] == []


def test_suggestions_are_cached(client, spotify):
    seed_listening(spotify)
    rid = make_rotation(client, spotify, [])
    deck(client, rid, "suggested")
    n = len([c for c in spotify.calls if c[0] == "top"])
    deck(client, rid, "suggested")
    assert len([c for c in spotify.calls if c[0] == "top"]) == n  # served from cache
    deck(client, rid, "suggested", refresh=True)
    assert len([c for c in spotify.calls if c[0] == "top"]) > n


def test_suggestions_skip_sources_without_scopes(client, spotify, db, user):
    seed_listening(spotify)
    user.granted_scopes = None  # logged in before suggestion scopes existed
    db.commit()
    rid = make_rotation(client, spotify, [])
    d = deck(client, rid, "suggested")
    assert set(d["missing_scopes"]) == {"user-top-read", "user-read-recently-played", "user-library-read"}
    assert d["items"] == []
    assert not [c for c in spotify.calls if c[0] in ("top", "recent", "liked")]
    assert client.get("/api/auth/me").json()["missing_scopes"]


def test_one_failing_source_does_not_break_the_deck(client, spotify, monkeypatch):
    from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService
    seed_listening(spotify)

    async def broken(*a, **k):
        raise SpotifyAPIError(500)
    monkeypatch.setattr(SpotifyService, "get_recently_played", staticmethod(broken))
    rid = make_rotation(client, spotify, [])
    got = set(ids(deck(client, rid, "suggested")))
    assert "recent1" not in got and "top1" in got


def test_add_suggestion_uses_cached_metadata(client, spotify):
    seed_listening(spotify)
    rid = make_rotation(client, spotify, [])
    deck(client, rid, "suggested")
    r = client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "favnew", "source": "suggested"})
    assert r.status_code == 201 and r.json()["title"] == "Song favnew"
    assert ("get_track", "favnew") not in spotify.calls
    assert "favnew" not in ids(deck(client, rid, "suggested"))


# ---------- search ----------

def test_search_flags_songs_in_rotation_and_pages(client, spotify):
    spotify.search_results["lorde"] = [track_object(f"s{i}") for i in range(15)]
    spotify.catalog["s3"] = track_object("s3")
    rid = make_rotation(client, spotify, [spotify_item("s1", 1)])
    r = client.get(f"/api/rotation/{rid}/restock/search", params={"q": "lorde"}).json()
    assert len(r["items"]) == 10 and r["next_offset"] == 10
    flags = {c["track_id"]: c["in_rotation"] for c in r["items"]}
    assert flags["s1"] is True and flags["s2"] is False
    r2 = client.get(f"/api/rotation/{rid}/restock/search", params={"q": "lorde", "offset": 10}).json()
    assert len(r2["items"]) == 5 and r2["next_offset"] is None
    # Unknown track: fetched from Spotify to validate it
    assert client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "s3", "source": "search"}).status_code == 201
    assert ("get_track", "s3") in spotify.calls
    assert client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "nope", "source": "search"}).status_code == 404


def test_restock_validation_and_ownership(client, spotify, db):
    rid = make_rotation(client, spotify, [])
    bad = client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "../x", "source": "search"})
    assert bad.status_code == 422
    assert client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "a", "source": "nope"}).status_code == 422
    assert client.get(f"/api/rotation/{rid}/restock/deck/nope").status_code == 422
    assert client.get("/api/rotation/999/restock/deck/picks").status_code == 404
