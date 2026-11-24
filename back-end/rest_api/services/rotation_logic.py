"""Pure rotation rules (no DB or network), per docs/DESIGN.md.

Due date for an active song, with interval = rotation.interval_hours:
  - kept before:              last_kept_at + interval x keep_multiplier (3 after a super keep)
  - grace period on:          max(added_at, rotation.created_at) + interval
                              (songs already in the playlist first come due at creation + interval)
  - grace period off:         added_at + interval
                              (if Spotify didn't report added_at: due at rotation creation)
"""
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from rest_api.clock import to_naive_utc
from rest_api.database.models.rotation_track import ACTIVE


def due_at(track, rotation) -> datetime | None:
    """When an active track comes due; None for tracks that aren't active."""
    if track.status != ACTIVE:
        return None
    interval = timedelta(hours=rotation.interval_hours)
    if track.last_kept_at is not None:
        return track.last_kept_at + interval * (getattr(track, "keep_multiplier", None) or 1)
    if rotation.grace_period:
        added = track.added_at or rotation.created_at
        return max(added, rotation.created_at) + interval
    if track.added_at is None:
        return rotation.created_at
    return track.added_at + interval


def is_due(track, rotation, now: datetime) -> bool:
    when = due_at(track, rotation)
    return when is not None and when <= now


def local_day_start(now: datetime, tz_offset_minutes: int) -> datetime:
    """Start of the user's current local day, as naive UTC.

    tz_offset_minutes follows JS Date.getTimezoneOffset(): minutes *behind* UTC
    (UTC-5 -> 300, UTC+2 -> -120).
    """
    local_now = now - timedelta(minutes=tz_offset_minutes)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight + timedelta(minutes=tz_offset_minutes)


def todays_batch_size(limit: int | None, reviewed_today: int, eligible: int, more: bool) -> int:
    """How many due songs to offer now under the daily review limit (None = no limit).

    `more` is the user's opt-in "review another batch" after finishing today's.
    """
    if limit is None:
        return eligible
    if more:
        return min(limit, eligible)
    return min(max(0, limit - reviewed_today), eligible)


@dataclass
class PlaylistTrack:
    """A track as currently present in the Spotify playlist (duplicates merged)."""

    track_id: str
    uri: str
    title: str
    artists: str | None
    album: str | None
    image_url: str | None
    duration_ms: int | None
    added_at: datetime | None  # None for very old playlists that lack added_at
    is_playable: bool = True  # False: still in the playlist but unavailable (greyed out)


def _parse_added_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return to_naive_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _pick_image(album: dict[str, Any]) -> str | None:
    images = album.get("images") or []
    if not images:
        return None
    # Smallest image that's still at least 300px wide, else the largest available
    sized = sorted(images, key=lambda i: i.get("width") or 0)
    for image in sized:
        if (image.get("width") or 0) >= 300:
            return image.get("url")
    return sized[-1].get("url")


def playlist_image(playlist: dict[str, Any]) -> str | None:
    """Thumbnail URL from a playlist object's `images` (None for e.g. a new, empty playlist)."""
    return _pick_image({"images": playlist.get("images") or []})


def parse_playlist_items(entries: Iterable[dict[str, Any]]) -> dict[str, PlaylistTrack]:
    """Spotify playlist item entries -> {track_id: PlaylistTrack}.

    Skips local files, episodes and unavailable (null) items. Duplicate copies of a
    track collapse to one entry anchored on the earliest added_at.

    Items are fetched with market=from_token, so Spotify may *relink* a track to a
    playable version with a different id. The playlist still holds the original, given in
    `linked_from`: that's the identity (and the URI to remove) we keep, while display
    metadata comes from the relinked item. `is_playable` is only present with a market;
    missing means playable.
    """
    tracks: dict[str, PlaylistTrack] = {}
    for entry in entries:
        if not entry or entry.get("is_local"):
            continue
        # Feb 2026 renamed "track" -> "item"; accept either
        item = entry.get("item") or entry.get("track")
        if not item or item.get("type", "track") != "track" or not item.get("id") or item.get("is_local"):
            continue
        added_at = _parse_added_at(entry.get("added_at"))
        original = item.get("linked_from") or {}
        track_id = original.get("id") or item["id"]
        uri = original.get("uri") or (item.get("uri") if not original else None) or f"spotify:track:{track_id}"
        playable = item.get("is_playable") is not False
        existing = tracks.get(track_id)
        if existing is not None:
            existing.is_playable = existing.is_playable or playable
            if added_at is not None and (existing.added_at is None or added_at < existing.added_at):
                existing.added_at = added_at
            continue
        album = item.get("album") or {}
        artists = ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))
        tracks[track_id] = PlaylistTrack(
            track_id=track_id,
            uri=uri,
            title=(item.get("name") or "Unknown track")[:300],
            artists=artists[:500] or None,
            album=(album.get("name") or None) and album["name"][:300],
            image_url=_pick_image(album),
            duration_ms=item.get("duration_ms"),
            added_at=added_at,
            is_playable=playable,
        )
    return tracks


def sort_queue(tracks: list, rotation, order: str = "overdue", day_key: str = "") -> list:
    """The review queue's order. Ties are broken by title for a stable order.

    overdue: most overdue first (the default).
    oldest:  longest in the playlist first (unknown add dates first, as the likely oldest).
    shuffle: a random order that stays the same for the day (`day_key`), so the daily
             batch doesn't change between page loads.
    """
    if order == "oldest":
        return sorted(tracks, key=lambda t: (
            t.added_at is not None, t.added_at or datetime.min, t.title.lower()
        ))
    if order == "shuffle":
        def shuffle_key(t):
            digest = hashlib.sha256(f"{day_key}:{t.track_id}".encode()).hexdigest()
            return (digest, t.title.lower())
        return sorted(tracks, key=shuffle_key)
    return sorted(tracks, key=lambda t: (due_at(t, rotation), t.title.lower()))
