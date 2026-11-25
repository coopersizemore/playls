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


def _month_bounds(month: str, tz_offset_minutes: int) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar month ("YYYY-MM") as naive UTC."""
    year, mon = (int(x) for x in month.split("-"))
    start = datetime(year, mon, 1)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1)
    shift = timedelta(minutes=tz_offset_minutes)
    return start + shift, end + shift


def recap_months(rotation: RotationDB, tz_offset_minutes: int = 0) -> list[str]:
    """Months the rotation has existed in (local time), newest first."""
    now = utcnow() - timedelta(minutes=tz_offset_minutes)
    first = rotation.created_at - timedelta(minutes=tz_offset_minutes)
    months, y, m = [], now.year, now.month
    while (y, m) >= (first.year, first.month) and len(months) < 36:
        months.append(f"{y:04}-{m:02}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return months


def recap(db: orm.Session, rotation: RotationDB, month: str, tz_offset_minutes: int = 0) -> dict:
    """One month of a rotation: listening (from the history) and turnover (from reviews and
    restocks). Computed on demand."""
    user = rotation.owner
    start, end = _month_bounds(month, tz_offset_minutes)
    now = utcnow()
    rows = db.query(RotationTrackDB).filter(RotationTrackDB.rotation_id == rotation.id).all()
    by_id = {r.id: r for r in rows}
    on = ls.enabled(user)
    plays = [p for p in ls.load_plays(db, user, start) if p.played_at < end] if on else []
    index = ls.PlayIndex(plays)
    counted = [p for p in plays if p.counts]
    plays_here = sum(1 for p in counted if ls.context_matches(rotation, p.context_type, p.context_uri))
    per_song, starts, skips, seen = [], 0, 0, set()
    for row in rows:
        found = [p for p in index.find(row.track_id, row.title, row.artists) if p.played_at not in seen]
        seen.update(p.played_at for p in found)
        n = sum(1 for p in found if p.counts)
        here = sum(1 for p in found if p.counts and ls.context_matches(rotation, p.context_type, p.context_uri))
        imported = [p for p in found if p.source == "import"]
        starts += len(imported)
        skips += sum(1 for p in imported if p.skipped or not p.counts)
        if n:
            per_song.append((row, n, here))
    elsewhere = sum(n - here for _, n, here in per_song)
    per_song.sort(key=lambda x: (-x[1], x[0].title or ""))
    days = []
    day = start
    while day < min(end, now):
        nxt = day + timedelta(days=1)
        days.append({
            "date": _local_date(day, tz_offset_minutes),
            "plays_here": sum(1 for p in counted if day <= p.played_at < nxt
                              and ls.context_matches(rotation, p.context_type, p.context_uri)),
        })
        day = nxt

    events = (
        db.query(ReviewEventDB.action, ReviewEventDB.rotation_track_id)
        .join(RotationTrackDB, ReviewEventDB.rotation_track_id == RotationTrackDB.id)
        .filter(RotationTrackDB.rotation_id == rotation.id, ReviewEventDB.created_at >= start,
                ReviewEventDB.created_at < end)
        .all()
    )
    actions = Counter(a for a, _ in events)
    kept = Counter(rid for a, rid in events if a in KEEP_ACTIONS)
    adds = db.query(RestockFeedbackDB).filter(
        RestockFeedbackDB.rotation_id == rotation.id, RestockFeedbackDB.action == ADD,
        RestockFeedbackDB.created_at >= start, RestockFeedbackDB.created_at < end,
    ).all()
    rows_by_track = {r.track_id: r for r in rows}
    later = ls.PlayIndex([p for p in ls.load_plays(db, user, start) if p.counts]) if on else ls.PlayIndex([])
    adds_played = 0
    for add in adds:
        row = rows_by_track.get(add.track_id)
        if row is None:
            continue
        if any(p.played_at > add.created_at for p in later.find(row.track_id, row.title, row.artists)):
            adds_played += 1

    def song(row, **extra):
        return {"track_id": row.track_id, "title": row.title, "artists": row.artists, "image_url": row.image_url,
                **extra}

    return {
        "month": month,
        "months": recap_months(rotation, tz_offset_minutes),
        "listening_enabled": on,
        "covered": on and user.listening_since is not None and user.listening_since < end,
        "plays_here": plays_here,
        "plays_elsewhere": elsewhere,
        "songs_played": len(per_song),
        "song_count": sum(1 for r in rows if r.status != "removed"),
        "days": days,
        "top_songs": [song(r, plays=n, plays_here=h) for r, n, h in per_song[:5]],
        "added": len(adds),
        "added_by_source": dict(Counter(a.source for a in adds)),
        "adds_played": adds_played,
        "kept": actions.get("keep", 0),
        "super_kept": actions.get("super_keep", 0),
        "removed": actions.get(REMOVE, 0),
        "rotated_out": actions.get("rotated_out", 0),
        "most_kept": [song(by_id[rid], times=n) for rid, n in kept.most_common(3) if rid in by_id],
        "starts": starts,
        "skips": skips,
    }
