"""Listening history: pure rules, capture (app open, cron), turning it off, retention."""
from datetime import timedelta

from rest_api.clock import utcnow
from rest_api.database.models import ListeningGapDB, PlayEventDB, TopTrackDB, UserDB
from rest_api.services import listening_logic as logic
from rest_api.services import listening_service as listening

from helpers import add_plays, played_entry, track_object

# ---------- pure rules ----------

def test_parse_plays_skips_junk_and_sorts():
    entries = [
        played_entry("a", 5, "spotify:playlist:p1"),
        None,
        {"track": None, "played_at": "2026-11-01T00:00:00Z"},
        {"track": {**track_object("ep"), "type": "episode"}, "played_at": "2026-11-01T00:00:00Z"},
        {"track": {**track_object("loc"), "is_local": True}, "played_at": "2026-11-01T00:00:00Z"},
        played_entry("b", 10),
    ]
    plays = logic.parse_plays(entries)
    assert [p.track_id for p in plays] == ["b", "a"]  # oldest first
    assert plays[1].context_type == "playlist" and plays[1].context_uri == "spotify:playlist:p1"
    assert plays[0].song_key == "song b|artist a"


def test_gap_only_when_a_full_page_is_all_new():
    now = utcnow()
    cursor = now - timedelta(hours=10)
    full_new = [logic.Play("x", None, now - timedelta(minutes=i)) for i in range(50)]
    assert logic.detect_gap(full_new, cursor) == (cursor, now - timedelta(minutes=49))
    overlapping = [logic.Play("x", None, cursor - timedelta(minutes=1))] + full_new[:49]
    assert logic.detect_gap(overlapping, cursor) is None
    assert logic.detect_gap(full_new[:30], cursor) is None  # under 50: nothing was missed
    assert logic.detect_gap(full_new, None) is None  # the first capture


def test_window_and_confidence():
    assert logic.window_days(24) == 21  # daily: at least 3 weeks
    assert logic.window_days(30 * 24) == 60
    assert logic.window_days(365 * 24) == 90
    now = utcnow()
    start = now - timedelta(days=21)
    assert not logic.is_confident(None, [], start, now)
    assert not logic.is_confident(now - timedelta(days=10), [], start, now)  # too short
    assert logic.is_confident(now - timedelta(days=30), [], start, now)
    gap = (now - timedelta(days=10), now - timedelta(days=4))  # 6 of 21 days missing
    assert not logic.is_confident(now - timedelta(days=30), [gap], start, now)


# ---------- capture ----------

def _plays(db, user):
    return db.query(PlayEventDB).filter_by(user_id=user.id).order_by(PlayEventDB.played_at).all()


def test_capture_stores_dedupes_and_throttles(client, db, user, spotify):
    spotify.played = [played_entry("a", 5, "spotify:playlist:p1"), played_entry("b", 60)]
    assert client.post("/api/user/me/listening/capture").json() == {"added": 2}
    rows = _plays(db, user)
    assert [r.track_id for r in rows] == ["b", "a"]
    assert rows[1].context_uri == "spotify:playlist:p1" and rows[1].source == "api"
    assert user.listening_since == rows[0].played_at
    # Within 15 minutes: no Spotify call at all
    calls = len(spotify.calls)
    assert client.post("/api/user/me/listening/capture").json() == {"added": 0}
    assert len(spotify.calls) == calls
    # Later: only new plays are added
    user.listening_captured_at -= timedelta(minutes=20)
    db.commit()
    spotify.played = [played_entry("c", 1)] + spotify.played
    assert client.post("/api/user/me/listening/capture").json() == {"added": 1}
    assert len(_plays(db, user)) == 3


def test_capture_records_a_gap_when_plays_were_missed(client, db, user, spotify):
    spotify.played = [played_entry("old", 600)]
    client.post("/api/user/me/listening/capture")
    user.listening_captured_at -= timedelta(hours=1)
    db.commit()
    spotify.played = [played_entry(f"n{i}", i + 1) for i in range(50)]  # all newer than "old"
    client.post("/api/user/me/listening/capture")
    gap = db.query(ListeningGapDB).one()
    assert gap.gap_end > gap.gap_start


def test_top_tracks_refresh_daily(client, db, user, spotify):
    spotify.top[("tracks", "short_term")] = [track_object("t1"), track_object("t2")]
    client.post("/api/user/me/listening/capture")
    tops = db.query(TopTrackDB).filter_by(time_range="short_term").order_by(TopTrackDB.rank).all()
    assert [t.track_id for t in tops] == ["t1", "t2"]
    user.listening_captured_at -= timedelta(hours=1)
    db.commit()
    client.post("/api/user/me/listening/capture")
    assert sum(1 for c in spotify.calls if c[0] == "top") == 3  # once per range, not again today


def test_capture_skips_missing_scopes_and_spotify_failures(client, db, user, spotify):
    user.granted_scopes = "playlist-read-private"
    db.commit()
    spotify.played = [played_entry("a", 5)]
    assert client.post("/api/user/me/listening/capture").json() == {"added": 0}
    assert not any(c[0] in ("recent", "top") for c in spotify.calls)
    user.granted_scopes = "user-read-recently-played user-top-read"
    user.listening_captured_at = None
    spotify.fail = True
    db.commit()
    r = client.post("/api/user/me/listening/capture")
    assert r.status_code == 200 and r.json() == {"added": 0}


def test_turning_history_off_deletes_it_and_stops_capture(client, db, user, spotify):
    spotify.played = [played_entry("a", 5)]
    client.post("/api/user/me/listening/capture")
    assert client.get("/api/user/me/listening").json()["plays"] == 1
    r = client.put("/api/user/me/settings", json={"listening_enabled": False})
    assert r.json()["listening_enabled"] is False
    assert db.query(PlayEventDB).count() == 0 and db.query(TopTrackDB).count() == 0
    assert client.post("/api/user/me/listening/capture").json() == {"added": 0}
    status = client.get("/api/user/me/listening").json()
    assert status["enabled"] is False and status["plays"] == 0 and status["since"] is None
    client.put("/api/user/me/settings", json={"listening_enabled": True})
    assert client.post("/api/user/me/listening/capture").json() == {"added": 1}


def test_cron_captures_and_purges(client, db, user, spotify, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    spotify.played = [played_entry("a", 5)]
    add_plays(db, user, "ancient", 2, days_ago=(400, 420))
    r = client.get("/api/cron/auto-restock", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["listening"]["users"] == 1 and body["listening"]["plays"] == 1
    assert body["listening_purged"] == 2
    assert [p.track_id for p in _plays(db, user)] == ["a"]


def test_capture_all_isolates_failures(db, user, spotify, monkeypatch):
    other = UserDB(spotify_id="other", access_token="t", refresh_token="r",
                   token_expires_at=utcnow() + timedelta(hours=1), granted_scopes="user-read-recently-played")
    db.add(other)
    db.commit()
    calls = []

    async def flaky(db_, u, force=False):
        calls.append(u.id)
        if u.id == user.id:
            raise RuntimeError("boom")
        return 3

    monkeypatch.setattr(listening, "capture", flaky)
    import asyncio
    stats = asyncio.run(listening.capture_all(db))
    assert sorted(calls) == sorted([user.id, other.id])
    assert stats["users"] == 2 and stats["plays"] == 3


# ---------- awareness: queue, tracks, history, digest, restock ----------

def _busy_rotation(client, db, user, spotify, n=30):
    """A 30-day manual rotation, everything due, played a lot from its playlist:
    a00 heavily (6 plays), most others once, a27..a29 not at all."""
    from helpers import backdate_rotation, cover_history, make_rotation, spotify_item

    rot = make_rotation(client, spotify, [spotify_item(f"a{i:02}", 200 - i) for i in range(n)])
    backdate_rotation(db, rot["id"], 100)
    cover_history(db, user, 120)
    add_plays(db, user, "a00", 6, context_uri="spotify:playlist:p1")
    for i in range(1, n - 3):
        add_plays(db, user, f"a{i:02}", 1, days_ago=(2 + i, 3 + i), context_uri="spotify:playlist:p1")
    return rot["id"]


def _by_id(tracks):
    return {t["track_id"]: t for t in tracks}


def test_queue_tracks_show_listening(client, db, user, spotify):
    rid = _busy_rotation(client, db, user, spotify)
    db.add(TopTrackDB(user_id=user.id, time_range="short_term", rank=2, track_id="a10",
                      song_key="song a10|artist a", captured_at=utcnow()))
    db.commit()
    tracks = _by_id(client.get(f"/api/rotation/{rid}/queue", params={"all": True}).json()["tracks"])
    a00 = tracks["a00"]["listening"]
    assert a00["plays"] == 6 and a00["plays_here"] == 6 and a00["heavy"] and a00["window_days"] == 60
    assert tracks["a10"]["listening"]["top_rank"] == {"short_term": 2} and tracks["a10"]["listening"]["heavy"]
    assert tracks["a05"]["listening"]["plays"] == 1 and not tracks["a05"]["listening"]["heavy"]
    assert tracks["a29"]["listening"]["few_plays"] is True
    rotation = client.get(f"/api/rotation/{rid}", params={"sync": False}).json()
    assert rotation["listening"]["plays_here"] == 6 + 26 and rotation["listening"]["top_song"] == "Song a00"
    assert _by_id(client.get(f"/api/rotation/{rid}/tracks").json())["a00"]["listening"]["plays"] == 6


def test_few_plays_needs_enough_history_and_a_used_playlist(client, db, user, spotify):
    rid = _busy_rotation(client, db, user, spotify)
    user.listening_since = utcnow() - timedelta(days=20)  # history shorter than the 60-day window
    db.commit()
    tracks = _by_id(client.get(f"/api/rotation/{rid}/queue", params={"all": True}).json()["tracks"])
    assert tracks["a29"]["listening"] is None
    assert tracks["a00"]["listening"]["heavy"]  # "a lot" doesn't need full coverage
    # Enough history, but the playlist is barely played: still nothing said
    user.listening_since = utcnow() - timedelta(days=120)
    db.query(PlayEventDB).filter(PlayEventDB.track_id.notin_(["a00", "a01"])).delete(synchronize_session=False)
    db.commit()
    tracks = _by_id(client.get(f"/api/rotation/{rid}/queue", params={"all": True}).json()["tracks"])
    assert tracks["a29"]["listening"] is None


def test_history_shows_plays_before_and_since(client, db, user, spotify):
    from helpers import review

    rid = _busy_rotation(client, db, user, spotify)
    review(client, rid, "a00", "keep")
    review(client, rid, "a01", "remove")
    add_plays(db, user, "a01", 2, days_ago=(-0.01, -0.005))  # played after the removal
    events = client.get(f"/api/rotation/{rid}/history").json()
    kept = next(e for e in events if e["action"] == "keep")
    removed = next(e for e in events if e["action"] == "remove")
    assert kept["plays_before"] == 6 and kept["plays_window_hours"] == 60 * 24
    assert removed["plays_before"] == 1 and removed["plays_since"] == 2
    # No history that far back: nothing claimed
    user.listening_since = utcnow() - timedelta(days=1)
    db.commit()
    kept = next(e for e in client.get(f"/api/rotation/{rid}/history").json() if e["action"] == "keep")
    assert kept["plays_before"] is None and kept["plays_window_hours"] is None


def test_listening_digest(client, db, user, spotify):
    rid = _busy_rotation(client, db, user, spotify)
    add_plays(db, user, "a02", 1, days_ago=(0.1, 0.2), context_uri="spotify:album:x")
    body = client.get(f"/api/rotation/{rid}/listening", params={"days": 30}).json()
    assert body["since"]
    total_here = sum(d["plays_here"] for d in body["days"])
    total_elsewhere = sum(d["plays_elsewhere"] for d in body["days"])
    assert total_here == 6 + 26 and total_elsewhere == 1
    assert body["days"] == sorted(body["days"], key=lambda d: d["date"], reverse=True)
    assert any(s["track_id"] == "a00" for d in body["days"] for s in d["songs"])


def test_restock_cards_show_recent_plays(client, db, user, spotify):
    from helpers import review

    rid = _busy_rotation(client, db, user, spotify)
    review(client, rid, "a00", "remove")
    client.post(f"/api/rotation/{rid}/flush")
    deck = client.get(f"/api/rotation/{rid}/restock/deck/bring_back").json()
    a00 = next(c for c in deck["items"] if c["track_id"] == "a00")
    assert a00["listening"]["plays"] == 6 and a00["listening"]["window_days"] == 28


def test_restock_outcomes(client, db, user, spotify):
    from helpers import restock_action

    rid = _busy_rotation(client, db, user, spotify)
    spotify.catalog["new1"] = track_object("new1")
    spotify.catalog["new2"] = track_object("new2")
    assert restock_action(client, rid, "add", "new1", "search").status_code == 201
    assert restock_action(client, rid, "add", "new2", "suggested").status_code == 201
    add_plays(db, user, "new1", 2, days_ago=(-0.01, -0.005))
    body = client.get(f"/api/rotation/{rid}/restock/outcomes").json()
    assert body["enabled"] and body["added"] == 2 and body["played"] == 1
    by_source = {s["source"]: s for s in body["by_source"]}
    assert by_source["search"] == {"source": "search", "added": 1, "played": 1}
    assert by_source["suggested"]["played"] == 0
    assert {s["track_id"]: s["plays"] for s in body["songs"]} == {"new1": 2, "new2": 0}


def test_rediscover_deck(client, db, user, spotify):
    from helpers import restock_action

    rid = _busy_rotation(client, db, user, spotify)
    add_plays(db, user, "old1", 6, days_ago=(120, 200), title="Old One")  # a lot back then, not since
    add_plays(db, user, "old2", 6, days_ago=(120, 200), title="Old Two")
    add_plays(db, user, "old2", 3, days_ago=(1, 10), title="Old Two")  # ...but played lately
    add_plays(db, user, "old3", 2, days_ago=(120, 200), title="Old Three")  # not enough back then
    add_plays(db, user, "a05", 6, days_ago=(120, 200))  # already in this rotation
    db.query(PlayEventDB).filter_by(track_id="old1").update({"image_url": "img"})
    db.commit()
    deck = client.get(f"/api/rotation/{rid}/restock/deck/rediscover").json()
    assert [c["track_id"] for c in deck["items"]] == ["old1"]
    assert deck["items"][0]["reason"].startswith("You played this 6× back in ")
    # Adding uses the stored details (no Spotify lookup) and records the source
    assert restock_action(client, rid, "add", "old1", "rediscover").status_code == 201
    assert not any(c[0] == "get_track" for c in spotify.calls)
    # Too little history to know what's "lately": nothing offered
    user.listening_since = utcnow() - timedelta(days=30)
    db.commit()
    assert client.get(f"/api/rotation/{rid}/restock/deck/rediscover").json()["items"] == []
