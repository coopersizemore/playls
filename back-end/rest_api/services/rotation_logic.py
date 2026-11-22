"""Pure rotation rules (no DB or network), per docs/DESIGN.md.

Due date for an active song, with interval = rotation.interval_hours:
  - kept before:              last_kept_at + interval
  - grace period on:          max(added_at, rotation.created_at) + interval
                              (songs already in the playlist first come due at creation + interval)
  - grace period off:         added_at + interval
                              (if Spotify didn't report added_at: due at rotation creation)
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from rest_api.clock import to_naive_utc
from rest_api.database.models.rotation_track import ACTIVE


def due_at(track, rotation) -> Optional[datetime]:
    """When an active track comes due; None for tracks that aren't active."""
    if track.status != ACTIVE:
        return None
    interval = timedelta(hours=rotation.interval_hours)
    if track.last_kept_at is not None:
        return track.last_kept_at + interval
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


def todays_batch_size(limit: Optional[int], reviewed_today: int, eligible: int, more: bool) -> int:
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
    artists: Optional[str]
    album: Optional[str]
    image_url: Optional[str]
    duration_ms: Optional[int]
    added_at: Optional[datetime]  # None for very old playlists that lack added_at


def _parse_added_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return to_naive_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _pick_image(album: Dict[str, Any]) -> Optional[str]:
    images = album.get("images") or []
    if not images:
        return None
    # Smallest image that's still at least 300px wide, else the largest available
    sized = sorted(images, key=lambda i: i.get("width") or 0)
    for image in sized:
        if (image.get("width") or 0) >= 300:
            return image.get("url")
    return sized[-1].get("url")


def parse_playlist_items(entries: Iterable[Dict[str, Any]]) -> Dict[str, PlaylistTrack]:
    """Spotify playlist item entries -> {track_id: PlaylistTrack}.

    Skips local files, episodes and unavailable (null) items. Duplicate copies of a
    track collapse to one entry anchored on the earliest added_at.
    """
    tracks: Dict[str, PlaylistTrack] = {}
    for entry in entries:
        if not entry or entry.get("is_local"):
            continue
        # Feb 2026 renamed "track" -> "item"; accept either
        item = entry.get("item") or entry.get("track")
        if not item or item.get("type", "track") != "track" or not item.get("id") or item.get("is_local"):
            continue
        added_at = _parse_added_at(entry.get("added_at"))
        existing = tracks.get(item["id"])
        if existing is not None:
            if added_at is not None and (existing.added_at is None or added_at < existing.added_at):
                existing.added_at = added_at
            continue
        album = item.get("album") or {}
        artists = ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))
        tracks[item["id"]] = PlaylistTrack(
            track_id=item["id"],
            uri=item.get("uri") or f"spotify:track:{item['id']}",
            title=(item.get("name") or "Unknown track")[:300],
            artists=artists[:500] or None,
            album=(album.get("name") or None) and album["name"][:300],
            image_url=_pick_image(album),
            duration_ms=item.get("duration_ms"),
            added_at=added_at,
        )
    return tracks


def sort_queue(tracks: List, rotation) -> List:
    """Most overdue first; ties broken by title for a stable order."""
    return sorted(tracks, key=lambda t: (due_at(t, rotation), t.title.lower()))
