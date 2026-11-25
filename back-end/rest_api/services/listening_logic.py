"""Pure listening-history rules (no DB or network), per docs/DESIGN.md "Listening history".

The history is an approximation: Spotify only returns the last 50 plays (each at least
~30 s long, never skips), so PlayLS saves them on every app open and from the daily cron.
Rules lean on "you listen to this a lot", which the data shows reliably. "Few plays lately"
is only said when the history clearly covers the period and the playlist itself is in use.
"""
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from rest_api.clock import to_naive_utc
from rest_api.services.restock_logic import song_key

PLAY_MIN_MS = 30_000  # an imported play shorter than this was a skip, not a listen
RECENT_PAGE = 50  # GET /me/player/recently-played returns at most this many

MIN_WINDOW_DAYS = 21  # also the least history "few plays lately" needs
MAX_WINDOW_DAYS = 90
FEW_PLAYS_MAX_GAP_SHARE = 0.2
FEW_PLAYS_MIN_PLAYLIST_PLAYS = 20
HEAVY_MIN_PLAYS = 3
HEAVY_TOP_RANGES = ("short_term", "medium_term")
TOP_SIZE = 50

# Queue order ("listening"): how far a song's due date is nudged, in intervals
HEAVY_SHIFT_INTERVALS = 1.0
FEW_PLAYS_SHIFT_INTERVALS = 0.5
NO_SHIFT_AFTER_OVERDUE_INTERVALS = 2  # songs this overdue are ordered purely by due date



@dataclass
class Play:
    track_id: str
    song_key: str | None
    played_at: datetime
    uri: str | None = None
    title: str | None = None
    artists: str | None = None
    album: str | None = None
    image_url: str | None = None
    duration_ms: int | None = None
    context_type: str | None = None
    context_uri: str | None = None


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return to_naive_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _image(album: dict[str, Any]) -> str | None:
    images = sorted(album.get("images") or [], key=lambda i: i.get("width") or 0)
    for image in images:
        if (image.get("width") or 0) >= 300:
            return image.get("url")
    return images[-1].get("url") if images else None


def parse_plays(items: Iterable[dict[str, Any]]) -> list[Play]:
    """recently-played items -> plays, oldest first. Skips nulls, local files and episodes."""
    plays: dict[datetime, Play] = {}
    for entry in items or []:
        if not entry:
            continue
        track = entry.get("track") or entry.get("item")
        played_at = parse_time(entry.get("played_at"))
        if (
            not track or played_at is None or track.get("type", "track") != "track"
            or not track.get("id") or track.get("is_local")
        ):
            continue
        album = track.get("album") or {}
        artists = ", ".join(a["name"] for a in track.get("artists") or [] if a.get("name"))[:500] or None
        title = (track.get("name") or "")[:300] or None
        context = entry.get("context") or {}
        plays[played_at] = Play(
            track_id=track["id"], song_key=song_key(title, artists), played_at=played_at,
            uri=track.get("uri") or f"spotify:track:{track['id']}", title=title, artists=artists,
            album=(album.get("name") or "")[:300] or None, image_url=_image(album),
            duration_ms=track.get("duration_ms"),
            context_type=(context.get("type") or None) and context["type"][:20],
            context_uri=(context.get("uri") or None) and context["uri"][:200],
        )
    return [plays[t] for t in sorted(plays)]


def detect_gap(plays: Sequence[Play], cursor: datetime | None, page_size: int = RECENT_PAGE):
    """(start, end) of plays probably missed, or None.

    A capture reads the latest 50 plays. If all 50 are newer than the newest play already
    stored, anything between the two may have been lost.
    """
    if cursor is None or len(plays) < page_size:
        return None
    oldest = min(p.played_at for p in plays)
    return (cursor, oldest) if oldest > cursor else None


def window_days(interval_hours: int) -> int:
    """The period listening stats cover for a rotation: two intervals, 21 to 90 days."""
    days = math.ceil(2 * interval_hours / 24)
    return max(MIN_WINDOW_DAYS, min(MAX_WINDOW_DAYS, days))


def covered(since: datetime | None, gaps: Iterable[tuple[datetime, datetime]], start: datetime, end: datetime):
    """(history span, gap-free time) within [start, end), as timedeltas."""
    if since is None or since >= end:
        return timedelta(0), timedelta(0)
    lo = max(since, start)
    span = end - lo
    missing = timedelta(0)
    for g_start, g_end in gaps:
        a, b = max(g_start, lo), min(g_end, end)
        if b > a:
            missing += b - a
    return span, max(timedelta(0), span - missing)


def is_confident(since, gaps, start: datetime, end: datetime) -> bool:
    """The history covers all of [start, end) with few gaps."""
    span, ok = covered(since, gaps, start, end)
    full = end - start
    return since is not None and since <= start and span >= full and ok >= full * (1 - FEW_PLAYS_MAX_GAP_SHARE)


@dataclass
class SongListening:
    """One song's listening, for the rotation's window (window_days)."""

    plays: int = 0  # from anywhere
    plays_here: int = 0  # from this rotation's playlist
    last_played_at: datetime | None = None
    top_rank: dict[str, int] = field(default_factory=dict)  # time_range -> rank (0 = top)
    heavy: bool = False  # "you listen to this a lot"
    heavy_strength: float = 0.0  # 0..1
    few_plays: bool = False  # confidently not played lately (see assess)
    starts: int = 0  # imported history only: times it started playing in the window
    skips: int = 0  # ...and how many of those were skipped


@dataclass
class RotationListening:
    window_days: int
    plays_here: int = 0  # plays from this playlist in the window
    confident: bool = False  # the history covers the window (needed for "few plays")
    songs: dict[int, SongListening] = field(default_factory=dict)  # rotation_track id -> stats


def heavy_strength(s: SongListening, average: float) -> float:
    """How strongly "you listen to this a lot" applies (0 = not heavy)."""
    strength = 0.0
    rank = s.top_rank.get("short_term")
    if rank is not None:
        strength = max(strength, 1.0 - 0.5 * rank / TOP_SIZE)
    rank = s.top_rank.get("medium_term")
    if rank is not None:
        strength = max(strength, 0.7 - 0.4 * rank / TOP_SIZE)
    threshold = max(HEAVY_MIN_PLAYS, 2 * average)
    if s.plays >= threshold:
        strength = max(strength, min(1.0, 0.5 + 0.5 * (s.plays - threshold) / max(threshold, 1)))
    return round(strength, 3)


def assess(
    songs: dict[int, SongListening], *, plays_here: int, confident: bool, size: int,
    in_playlist_since: dict[int, datetime | None], window_start: datetime,
) -> None:
    """Fill `heavy`, `heavy_strength` and `few_plays` for a rotation's songs (in place).

    few_plays is deliberately hard to reach. All of these must hold:
      - the history covers the window (`confident`: the whole window, under 20% gaps)
      - the playlist itself was played at least max(20, its size) times in the window
      - the song had no plays anywhere in it, isn't a top track, and was in the playlist
        for the whole window
    """
    average = sum(s.plays for s in songs.values()) / max(size, 1)
    busy = plays_here >= max(FEW_PLAYS_MIN_PLAYLIST_PLAYS, size)
    for row_id, s in songs.items():
        s.heavy_strength = heavy_strength(s, average)
        s.heavy = s.heavy_strength > 0
        since = in_playlist_since.get(row_id)
        s.few_plays = (
            confident and busy and s.plays == 0 and not s.top_rank and not s.heavy
            and since is not None and since <= window_start
        )


def queue_shift(s: SongListening | None, due: datetime | None, interval: timedelta, now: datetime) -> timedelta:
    """How far the "listening" order moves a due song: heavily played ones later (up to one
    interval), rarely played ones half an interval sooner. Songs more than two intervals
    overdue aren't moved, so heavily played songs still reach the front as they age."""
    if s is None or due is None:
        return timedelta(0)
    if now - due > interval * NO_SHIFT_AFTER_OVERDUE_INTERVALS:
        return timedelta(0)
    if s.heavy:
        return interval * (HEAVY_SHIFT_INTERVALS * s.heavy_strength)
    if s.few_plays:
        return -interval * FEW_PLAYS_SHIFT_INTERVALS
    return timedelta(0)


def protected_by_plays(songs: dict[int, SongListening], row_ids: Sequence[int], percent: int) -> set[int]:
    """Auto rotations: the most played `percent`% of the playlist (songs with 3+ plays only)."""
    if percent <= 0 or not row_ids:
        return set()
    n = math.ceil(len(row_ids) * percent / 100)
    ranked = sorted(
        (r for r in row_ids if songs.get(r) and songs[r].plays >= HEAVY_MIN_PLAYS),
        key=lambda r: (-songs[r].plays, -songs[r].heavy_strength, r),
    )
    return set(ranked[:n])


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def rediscover_reason(plays: int, peak_month: int | None) -> str:
    when = f" back in {MONTHS[peak_month - 1]}" if peak_month else ""
    return f"You played this {plays}×{when}"
