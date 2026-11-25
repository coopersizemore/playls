"""Read-only listening reports for a rotation: plays around history events, daily digests,
restock outcomes and the monthly recap. All from stored history (no Spotify calls)."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import sqlalchemy.orm as orm

from rest_api.clock import utcnow
from rest_api.database.models.restock_feedback import ADD, RestockFeedbackDB
from rest_api.database.models.review_event import KEEP_ACTIONS, REMOVE, ReviewEventDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.rotation_track import RotationTrackDB
from rest_api.database.models.user import UserDB
from rest_api.services import listening_service as ls

HISTORY_WINDOW_INTERVALS = 2  # "N plays in the last 2 intervals" on kept / removed events


def _local_date(at: datetime, tz_offset_minutes: int) -> str:
    return (at - timedelta(minutes=tz_offset_minutes)).date().isoformat()


def event_plays(
    db: orm.Session, rotation: RotationDB, events: list[tuple[ReviewEventDB, RotationTrackDB]]
) -> dict[int, tuple[int | None, int, int | None]]:
    """{event id: (plays before, window hours, plays since)} for keeps and removals.

    `before` is the song's plays (anywhere) in the two intervals before the event, and None
    when the history doesn't reach that far back. `since` (removals only) is None when the
    history started after the removal.
    """
    user = rotation.owner
    wanted = [(e, t) for e, t in events if e.action in (*KEEP_ACTIONS, REMOVE)]
    if not wanted or not ls.enabled(user) or user.listening_since is None:
        return {}
    window = timedelta(hours=rotation.interval_hours * HISTORY_WINDOW_INTERVALS)
    now = utcnow()
    earliest = max(min(e.created_at for e, _ in wanted) - window, now - timedelta(days=ls.RETENTION_DAYS))
    index = ls.PlayIndex([p for p in ls.load_plays(db, user, earliest) if p.counts])
    out = {}
    for event, track in wanted:
        plays = index.find(track.track_id, track.title, track.artists)
        start = event.created_at - window
        before = (
            sum(1 for p in plays if start <= p.played_at < event.created_at)
            if user.listening_since <= start else None
        )
        since = None
        if event.action == REMOVE and user.listening_since <= event.created_at:
            since = sum(1 for p in plays if p.played_at > event.created_at)
        out[event.id] = (before, int(window.total_seconds() // 3600), since)
    return out


def digest(db: orm.Session, rotation: RotationDB, days: int = 30, tz_offset_minutes: int = 0) -> dict:
    """Daily listening for this rotation, newest day first: plays from its playlist, and plays
    of its songs from anywhere else."""
    user = rotation.owner
    if not ls.enabled(user):
        return {"since": None, "days": []}
    now = utcnow()
    rows = db.query(RotationTrackDB).filter(RotationTrackDB.rotation_id == rotation.id).all()
    plays = [p for p in ls.load_plays(db, user, now - timedelta(days=days)) if p.counts]
    index = ls.PlayIndex(plays)

    def new_day():
        return {"here": 0, "elsewhere": 0, "songs": Counter(), "songs_here": Counter()}

    per_day: dict[str, dict] = defaultdict(new_day)
    seen = set()
    for row in rows:
        for p in index.find(row.track_id, row.title, row.artists):
            if p.played_at in seen:
                continue
            seen.add(p.played_at)
            day = per_day[_local_date(p.played_at, tz_offset_minutes)]
            here = ls.context_matches(rotation, p.context_type, p.context_uri)
            day["here" if here else "elsewhere"] += 1
            day["songs"][row.id] += 1
            if here:
                day["songs_here"][row.id] += 1
    # Plays from the playlist of songs it no longer has a row for still count as "here"
    for p in plays:
        if p.played_at not in seen and ls.context_matches(rotation, p.context_type, p.context_uri):
            per_day[_local_date(p.played_at, tz_offset_minutes)]["here"] += 1
    rows_by_id = {r.id: r for r in rows}
    out = []
    for date in sorted(per_day, reverse=True):
        day = per_day[date]
        out.append({
            "date": date,
            "plays_here": day["here"],
            "plays_elsewhere": day["elsewhere"],
            "songs": [
                {"track_id": rows_by_id[rid].track_id, "title": rows_by_id[rid].title,
                 "artists": rows_by_id[rid].artists, "image_url": rows_by_id[rid].image_url,
                 "plays": n, "plays_here": day["songs_here"][rid]}
                for rid, n in sorted(day["songs"].items(), key=lambda kv: (-kv[1], rows_by_id[kv[0]].title or ""))
            ],
        })
    return {"since": user.listening_since, "days": out}


def restock_outcomes(db: orm.Session, rotation: RotationDB, user: UserDB, days: int = 90) -> dict:
    """Of the songs added to this rotation in the last `days`, how many have been played
    since (anywhere), overall and by source. Display only: it changes no scoring."""
    now = utcnow()
    since = now - timedelta(days=days)
    adds = db.query(RestockFeedbackDB).filter(
        RestockFeedbackDB.rotation_id == rotation.id, RestockFeedbackDB.action == ADD,
        RestockFeedbackDB.created_at >= since,
    ).order_by(RestockFeedbackDB.created_at.desc()).all()
    rows = {r.track_id: r for r in db.query(RotationTrackDB).filter(RotationTrackDB.rotation_id == rotation.id)}
    on = ls.enabled(user)
    index = ls.PlayIndex([p for p in ls.load_plays(db, user, since) if p.counts]) if on else ls.PlayIndex([])
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: {"added": 0, "played": 0})
    songs, seen = [], set()
    for add in adds:
        row = rows.get(add.track_id)
        if row is None or add.track_id in seen:
            continue
        seen.add(add.track_id)
        plays = sum(1 for p in index.find(row.track_id, row.title, row.artists) if p.played_at > add.created_at)
        by_source[add.source]["added"] += 1
        by_source[add.source]["played"] += 1 if plays else 0
        songs.append({
            "track_id": row.track_id, "title": row.title, "artists": row.artists, "image_url": row.image_url,
            "source": add.source, "added_at": add.created_at, "plays": plays, "status": row.status,
        })
    return {
        "enabled": on,
        "window_days": days,
        "added": len(songs),
        "played": sum(1 for s in songs if s["plays"]),
        "by_source": [{"source": k, **v} for k, v in sorted(by_source.items(), key=lambda kv: -kv[1]["added"])],
        "songs": songs,
    }
