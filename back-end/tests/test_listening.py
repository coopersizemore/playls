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
