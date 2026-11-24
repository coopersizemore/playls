"""Liked Songs rotations: creation, the fingerprint sync and its guards, unlike/like writes."""
import asyncio

import pytest
from sqlalchemy.exc import IntegrityError

from rest_api.clock import utcnow
from rest_api.database.models import RotationDB, RotationTrackDB
from rest_api.database.models.rotation import LIKED_SONGS
from rest_api.services import sync_service
from rest_api.services.db import rotation_service
from rest_api.services.spotify.spotify_service import SpotifyService

from helpers import (
    count_calls,
    grant_library_write,
    liked_entry,
    make_liked_rotation,
    restock_action,
    review,
    spotify_item,
    track_object,
)


def rows(db, rid):
    db.expire_all()
    return {t.track_id: t for t in db.query(RotationTrackDB).filter_by(rotation_id=rid)}


def sync(client, rid):
    r = client.get(f"/api/rotation/{rid}")
    assert r.status_code == 200, r.text
    return r.json()


def liked_ids(spotify):
    return [t["id"] for t, _ in spotify.liked]


# ---------- creation ----------

def test_create_imports_liked_songs(client, spotify, db, user):
    rotation = make_liked_rotation(client, spotify, db, user, n=5)
    assert rotation["is_liked"] is True
    assert rotation["playlist_id"] == LIKED_SONGS
    assert rotation["name"] == "Liked Songs"
    assert rotation["active_count"] == 5
    assert count_calls(spotify, "get_playlist") == 0  # never treated as a playlist
    added = rows(db, rotation["id"])["l0"].added_at
    assert added is not None and (utcnow() - added).days == 10  # the like date


def test_create_needs_the_library_write_scope(client, spotify, user):
    spotify.liked[:] = [liked_entry("l0")]
    r = client.post("/api/rotation/", json={"liked_songs": True})
    assert r.status_code == 403
    assert "Reconnect" in r.json()["detail"]
    assert client.get("/api/user/me/rotations?sync=false").json() == []


def test_existing_users_arent_asked_to_reconnect_for_it(client, user):
    # The new scope is requested on login but isn't part of /auth/me's reconnect prompt
    assert "user-library-modify" not in client.get("/api/auth/me").json()["missing_scopes"]


def test_only_one_liked_songs_rotation(client, spotify, db, user):
    make_liked_rotation(client, spotify, db, user)
    assert client.post("/api/rotation/", json={"liked_songs": True}).status_code == 409


def test_too_many_liked_songs_is_refused(client, spotify, db, user, monkeypatch):
    monkeypatch.setattr(rotation_service, "MAX_LIKED_SONGS", 3)
    grant_library_write(db, user)
    spotify.liked[:] = [liked_entry(f"l{i}") for i in range(4)]
    r = client.post("/api/rotation/", json={"liked_songs": True})
    assert r.status_code == 400


@pytest.mark.parametrize("body", [
    {"liked_songs": True, "kind": "auto"},
    {"liked_songs": True, "playlist_id": "p1"},
])
def test_invalid_liked_songs_bodies(client, body):
    assert client.post("/api/rotation/", json=body).status_code == 422


def test_db_refuses_an_auto_liked_rotation(db, user):
    db.add(RotationDB(owner_id=user.id, playlist_id=LIKED_SONGS, name="x", kind="auto",
                      target_size=50, rotate_percent=20, created_at=utcnow()))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_playlist_rotations_still_work_alongside(client, spotify, db, user):
    make_liked_rotation(client, spotify, db, user)
    spotify.add_playlist("p1", [spotify_item("a", 5)])
    r = client.post("/api/rotation/", json={"playlist_id": "p1"})
    assert r.status_code == 201
    assert r.json()["is_liked"] is False


# ---------- sync ----------

def test_unchanged_library_skips_the_full_read(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    before = count_calls(spotify, "liked_all")
    sync(client, rid)
    assert count_calls(spotify, "liked_all") == before  # one page read, no full read
    assert count_calls(spotify, "liked_page") >= 1


def test_like_in_spotify_is_picked_up(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    spotify.liked.insert(0, liked_entry("new", added_days_ago=0))
    assert sync(client, rid)["active_count"] == 6
    assert rows(db, rid)["new"].status == "active"


def test_unlike_in_spotify_marks_it_removed(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    del spotify.liked[3]  # l3, not on the "first page" edge
    assert sync(client, rid)["active_count"] == 4
    row = rows(db, rid)["l3"]
    assert row.status == "removed" and row.removed_by == "external"


def test_like_and_unlike_together_are_both_seen(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    del spotify.liked[4]
    spotify.liked.insert(0, liked_entry("new", added_days_ago=0))  # total unchanged
    sync(client, rid)
    r = rows(db, rid)
    assert r["l4"].status == "removed" and r["new"].status == "active"


def test_first_sync_of_the_day_reads_everything(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    rotation = db.get(RotationDB, rid)
    rotation.snapshot_id = rotation.snapshot_id.replace(utcnow().strftime("%Y%m%d"), "20000101")
    db.commit()
    before = count_calls(spotify, "liked_all")
    sync(client, rid)
    assert count_calls(spotify, "liked_all") == before + 1


def test_fingerprint_uses_linked_from():
    page = {"total": 1, "items": [{"track": {"id": "relinked", "linked_from": {"id": "orig"}}}]}
    same = {"total": 1, "items": [{"track": {"id": "orig"}}]}
    assert sync_service.library_fingerprint(page) == sync_service.library_fingerprint(same)
    assert sync_service.library_fingerprint({"items": []}) is None


# ---------- guards ----------

def test_change_during_read_marks_nothing_removed(client, spotify, db, user, monkeypatch):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    real = SpotifyService.get_all_saved_tracks

    async def shifted_read(u, d, first=None):
        # A like lands mid-read: the read misses l4 (shifted onto a page already read)
        entries, total = await real(u, d, first)
        spotify.liked.insert(0, liked_entry("mid", added_days_ago=0))
        return [e for e in entries if e["track"]["id"] != "l4"], total - 1

    monkeypatch.setattr(SpotifyService, "get_all_saved_tracks", staticmethod(shifted_read))
    del spotify.liked[0]  # a real change, so the fingerprint differs and a full read runs
    sync(client, rid)
    r = rows(db, rid)
    assert r["l4"].status == "active"  # not wrongly removed
    assert r["l0"].status == "active"  # removals not applied from an untrusted read
    monkeypatch.setattr(SpotifyService, "get_all_saved_tracks", staticmethod(real))
    sync(client, rid)  # the next sync reads again and applies everything
    r = rows(db, rid)
    assert r["l0"].status == "removed" and r["l4"].status == "active" and r["mid"].status == "active"


def test_short_read_marks_nothing_removed(client, spotify, db, user, monkeypatch):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    real = SpotifyService.get_all_saved_tracks

    async def short_read(u, d, first=None):
        entries, total = await real(u, d, first)
        return entries[:-1], total  # one item missing, total says otherwise

    monkeypatch.setattr(SpotifyService, "get_all_saved_tracks", staticmethod(short_read))
    spotify.liked.insert(0, liked_entry("new", added_days_ago=0))
    sync(client, rid)
    r = rows(db, rid)
    assert all(row.status == "active" for row in r.values())
    assert "new" in r  # additions still applied


def test_mass_removal_is_distrusted(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user, n=40)["id"]
    del spotify.liked[10:30]  # 20 of 40 gone at once
    sync(client, rid)
    assert sum(1 for t in rows(db, rid).values() if t.status == "active") == 40


def test_small_removals_still_apply_in_big_libraries(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user, n=40)["id"]
    del spotify.liked[10:15]
    sync(client, rid)
    assert sum(1 for t in rows(db, rid).values() if t.status == "active") == 35


def test_unparseable_read_marks_nothing_removed(client, spotify, db, user, monkeypatch):
    rid = make_liked_rotation(client, spotify, db, user)["id"]

    async def junk(u, d, first=None):
        return [{"weird": True}] * 5, 5

    monkeypatch.setattr(SpotifyService, "get_all_saved_tracks", staticmethod(junk))
    spotify.liked.insert(0, liked_entry("new", added_days_ago=0))
    sync(client, rid)
    assert all(row.status == "active" for row in rows(db, rid).values())


# ---------- writes ----------

def test_review_remove_unlikes_on_flush(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user, grace=False)["id"]
    assert review(client, rid, "l2", "remove").status_code == 200
    assert "l2" in liked_ids(spotify)  # batched until the flush
    assert client.post(f"/api/rotation/{rid}/flush").json()["removed"] == 1
    assert ("unlike", ("spotify:track:l2",)) in spotify.calls
    assert "l2" not in liked_ids(spotify)
    row = rows(db, rid)["l2"]
    assert row.status == "removed" and row.removed_by == "user"
    assert db.get(RotationDB, rid).snapshot_id is None  # nothing adopted; next sync re-reads
    before = count_calls(spotify, "liked_all")
    assert sync(client, rid)["active_count"] == 4
    assert count_calls(spotify, "liked_all") == before + 1


def test_pending_unlike_can_be_undone(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user, grace=False)["id"]
    review(client, rid, "l2", "remove")
    assert review(client, rid, "l2", "undo").status_code == 200
    client.post(f"/api/rotation/{rid}/flush")
    assert count_calls(spotify, "unlike") == 0
    assert "l2" in liked_ids(spotify)


def test_failed_unlike_stays_pending(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user, grace=False)["id"]
    review(client, rid, "l2", "remove")
    spotify.fail = True
    sync(client, rid)  # sync fails (sync_ok false) but doesn't lose the decision
    spotify.fail = False
    assert rows(db, rid)["l2"].status == "pending_removal"
    sync(client, rid)
    assert "l2" not in liked_ids(spotify)


def test_restock_add_likes_and_undo_unlikes(client, spotify, db, user):
    rid = make_liked_rotation(client, spotify, db, user)["id"]
    spotify.catalog["n1"] = track_object("n1")
    assert restock_action(client, rid, "add", "n1", "search").status_code == 201
    assert ("like", ("spotify:track:n1",)) in spotify.calls
    assert liked_ids(spotify)[0] == "n1"
    assert count_calls(spotify, "add") == 0  # no playlist add
    assert restock_action(client, rid, "undo", "n1", "search").json() == {"undone": "add"}
    assert "n1" not in liked_ids(spotify)
    assert sync(client, rid)["active_count"] == 5


def test_library_writes_use_query_uris_in_batches_of_40(db, user, monkeypatch):
    sent = []

    async def fake_request(endpoint, u, d, method="GET", data=None, params=None):
        sent.append((method, endpoint, params, data))
        return {}

    monkeypatch.setattr(SpotifyService, "make_spotify_request", staticmethod(fake_request))
    uris = [f"spotify:track:t{i}" for i in range(85)]
    asyncio.run(SpotifyService.remove_from_library(uris, user, db))
    asyncio.run(SpotifyService.save_to_library(uris[:2], user, db))
    assert [(m, e) for m, e, _, _ in sent] == [("DELETE", "/me/library")] * 3 + [("PUT", "/me/library")]
    assert [len(p["uris"].split(",")) for _, _, p, _ in sent] == [40, 40, 5, 2]
    assert all(d is None for *_, d in sent)
