"""Pure restock rules (no DB or network): weights, suggestion scoring, sampling.

Sources (see docs/DESIGN.md, "Restock"):
  bring_back  songs removed from this rotation; weight ramps from 10% to 100% over
              ~90 days after removal; each "Not now" halves it, fading over time
  picks       admin-curated songs shared by everyone
  suggested   scored from the user's listening (top tracks, liked, recently played)
              plus discoveries found by searching their top artists and albums
  search      manual catalog search (no scoring)
"""
import hashlib
import math
import random
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

BRING_BACK_FLOOR = 0.1  # weight right after removal
BRING_BACK_RECOVERY_DAYS = 90  # days until full weight
SKIP_FACTOR = 0.5  # a fresh "Not now" halves the weight...
SKIP_HALF_LIFE_DAYS = 30  # ...and its effect halves every 30 days after that
# Listening history: each play of a removed song since it left raises its bring-back weight
# by half, up to 4 plays (x3); being a current top track counts as 2 plays
BRING_BACK_PLAY_BOOST = 0.5
BRING_BACK_MAX_PLAYS = 4
TOP_COUNTS_AS_PLAYS = 2
DISCOVERY_SHARE = 1 / 3  # target share of "new to you" songs in the suggested deck

TOP_WINDOW_WEIGHTS = {"short_term": 3.0, "medium_term": 2.0, "long_term": 1.0}
TOP_WINDOW_REASONS = {
    "short_term": "In your top tracks this month",
    "medium_term": "In your top tracks the last 6 months",
    "long_term": "One of your top tracks this year",
}


# ---------- track metadata ----------

def _pick_image(album: dict[str, Any]) -> str | None:
    images = album.get("images") or []
    if not images:
        return None
    sized = sorted(images, key=lambda i: i.get("width") or 0)
    for image in sized:
        if (image.get("width") or 0) >= 300:
            return image.get("url")
    return sized[-1].get("url")


def song_key(title: str | None, artists: str | None) -> str | None:
    """Identity of a song apart from its track id: normalized title + first artist.

    The same song often has several track ids: Spotify relinks playlist and library tracks
    to a playable version (rows keep the original id, from `linked_from`, while top tracks,
    search and the like return the playable one), and singles reappear on albums. Track ids
    alone then miss that a suggested song is already in the rotation.
    """
    if not title:
        return None
    first_artist = (artists or "").split(", ")[0]
    return f"{' '.join(title.casefold().split())}|{' '.join(first_artist.casefold().split())}"


def track_meta(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Spotify track object -> compact, JSON-safe dict. None for local files/episodes/nulls."""
    if not item or item.get("type", "track") != "track" or not item.get("id") or item.get("is_local"):
        return None
    album = item.get("album") or {}
    artists = [a for a in item.get("artists") or [] if a.get("name")]
    return {
        "track_id": item["id"],
        "uri": item.get("uri") or f"spotify:track:{item['id']}",
        "title": (item.get("name") or "Unknown track")[:300],
        "artists": ", ".join(a["name"] for a in artists)[:500] or None,
        "artist_ids": [a["id"] for a in artists if a.get("id")],
        "album": (album.get("name") or "")[:300] or None,
        "album_id": album.get("id"),
        "image_url": _pick_image(album),
        "duration_ms": item.get("duration_ms"),
    }


# ---------- skip penalty ----------

def skip_decay(skipped_at: datetime, now: datetime) -> float:
    """How much one "Not now" still counts: 1.0 when fresh, halving every SKIP_HALF_LIFE_DAYS."""
    days = max(0.0, (now - skipped_at).total_seconds() / 86400)
    return 0.5 ** (days / SKIP_HALF_LIFE_DAYS)


def skip_multiplier(effective_skips: float, factor: float = SKIP_FACTOR) -> float:
    """Weight multiplier for a (fading) skip count: 1 skip just now -> `factor` (0.5 by default),
    fully faded -> 1.0. A lower factor is a stronger Not now."""
    return factor ** effective_skips


# ---------- bring back ----------

def bring_back_play_multiplier(plays_since: int = 0, top: bool = False) -> float:
    """Boost for a removed song you've kept playing elsewhere (listening history)."""
    plays = min(BRING_BACK_MAX_PLAYS, plays_since + (TOP_COUNTS_AS_PLAYS if top else 0))
    return 1 + BRING_BACK_PLAY_BOOST * plays


def bring_back_weight(
    removed_at: datetime | None, now: datetime, skips: float, keeps: int = 0,
    recovery_days: float = BRING_BACK_RECOVERY_DAYS, skip_factor: float = SKIP_FACTOR,
    plays_since: int = 0, top: bool = False,
) -> float:
    """Low right after removal, full after `recovery_days` (90 by default); lowered by (fading)
    "Not now"s; small boost per past keep; raised by plays since it left (and being a top track)."""
    if removed_at is None:
        ramp = 1.0
    else:
        days = max(0.0, (now - removed_at).total_seconds() / 86400)
        ramp = BRING_BACK_FLOOR + (1 - BRING_BACK_FLOOR) * min(1.0, days / max(recovery_days, 1))
    return (
        ramp * skip_multiplier(skips, skip_factor) * (1 + 0.1 * min(keeps, 5))
        * bring_back_play_multiplier(plays_since, top)
    )


def bring_back_reason(removed_at: datetime | None, now: datetime, keeps: int, plays_since: int = 0) -> str:
    if removed_at is None:
        return "Previously in this rotation"
    days = (now - removed_at).days
    if days < 1:
        when = "today"
    elif days < 60:
        when = f"{days} day{'s' if days != 1 else ''} ago"
    else:
        when = f"{days // 30} months ago"
    kept = f" · kept {keeps}×" if keeps else ""
    played = f" · played {plays_since}× since" if plays_since else ""
    return f"Removed {when}{kept}{played}"


# ---------- suggestions ----------

def score_suggestion(
    features: dict[str, Any],
    skips: float = 0,
    in_other_rotation: bool = False,
    now: datetime | None = None,
    skip_factor: float = SKIP_FACTOR,
) -> tuple[float, str]:
    """Score a candidate from cached listening features. Returns (score, reason).

    features keys (all optional):
      top: {window: rank}      rank 0 = top track in that window (out of ~50)
      recent_plays: int        plays among the last 50 recently played
      liked_at: ISO str        when it was saved to Liked Songs
      artist_rank: int         best rank of its artists among the user's top artists
      artist_rank_total: int
      discovery: "artist" | "album" | "genre"   found by searching from a seed
      seed: str                the artist/album/genre name the search started from
    """
    parts: list[tuple[float, str]] = []

    for window, rank in (features.get("top") or {}).items():
        weight = TOP_WINDOW_WEIGHTS.get(window)
        if weight is not None:
            parts.append((weight * (1 - min(rank, 49) / 50), TOP_WINDOW_REASONS[window]))

    plays = features.get("recent_plays") or 0
    if plays:
        parts.append((0.6 * min(plays, 3), "Played recently" if plays == 1 else f"Played {plays}× recently"))

    liked_at = features.get("liked_at")
    if liked_at:
        bonus = 1.0
        if now is not None:
            try:
                liked = datetime.fromisoformat(liked_at.replace("Z", "+00:00")).replace(tzinfo=None)
                if (now - liked).days <= 60:
                    bonus += 0.5
            except ValueError:
                pass
        parts.append((bonus, "In your Liked Songs"))

    rank = features.get("artist_rank")
    if rank is not None:
        total = max(features.get("artist_rank_total") or 20, 1)
        parts.append((1.5 * (1 - min(rank, total - 1) / total), "By one of your top artists"))

    discovery = features.get("discovery")
    if discovery:
        seed = features.get("seed") or ""
        reason = {
            "artist": f"More from {seed}",
            "album": f"From {seed}, an album you've been playing",
            "genre": f"More {seed}",
        }.get(discovery, "New for you")
        # Novelty: songs the user hasn't engaged with get a base score of their own
        parts.append((1.2, reason))

    if not parts:
        return 0.0, "Suggested for you"
    score = sum(p[0] for p in parts)
    # The single biggest contributor explains the suggestion best
    reason = max(parts, key=lambda p: p[0])[1]
    score *= skip_multiplier(skips, skip_factor)
    if in_other_rotation:
        score *= 0.6
    return score, reason


def is_discovery(features: dict[str, Any]) -> bool:
    """True when the user hasn't engaged with the song itself (found only via a search seed)."""
    return bool(features.get("discovery")) and not (
        features.get("top") or features.get("recent_plays") or features.get("liked_at")
    )


# ---------- sampling ----------

def daily_seed(*parts: Any) -> int:
    """Stable seed so a deck doesn't reshuffle on every reload the same day."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:16], 16)


def weighted_order(items: Sequence[Any], weights: Sequence[float], seed: int) -> list[Any]:
    """Weighted random order without replacement (Efraimidis–Spirakis).

    Higher weights tend to come first, but low-weight items still surface sometimes.
    Zero/negative weights go last.
    """
    rng = random.Random(seed)
    keyed = []
    for item, w in zip(items, weights, strict=True):
        u = rng.random() or 1e-12
        key = math.log(u) / w if w > 0 else float("-inf")
        keyed.append((key, item))
    keyed.sort(key=lambda kv: kv[0], reverse=True)
    return [item for _, item in keyed]


def blend(known: list[Any], discoveries: list[Any], size: int, discovery_share: float = DISCOVERY_SHARE) -> list[Any]:
    """Interleave two ordered lists so about `discovery_share` of the deck is discoveries."""
    out: list[Any] = []
    k = d = 0
    while len(out) < size and (k < len(known) or d < len(discoveries)):
        want_discovery = d < len(discoveries) and (
            k >= len(known) or (d + 1) / (len(out) + 1) <= discovery_share
        )
        if want_discovery:
            out.append(discoveries[d])
            d += 1
        else:
            out.append(known[k])
            k += 1
    return out


def dedupe(values: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out
