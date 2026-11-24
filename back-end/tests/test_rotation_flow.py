"""End-to-end rotation loop through the API, with SQLite and a fake Spotify."""
from datetime import timedelta

from rest_api.clock import utcnow
from rest_api.database.models import RotationDB, RotationTrackDB
from tests.conftest import spotify_item


def make_rotation(client, spotify, items, interval_days=30, playlist_id="p1", grace=True, **kw):
    spotify.add_playlist(playlist_id, items, **kw)
    r = client.post("/api/rotation/", json={
        "playlist_id": playlist_id, "interval_hours": interval_days * 24, "grace_period": grace,
    })
    assert r.status_code == 201, r.text
    return r.json()


def shift_events(db, days):
    """Move every review event `days` into the past (simulates a new day)."""
    from rest_api.database.models import ReviewEventDB
    for event in db.query(ReviewEventDB):
        event.created_at -= timedelta(days=days)
    db.commit()


def set_limit(db, limit):
    from rest_api.database.models import UserDB
    db.query(UserDB).one().review_limit = limit
    db.commit()


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
    r = client.post("/api/rotation/", json={"name": "Fresh", "interval_hours": 14 * 24})
    assert r.status_code == 201
    assert ("create", "Fresh") in spotify.calls
    assert r.json()["playlist_id"].startswith("new")


def test_from_scratch_requires_name(client, spotify):
    assert client.post("/api/rotation/", json={"interval_hours": 14}).status_code == 422


def test_server_managed_fields_rejected(client, spotify):
    spotify.add_playlist("p1", [])
    r = client.post("/api/rotation/", json={"playlist_id": "p1", "owner_id": 999})
    assert r.status_code == 422


def test_queue_review_and_flush(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100), spotify_item("b", 100), spotify_item("c", 1)])
    backdate_rotation(db, rot["id"], 60)
    rid = rot["id"]

    queue = client.get(f"/api/rotation/{rid}/queue").json()["tracks"]
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

    assert client.get(f"/api/rotation/{rid}/queue").json()["tracks"] == []
    history = client.get(f"/api/rotation/{rid}/history").json()
    assert [(h["action"], h["track"]["track_id"]) for h in history] == [("remove", "b"), ("keep", "a")]


def test_skip_keeps_song_due_but_holds_it_until_tomorrow(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    backdate_rotation(db, rot["id"], 60)
    client.post(f"/api/rotation/{rot['id']}/review", json={"track_id": "a", "action": "skip"})
    q = client.get(f"/api/rotation/{rot['id']}/queue").json()
    assert q["tracks"] == [] and q["due_count"] == 1
    # Next day: the skip is in the past, so the song is offered again
    shift_events(db, days=1)
    assert [t["track_id"] for t in client.get(f"/api/rotation/{rot['id']}/queue").json()["tracks"]] == ["a"]


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
    r = client.put(f"/api/rotation/{rot['id']}", json={"interval_hours": 12, "name": "Renamed", "grace_period": False})
    assert (r.json()["interval_hours"], r.json()["name"], r.json()["grace_period"]) == (12, "Renamed", False)
    assert client.put(f"/api/rotation/{rot['id']}", json={"owner_id": 5}).status_code == 422
    assert client.delete(f"/api/rotation/{rot['id']}").status_code == 200
    assert db.query(RotationTrackDB).count() == 0  # cascade
    assert "p1" in spotify.playlists  # Spotify playlist untouched


def test_other_users_rotation_is_404(client, spotify, db):
    from rest_api.database.models import UserDB
    other = UserDB(spotify_id="other")
    db.add(other)
    db.commit()
    db.add(RotationDB(owner_id=other.id, playlist_id="x", name="theirs", interval_hours=720, created_at=utcnow()))
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


def test_grace_period_off_makes_old_and_undated_songs_due_now(client, spotify):
    body = make_rotation(client, spotify, [spotify_item("old", 100), spotify_item("undated"), spotify_item("new", 1)],
                         grace=False)
    assert body["grace_period"] is False
    assert body["due_count"] == 2  # old (added 100 days ago) and undated; new isn't due for 29 days
    due = {t["track_id"] for t in client.get(f"/api/rotation/{body['id']}/queue").json()["tracks"]}
    assert due == {"old", "undated"}


def test_grace_period_defaults_on(client, spotify):
    spotify.add_playlist("p1", [spotify_item("old", 100)])
    body = client.post("/api/rotation/", json={"playlist_id": "p1"}).json()
    assert (body["grace_period"], body["interval_hours"], body["due_count"]) == (True, 720, 0)


def test_turning_grace_off_later_applies_retroactively(client, spotify):
    body = make_rotation(client, spotify, [spotify_item("old", 100)])
    assert body["due_count"] == 0
    r = client.put(f"/api/rotation/{body['id']}", json={"grace_period": False})
    assert r.json()["due_count"] == 1


def test_interval_bounds(client, spotify):
    spotify.add_playlist("p1", [])
    assert client.post("/api/rotation/", json={"playlist_id": "p1", "interval_hours": 0}).status_code == 422
    assert client.post("/api/rotation/", json={"playlist_id": "p1", "interval_hours": 365 * 24 + 1}).status_code == 422


def many_old_songs(n):
    # Distinct ages so "most overdue first" is well defined: s000 is the oldest
    return [spotify_item(f"s{i:03d}", 400 - i) for i in range(n)]


def test_queue_is_capped_at_daily_limit_most_overdue_first(client, spotify, db):
    set_limit(db, 20)
    rot = make_rotation(client, spotify, many_old_songs(100), grace=False)
    q = client.get(f"/api/rotation/{rot['id']}/queue").json()
    assert [t["track_id"] for t in q["tracks"]] == [f"s{i:03d}" for i in range(20)]
    assert (q["due_count"], q["daily_limit"], q["remaining_after_batch"], q["limit_reached"]) == (100, 20, 80, True)


def test_default_limit_is_50(client, spotify, db):
    rot = make_rotation(client, spotify, many_old_songs(60), grace=False)
    assert len(client.get(f"/api/rotation/{rot['id']}/queue").json()["tracks"]) == 50


def test_reviews_use_up_todays_allowance_and_reset_tomorrow(client, spotify, db):
    set_limit(db, 5)
    rot = make_rotation(client, spotify, many_old_songs(12), grace=False)
    rid = rot["id"]
    for t in client.get(f"/api/rotation/{rid}/queue").json()["tracks"][:3]:
        client.post(f"/api/rotation/{rid}/review", json={"track_id": t["track_id"], "action": "keep"})
    q = client.get(f"/api/rotation/{rid}/queue").json()
    assert (len(q["tracks"]), q["reviewed_today"]) == (2, 3)  # reload mid-batch: the rest of today's 5

    for t in q["tracks"]:
        client.post(f"/api/rotation/{rid}/review", json={"track_id": t["track_id"], "action": "keep"})
    q = client.get(f"/api/rotation/{rid}/queue").json()
    assert q["tracks"] == [] and q["limit_reached"] and q["remaining_after_batch"] == 7

    shift_events(db, days=1)
    q = client.get(f"/api/rotation/{rid}/queue").json()
    assert (len(q["tracks"]), q["reviewed_today"]) == (5, 0)


def test_review_more_serves_another_full_batch(client, spotify, db):
    set_limit(db, 5)
    rot = make_rotation(client, spotify, many_old_songs(12), grace=False)
    rid = rot["id"]
    for t in client.get(f"/api/rotation/{rid}/queue").json()["tracks"]:
        client.post(f"/api/rotation/{rid}/review", json={"track_id": t["track_id"], "action": "remove"})
    more = client.get(f"/api/rotation/{rid}/queue", params={"more": True}).json()
    assert len(more["tracks"]) == 5 and not more["limit_reached"] and more["remaining_after_batch"] == 2


def test_undo_refunds_allowance(client, spotify, db):
    set_limit(db, 2)
    rot = make_rotation(client, spotify, many_old_songs(5), grace=False)
    rid = rot["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "s000", "action": "remove"})
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "s000", "action": "undo"})
    q = client.get(f"/api/rotation/{rid}/queue").json()
    assert (q["reviewed_today"], len(q["tracks"])) == (0, 2)


def test_no_limit_serves_everything(client, spotify, db):
    set_limit(db, None)
    rot = make_rotation(client, spotify, many_old_songs(120), grace=False)
    q = client.get(f"/api/rotation/{rot['id']}/queue").json()
    assert (len(q["tracks"]), q["daily_limit"], q["limit_reached"]) == (120, None, False)


def test_summary_reports_ready_today(client, spotify, db):
    set_limit(db, 20)
    make_rotation(client, spotify, many_old_songs(100), grace=False)
    [summary] = client.get("/api/user/me/rotations").json()
    assert (summary["due_count"], summary["ready_today"], summary["daily_limit"]) == (100, 20, 20)


def test_day_boundary_follows_client_timezone(client, spotify, db):
    """An event 3 hours ago counts as 'today' only if local midnight was more than 3 hours ago."""
    from rest_api.clock import utcnow
    from rest_api.database.models import ReviewEventDB
    set_limit(db, 1)
    rot = make_rotation(client, spotify, many_old_songs(3), grace=False)
    rid = rot["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "s000", "action": "keep"})
    event = db.query(ReviewEventDB).one()
    event.created_at = utcnow() - timedelta(hours=3)
    db.commit()
    now = utcnow()
    # Pick an offset whose local midnight was 1 hour ago -> the event was "yesterday"
    offset_yesterday = (now.hour * 60 + now.minute) - 60
    # ...and one whose local midnight was 5 hours ago -> the event was "today"
    offset_today = (now.hour * 60 + now.minute) - 300
    clamp = lambda m: max(-840, min(840, m))
    if clamp(offset_yesterday) == offset_yesterday:
        q = client.get(f"/api/rotation/{rid}/queue", params={"tz_offset": offset_yesterday}).json()
        assert q["reviewed_today"] == 0
    if clamp(offset_today) == offset_today:
        q = client.get(f"/api/rotation/{rid}/queue", params={"tz_offset": offset_today}).json()
        assert q["reviewed_today"] == 1


def test_settings_roundtrip_and_validation(client):
    assert client.get("/api/user/me/settings").json() == {"review_limit": 50}
    assert client.put("/api/user/me/settings", json={"review_limit": 20}).json() == {"review_limit": 20}
    assert client.put("/api/user/me/settings", json={"review_limit": None}).json() == {"review_limit": None}
    assert client.get("/api/user/me/settings").json() == {"review_limit": None}
    for bad in (0, 1001, "lots"):
        assert client.put("/api/user/me/settings", json={"review_limit": bad}).status_code == 422
    assert client.put("/api/user/me/settings", json={}).status_code == 422


def test_rotation_carries_playlist_cover_and_refreshes_it(client, spotify):
    spotify.add_playlist("p1", [spotify_item("a", 1)])
    spotify.playlists["p1"]["images"] = [{"url": "cover-640", "width": 640}, {"url": "cover-300", "width": 300}]
    body = client.post("/api/rotation/", json={"playlist_id": "p1"}).json()
    assert body["image_url"] == "cover-300"
    # Spotify regenerates mosaic covers when the contents change; sync picks it up
    spotify.playlists["p1"]["images"] = [{"url": "new-cover", "width": None}]
    assert client.get(f"/api/rotation/{body['id']}").json()["image_url"] == "new-cover"
    [summary] = client.get("/api/user/me/rotations").json()
    assert summary["image_url"] == "new-cover"


def test_new_empty_playlist_has_no_cover(client, spotify):
    body = client.post("/api/rotation/", json={"name": "Fresh"}).json()
    assert body["image_url"] is None


def test_undo_keep_restores_previous_due_date(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    backdate_rotation(db, rid, 60)
    before = client.get(f"/api/rotation/{rid}/tracks").json()[0]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"})
    r = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "undo"})
    assert r.status_code == 200
    assert (r.json()["last_kept_at"], r.json()["due_at"]) == (before["last_kept_at"], before["due_at"])
    # Due again, and the undone keep no longer counts toward today's limit or shows in History
    q = client.get(f"/api/rotation/{rid}/queue").json()
    assert [t["track_id"] for t in q["tracks"]] == ["a"] and q["reviewed_today"] == 0
    assert client.get(f"/api/rotation/{rid}/history").json() == []


def test_undo_second_keep_restores_first_keep(client, spotify, db):
    from rest_api.database.models import ReviewEventDB
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    first = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"}).json()
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"})
    r = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "undo"}).json()
    assert r["last_kept_at"] == first["last_kept_at"]
    assert db.query(ReviewEventDB).count() == 1


def test_undo_skip_releases_the_hold(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    backdate_rotation(db, rid, 60)
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "skip"})
    assert client.get(f"/api/rotation/{rid}/queue").json()["tracks"] == []  # held until tomorrow
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "undo"})
    assert [t["track_id"] for t in client.get(f"/api/rotation/{rid}/queue").json()["tracks"]] == ["a"]


def test_undo_removal_after_flush_is_refused_with_guidance(client, spotify):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "remove"})
    client.post(f"/api/rotation/{rid}/flush")
    r = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "undo"})
    assert r.status_code == 409 and "Add it back" in r.json()["detail"]


def test_new_playlist_gets_empty_description_not_null(monkeypatch):
    """Spotify can show "null" for playlists created without a description; always send ""."""
    import asyncio
    from rest_api.services.spotify.spotify_service import SpotifyService
    sent = {}

    async def capture(endpoint, user, db, method="GET", data=None, params=None):
        sent.update(endpoint=endpoint, **(data or {}))
        return {"id": "made"}
    monkeypatch.setattr(SpotifyService, "make_spotify_request", staticmethod(capture))
    asyncio.run(SpotifyService.create_playlist("Fresh", None, None, description=None))
    assert (sent["endpoint"], sent["description"], sent["public"]) == ("/me/playlists", "", False)
    asyncio.run(SpotifyService.create_playlist("Fresh", None, None, description="Road trip"))
    assert sent["description"] == "Road trip"


def unplayable_item(track_id, days):
    entry = spotify_item(track_id, days)
    entry["item"]["is_playable"] = False
    entry["item"]["restrictions"] = {"reason": "market"}
    return entry


def test_review_all_songs_ignores_limit_and_due_dates(client, spotify, db):
    set_limit(db, 1)
    rot = make_rotation(client, spotify, [spotify_item("old", 100), spotify_item("new", 1)])  # grace: none due
    rid = rot["id"]
    assert client.get(f"/api/rotation/{rid}/queue").json()["tracks"] == []
    q = client.get(f"/api/rotation/{rid}/queue", params={"all": True}).json()
    assert {t["track_id"] for t in q["tracks"]} == {"old", "new"} and q["daily_limit"] is None


def test_reset_due_dates(client, spotify, db):
    from rest_api.database.models import ReviewEventDB
    rot = make_rotation(client, spotify, [spotify_item("a", 100), spotify_item("b", 100)], grace=False)
    rid = rot["id"]
    assert rot["due_count"] == 2
    r = client.post(f"/api/rotation/{rid}/reset-due")
    assert r.status_code == 200 and r.json()["due_count"] == 0
    assert r.json()["next_due_at"] > utcnow().isoformat()
    assert db.query(ReviewEventDB).count() == 0  # not recorded as keeps


def test_find_and_remove_unplayable_songs(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("ok", 10), unplayable_item("gone", 10)])
    rid = rot["id"]
    preview = client.get(f"/api/rotation/{rid}/unplayable").json()
    assert [t["track_id"] for t in preview["tracks"]] == ["gone"] and preview["tracks"][0]["is_playable"] is False
    r = client.post(f"/api/rotation/{rid}/remove-unplayable").json()
    assert r == {"removed": 1, "flushed": True}
    assert ("remove", "p1", ("spotify:track:gone",)) in spotify.calls
    assert [i["item"]["id"] for i in spotify.playlists["p1"]["items"]] == ["ok"]
    assert db.query(RotationTrackDB).filter_by(track_id="gone").one().status == "removed"
    # Unavailable songs aren't offered back
    assert client.get(f"/api/rotation/{rid}/restock/deck/bring_back").json()["items"] == []
    # Not counted as reviews
    assert client.get(f"/api/rotation/{rid}/queue").json()["reviewed_today"] == 0


def test_availability_refreshes_even_without_playlist_change(client, spotify, db):
    rot = make_rotation(client, spotify, [spotify_item("a", 10)])
    rid = rot["id"]
    # Spotify pulls the track without the playlist (snapshot) changing
    spotify.playlists["p1"]["items"] = [unplayable_item("a", 10)]
    client.get(f"/api/rotation/{rid}")  # normal sync: snapshot unchanged, not re-read
    assert db.query(RotationTrackDB).filter_by(track_id="a").one().is_playable is True
    assert [t["track_id"] for t in client.get(f"/api/rotation/{rid}/unplayable").json()["tracks"]] == ["a"]


def test_remove_unplayable_when_spotify_down_stays_pending(client, spotify, db):
    rot = make_rotation(client, spotify, [unplayable_item("gone", 10)])
    rid = rot["id"]
    spotify.fail = True
    assert client.post(f"/api/rotation/{rid}/remove-unplayable").json() == {"removed": 1, "flushed": False}
    assert db.query(RotationTrackDB).filter_by(track_id="gone").one().status == "pending_removal"


def test_super_keep_comes_due_at_three_intervals_and_undoes(client, spotify, db):
    from datetime import datetime
    rot = make_rotation(client, spotify, [spotify_item("a", 100), spotify_item("b", 100)], grace=False)
    rid = rot["id"]
    keep = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"}).json()
    sk = client.post(f"/api/rotation/{rid}/review", json={"track_id": "b", "action": "super_keep"}).json()
    gap = lambda t: datetime.fromisoformat(t["due_at"]) - datetime.fromisoformat(t["last_kept_at"])
    assert gap(keep) == timedelta(days=30) and gap(sk) == timedelta(days=90)
    assert sk["keep_multiplier"] == 3
    # Counts toward the daily tally and shows in History
    q = client.get(f"/api/rotation/{rid}/queue").json()
    assert q["reviewed_today"] == 2
    assert [h["action"] for h in client.get(f"/api/rotation/{rid}/history").json()] == ["super_keep", "keep"]
    # Undo restores the previous state
    undone = client.post(f"/api/rotation/{rid}/review", json={"track_id": "b", "action": "undo"}).json()
    assert (undone["last_kept_at"], undone["keep_multiplier"]) == (None, 1)


def test_plain_keep_after_super_keep_resets_multiplier(client, spotify):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "super_keep"})
    r = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "keep"}).json()
    assert r["keep_multiplier"] == 1
    undone = client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "undo"}).json()
    assert undone["keep_multiplier"] == 3  # back to the super keep


def test_reset_due_clears_super_keep(client, spotify):
    rot = make_rotation(client, spotify, [spotify_item("a", 100)])
    rid = rot["id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": "super_keep"})
    client.post(f"/api/rotation/{rid}/reset-due")
    assert client.get(f"/api/rotation/{rid}/tracks").json()[0]["keep_multiplier"] == 1


def test_changing_a_decision_replaces_it(client, spotify, db):
    """Going back in Review and picking a different action = undo the old one, apply the new one."""
    rot = make_rotation(client, spotify, [spotify_item("a", 100)], grace=False)
    rid = rot["id"]
    review = lambda action: client.post(f"/api/rotation/{rid}/review", json={"track_id": "a", "action": action})
    assert review("keep").status_code == 200
    assert review("undo").status_code == 200 and review("remove").json()["status"] == "pending_removal"
    assert review("undo").status_code == 200 and review("skip").status_code == 200
    assert [h["action"] for h in client.get(f"/api/rotation/{rid}/history").json()] == ["skip"]
    assert client.get(f"/api/rotation/{rid}/queue").json()["reviewed_today"] == 1
    assert client.get(f"/api/rotation/{rid}/tracks").json()[0]["status"] == "active"
