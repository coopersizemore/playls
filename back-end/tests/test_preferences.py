"""Tweakable behavior: resolving settings, and each setting's effect on reviewing and restocking."""
from datetime import timedelta
from types import SimpleNamespace

from rest_api.clock import utcnow
from rest_api.database.models import ReviewEventDB, RotationTrackDB
from rest_api.services import auto_rotation_logic as auto
from rest_api.services import preferences as prefs
from rest_api.services.rotation_logic import sort_queue

from helpers import make_rotation, many_old_songs, review, set_account, spotify_item

ROT = SimpleNamespace(interval_hours=24, grace_period=False, created_at=utcnow() - timedelta(days=500))


# ---------- resolving ----------

def test_rotation_override_then_account_then_default():
    owner = SimpleNamespace(super_keep_multiplier=None, skip_hold_days=7, review_limit=50)
    rotation = SimpleNamespace(owner=owner, super_keep_multiplier=None, skip_hold_days=None, review_limit=None)
    assert prefs.for_rotation(rotation, "super_keep_multiplier") == 3  # built-in default
    assert prefs.for_rotation(rotation, "skip_hold_days") == 7  # account setting
    rotation.skip_hold_days = 3
    assert prefs.for_rotation(rotation, "skip_hold_days") == 3  # rotation override
    rotation.skip_hold_days = 4  # not an allowed choice: ignored
    assert prefs.for_rotation(rotation, "skip_hold_days") == 7


def test_rotation_review_limit_override():
    rotation = SimpleNamespace(owner=SimpleNamespace(review_limit=50), review_limit=None)
    assert prefs.review_limit(rotation) == 50
    rotation.review_limit = 5
    assert prefs.review_limit(rotation) == 5
    rotation.review_limit = prefs.NO_LIMIT
    assert prefs.review_limit(rotation) is None


def test_queue_orders():
    def song(tid, added_days):
        return SimpleNamespace(track_id=tid, title=tid, added_at=utcnow() - timedelta(days=added_days),
                               last_kept_at=None, keep_multiplier=1, status="active")
    a, b, c = song("a", 10), song("b", 300), song("c", 50)
    b.last_kept_at = utcnow() - timedelta(days=2)  # kept recently: least overdue
    assert sort_queue([a, b, c], ROT) == [c, a, b]
    assert sort_queue([a, b, c], ROT, order="oldest") == [b, c, a]
    shuffled = sort_queue([a, b, c], ROT, order="shuffle", day_key="1:2026-11-24")
    assert shuffled == sort_queue([c, b, a], ROT, order="shuffle", day_key="1:2026-11-24")  # stable for the day
    assert {t.track_id for t in shuffled} == {"a", "b", "c"}


def test_auto_cooldown_and_mix_are_parameters():
    now = utcnow()
    assert not auto.cooled_down(now - timedelta(days=20), now)  # 4 weeks by default
    assert auto.cooled_down(now - timedelta(days=20), now, 14)
    import random
    counts = auto.allocate(10, 10, 10, 10, random.Random(1), pick_chance=0, bring_back_share=0)
    assert counts == {"picks": 0, "bring_back": 0, "suggested": 10}


# ---------- effects ----------

def test_super_keep_length_follows_account_then_rotation(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item(t, 60) for t in ("a", "b")], grace=False)["id"]
    set_account(db, super_keep_multiplier=5)
    assert review(client, rid, "a", "super_keep").json()[
        "keep_multiplier"] == 5
    r = client.put(f"/api/rotation/{rid}", json={"super_keep_multiplier": 2})
    assert r.status_code == 200
    assert r.json()["super_keep_multiplier"] == 2 and r.json()["overrides"]["super_keep_multiplier"] == 2
    assert review(client, rid, "b", "super_keep").json()[
        "keep_multiplier"] == 2
    # Clearing the override goes back to the account setting
    r = client.put(f"/api/rotation/{rid}", json={"super_keep_multiplier": None}).json()
    assert r["super_keep_multiplier"] == 5 and r["overrides"]["super_keep_multiplier"] is None


def test_skip_hold_days(client, spotify, db):
    rid = make_rotation(client, spotify, many_old_songs(3), grace=False)["id"]
    review(client, rid, "s000", "skip")
    for e in db.query(ReviewEventDB):
        e.created_at -= timedelta(days=1, hours=1)  # skipped yesterday
    db.commit()
    def queue():
        return [t["track_id"] for t in client.get(f"/api/rotation/{rid}/queue").json()["tracks"]]
    assert "s000" in queue()  # default: back the next day
    client.put(f"/api/rotation/{rid}", json={"skip_hold_days": 3})
    assert "s000" not in queue()  # held for 3 days
    assert client.get(f"/api/rotation/{rid}").json()["skip_hold_days"] == 3


def test_rotation_daily_limit_override(client, spotify, db):
    rid = make_rotation(client, spotify, many_old_songs(12), grace=False)["id"]
    def size():
        return len(client.get(f"/api/rotation/{rid}/queue").json()["tracks"])
    set_account(db, review_limit=10)
    assert size() == 10
    client.put(f"/api/rotation/{rid}", json={"review_limit": 3})
    assert size() == 3 and client.get(f"/api/rotation/{rid}").json()["daily_limit"] == 3
    client.put(f"/api/rotation/{rid}", json={"review_limit": 0})  # no limit for this rotation
    assert size() == 12 and client.get(f"/api/rotation/{rid}").json()["daily_limit"] is None


def test_review_order_oldest(client, spotify, db):
    # Added long ago but kept recently vs added recently: "oldest" puts the long-held song first
    items = [spotify_item("old", 400), spotify_item("new", 100)]
    rid = make_rotation(client, spotify, items, grace=False)["id"]
    row = db.query(RotationTrackDB).filter_by(rotation_id=rid, track_id="old").one()
    row.last_kept_at = utcnow() - timedelta(days=31)  # just due again
    db.commit()
    def order():
        return [t["track_id"] for t in client.get(f"/api/rotation/{rid}/queue").json()["tracks"]]
    assert order() == ["new", "old"]  # most overdue first
    client.put(f"/api/rotation/{rid}", json={"review_order": "oldest"})
    assert order() == ["old", "new"]


def test_auto_only_settings_rejected_on_manual(client, spotify):
    rid = make_rotation(client, spotify, [spotify_item("a", 5)])["id"]
    assert client.put(f"/api/rotation/{rid}", json={"return_cooldown_days": 14}).status_code == 400
    assert client.put(f"/api/rotation/{rid}", json={"skip_hold_days": 5}).status_code == 422


def test_deck_size_setting(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item(f"s{i:02}", 10) for i in range(15)])["id"]
    for i in range(15):
        review(client, rid, f"s{i:02}", "remove")
    client.post(f"/api/rotation/{rid}/flush")
    def deck():
        return client.get(f"/api/rotation/{rid}/restock/deck/bring_back").json()["items"]
    assert len(deck()) == 15
    client.put("/api/user/me/settings", json={"deck_size": 10})
    assert len(deck()) == 10
