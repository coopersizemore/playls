"""Listening history changing behavior: queue order, the heavy-songs setting, auto rotation
holds and protection, and Bring back weights."""
from datetime import timedelta
from types import SimpleNamespace

from rest_api.clock import utcnow
from rest_api.database.models import RotationDB, RotationTrackDB
from rest_api.services import auto_rotation_logic as auto
from rest_api.services import listening_logic as ll
from rest_api.services import preferences as prefs
from rest_api.services import restock_logic
from rest_api.services import rotation_logic as logic

from helpers import (
    active_rows,
    add_plays,
    backdate_rotation,
    cover_history,
    create_auto,
    make_due,
    make_rotation,
    review,
    set_account,
    spotify_item,
    stock_signals,
)

# ---------- pure rules ----------

def _row(i, kept_days_ago, title=None):
    now = utcnow()
    return SimpleNamespace(
        id=i, track_id=f"t{i}", title=title or f"t{i:02}", status="active", added_at=now - timedelta(days=400),
        last_kept_at=now - timedelta(days=kept_days_ago), keep_multiplier=1, is_playable=True, listening_holds=0,
    )


def test_listening_order_nudges_but_never_starves():
    rotation = SimpleNamespace(interval_hours=30 * 24, grace_period=True, created_at=utcnow() - timedelta(days=500))
    now = utcnow()
    heavy = ll.SongListening(plays=9, heavy=True, heavy_strength=1.0)
    few = ll.SongListening(few_plays=True)
    # Due 10, 8, 6 days ago (kept 40, 38, 36 days ago)
    a, b, c = _row(1, 40), _row(2, 38), _row(3, 36)
    order = logic.sort_queue([a, b, c], rotation, "listening", listening={1: heavy, 3: few}, now=now)
    assert [t.id for t in order] == [3, 2, 1]  # heavy slides back, rarely played comes forward
    assert [t.id for t in logic.sort_queue([a, b, c], rotation, "overdue")] == [1, 2, 3]
    # Two intervals overdue: no nudge, so a heavily played song still reaches the front
    old = _row(4, 30 + 61)
    order = logic.sort_queue([old, b, c], rotation, "listening", listening={4: heavy}, now=now)
    assert order[0].id == 4
    # No history: same as overdue
    assert logic.sort_queue([a, b, c], rotation, "listening", listening={}, now=now) == [a, b, c]


def _auto_rot():
    now = utcnow()
    return SimpleNamespace(target_size=5, rotate_percent=40, interval_hours=168,  # 2 leave
                           created_at=now - timedelta(days=8), last_rotated_at=None)


def test_auto_holds_a_heavy_song_up_to_the_cap():
    rotation = _auto_rot()
    tracks = [_row(i, 0) for i in range(1, 6)]
    for i, t in enumerate(tracks):
        t.last_kept_at, t.added_at = None, utcnow() - timedelta(days=50 - i)  # 1 is oldest
    heavy = {1: ll.SongListening(plays=8, heavy=True, heavy_strength=0.9)}
    leaving, held = auto.plan_rotate_out(tracks, rotation, utcnow(), listening=heavy, hold_cap=1)
    assert [t.id for t in leaving] == [2, 3] and [t.id for t in held] == [1]
    tracks[0].listening_holds = 1  # already held once: leaves this time
    leaving, held = auto.plan_rotate_out(tracks, rotation, utcnow(), listening=heavy, hold_cap=1)
    assert [t.id for t in leaving] == [1, 2] and held == []
    # The schedule puts the held song first in line for the following rotation
    tracks[0].listening_holds = 0
    schedule = auto.leaving_schedule(tracks, rotation, utcnow(), listening=heavy, hold_cap=1)
    nxt = schedule[2]  # the next rotation (already due here, so "now")
    assert schedule[3] == nxt and schedule[1] == nxt + timedelta(days=7)


def test_auto_holds_never_stall_turnover_and_top_percent_never_leaves():
    rotation = _auto_rot()
    tracks = [_row(i, 0) for i in range(1, 6)]
    for i, t in enumerate(tracks):
        t.last_kept_at, t.added_at = None, utcnow() - timedelta(days=50 - i)
    everyone = {t.id: ll.SongListening(plays=5 + t.id, heavy=True, heavy_strength=0.8) for t in tracks}
    leaving, held = auto.plan_rotate_out(tracks, rotation, utcnow(), listening=everyone, hold_cap=3)
    assert len(leaving) == 2  # all favorites: the oldest leave anyway
    # Top 25% of 5 songs = 2 most played (5 and 4) are shielded outright
    leaving, _ = auto.plan_rotate_out(tracks, rotation, utcnow(), listening=everyone, protect_percent=25)
    assert {t.id for t in leaving} == {1, 2}
    assert ll.protected_by_plays(everyone, [t.id for t in tracks], 25) == {5, 4}


def test_bring_back_weight_counts_plays_since_removal():
    now = utcnow()
    base = restock_logic.bring_back_weight(now - timedelta(days=200), now, 0)
    assert restock_logic.bring_back_weight(now - timedelta(days=200), now, 0, plays_since=1) == base * 1.5
    assert restock_logic.bring_back_weight(now - timedelta(days=200), now, 0, plays_since=10) == base * 3
    assert restock_logic.bring_back_weight(now - timedelta(days=200), now, 0, top=True) == base * 2
    assert restock_logic.bring_back_reason(now - timedelta(days=5), now, 0, 3) == "Removed 5 days ago · played 3× since"


def test_new_preferences_resolve():
    owner = SimpleNamespace(heavy_listening_review=None, review_order=None)
    rotation = SimpleNamespace(owner=owner, heavy_listening_review=None, listening_hold_rotations=None,
                               listening_protect_top_percent=None)
    assert prefs.for_rotation(rotation, "review_order") == "listening"
    assert prefs.for_rotation(rotation, "heavy_listening_review") == "inform"
    owner.heavy_listening_review = "never"
    assert prefs.for_rotation(rotation, "heavy_listening_review") == "never"
    rotation.heavy_listening_review = "less_often"
    assert prefs.for_rotation(rotation, "heavy_listening_review") == "less_often"
    assert prefs.for_rotation(rotation, "listening_hold_rotations") == 1
    assert prefs.for_rotation(rotation, "listening_protect_top_percent") == 0


# ---------- through the API ----------

def _manual(client, db, user, spotify):
    """10 songs, all due (most overdue first: m0), m0 played heavily from the playlist."""
    rot = make_rotation(client, spotify, [spotify_item(f"m{i}", 200 - i) for i in range(10)])
    backdate_rotation(db, rot["id"], 100)
    for i, row in enumerate(sorted(db.query(RotationTrackDB).all(), key=lambda r: r.track_id)):
        row.last_kept_at = utcnow() - timedelta(days=31 + 10 - i)  # m0 most overdue, by under 2 intervals
    db.commit()
    cover_history(db, user)
    add_plays(db, user, "m0", 8, context_uri="spotify:playlist:p1")
    return rot["id"]


def _queue_ids(client, rid):
    q = client.get(f"/api/rotation/{rid}/queue").json()
    return [t["track_id"] for t in q["tracks"]], q


def test_default_order_moves_heavy_songs_back(client, db, user, spotify):
    rid = _manual(client, db, user, spotify)
    ids, _ = _queue_ids(client, rid)
    assert ids[0] != "m0" and ids.index("m0") > 0
    set_account(db, review_order="overdue")
    ids, _ = _queue_ids(client, rid)
    assert ids[0] == "m0"


def test_heavy_listening_review_setting(client, db, user, spotify):
    rid = _manual(client, db, user, spotify)
    ids, q = _queue_ids(client, rid)
    assert "m0" in ids and q["due_count"] == 10
    assert client.put("/api/user/me/settings", json={"heavy_listening_review": "never"}).status_code == 200
    ids, q = _queue_ids(client, rid)
    assert "m0" not in ids and q["due_count"] == 9
    tracks = {t["track_id"]: t for t in client.get(f"/api/rotation/{rid}/tracks").json()}
    assert tracks["m0"]["listening"]["held"] is True and tracks["m0"]["due_at"] is None
    # less often: due one interval later (m0 is 11 days overdue on a 30-day interval)
    r = client.put(f"/api/rotation/{rid}", json={"heavy_listening_review": "less_often"})
    assert r.status_code == 200 and r.json()["heavy_listening_review"] == "less_often"
    ids, q = _queue_ids(client, rid)
    assert "m0" not in ids and q["due_count"] == 9
    tracks = {t["track_id"]: t for t in client.get(f"/api/rotation/{rid}/tracks").json()}
    assert tracks["m0"]["due_at"] > utcnow().isoformat()
    assert client.put("/api/user/me/settings", json={"heavy_listening_review": "always"}).status_code == 422


def test_auto_rotation_holds_a_favorite_once(client, spotify, db, user):
    stock_signals(spotify, 80)
    summary = create_auto(client, target_size=30)
    rid = summary["id"]
    rows = sorted(active_rows(db, rid), key=lambda r: r.track_id)
    for i, row in enumerate(rows):
        row.added_at = utcnow() - timedelta(days=100 - i)  # rows[0] is oldest
    db.commit()
    cover_history(db, user)
    add_plays(db, user, rows[0].track_id, 8, context_uri=f"spotify:playlist:{summary['playlist_id']}")
    make_due(db, rid)
    client.get(f"/api/rotation/{rid}")
    favorite = db.get(RotationTrackDB, rows[0].id)
    assert favorite.status == "active" and favorite.listening_holds == 1
    out = {r.track_id for r in db.query(RotationTrackDB).filter_by(rotation_id=rid, status="removed")}
    assert out == {r.track_id for r in rows[1:7]}  # the next song in line left instead
    # Next rotation: the hold is used up, so it leaves
    rotation = db.get(RotationDB, rid)
    rotation.last_rotated_at -= timedelta(days=8)
    db.commit()
    client.get(f"/api/rotation/{rid}")
    assert db.get(RotationTrackDB, rows[0].id).status == "removed"


def test_keep_resets_auto_holds(client, spotify, db, user):
    stock_signals(spotify, 40)
    rid = create_auto(client, target_size=30)["id"]
    row = active_rows(db, rid)[0]
    row.listening_holds = 1
    db.commit()
    review(client, rid, row.track_id, "keep")
    db.refresh(row)
    assert row.listening_holds == 0


def test_bring_back_deck_favours_songs_still_played(client, db, user, spotify):
    rid = _manual(client, db, user, spotify)
    for tid in ("m1", "m2"):
        review(client, rid, tid, "remove")
    client.post(f"/api/rotation/{rid}/flush")
    add_plays(db, user, "m2", 3, days_ago=(-0.01, -0.005), context_uri="spotify:album:x")
    deck = {c["track_id"]: c for c in client.get(f"/api/rotation/{rid}/restock/deck/bring_back").json()["items"]}
    assert deck["m2"]["score"] > deck["m1"]["score"]
    assert deck["m2"]["reason"].endswith("played 3× since")
