"""Listening history: capturing plays, importing an export, and per-song stats.

Capture (`capture`) reads the latest 50 plays and the top tracks. It runs when the app is
opened (POST /user/me/listening/capture, at most every CAPTURE_EVERY per user), after
login, and from the daily cron (`capture_all`). Stats (`for_rotation`, `song_plays`, ...)
read the stored history; nothing here calls Spotify except capture.
"""
import logging
import time
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
import sqlalchemy.orm as orm
from sqlalchemy import or_

from rest_api import request_context
from rest_api.clock import utcnow
from rest_api.database.models.listening import (
    API,
    IMPORT,
    TIME_RANGES,
    ListeningGapDB,
    PlayEventDB,
    TopTrackDB,
)
from rest_api.database.models.rotation import RotationDB, is_liked
from rest_api.database.models.user import DEMO, UserDB
from rest_api.services import health
from rest_api.services import listening_logic as logic
from rest_api.services.auth_service import missing_scopes
from rest_api.services.restock_logic import song_key
from rest_api.services.spotify.spotify_service import SpotifyAPIError
from rest_api.services.spotify.spotify_service import SpotifyService as ss

logger = logging.getLogger(__name__)

CAPTURE_EVERY = timedelta(minutes=15)
FORCED_CAPTURE_EVERY = timedelta(seconds=30)
TOP_EVERY = timedelta(hours=24)
RETENTION_DAYS = 365
IMPORT_MATCH_WINDOW = timedelta(minutes=4)  # an imported play this close to a captured one is the same play
CRON_BUDGET_SECONDS = 120


def enabled(user: UserDB) -> bool:
    return user.listening_enabled is not False


# ---------- capture ----------

def _claim(db: orm.Session, user: UserDB, now: datetime, every: timedelta) -> bool:
    """Take the capture for this user (so two tabs and the cron don't both fetch)."""
    claimed = db.query(UserDB).filter(
        UserDB.id == user.id,
        or_(UserDB.listening_captured_at.is_(None), UserDB.listening_captured_at < now - every),
    ).update({UserDB.listening_captured_at: now}, synchronize_session=False)
    db.commit()
    db.refresh(user)
    return bool(claimed)


def _store(db: orm.Session, user: UserDB, plays: list[logic.Play], now: datetime) -> int:
    """Insert new plays, record a gap if some were probably missed, advance the cursor."""
    if user.listening_since is None:
        # History starts at the oldest play we can see (nothing earlier is known)
        user.listening_since = plays[0].played_at if plays else now
    gap = logic.detect_gap(plays, user.listening_cursor)
    if gap is not None:
        db.add(ListeningGapDB(user_id=user.id, gap_start=gap[0], gap_end=gap[1]))
        health.count("listening.gap")
    if not plays:
        return 0
    existing = {
        t for (t,) in db.query(PlayEventDB.played_at).filter(
            PlayEventDB.user_id == user.id,
            PlayEventDB.played_at >= plays[0].played_at,
            PlayEventDB.played_at <= plays[-1].played_at,
        )
    }
    added = 0
    for p in plays:
        if p.played_at in existing:
            continue
        db.add(PlayEventDB(
            user_id=user.id, track_id=p.track_id, song_key=p.song_key, uri=p.uri, title=p.title,
            artists=p.artists, album=p.album, image_url=p.image_url, duration_ms=p.duration_ms,
            played_at=p.played_at, context_type=p.context_type, context_uri=p.context_uri, source=API,
        ))
        added += 1
    newest = plays[-1].played_at
    if user.listening_cursor is None or newest > user.listening_cursor:
        user.listening_cursor = newest
    return added


async def _refresh_top(db: orm.Session, user: UserDB, now: datetime) -> None:
    refreshed = False
    for time_range in TIME_RANGES:
        try:
            page = await ss.get_top_items("tracks", user, db, time_range=time_range, limit=50)
        except (SpotifyAPIError, httpx.HTTPError):
            logger.warning("Top tracks (%s) failed for user %s", time_range, user.id, exc_info=True)
            health.count("listening.top_failed")
            continue
        db.query(TopTrackDB).filter(TopTrackDB.user_id == user.id, TopTrackDB.time_range == time_range).delete()
        for rank, item in enumerate((page or {}).get("items") or []):
            if not item or not item.get("id"):
                continue
            artists = ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))
            db.add(TopTrackDB(
                user_id=user.id, time_range=time_range, rank=rank, track_id=item["id"],
                song_key=song_key(item.get("name"), artists), captured_at=now,
            ))
        refreshed = True
    if refreshed:
        user.top_tracks_captured_at = now


async def capture(db: orm.Session, user: UserDB, force: bool = False) -> int:
    """Save the user's latest plays (and, daily, their top tracks). Returns plays added.

    Never raises for Spotify trouble: a capture is best effort and must not fail the
    request (or login) that triggered it.
    """
    if user.provider == DEMO or not enabled(user):
        return 0
    now = utcnow()
    if not _claim(db, user, now, FORCED_CAPTURE_EVERY if force else CAPTURE_EVERY):
        return 0
    missing = set(missing_scopes(user, ["user-read-recently-played", "user-top-read"]))
    added = 0
    if "user-read-recently-played" not in missing:
        try:
            page = await ss.get_recently_played(user, db)
        except (SpotifyAPIError, httpx.HTTPError):
            logger.warning("Recently played failed for user %s", user.id, exc_info=True)
            health.count("listening.capture_failed")
            page = None
        if page is not None:
            added = _store(db, user, logic.parse_plays(page.get("items") or []), now)
    if "user-top-read" not in missing and (
        user.top_tracks_captured_at is None or user.top_tracks_captured_at < now - TOP_EVERY
    ):
        await _refresh_top(db, user, now)
    db.commit()
    if added:
        health.count("listening.plays", added)
    return added


async def safe_capture(db: orm.Session, user: UserDB, force: bool = False) -> int:
    try:
        return await capture(db, user, force=force)
    except Exception:
        db.rollback()
        logger.warning("Listening capture failed for user %s", user.id, exc_info=True)
        health.count("listening.capture_failed")
        return 0


async def capture_all(db: orm.Session, budget_seconds: float = CRON_BUDGET_SECONDS) -> dict[str, int]:
    """Cron: capture for every real account with listening history on. One failure doesn't
    stop the rest; stops early when the time budget runs out."""
    started = time.monotonic()
    stats = {"users": 0, "plays": 0, "skipped": 0}
    ids = [
        uid for (uid,) in db.query(UserDB.id)
        .filter(UserDB.provider != DEMO, UserDB.listening_enabled.is_(True))
        .order_by(UserDB.id)
    ]
    for user_id in ids:
        if time.monotonic() - started > budget_seconds:
            stats["skipped"] += 1
            continue
        user = db.get(UserDB, user_id)
        if user is None:
            continue
        stats["users"] += 1
        stats["plays"] += await safe_capture(db, user)
    return stats


# ---------- turning it off, retention ----------

def delete_history(db: orm.Session, user: UserDB) -> None:
    for model in (PlayEventDB, ListeningGapDB, TopTrackDB):
        db.query(model).filter(model.user_id == user.id).delete(synchronize_session=False)
    user.listening_since = user.listening_cursor = None
    user.listening_captured_at = user.top_tracks_captured_at = None


def set_enabled(db: orm.Session, user: UserDB, value: bool) -> None:
    user.listening_enabled = value
    if not value:
        delete_history(db, user)
    db.commit()


def purge(db: orm.Session) -> int:
    """Delete plays (and gaps) older than RETENTION_DAYS."""
    cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
    n = db.query(PlayEventDB).filter(PlayEventDB.played_at < cutoff).delete(synchronize_session=False)
    db.query(ListeningGapDB).filter(ListeningGapDB.gap_end < cutoff).delete(synchronize_session=False)
    db.commit()
    return n


# ---------- import (Extended Streaming History) ----------

@dataclass
class ImportRow:
    ts: datetime
    ms_played: int
    uri: str
    track: str | None
    artist: str | None
    album: str | None
    reason_end: str | None
    skipped: bool | None


def import_plays(db: orm.Session, user: UserDB, rows: list[ImportRow]) -> dict[str, int]:
    """Add plays from the user's Spotify export. Rows already captured from the API (same
    song within a few minutes), duplicates and rows past retention are left out."""
    now = utcnow()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    rows = sorted(
        (r for r in rows if r.ts >= cutoff and r.ts <= now and r.uri.startswith("spotify:track:")),
        key=lambda r: r.ts,
    )
    stats = {"added": 0, "duplicates": 0, "received": len(rows)}
    if not rows:
        return stats
    lo, hi = rows[0].ts - IMPORT_MATCH_WINDOW, rows[-1].ts + IMPORT_MATCH_WINDOW
    taken = set()
    captured: dict[str, list[datetime]] = defaultdict(list)
    for played_at, key, source in db.query(PlayEventDB.played_at, PlayEventDB.song_key, PlayEventDB.source).filter(
        PlayEventDB.user_id == user.id, PlayEventDB.played_at >= lo, PlayEventDB.played_at <= hi
    ):
        taken.add(played_at)
        if source == API and key:
            captured[key].append(played_at)
    for times in captured.values():
        times.sort()

    def near_captured(key, ts) -> bool:
        times = captured.get(key) or []
        i = bisect_left(times, ts - IMPORT_MATCH_WINDOW)
        return i < len(times) and times[i] <= ts + IMPORT_MATCH_WINDOW

    for r in rows:
        track_id = r.uri.split(":")[2][:64]
        title = (r.track or "")[:300] or None
        artists = (r.artist or "")[:500] or None
        key = song_key(title, artists)
        if r.ts in taken or (key and near_captured(key, r.ts)):
            stats["duplicates"] += 1
            continue
        taken.add(r.ts)
        db.add(PlayEventDB(
            user_id=user.id, track_id=track_id, song_key=key, uri=r.uri[:128], title=title, artists=artists,
            album=(r.album or "")[:300] or None, played_at=r.ts, source=IMPORT, ms_played=r.ms_played,
            skipped=r.skipped, reason_end=(r.reason_end or "")[:20] or None,
        ))
        stats["added"] += 1
    first, last = rows[0].ts, rows[-1].ts
    # The export covers [first, last]: earlier gaps inside it are filled now
    db.query(ListeningGapDB).filter(
        ListeningGapDB.user_id == user.id, ListeningGapDB.gap_start >= first, ListeningGapDB.gap_end <= last
    ).delete(synchronize_session=False)
    if user.listening_since is not None and last < user.listening_since:
        # Between the export and the start of captured history, nothing is known
        db.add(ListeningGapDB(user_id=user.id, gap_start=last, gap_end=user.listening_since))
    if user.listening_since is None or first < user.listening_since:
        user.listening_since = first
    if user.listening_cursor is None or last > user.listening_cursor:
        user.listening_cursor = last
    db.commit()
    health.count("listening.imported", stats["added"])
    return stats


# ---------- reading the history ----------

@dataclass
class PlayRow:
    track_id: str
    song_key: str | None
    played_at: datetime
    context_type: str | None
    context_uri: str | None
    source: str
    ms_played: int | None
    skipped: bool | None

    @property
    def counts(self) -> bool:
        """A real listen (captured plays always are; imported ones need 30 s)."""
        return self.ms_played is None or self.ms_played >= logic.PLAY_MIN_MS


def _memo() -> dict:
    ctx = request_context.current()
    return ctx.memo if ctx is not None else {}


def load_plays(db: orm.Session, user: UserDB, since: datetime) -> list[PlayRow]:
    """The user's plays since `since`, oldest first (cached for the request)."""
    memo = _memo()
    cached = memo.get(("plays", user.id))
    if cached is not None and cached[0] <= since:
        return [p for p in cached[1] if p.played_at >= since]
    rows = [
        PlayRow(*r) for r in db.query(
            PlayEventDB.track_id, PlayEventDB.song_key, PlayEventDB.played_at, PlayEventDB.context_type,
            PlayEventDB.context_uri, PlayEventDB.source, PlayEventDB.ms_played, PlayEventDB.skipped,
        ).filter(PlayEventDB.user_id == user.id, PlayEventDB.played_at >= since).order_by(PlayEventDB.played_at)
    ]
    memo[("plays", user.id)] = (since, rows)
    return rows


def top_ranks(db: orm.Session, user: UserDB) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """({track_id: {range: rank}}, {song_key: {range: rank}}) from the latest snapshot."""
    memo = _memo()
    key = ("top", user.id)
    if key in memo:
        return memo[key]
    by_id: dict[str, dict[str, int]] = defaultdict(dict)
    by_key: dict[str, dict[str, int]] = defaultdict(dict)
    for time_range, rank, track_id, skey in db.query(
        TopTrackDB.time_range, TopTrackDB.rank, TopTrackDB.track_id, TopTrackDB.song_key
    ).filter(TopTrackDB.user_id == user.id):
        by_id[track_id][time_range] = rank
        if skey:
            by_key[skey].setdefault(time_range, rank)
            by_key[skey][time_range] = min(by_key[skey][time_range], rank)
    memo[key] = (dict(by_id), dict(by_key))
    return memo[key]


def gaps(db: orm.Session, user: UserDB, since: datetime) -> list[tuple[datetime, datetime]]:
    return [
        (a, b) for a, b in db.query(ListeningGapDB.gap_start, ListeningGapDB.gap_end)
        .filter(ListeningGapDB.user_id == user.id, ListeningGapDB.gap_end >= since)
    ]


class PlayIndex:
    """Plays looked up by track id or by song (relinked and re-released copies match)."""

    def __init__(self, plays: list[PlayRow]):
        self.by_id: dict[str, list[PlayRow]] = defaultdict(list)
        self.by_key: dict[str, list[PlayRow]] = defaultdict(list)
        for p in plays:
            self.by_id[p.track_id].append(p)
            if p.song_key:
                self.by_key[p.song_key].append(p)

    def find(self, track_id: str, title: str | None, artists: str | None) -> list[PlayRow]:
        found = {p.played_at: p for p in self.by_id.get(track_id, ())}
        key = song_key(title, artists)
        for p in self.by_key.get(key, ()) if key else ():
            found.setdefault(p.played_at, p)
        return [found[t] for t in sorted(found)]


def top_for(ranks, track_id: str, title: str | None, artists: str | None) -> dict[str, int]:
    by_id, by_key = ranks
    found = dict(by_id.get(track_id) or {})
    key = song_key(title, artists)
    for time_range, rank in (by_key.get(key) or {}).items() if key else ():
        found[time_range] = min(rank, found.get(time_range, rank))
    return found


def context_matches(rotation: RotationDB, context_type: str | None, context_uri: str | None) -> bool:
    """The play came from this rotation's playlist (or, for Liked Songs, the library)."""
    if is_liked(rotation):
        return context_type == "collection"
    return context_uri == f"spotify:playlist:{rotation.playlist_id}"


def for_rotation(rotation: RotationDB, rows: list, now: datetime) -> logic.RotationListening:
    """Listening stats for these rows of the rotation, over its window (cached per request)."""
    window = logic.window_days(rotation.interval_hours)
    result = logic.RotationListening(window_days=window)
    db = orm.object_session(rotation)
    user = rotation.owner
    if db is None or user is None or not enabled(user) or not rows:
        return result
    memo = _memo()
    key = ("rotation", rotation.id, tuple(sorted(r.id for r in rows)))
    if key in memo:
        return memo[key]
    start = now - timedelta(days=window)
    plays = [p for p in load_plays(db, user, start) if p.played_at <= now]
    index = PlayIndex(plays)
    ranks = top_ranks(db, user)
    result.plays_here = sum(1 for p in plays if p.counts and context_matches(rotation, p.context_type, p.context_uri))
    result.confident = logic.is_confident(user.listening_since, gaps(db, user, start), start, now)
    for row in rows:
        s = logic.SongListening(top_rank=top_for(ranks, row.track_id, row.title, row.artists))
        for p in index.find(row.track_id, row.title, row.artists):
            if p.source == IMPORT:
                s.starts += 1
                if p.skipped or not p.counts:
                    s.skips += 1
            if not p.counts:
                continue
            s.plays += 1
            if context_matches(rotation, p.context_type, p.context_uri):
                s.plays_here += 1
            s.last_played_at = p.played_at
        result.songs[row.id] = s
    logic.assess(
        result.songs, plays_here=result.plays_here, confident=result.confident, size=len(rows),
        in_playlist_since={r.id: r.added_at or rotation.created_at for r in rows}, window_start=start,
    )
    memo[key] = result
    return result


def song_plays(db: orm.Session, user: UserDB, metas: list[dict[str, Any]], days: int = 28) -> dict[str, dict]:
    """{track_id: {"plays", "last_played_at", "window_days"}} for songs with plays in the last
    `days` (restock cards)."""
    if not enabled(user) or not metas:
        return {}
    now = utcnow()
    index = PlayIndex([p for p in load_plays(db, user, now - timedelta(days=days)) if p.counts])
    out = {}
    for meta in metas:
        found = index.find(meta["track_id"], meta.get("title"), meta.get("artists"))
        if found:
            out[meta["track_id"]] = {"plays": len(found), "last_played_at": found[-1].played_at, "window_days": days}
    return out


def plays_since(db: orm.Session, user: UserDB, rows: list) -> dict[int, tuple[int, bool]]:
    """{row id: (plays anywhere since it was removed, a current top track)} for removed rows."""
    if not enabled(user) or not rows:
        return {}
    now = utcnow()
    oldest = min((r.removed_at for r in rows if r.removed_at), default=now)
    index = PlayIndex([p for p in load_plays(db, user, max(oldest, now - timedelta(days=RETENTION_DAYS))) if p.counts])
    ranks = top_ranks(db, user)
    out = {}
    for r in rows:
        since = r.removed_at or datetime.min
        n = sum(1 for p in index.find(r.track_id, r.title, r.artists) if p.played_at > since)
        top = any(k in logic.HEAVY_TOP_RANGES for k in top_for(ranks, r.track_id, r.title, r.artists))
        out[r.id] = (n, top)
    return out


def status(db: orm.Session, user: UserDB) -> dict[str, Any]:
    count = db.query(PlayEventDB).filter(PlayEventDB.user_id == user.id).count()
    imported = db.query(PlayEventDB.id).filter(
        PlayEventDB.user_id == user.id, PlayEventDB.source == IMPORT
    ).first() is not None
    return {
        "enabled": enabled(user),
        "since": user.listening_since,
        "last_captured_at": user.listening_captured_at,
        "plays": count,
        "has_import": imported,
        "missing_scopes": missing_scopes(user, ["user-read-recently-played", "user-top-read"]),
    }
