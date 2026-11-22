"""End-to-end rotation loop through the API, with SQLite and a fake Spotify."""
from datetime import timedelta

from rest_api.clock import utcnow
from rest_api.database.models import RotationDB, RotationTrackDB
from tests.conftest import spotify_item


def make_rotation(client, spotify, items, interval=30, playlist_id="p1", **kw):
    spotify.add_playlist(playlist_id, items, **kw)
    r = client.post("/api/rotation/", json={"playlist_id": playlist_id, "interval_days": interval})
    assert r.status_code == 201, r.text
    return r.json()


def backdate_rotation(db, rotation_id, days):
    """Pretend the rotation was created `days` ago (so the grace period has run out)."""
    rot = db.get(RotationDB, rotation_id)
    rot.created_at = utcnow() - timedelta(days=days)
    db.commit()


def test_create_from_existing_imports_tracks_with_grace_period(client, spotify):
    body = make_rotation(client, spotify, [spotify_item("a", 400), spotify_item("b", 5)])
    assert body["name"] == "Mix"  # defaults to the playlist name
    assert body["active_count"] == 2
    assert body["due_count"] == 0  # old songs wait creation + N, not added_at + N


def test_cannot_rotate_playlist_you_dont_own(client, spotify):
    spotify.add_playlist("theirs", [], owner="someone-else")
    r = client.post("/api/rotation/", json={"playlist_id": "theirs"})
    assert r.status_code == 400


def test_collaborative_playlist_is_allowed(client, spotify):
    make_rotation(client, spotify, [], playlist_id="collab", owner="someone-else", collaborative=True)


def test_one_rotation_per_playlist(client, spotify):
    make_rotation(client, spotify, [])
    assert client.post("/api/rotation/", json={"playlist_id": "p1"}).status_code == 409


def test_missing_playlist_is_404(client, spotify):
    assert client.post("/api/rotation/", json={"playlist_id": "nope"}).status_code == 404


def test_create_from_scratch_creates_private_playlist(client, spotify):
    r = client.post("/api/rotation/", json={"name": "Fresh", "interval_days": 14})
    assert r.status_code == 201
    assert ("create", "Fresh") in spotify.calls
    assert r.json()["playlist_id"].startswith("new")


def test_from_scratch_requires_name(client, spotify):
    assert client.post("/api/rotation/", json={"interval_days": 14}).status_code == 422


def test_server_managed_fields_rejected(client, spotify):
    spotify.add_playlist("p1", [])
    r = client.post("/api/rotation/", json={"playlist_id": "p1", "owner_id": 999})
    assert r.status_code == 422


def test_queue_review_and_flush(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100), spotify_item("b", 100), spotify_item("c", 1)])
    backdate_rotation(db, rot["id"], 60)
    rid = rot["id"]

    queue = client.get(f"/api/rotation/{rid}/queue").json()
    assert [t["track_id"] for t in queue] == ["a", "b"]  # c isn't due yet

    keep = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"})
    assert keep.status_code == 200
    assert keep.json()["due_at"] > utcnow().isoformat()

    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": "b", "action": "remove"}).json()[
        "status"] == "pending_removal"
    assert ("remove", "p1", ("spotify:track:b",)) not in spotify.calls  # nothing sent per swipe

    flush = client.post(f"/api/rotation/{rid}/flush").json()
    assert flush == {"removed": 1, "pending": 0}
    assert ("remove", "p1", ("spotify:track:b",)) in spotify.calls
    assert [i["item"]["id"] for i in spotify.playlists["p1"]["items"]] == ["a", "c"]

    assert client.get(f"/api/rotation/{rid}/queue").json() == []
    history = client.get(f"/api/rotation/{rid}/history").json()
    assert [(h["action"], h["track"]["track_id"]) for h in history] == [("remove", "b"), ("keep", "a")]


def test_skip_leaves_song_due(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    backdate_rotation(db, rot["id"], 60)
    client.post(f"/api/rotation/{rot['id']}/review", json={"track_id": "a", "action": "skip"})
    assert [t["track_id"] for t in client.get(f"/api/rotation/{rot['id']}/queue").json()] == ["a"]


def test_undo_pending_removal(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "undo"}).json()[
        "status"] == "active"
    # Undo only applies to pending removals
    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "undo"}).status_code == 409
    assert client.post(f"/api/rotation/{rid}/flush").json()["removed"] == 0


def test_review_unknown_track_404_and_removed_track_409(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 1)])
    rid = rot["id"]
    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": "zzz", "action": "keep"}).status_code == 404
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"}).status_code == 409


def test_sync_flushes_pending_removals_first(client, spotify):
    rot = make_rotation(client, spotify, [spotify_item("a", 1), spotify_item("b", 1)])
    client.post(f"/api/rotation/{rot['id']}/review", json={"track_id": "a", "action": "remove"})
    summary = client.get(f"/api/rotation/{rot['id']}").json()  # sync=true by default
    assert summary["pending_removal_count"] == 0
    assert summary["active_count"] == 1
    assert ("remove", "p1", ("spotify:track:a",)) in spotify.calls


def test_sync_picks_up_external_changes(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 1), spotify_item("b", 1)])
    p = spotify.playlists["p1"]
    p["items"] = [spotify_item("b", 1), spotify_item("new", 0)]  # a removed in Spotify, new added
    spotify.touch("p1")

    tracks = {t["track_id"]: t for t in client.get(f"/api/rotation/{rot['id']}/tracks").json()}
    assert set(tracks) == {"a", "b"}  # /tracks doesn't sync
    client.get(f"/api/rotation/{rot['id']}")
    tracks = {t["track_id"] for t in client.get(f"/api/rotation/{rot['id']}/tracks").json()}
    assert tracks == {"b", "new"}
    row = db.query(RotationTrackDB).filter_by(track_id="a").one()
    assert (row.status, row.removed_by) == ("removed", "external")


def test_readded_track_is_reactivated_with_fresh_anchor(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    client.post(f"/api/rotation/{rid}/flush")
    spotify.playlists["p1"]["items"] = [spotify_item("a", 0)]
    spotify.touch("p1")
    client.get(f"/api/rotation/{rid}")
    row = db.query(RotationTrackDB).filter_by(track_id="a").one()
    assert row.status == "active" and row.removed_at is None and row.last_kept_at is None


def test_unchanged_snapshot_skips_item_fetch(client, spotify):
    rot = make_rotation(client, spotify, [spotify_item("a", 1)])
    before = [c for c in spotify.calls if c[0] == "get_items"]
    client.get(f"/api/rotation/{rot['id']}")
    assert [c for c in spotify.calls if c[0] == "get_items"] == before


def test_unparseable_response_does_not_wipe_rotation(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 1)])
    spotify.playlists["p1"]["items"] = [{"added_at": None, "is_local": False, "weird": {}}]
    spotify.touch("p1")
    client.get(f"/api/rotation/{rot['id']}")
    assert db.query(RotationTrackDB).filter_by(track_id="a").one().status == "active"


def test_spotify_failure_returns_stale_data_with_flag(client, spotify):
    rot = make_rotation(client, spotify, [spotify_item("a", 1)])
    spotify.fail = True
    r = client.get(f"/api/rotation/{rot['id']}")
    assert r.status_code == 200
    assert r.json()["sync_ok"] is False and r.json()["active_count"] == 1
    assert client.get(f"/api/rotation/{rot['id']}/queue").status_code == 200


def test_flush_failure_keeps_removals_pending(client, spotify):
    rot = make_rotation(client, spotify, [spotify_item("a", 1)])
    client.post(f"/api/rotation/{rot['id']}/review", json={"track_id": "a", "action": "remove"})
    spotify.fail = True
    assert client.post(f"/api/rotation/{rot['id']}/flush").status_code == 502
    spotify.fail = False
    assert client.post(f"/api/rotation/{rot['id']}/flush").json()["removed"] == 1


def test_update_and_delete(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 1)])
    r = client.put(f"/api/rotation/{rot['id']}", json={"interval_days": 7, "name": "Renamed"})
    assert (r.json()["interval_days"], r.json()["name"]) == (7, "Renamed")
    assert client.put(f"/api/rotation/{rot['id']}", json={"owner_id": 5}).status_code == 422
    assert client.delete(f"/api/rotation/{rot['id']}").status_code == 200
    assert db.query(RotationTrackDB).count() == 0  # cascade
    assert "p1" in spotify.playlists  # Spotify playlist untouched


def test_other_users_rotation_is_404(client, spotify, db):
    from rest_api.database.models import UserDB
    other = UserDB(spotify_id="other")
    db.add(other)
    db.commit()
    db.add(RotationDB(owner_id=other.id, playlist_id="x", name="theirs", interval_days=30, created_at=utcnow()))
    db.commit()
    rid = db.query(RotationDB).filter_by(name="theirs").one().id
    assert client.get(f"/api/rotation/{rid}").status_code == 404
    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"}).status_code == 404


def test_user_rotations_lists_due_counts(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100), spotify_item("b", 1)])
    backdate_rotation(db, rot["id"], 60)
    [summary] = client.get("/api/user/me/rotations").json()
    assert (summary["active_count"], summary["due_count"]) == (2, 1)
    assert summary["next_due_at"] is not None


def test_playlists_flag_rotatable_and_existing_rotation(client, spotify):
    rot = make_rotation(client, spotify, [])
    spotify.add_playlist("theirs", [], owner="else")
    playlists = {p["id"]: p for p in client.get("/api/spotify/playlists").json()}
    assert playlists["p1"]["rotatable"] and playlists["p1"]["rotation_id"] == rot["id"]
    assert not playlists["theirs"]["rotatable"] and playlists["theirs"]["rotation_id"] is None
