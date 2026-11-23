"""Auto rotations: pure rules, then end to end (create + fill, rotate out, restock, cron)."""
import random
from datetime import timedelta
from types import SimpleNamespace

import pytest

from rest_api.clock import utcnow
from rest_api.database.models import CuratedPickDB, ReviewEventDB, RotationDB, RotationTrackDB
from rest_api.services import auto_rotation_logic as auto
from tests.conftest import track_object


# ---------- pure rules ----------

def _rot(**kw):
    now = utcnow()
    base = dict(target_size=50, rotate_percent=20, interval_hours=168, created_at=now - timedelta(days=8),
                last_rotated_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _track(i, added_days, kept_days=None, mult=1, playable=True):
    now = utcnow()
    return SimpleNamespace(
        id=i, title=f"t{i:03}", added_at=now - timedelta(days=added_days), is_playable=playable,
        last_kept_at=None if kept_days is None else now - timedelta(days=kept_days), keep_multiplier=mult,
    )


def test_rotate_out_count_includes_excess():
    assert auto.per_rotation(50, 20) == 10
    assert auto.rotate_out_count(50, 20, 50) == 10
    assert auto.rotate_out_count(50, 20, 55) == 15  # 5 over target leave too
    assert auto.rotate_out_count(30, 5, 30) == 2
    assert auto.rotate_out_count(50, 20, 4) == 4


def test_leaving_order_oldest_first_keeps_slow_the_clock_and_protect():
    rotation = _rot(target_size=5, rotate_percent=40)  # 2 leave per rotation
    tracks = [
        _track(1, 100),                 # oldest
        _track(2, 90, kept_days=30),    # kept before the last period: age 30
        _track(3, 90, kept_days=60, mult=3),  # super kept 60 days ago: effective age 20
        _track(4, 40),
        _track(5, 200, kept_days=2),    # kept this period: protected
        _track(6, 1, playable=False),   # unavailable leaves first
    ]
    leaving = auto.choose_rotate_out(tracks, rotation, utcnow())
    # 2 + 1 over the target = 3
    assert [t.id for t in leaving] == [6, 1, 4]
    order = [t.id for t in auto.rotate_out_order(tracks, rotation, utcnow())]
    assert order[-1] == 5  # protected last
    assert order.index(2) < order.index(3)  # the super keep ages slower


def test_leaving_schedule_groups_by_rotation():
    rotation = _rot(target_size=4, rotate_percent=50, created_at=utcnow() - timedelta(days=1))
    tracks = [_track(i, 10 * i) for i in range(1, 5)]
    schedule = auto.leaving_schedule(tracks, rotation, utcnow())
    nxt = auto.next_rotation_at(rotation)
    assert schedule[4] == schedule[3] == nxt  # the two oldest leave next
    assert schedule[2] == schedule[1] == nxt + timedelta(days=7)


def test_allocate_spills_shortfalls():
    rng = random.Random(1)
    for slots in (1, 6, 30, 200):
        counts = auto.allocate(slots, 3, 10, 1000, rng)
        assert sum(counts.values()) == slots
        assert counts["picks"] <= 3 and counts["bring_back"] <= 10
    # For you can't cover it: bring back and picks fill in
    assert auto.allocate(10, 2, 5, 1, rng) == {"picks": 2, "bring_back": 5, "suggested": 1}


def test_cooldown():
    now = utcnow()
    assert not auto.cooled_down(now - timedelta(days=27), now)
    assert auto.cooled_down(now - timedelta(days=29), now)


# ---------- end to end ----------

def stock_signals(spotify, n, prefix="s"):
    tracks = [track_object(f"{prefix}{i:03}", artists=((f"Artist{i}", f"ar{i}"),)) for i in range(n)]
    for t in tracks:
        spotify.catalog[t["id"]] = t
    spotify.top[("tracks", "short_term")] = tracks[:50]
    spotify.top[("tracks", "medium_term")] = tracks[50:100]
    spotify.top[("tracks", "long_term")] = tracks[100:150]
    return tracks


def create_auto(client, **body):
    r = client.post("/api/rotation/", json={"kind": "auto", "name": "Fresh", **body})
    assert r.status_code == 201, r.text
    return r.json()


def active_rows(db, rid):
    return db.query(RotationTrackDB).filter_by(rotation_id=rid, status="active").all()


def make_due(db, rid, days=8):
    rotation = db.get(RotationDB, rid)
    rotation.created_at -= timedelta(days=days)
    if rotation.last_rotated_at:
        rotation.last_rotated_at -= timedelta(days=days)
    db.commit()


def test_create_auto_fills_to_target_with_defaults(client, spotify, db):
    stock_signals(spotify, 80)
    summary = create_auto(client, target_size=30)
    assert summary["kind"] == "auto"
    assert summary["target_size"] == 30 and summary["rotate_percent"] == 20
    assert summary["interval_hours"] == 168  # weekly by default
    assert summary["active_count"] == 30
    playlist = spotify.playlists[summary["playlist_id"]]
    assert len(playlist["items"]) == 30
    assert summary["reviewed_today"] == 0  # system events don't use the daily limit
    events = db.query(ReviewEventDB).filter_by(action="auto_added").count()
    assert events == 30
    history = client.get(f"/api/rotation/{summary['id']}/history").json()
    assert {e["action"] for e in history} == {"auto_added"}


def test_create_auto_defaults_to_50_and_reports_short_pool(client, spotify, db):
    stock_signals(spotify, 20)
    summary = create_auto(client)
    assert summary["target_size"] == 50
    assert summary["active_count"] == 20  # filled as far as it could


def test_auto_validation(client, spotify):
    spotify.add_playlist("p1", [])
    assert client.post("/api/rotation/", json={"kind": "auto", "playlist_id": "p1", "name": "x"}).status_code == 422
    assert client.post("/api/rotation/", json={"name": "x", "target_size": 50}).status_code == 422
    assert client.post("/api/rotation/", json={"kind": "auto", "name": "x", "target_size": 40}).status_code == 422


def test_rotation_swaps_oldest_out_and_restocks(client, spotify, db):
    stock_signals(spotify, 80)
    rid = create_auto(client, target_size=30)["id"]
    rows = sorted(active_rows(db, rid), key=lambda r: r.track_id)
    for i, row in enumerate(rows):
        row.added_at = utcnow() - timedelta(days=100 - i)  # rows[0] is oldest
    db.commit()
    # Keep the oldest song during this period: it's protected
    assert client.post(f"/api/rotation/{rid}/review", json={"track_id": rows[0].track_id, "action": "keep"}).status_code == 200
    make_due(db, rid)

    summary = client.get(f"/api/rotation/{rid}").json()
    assert summary["active_count"] == 30
    out = db.query(RotationTrackDB).filter_by(rotation_id=rid, status="removed").all()
    assert len(out) == 6  # 20% of 30
    assert all(r.removed_by == "rotation" for r in out)
    assert {r.track_id for r in out} == {r.track_id for r in rows[1:7]}
    assert db.query(ReviewEventDB).filter_by(action="rotated_out").count() == 6
    assert summary["next_rotation_at"] > utcnow().isoformat()
    # Nothing is due again until next week: a second load doesn't rotate again
    assert client.get(f"/api/rotation/{rid}").json()["active_count"] == 30
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, status="removed").count() == 6


def test_rotated_out_songs_wait_four_weeks_then_can_return(client, spotify, db):
    stock_signals(spotify, 30)  # exactly enough to fill once
    rid = create_auto(client, target_size=30)["id"]
    make_due(db, rid)
    summary = client.get(f"/api/rotation/{rid}").json()
    assert summary["active_count"] == 24  # 6 left; nothing new to add and they're cooling down

    for row in db.query(RotationTrackDB).filter_by(rotation_id=rid, status="removed"):
        row.removed_at = utcnow() - timedelta(days=29)
    db.commit()
    spotify.touch(summary["playlist_id"])
    assert client.get(f"/api/rotation/{rid}").json()["active_count"] == 30  # brought back


def test_picks_sometimes_join(client, spotify, db, monkeypatch):
    stock_signals(spotify, 80)
    pick = track_object("pick1")
    spotify.catalog["pick1"] = pick
    db.add(CuratedPickDB(track_id="pick1", uri="spotify:track:pick1", title="Pick", created_at=utcnow()))
    db.commit()
    monkeypatch.setattr(auto, "PICK_CHANCE", 1.0)
    rid = create_auto(client, target_size=30)["id"]
    assert any(r.track_id == "pick1" for r in active_rows(db, rid))


def test_review_queue_is_whats_leaving_next_and_remove_refills(client, spotify, db):
    stock_signals(spotify, 80)
    rid = create_auto(client, target_size=30)["id"]
    queue = client.get(f"/api/rotation/{rid}/queue").json()
    assert queue["due_count"] == 6 and len(queue["tracks"]) == 6
    first = queue["tracks"][0]["track_id"]
    kept = client.post(f"/api/rotation/{rid}/review", json={"track_id": first, "action": "keep"}).json()
    assert kept["protected"] is True
    queue = client.get(f"/api/rotation/{rid}/queue").json()
    assert first not in [t["track_id"] for t in queue["tracks"]]

    victim = queue["tracks"][0]["track_id"]
    client.post(f"/api/rotation/{rid}/review", json={"track_id": victim, "action": "remove"})
    client.post(f"/api/rotation/{rid}/flush")
    assert len(active_rows(db, rid)) == 30  # the freed slot was refilled
    assert victim not in {r.track_id for r in active_rows(db, rid)}


def test_reset_due_and_target_edits(client, spotify, db):
    stock_signals(spotify, 80)
    rid = create_auto(client, target_size=30)["id"]
    assert client.post(f"/api/rotation/{rid}/reset-due").status_code == 400
    assert client.put(f"/api/rotation/{rid}", json={"target_size": 50, "rotate_percent": 10}).status_code == 200
    spotify.touch(db.get(RotationDB, rid).playlist_id)
    assert client.get(f"/api/rotation/{rid}").json()["active_count"] == 50  # topped up

    spotify.add_playlist("p1", [])
    manual = client.post("/api/rotation/", json={"playlist_id": "p1"}).json()["id"]
    assert client.put(f"/api/rotation/{manual}", json={"target_size": 50}).status_code == 400


def test_spotify_failure_during_rotation_is_retried(client, spotify, db, monkeypatch):
    stock_signals(spotify, 80)
    rid = create_auto(client, target_size=30)["id"]
    make_due(db, rid)
    before = db.get(RotationDB, rid).last_rotated_at

    async def boom(*a, **k):
        from rest_api.services.spotify.spotify_service import SpotifyAPIError
        raise SpotifyAPIError(500)

    from rest_api.services.spotify.spotify_service import SpotifyService
    real = SpotifyService.remove_items_from_playlist
    monkeypatch.setattr(SpotifyService, "remove_items_from_playlist", staticmethod(boom))
    assert client.get(f"/api/rotation/{rid}").status_code == 200
    db.expire_all()
    assert db.get(RotationDB, rid).last_rotated_at == before  # claim released
    monkeypatch.setattr(SpotifyService, "remove_items_from_playlist", staticmethod(real))
    client.get(f"/api/rotation/{rid}")
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, status="removed").count() == 6


def test_cron_requires_secret_and_runs(client, spotify, db, monkeypatch):
    stock_signals(spotify, 80)
    rid = create_auto(client, target_size=30)["id"]
    make_due(db, rid)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert client.get("/api/cron/auto-restock").status_code == 404
    monkeypatch.setenv("CRON_SECRET", "s3cret-value")
    assert client.get("/api/cron/auto-restock", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.get("/api/cron/auto-restock", headers={"Authorization": "Bearer s3cret-value"})
    assert r.status_code == 200 and r.json()["ok"] == 1
    assert db.query(RotationTrackDB).filter_by(rotation_id=rid, status="removed").count() == 6
