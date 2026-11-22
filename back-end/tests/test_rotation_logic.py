"""Pure rules: due-date math (incl. grace period) and Spotify item parsing."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from rest_api.clock import utcnow
from rest_api.services.rotation_logic import due_at, is_due, parse_playlist_items, sort_queue
from tests.conftest import spotify_item

CREATED = datetime(2026, 1, 1)
ROTATION = SimpleNamespace(created_at=CREATED, interval_days=30)


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
    assert due_at(t, SimpleNamespace(created_at=CREATED, interval_days=7)) == datetime(2026, 2, 8)


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
