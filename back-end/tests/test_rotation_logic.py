"""Pure rules: due-date math (incl. grace period) and Spotify item parsing."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from rest_api.clock import utcnow
from rest_api.services.rotation_logic import (
    due_at,
    is_due,
    local_day_start,
    parse_playlist_items,
    sort_queue,
    todays_batch_size,
)

from helpers import spotify_item

CREATED = datetime(2026, 1, 1)
ROTATION = SimpleNamespace(created_at=CREATED, interval_hours=30 * 24, grace_period=True)
NO_GRACE = SimpleNamespace(created_at=CREATED, interval_hours=30 * 24, grace_period=False)


def track(added_at, last_kept_at=None, status="active", title="t"):
    return SimpleNamespace(added_at=added_at, last_kept_at=last_kept_at, status=status, title=title)


def test_existing_song_gets_grace_period_from_rotation_creation():
    old = track(datetime(2024, 1, 1))  # in the playlist long before the rotation
    assert due_at(old, ROTATION) == CREATED + timedelta(days=30)


def test_song_added_after_creation_is_due_n_days_after_added():
    new = track(datetime(2026, 2, 10))
    assert due_at(new, ROTATION) == datetime(2026, 3, 12)


def test_keep_resets_anchor_to_keep_date():
    kept = track(datetime(2024, 1, 1), last_kept_at=datetime(2026, 5, 1))
    assert due_at(kept, ROTATION) == datetime(2026, 5, 31)


def test_interval_change_applies_immediately():
    t = track(datetime(2026, 2, 1))
    weekly = SimpleNamespace(created_at=CREATED, interval_hours=7 * 24, grace_period=True)
    assert due_at(t, weekly) == datetime(2026, 2, 8)


def test_non_active_tracks_are_never_due():
    for status in ("pending_removal", "removed"):
        t = track(datetime(2020, 1, 1), status=status)
        assert due_at(t, ROTATION) is None
        assert not is_due(t, ROTATION, datetime(2030, 1, 1))


def test_is_due_boundary():
    t = track(datetime(2026, 2, 1))
    assert is_due(t, ROTATION, datetime(2026, 3, 3))
    assert not is_due(t, ROTATION, datetime(2026, 3, 2, 23, 59))


def test_sort_queue_most_overdue_first():
    a, b = track(datetime(2026, 3, 1), title="b"), track(datetime(2026, 2, 1), title="a")
    assert sort_queue([a, b], ROTATION) == [b, a]


def test_parse_items_basic_fields():
    parsed = parse_playlist_items([spotify_item("t1", added_days_ago=3)])
    t = parsed["t1"]
    assert t.uri == "spotify:track:t1"
    assert t.artists == "Artist A, Artist B"
    assert t.image_url == "small"  # smallest image >= 300px
    assert t.added_at is not None and t.added_at.tzinfo is None


def test_parse_items_skips_local_episodes_and_nulls():
    entries = [
        spotify_item("l1", local=True),
        spotify_item("e1", kind="episode"),
        {"added_at": None, "is_local": False, "item": None},
        None,
        spotify_item("ok"),
    ]
    assert list(parse_playlist_items(entries)) == ["ok"]


def test_parse_items_accepts_legacy_track_key():
    entry = spotify_item("t1")
    entry["track"] = entry.pop("item")
    assert "t1" in parse_playlist_items([entry])


def test_duplicates_collapse_to_earliest_added_at():
    parsed = parse_playlist_items([spotify_item("t1", added_days_ago=1), spotify_item("t1", added_days_ago=10)])
    assert len(parsed) == 1
    assert parsed["t1"].added_at < utcnow() - timedelta(days=9)


def test_missing_added_at_is_none():
    assert parse_playlist_items([spotify_item("t1")])["t1"].added_at is None


def test_without_grace_existing_song_is_due_from_its_added_at():
    old = track(datetime(2024, 1, 1))
    assert due_at(old, NO_GRACE) == datetime(2024, 1, 31)
    assert is_due(old, NO_GRACE, CREATED)


def test_without_grace_unknown_added_at_is_due_at_creation():
    assert due_at(track(None), NO_GRACE) == CREATED


def test_with_grace_unknown_added_at_waits_full_interval():
    assert due_at(track(None), ROTATION) == CREATED + timedelta(days=30)


def test_keep_overrides_grace_setting():
    kept = track(None, last_kept_at=datetime(2026, 5, 1))
    assert due_at(kept, NO_GRACE) == due_at(kept, ROTATION) == datetime(2026, 5, 31)


def test_sub_day_interval():
    hourly = SimpleNamespace(created_at=CREATED, interval_hours=6, grace_period=True)
    assert due_at(track(datetime(2026, 2, 1)), hourly) == datetime(2026, 2, 1, 6)


def test_local_day_start():
    now = datetime(2026, 3, 10, 3, 30)  # 03:30 UTC
    assert local_day_start(now, 0) == datetime(2026, 3, 10)
    # UTC-5 (offset 300): local time is 22:30 on the 9th -> local midnight = 05:00 UTC on the 9th
    assert local_day_start(now, 300) == datetime(2026, 3, 9, 5)
    # UTC+2 (offset -120): local 05:30 on the 10th -> midnight = 22:00 UTC on the 9th
    assert local_day_start(now, -120) == datetime(2026, 3, 9, 22)


def test_todays_batch_size():
    assert todays_batch_size(None, 999, 300, more=False) == 300
    assert todays_batch_size(50, 0, 300, more=False) == 50
    assert todays_batch_size(50, 30, 300, more=False) == 20
    assert todays_batch_size(50, 80, 300, more=False) == 0
    assert todays_batch_size(50, 80, 300, more=True) == 50
    assert todays_batch_size(50, 0, 10, more=False) == 10


def test_relinked_track_keeps_playlist_identity():
    """With market=from_token Spotify may swap in a playable version; the playlist still holds the original."""
    entry = spotify_item("relinked", 3)
    entry["item"]["linked_from"] = {"id": "orig", "uri": "spotify:track:orig"}
    entry["item"]["is_playable"] = True
    t = parse_playlist_items([entry])["orig"]
    assert (t.track_id, t.uri, t.title) == ("orig", "spotify:track:orig", "Song relinked")


def test_unplayable_flag():
    gone = spotify_item("gone", 3)
    gone["item"]["is_playable"] = False
    gone["item"]["restrictions"] = {"reason": "market"}
    parsed = parse_playlist_items([gone, spotify_item("fine", 3)])
    assert parsed["gone"].is_playable is False
    assert parsed["fine"].is_playable is True  # field absent -> playable


def test_super_keep_triples_the_wait():
    kept = SimpleNamespace(added_at=datetime(2024, 1, 1), last_kept_at=datetime(2026, 5, 1),
                           status="active", title="t", keep_multiplier=3)
    assert due_at(kept, ROTATION) == datetime(2026, 5, 1) + timedelta(days=90)
