"""Auto rotations: rotate songs out on schedule and restock the playlist to its target size.

`maintain` runs after a successful sync (whenever the app opens a rotation) and from the
daily cron job, so a playlist keeps turning over even if the owner only listens in Spotify.
New songs come from the same sources as manual restocking: For you (scored listening
signals), the occasional PlayLS pick, and songs that rotated out at least
RETURN_COOLDOWN_DAYS ago (weighted by the bring-back rules).
"""
import logging
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

import sqlalchemy.orm as orm
from sqlalchemy import func

from rest_api.clock import utcnow
from rest_api.database.models.curated_pick import CuratedPickDB
from rest_api.database.models.restock_feedback import ADD, BRING_BACK, PICKS, SUGGESTED, RestockFeedbackDB
from rest_api.database.models.review_event import AUTO_ADDED, KEEP, ROTATED_OUT, ReviewEventDB
from rest_api.database.models.rotation import AUTO, RotationDB
from rest_api.database.models.rotation_track import (
    ACTIVE,
    PENDING_REMOVAL,
    REMOVED,
    REMOVED_BY_ROTATION,
    RotationTrackDB,
)
from rest_api.database.models.user import UserDB
from rest_api.services import auto_rotation_logic as auto
from rest_api.services import restock_logic
from rest_api.services import restock_service as rsv
from rest_api.services.spotify.spotify_service import SpotifyService as ss

logger = logging.getLogger(__name__)


@dataclass
class MaintainResult:
    rotated_out: int = 0
    added: int = 0
    short_by: int = 0  # slots that couldn't be filled (not enough candidates)
    sources: Dict[str, int] = field(default_factory=dict)


def _active(db: orm.Session, rotation: RotationDB) -> List[RotationTrackDB]:
    return db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.status == ACTIVE
    ).all()


# ---------- choosing new songs ----------

async def choose_additions(
    db: orm.Session, rotation: RotationDB, user: UserDB, slots: int, now
) -> List[Dict[str, Any]]:
    """Up to `slots` new songs as [{meta, source}], mixed across the three sources."""
    if slots <= 0:
        return []
    rows = rsv._rotation_rows(db, rotation)
    blocked = rsv._blocked(db, user)
    skips = rsv._skip_counts(db, user)
    rng = random.Random(restock_logic.daily_seed(user.id, rotation.id, "auto", now.isoformat()))
    taken: set = set()

    # Bring back: songs that left at least the cooldown ago
    removed = [
        r for r in rows.values()
        if r.status == REMOVED and r.is_playable and r.track_id not in blocked
        and auto.cooled_down(r.removed_at, now)
    ]
    keeps = Counter({
        row_id: n for row_id, n in db.query(ReviewEventDB.rotation_track_id, func.count())
        .filter(ReviewEventDB.rotation_track_id.in_([r.id for r in removed]), ReviewEventDB.action == KEEP)
        .group_by(ReviewEventDB.rotation_track_id)
    }) if removed else Counter()
    back_weights = [restock_logic.bring_back_weight(r.removed_at, now, skips[r.track_id], keeps[r.id]) for r in removed]
    back = [rsv._row_meta(r) for r in restock_logic.weighted_order(removed, back_weights, rng.randrange(2**32))]

    # PlayLS picks that are live and not in (or recently out of) this rotation
    picks, seen = [], set()
    for pick in rsv.active_picks_query(db, now).order_by(CuratedPickDB.created_at.desc(), CuratedPickDB.id.desc()):
        row = rows.get(pick.track_id)
        if pick.track_id in seen or pick.track_id in blocked:
            continue
        if row is not None and (row.status != REMOVED or not auto.cooled_down(row.removed_at, now)):
            continue
        seen.add(pick.track_id)
        picks.append(pick)
    picks.sort(key=lambda p: skips[p.track_id])
    pick_metas = [rsv._row_meta(p) for p in picks]

    # For you: scored listening signals (anything this rotation ever held is handled above)
    payload = await rsv.suggestion_signals(db, user)
    elsewhere = rsv._in_other_rotations(db, user, rotation)
    known, discoveries = [], []
    for track_id, entry in payload["candidates"].items():
        if track_id in rows or track_id in blocked:
            continue
        score, _ = restock_logic.score_suggestion(entry["features"], skips[track_id], track_id in elsewhere, now)
        if score <= 0:
            continue
        (discoveries if restock_logic.is_discovery(entry["features"]) else known).append((entry["meta"], score))
    order = lambda items: restock_logic.weighted_order(
        [m for m, _ in items], [s for _, s in items], rng.randrange(2**32)
    )
    for_you = restock_logic.blend(order(known), order(discoveries), len(known) + len(discoveries))

    # Picks and bring-back songs can also turn up in For you; don't double count them
    pick_ids = {m["track_id"] for m in pick_metas}
    for_you = [m for m in for_you if m["track_id"] not in pick_ids]

    counts = auto.allocate(slots, len(pick_metas), len(back), len(for_you), rng)
    chosen: List[Dict[str, Any]] = []
    for source, pool in ((PICKS, pick_metas), (BRING_BACK, back), (SUGGESTED, for_you)):
        want = counts["picks" if source == PICKS else "bring_back" if source == BRING_BACK else "suggested"]
        for meta in pool:
            if want <= 0:
                break
            if meta["track_id"] in taken:
                continue
            taken.add(meta["track_id"])
            chosen.append({"meta": meta, "source": source})
            want -= 1
    # Interleave so a restock doesn't land as a block of picks followed by a block of For you
    rng.shuffle(chosen)
    return chosen


# ---------- applying ----------

async def _rotate_out(db: orm.Session, rotation: RotationDB, user: UserDB, leaving: List[RotationTrackDB], now) -> None:
    if not leaving:
        return
    await ss.remove_items_from_playlist(rotation.playlist_id, [t.uri for t in leaving], user, db)
    for track in leaving:
        track.status = REMOVED
        track.removed_at = now
        track.removed_by = REMOVED_BY_ROTATION
        db.add(ReviewEventDB(rotation_track_id=track.id, action=ROTATED_OUT, created_at=now))
    db.commit()


async def _add(db: orm.Session, rotation: RotationDB, user: UserDB, chosen: List[Dict[str, Any]], now) -> None:
    if not chosen:
        return
    await ss.add_items_to_playlist(rotation.playlist_id, [c["meta"]["uri"] for c in chosen], user, db)
    rows = rsv._rotation_rows(db, rotation)
    for c in chosen:
        meta = c["meta"]
        row = rows.get(meta["track_id"])
        if row is None:
            row = RotationTrackDB(rotation_id=rotation.id, track_id=meta["track_id"])
            db.add(row)
        row.uri, row.title, row.artists = meta["uri"], meta["title"], meta.get("artists")
        row.album, row.image_url, row.duration_ms = meta.get("album"), meta.get("image_url"), meta.get("duration_ms")
        row.status, row.added_at, row.last_kept_at, row.keep_multiplier = ACTIVE, now, None, 1
        row.removed_at = row.removed_by = None
        row.is_playable = True
        db.flush()
        db.add(ReviewEventDB(rotation_track_id=row.id, action=AUTO_ADDED, created_at=now))
        db.add(RestockFeedbackDB(
            user_id=user.id, rotation_id=rotation.id, track_id=meta["track_id"], source=c["source"],
            action=ADD, created_at=now,
        ))
    db.commit()


async def maintain(db: orm.Session, rotation: RotationDB, user: UserDB, now=None) -> MaintainResult:
    """Rotate out if a rotation is due, then fill the playlist back up to its target.

    Call after a successful sync, so the rows match Spotify. A rotation that was missed
    (nobody opened the app and the cron didn't run) happens once, not once per missed period.
    """
    result = MaintainResult()
    if rotation.kind != AUTO:
        return result
    now = now or utcnow()

    # Nothing pending should be left after the sync's flush; if something is, wait for it
    pending = db.query(RotationTrackDB).filter(
        RotationTrackDB.rotation_id == rotation.id, RotationTrackDB.status == PENDING_REMOVAL
    ).count()
    if pending:
        return result

    active = _active(db, rotation)
    if auto.is_rotation_due(rotation, now):
        previous = rotation.last_rotated_at
        # Claim this rotation first, so a concurrent request or the cron can't rotate it twice
        claimed = db.query(RotationDB).filter(
            RotationDB.id == rotation.id,
            RotationDB.last_rotated_at.is_(None) if previous is None else RotationDB.last_rotated_at == previous,
        ).update({RotationDB.last_rotated_at: now}, synchronize_session=False)
        db.commit()
        db.refresh(rotation)
        if not claimed:
            return result
        # Leaving order uses the period that just ended
        rotation.last_rotated_at = previous
        leaving = auto.choose_rotate_out(active, rotation, now)
        rotation.last_rotated_at = now
        try:
            await _rotate_out(db, rotation, user, leaving, now)
        except Exception:
            db.rollback()
            # Give the claim back so the next sync retries
            db.query(RotationDB).filter(RotationDB.id == rotation.id).update(
                {RotationDB.last_rotated_at: previous}, synchronize_session=False
            )
            db.commit()
            db.refresh(rotation)
            raise
        result.rotated_out = len(leaving)
        leaving_ids = {t.id for t in leaving}
        active = [t for t in active if t.id not in leaving_ids]

    slots = rotation.target_size - len(active)
    if slots > 0:
        chosen = await choose_additions(db, rotation, user, slots, now)
        await _add(db, rotation, user, chosen, now)
        result.added = len(chosen)
        result.short_by = slots - len(chosen)
        result.sources = dict(Counter(c["source"] for c in chosen))
    if result.rotated_out or result.added:
        logger.info(
            "Auto rotation %s: rotated out %d, added %d %s", rotation.id, result.rotated_out, result.added,
            result.sources,
        )
    return result


async def run_all(db: orm.Session) -> Dict[str, int]:
    """Cron entry point: sync and maintain every auto rotation. One failure doesn't stop the rest."""
    from rest_api.services.db.rotation_service import try_sync

    stats = Counter()
    ids = [rid for (rid,) in db.query(RotationDB.id).filter(RotationDB.kind == AUTO).order_by(RotationDB.id)]
    for rotation_id in ids:
        rotation = db.get(RotationDB, rotation_id)
        if rotation is None:
            continue
        stats["rotations"] += 1
        # try_sync also runs maintain
        if await try_sync(db, rotation, rotation.owner):
            stats["ok"] += 1
        else:
            stats["failed"] += 1
    return dict(stats)
