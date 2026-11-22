"""Restocking a rotation: the four sources, adding a song, and "Not now" feedback.

Spotify stays the source of truth: adding a song writes it to the playlist right away
and upserts its rotation_track row so it's in rotation immediately (the next sync
reconciles anything else).
"""
import logging
import random
from collections import Counter
from datetime import timedelta
from typing import Any, Dict, List, Optional

import httpx
import sqlalchemy.orm as orm
from fastapi import HTTPException
from sqlalchemy import func

from rest_api.clock import to_naive_utc, utcnow
from rest_api.database.models.curated_pick import CuratedPickDB
from rest_api.database.models.restock_feedback import (
    ADD,
    BRING_BACK,
    PICKS,
    SKIP,
    SUGGESTED,
    RestockFeedbackDB,
)
from rest_api.database.models.review_event import KEEP, ReviewEventDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.rotation_track import ACTIVE, PENDING_REMOVAL, REMOVED, RotationTrackDB
from rest_api.database.models.suggestion_cache import SuggestionCacheDB
from rest_api.database.models.user import UserDB
from rest_api.models.restock import CandidateOut, DeckOut, SearchOut
from rest_api.services import restock_logic as logic
from rest_api.services.auth_service import SUGGESTION_SCOPES, missing_scopes
from rest_api.services.db.rotation_service import track_out
from rest_api.services.rotation_logic import local_day_start
from rest_api.services.spotify.spotify_service import SpotifyAPIError, SpotifyService as ss

logger = logging.getLogger(__name__)

SUGGESTION_CACHE_HOURS = 6
LIKED_RECENT_PAGES = 4  # newest 200 liked songs...
SEED_ARTISTS = 5  # ...plus searches from the top 5 artists
SEED_ALBUMS = 3  # ...and the 3 albums the user plays most


# ---------- shared lookups ----------

def _today(tz_offset_minutes: int):
    return local_day_start(utcnow(), tz_offset_minutes)


def _rotation_rows(db: orm.Session, rotation: RotationDB) -> Dict[str, RotationTrackDB]:
    return {r.track_id: r for r in db.query(RotationTrackDB).filter(RotationTrackDB.rotation_id == rotation.id)}


def _in_other_rotations(db: orm.Session, user: UserDB, rotation: RotationDB) -> set:
    rows = (
        db.query(RotationTrackDB.track_id)
        .join(RotationDB, RotationTrackDB.rotation_id == RotationDB.id)
        .filter(
            RotationDB.owner_id == user.id,
            RotationDB.id != rotation.id,
            RotationTrackDB.status.in_((ACTIVE, PENDING_REMOVAL)),
        )
    )
    return {track_id for (track_id,) in rows}


def _skip_counts(db: orm.Session, user: UserDB) -> Counter:
    """All-time "Not now" count per track for this user (any source, any rotation)."""
    rows = (
        db.query(RestockFeedbackDB.track_id, func.count())
        .filter(RestockFeedbackDB.user_id == user.id, RestockFeedbackDB.action == SKIP)
        .group_by(RestockFeedbackDB.track_id)
    )
    return Counter({track_id: n for track_id, n in rows})


def _skipped_since(db: orm.Session, user: UserDB, since) -> set:
    rows = db.query(RestockFeedbackDB.track_id).filter(
        RestockFeedbackDB.user_id == user.id,
        RestockFeedbackDB.action == SKIP,
        RestockFeedbackDB.created_at >= since,
    )
    return {track_id for (track_id,) in rows}


def _seed(user: UserDB, rotation: RotationDB, source: str, day_start) -> int:
    return logic.daily_seed(user.id, rotation.id, source, day_start.date().isoformat())


def _candidate(meta: Dict[str, Any], source: str, **extra) -> CandidateOut:
    return CandidateOut(
        track_id=meta["track_id"],
        uri=meta["uri"],
        title=meta["title"],
        artists=meta.get("artists"),
        album=meta.get("album"),
        image_url=meta.get("image_url"),
        duration_ms=meta.get("duration_ms"),
        source=source,
        **extra,
    )


def _row_meta(row) -> Dict[str, Any]:
    return {
        "track_id": row.track_id, "uri": row.uri, "title": row.title, "artists": row.artists,
        "album": row.album, "image_url": row.image_url, "duration_ms": row.duration_ms,
    }


# ---------- 1. bring back ----------

def bring_back_deck(db: orm.Session, rotation: RotationDB, user: UserDB, tz_offset_minutes: int = 0) -> DeckOut:
    now = utcnow()
    today = _today(tz_offset_minutes)
    skipped_today = _skipped_since(db, user, today)
    skips = _skip_counts(db, user)
    removed = [
        r for r in db.query(RotationTrackDB).filter(
            RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.status == REMOVED
        )
        if r.track_id not in skipped_today
    ]
    keeps = Counter({
        row_id: n for row_id, n in db.query(ReviewEventDB.rotation_track_id, func.count())
        .filter(ReviewEventDB.rotation_track_id.in_([r.id for r in removed]), ReviewEventDB.action == KEEP)
        .group_by(ReviewEventDB.rotation_track_id)
    }) if removed else Counter()

    weights = [logic.bring_back_weight(r.removed_at, now, skips[r.track_id], keeps[r.id]) for r in removed]
    ordered = logic.weighted_order(list(zip(removed, weights)), weights, _seed(user, rotation, BRING_BACK, today))
    return DeckOut(source=BRING_BACK, items=[
        _candidate(_row_meta(r), BRING_BACK, score=round(w, 4),
                   reason=logic.bring_back_reason(r.removed_at, now, keeps[r.id]))
        for r, w in ordered[:logic.DECK_SIZE]
    ])


# ---------- 2. PlayLS picks ----------

def active_picks_query(db: orm.Session, now):
    return db.query(CuratedPickDB).filter(
        (CuratedPickDB.starts_at.is_(None)) | (CuratedPickDB.starts_at <= now),
        (CuratedPickDB.ends_at.is_(None)) | (CuratedPickDB.ends_at > now),
    )


def picks_deck(db: orm.Session, rotation: RotationDB, user: UserDB, tz_offset_minutes: int = 0) -> DeckOut:
    now = utcnow()
    rows = _rotation_rows(db, rotation)
    skipped_today = _skipped_since(db, user, _today(tz_offset_minutes))
    skips = _skip_counts(db, user)
    seen, picks = set(), []
    for pick in active_picks_query(db, now).order_by(CuratedPickDB.created_at.desc(), CuratedPickDB.id.desc()):
        row = rows.get(pick.track_id)
        if pick.track_id in seen or pick.track_id in skipped_today or (row and row.status != REMOVED):
            continue
        seen.add(pick.track_id)
        picks.append(pick)
    # Newest first, but songs the user has passed on before sink to the back
    picks.sort(key=lambda p: skips[p.track_id])
    return DeckOut(source=PICKS, items=[
        _candidate(_row_meta(p), PICKS, note=p.note, reason=p.note or "PlayLS pick")
        for p in picks[:logic.DECK_SIZE]
    ])


# ---------- 3. suggested for you ----------

async def _safe(label: str, coro):
    """Run one signal source; a failure (or missing scope) skips it instead of failing the deck."""
    try:
        return await coro
    except (SpotifyAPIError, httpx.HTTPError):
        logger.warning("Suggestion source %s failed", label, exc_info=True)
        return None


async def _gather_signals(db: orm.Session, user: UserDB) -> Dict[str, Any]:
    """Collect listening signals from Spotify into {track_id: {meta, features}} (about 15–20 calls)."""
    missing = missing_scopes(user, SUGGESTION_SCOPES)
    candidates: Dict[str, Dict[str, Any]] = {}

    def add(item, **features):
        meta = logic.track_meta(item)
        if meta is None:
            return None
        entry = candidates.setdefault(meta["track_id"], {"meta": meta, "features": {}})
        f = entry["features"]
        for key, value in features.items():
            if key == "top":
                f.setdefault("top", {}).update(value)
            elif key == "recent_plays":
                f["recent_plays"] = f.get("recent_plays", 0) + value
            elif key in ("discovery", "seed"):
                f.setdefault(key, value)  # first seed wins
            else:
                f[key] = value
        return meta

    top_tracks: Dict[str, List[Dict]] = {}
    artist_rank: Dict[str, int] = {}
    artist_names: List[str] = []

    if "user-top-read" not in missing:
        for window in ("short_term", "medium_term", "long_term"):
            page = await _safe(f"top:{window}", ss.get_top_items("tracks", user, db, time_range=window))
            items = (page or {}).get("items") or []
            top_tracks[window] = items
            for rank, item in enumerate(items):
                add(item, top={window: rank})
        page = await _safe("top:artists", ss.get_top_items("artists", user, db, time_range="medium_term", limit=20))
        artists = (page or {}).get("items") or []
        for rank, artist in enumerate(artists):
            if artist.get("id"):
                artist_rank.setdefault(artist["id"], rank)
            if artist.get("name"):
                artist_names.append(artist["name"])

    if "user-read-recently-played" not in missing:
        page = await _safe("recent", ss.get_recently_played(user, db))
        for entry in (page or {}).get("items") or []:
            add(entry.get("track"), recent_plays=1)

    if "user-library-read" not in missing:
        total = None
        for i in range(LIKED_RECENT_PAGES):
            page = await _safe(f"liked:{i}", ss.get_saved_tracks(user, db, offset=i * 50))
            if not page:
                break
            total = page.get("total")
            for entry in page.get("items") or []:
                add(entry.get("track"), liked_at=entry.get("added_at"))
            if not page.get("next"):
                break
        # One random page from deeper in the library, so old favorites resurface too
        if total and total > LIKED_RECENT_PAGES * 50:
            offset = random.randrange(LIKED_RECENT_PAGES * 50, total, 50)
            page = await _safe("liked:deep", ss.get_saved_tracks(user, db, offset=offset))
            for entry in (page or {}).get("items") or []:
                add(entry.get("track"), liked_at=entry.get("added_at"))

    # Discoveries: search from the user's favorite artists and most-played albums
    clean = lambda s: s.replace('"', "").strip()
    for name in logic.dedupe(artist_names)[:SEED_ARTISTS]:
        result = await _safe(f"search:artist:{name}", ss.search(f'artist:"{clean(name)}"', user, db, "track", 10))
        for item in ((result or {}).get("tracks") or {}).get("items") or []:
            add(item, discovery="artist", seed=name)

    album_counts: Counter = Counter()
    album_info: Dict[str, tuple] = {}
    for window in ("short_term", "medium_term"):
        for item in top_tracks.get(window, []):
            album = item.get("album") or {}
            if album.get("id") and album.get("album_type", "album") != "single":
                album_counts[album["id"]] += 1
                artist = ((album.get("artists") or item.get("artists") or [{}])[0]).get("name", "")
                album_info[album["id"]] = (album.get("name") or "", artist)
    for album_id, _ in album_counts.most_common(SEED_ALBUMS):
        album_name, artist = album_info[album_id]
        q = f'album:"{clean(album_name)}"' + (f' artist:"{clean(artist)}"' if artist else "")
        result = await _safe(f"search:album:{album_name}", ss.search(q, user, db, "track", 10))
        for item in ((result or {}).get("tracks") or {}).get("items") or []:
            add(item, discovery="album", seed=album_name)

    for entry in candidates.values():
        ranks = [artist_rank[a] for a in entry["meta"].get("artist_ids", []) if a in artist_rank]
        if ranks:
            entry["features"]["artist_rank"] = min(ranks)
            entry["features"]["artist_rank_total"] = max(len(artist_rank), 1)

    return {"candidates": candidates, "missing_scopes": missing}


async def suggestion_signals(db: orm.Session, user: UserDB, refresh: bool = False) -> Dict[str, Any]:
    """Cached listening signals (refreshed every few hours, or on demand)."""
    cache = db.get(SuggestionCacheDB, user.id)
    fresh = cache and cache.created_at > utcnow() - timedelta(hours=SUGGESTION_CACHE_HOURS)
    # Re-gather if the cache predates a reconnect that granted new scopes
    if fresh and not refresh and cache.payload.get("missing_scopes") == missing_scopes(user, SUGGESTION_SCOPES):
        return cache.payload
    payload = await _gather_signals(db, user)
    if cache is None:
        db.add(SuggestionCacheDB(user_id=user.id, payload=payload, created_at=utcnow()))
    else:
        cache.payload = payload
        cache.created_at = utcnow()
    db.commit()
    return payload


async def suggested_deck(
    db: orm.Session, rotation: RotationDB, user: UserDB, tz_offset_minutes: int = 0, refresh: bool = False
) -> DeckOut:
    payload = await suggestion_signals(db, user, refresh)
    now = utcnow()
    today = _today(tz_offset_minutes)
    rows = _rotation_rows(db, rotation)  # in rotation, or removed from it (that's "bring back")
    skipped_today = _skipped_since(db, user, today)
    skips = _skip_counts(db, user)
    elsewhere = _in_other_rotations(db, user, rotation)

    known, discoveries = [], []
    for track_id, entry in payload["candidates"].items():
        if track_id in rows or track_id in skipped_today:
            continue
        score, reason = logic.score_suggestion(
            entry["features"], skips[track_id], track_id in elsewhere, now
        )
        if score <= 0:
            continue
        item = (_candidate(entry["meta"], SUGGESTED, reason=reason, score=round(score, 4)), score)
        (discoveries if logic.is_discovery(entry["features"]) else known).append(item)

    seed = _seed(user, rotation, SUGGESTED, today)
    order = lambda items, salt: [c for c, _ in logic.weighted_order(items, [s for _, s in items], seed + salt)]
    deck = logic.blend(order(known, 0), order(discoveries, 1), logic.DECK_SIZE)
    return DeckOut(source=SUGGESTED, items=deck, missing_scopes=payload.get("missing_scopes", []))


# ---------- 4. search ----------

async def search(db: orm.Session, rotation: RotationDB, user: UserDB, q: str, offset: int = 0) -> SearchOut:
    result = await ss.search(q, user, db, "track", 10, offset)
    page = (result or {}).get("tracks") or {}
    rows = _rotation_rows(db, rotation)
    items = []
    for item in page.get("items") or []:
        meta = logic.track_meta(item)
        if meta is None:
            continue
        row = rows.get(meta["track_id"])
        items.append(_candidate(meta, "search", in_rotation=bool(row and row.status != REMOVED)))
    next_offset = offset + 10 if page.get("next") and offset + 10 <= 1000 else None
    return SearchOut(items=items, next_offset=next_offset)


# ---------- actions ----------

async def _resolve_meta(db: orm.Session, user: UserDB, track_id: str, row: Optional[RotationTrackDB]):
    if row is not None:
        return _row_meta(row)
    pick = db.query(CuratedPickDB).filter(CuratedPickDB.track_id == track_id).first()
    if pick is not None:
        return _row_meta(pick)
    cache = db.get(SuggestionCacheDB, user.id)
    cached = ((cache.payload if cache else {}) or {}).get("candidates", {}).get(track_id)
    if cached:
        return cached["meta"]
    try:
        meta = logic.track_meta(await ss.get_track(track_id, user, db))
    except SpotifyAPIError as e:
        if e.upstream_status in (400, 404):
            raise HTTPException(status_code=404, detail="Track not found")
        raise
    if meta is None:
        raise HTTPException(status_code=400, detail="Only Spotify tracks can be added")
    return meta


async def add_to_rotation(db: orm.Session, rotation: RotationDB, user: UserDB, track_id: str, source: str):
    """Add a song to the rotation's Spotify playlist now, and to the rotation itself."""
    row = db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.track_id == track_id
    ).first()
    if row is not None and row.status in (ACTIVE, PENDING_REMOVAL):
        raise HTTPException(status_code=409, detail="That song is already in this rotation")
    meta = await _resolve_meta(db, user, track_id, row)

    await ss.add_items_to_playlist(rotation.playlist_id, [meta["uri"]], user, db)

    now = utcnow()
    if row is None:
        row = RotationTrackDB(rotation_id=rotation.id, track_id=track_id)
        db.add(row)
    row.uri, row.title, row.artists = meta["uri"], meta["title"], meta.get("artists")
    row.album, row.image_url, row.duration_ms = meta.get("album"), meta.get("image_url"), meta.get("duration_ms")
    # A fresh start: comes due one interval from now
    row.status, row.added_at, row.last_kept_at = ACTIVE, now, None
    row.removed_at = row.removed_by = None
    db.add(RestockFeedbackDB(
        user_id=user.id, rotation_id=rotation.id, track_id=track_id, source=source, action=ADD, created_at=now,
    ))
    db.commit()
    db.refresh(row)
    return track_out(row, rotation)


def record_skip(db: orm.Session, rotation: RotationDB, user: UserDB, track_id: str, source: str) -> None:
    """"Not now": hides the song for the rest of today and halves its future weight."""
    db.add(RestockFeedbackDB(
        user_id=user.id, rotation_id=rotation.id, track_id=track_id, source=source, action=SKIP,
        created_at=utcnow(),
    ))
    db.commit()


# ---------- curation (admin) ----------

async def create_pick(db: orm.Session, admin: UserDB, track_id: str, note, starts_at, ends_at) -> CuratedPickDB:
    try:
        meta = logic.track_meta(await ss.get_track(track_id, admin, db))
    except SpotifyAPIError as e:
        if e.upstream_status in (400, 404):
            raise HTTPException(status_code=404, detail="Track not found")
        raise
    if meta is None:
        raise HTTPException(status_code=400, detail="Only Spotify tracks can be picks")
    starts_at = to_naive_utc(starts_at) if starts_at else None
    ends_at = to_naive_utc(ends_at) if ends_at else None
    if starts_at and ends_at and ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    pick = CuratedPickDB(
        track_id=meta["track_id"], uri=meta["uri"], title=meta["title"], artists=meta.get("artists"),
        album=meta.get("album"), image_url=meta.get("image_url"), duration_ms=meta.get("duration_ms"),
        note=note, starts_at=starts_at, ends_at=ends_at, created_by=admin.id, created_at=utcnow(),
    )
    db.add(pick)
    db.commit()
    db.refresh(pick)
    return pick
