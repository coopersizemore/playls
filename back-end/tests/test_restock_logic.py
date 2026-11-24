"""Pure restock rules: bring-back weights, suggestion scoring, sampling, blending."""
from datetime import datetime, timedelta

from rest_api.services.restock_logic import (
    blend,
    bring_back_weight,
    is_discovery,
    score_suggestion,
    skip_decay,
    skip_multiplier,
    track_meta,
    weighted_order,
)

from helpers import track_object

NOW = datetime(2026, 11, 22)


def test_bring_back_starts_low_and_recovers_over_90_days():
    fresh = bring_back_weight(NOW, NOW, skips=0)
    month = bring_back_weight(NOW - timedelta(days=30), NOW, skips=0)
    full = bring_back_weight(NOW - timedelta(days=90), NOW, skips=0)
    later = bring_back_weight(NOW - timedelta(days=400), NOW, skips=0)
    assert fresh == 0.1
    assert fresh < month < full
    assert full == later == 1.0


def test_bring_back_skips_halve_weight_and_keeps_boost_it():
    base = bring_back_weight(NOW - timedelta(days=90), NOW, skips=0)
    assert bring_back_weight(NOW - timedelta(days=90), NOW, skips=1) == base / 2
    assert bring_back_weight(NOW - timedelta(days=90), NOW, skips=2) == base / 4
    assert bring_back_weight(NOW - timedelta(days=90), NOW, skips=0, keeps=3) > base


def test_score_prefers_short_term_top_tracks():
    short, _ = score_suggestion({"top": {"short_term": 0}})
    long, _ = score_suggestion({"top": {"long_term": 0}})
    low_rank, _ = score_suggestion({"top": {"short_term": 45}})
    assert short > long and short > low_rank


def test_score_reason_is_biggest_contributor():
    _, reason = score_suggestion({"top": {"long_term": 40}, "liked_at": "2020-01-01T00:00:00Z"}, now=NOW)
    assert reason == "In your Liked Songs"
    _, reason = score_suggestion({"discovery": "artist", "seed": "Björk"})
    assert reason == "More from Björk"


def test_recent_like_gets_a_bonus():
    old, _ = score_suggestion({"liked_at": "2020-01-01T00:00:00Z"}, now=NOW)
    new, _ = score_suggestion({"liked_at": "2026-11-01T00:00:00Z"}, now=NOW)
    assert new > old


def test_skips_and_other_rotations_lower_score():
    base, _ = score_suggestion({"top": {"short_term": 0}})
    assert score_suggestion({"top": {"short_term": 0}}, skips=1)[0] == base / 2
    assert score_suggestion({"top": {"short_term": 0}}, in_other_rotation=True)[0] < base


def test_discovery_only_when_user_has_not_engaged():
    assert is_discovery({"discovery": "artist", "seed": "X"})
    assert not is_discovery({"discovery": "artist", "seed": "X", "liked_at": "2026-01-01T00:00:00Z"})
    assert not is_discovery({"top": {"short_term": 3}})


def test_weighted_order_is_deterministic_and_favors_heavy_items():
    items = list(range(50))
    weights = [100.0 if i < 5 else 0.01 for i in items]
    a = weighted_order(items, weights, seed=42)
    assert a == weighted_order(items, weights, seed=42)
    assert set(a[:5]) == {0, 1, 2, 3, 4}


def test_zero_weight_goes_last():
    assert weighted_order(["a", "b"], [0.0, 1.0], seed=1) == ["b", "a"]


def test_blend_mixes_about_a_third_discoveries():
    deck = blend(["k"] * 30, ["d"] * 30, 30)
    assert len(deck) == 30 and deck.count("d") == 10
    assert deck[:3] == ["k", "k", "d"]
    # Falls back to whichever list still has items
    assert blend([], ["d"] * 5, 30) == ["d"] * 5
    assert blend(["k"] * 5, [], 30) == ["k"] * 5


def test_track_meta():
    meta = track_meta(track_object("t1", artists=(("A", "a1"), ("B", "b1"))))
    assert (meta["artists"], meta["artist_ids"], meta["album_id"]) == ("A, B", ["a1", "b1"], "alb_1")
    assert track_meta({"id": "e1", "type": "episode"}) is None
    assert track_meta(None) is None


def test_skip_penalty_fades_with_a_30_day_half_life():
    assert skip_decay(NOW, NOW) == 1.0
    assert skip_decay(NOW - timedelta(days=30), NOW) == 0.5
    assert skip_decay(NOW - timedelta(days=90), NOW) == 0.125
    assert skip_multiplier(1.0) == 0.5  # fresh skip halves
    assert skip_multiplier(0.0) == 1.0  # fully faded
    assert skip_multiplier(skip_decay(NOW - timedelta(days=30), NOW)) == 0.5 ** 0.5  # ~0.71


def test_old_skips_hurt_less_than_fresh_ones():
    fresh = score_suggestion({"top": {"short_term": 0}}, skips=skip_decay(NOW, NOW))[0]
    old = score_suggestion({"top": {"short_term": 0}}, skips=skip_decay(NOW - timedelta(days=60), NOW))[0]
    none = score_suggestion({"top": {"short_term": 0}})[0]
    assert fresh < old < none
