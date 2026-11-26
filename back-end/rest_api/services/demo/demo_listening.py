"""A demo account's listening history: a few weeks of synthetic plays plus top tracks.

Demo accounts never capture from Spotify, so this is all the history they have. It's
shaped to show every listening feature: heavily played songs (due and not due), a few due
songs with no plays in a well-used playlist ("Few plays lately"), plays elsewhere, a
removed song still being played (Bring back), heavy plays in the auto rotation's leaving
group (holds), and songs played a lot months ago (Rediscover).
"""
import random
from datetime import timedelta

from sqlalchemy.orm import Session

from rest_api.database.models.listening import TIME_RANGES, PlayEventDB, TopTrackDB
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.rotation_track import RotationTrackDB
from rest_api.database.models.user import UserDB
from rest_api.services.restock_logic import song_key, track_meta

from .catalog import catalog

HISTORY_DAYS = 200
RECENT_DAYS = 20  # moderate and heavy plays fall in the last 20 days


class _Plays:
    def __init__(self, db: Session, user: UserDB, now, rng: random.Random):
        self.db, self.user, self.now, self.rng = db, user, now, rng
        self.taken: set = set()

    def add(self, meta: dict, n: int, context_uri: str | None, days: tuple[float, float] = (0.2, RECENT_DAYS)):
        for _ in range(n):
            at = self.now - timedelta(days=self.rng.uniform(*days))
            at = at.replace(microsecond=0)
            while at in self.taken:
                at += timedelta(seconds=1)
            self.taken.add(at)
            ctype = (context_uri or "").split(":")[1] if context_uri else None
            self.db.add(PlayEventDB(
                user_id=self.user.id, track_id=meta["track_id"], song_key=song_key(meta["title"], meta.get("artists")),
                uri=meta["uri"], title=meta["title"], artists=meta.get("artists"), album=meta.get("album"),
                image_url=meta.get("image_url"), duration_ms=meta.get("duration_ms"), played_at=at,
                context_type=ctype, context_uri=context_uri,
            ))


def _row_meta(row: RotationTrackDB) -> dict:
    return {"track_id": row.track_id, "uri": row.uri, "title": row.title, "artists": row.artists,
            "album": row.album, "image_url": row.image_url, "duration_ms": row.duration_ms}


def seed(
    db: Session, user: UserDB, now, mix: RotationDB, mix_active: list, mix_removed: list,
    auto: RotationDB, auto_rows: list,
) -> None:
    rng = random.Random(user.id)
    plays = _Plays(db, user, now, rng)
    here = f"spotify:playlist:{mix.playlist_id}"
    for i, row in enumerate(mix_active):
        meta = _row_meta(row)
        if i in (0, 1, 20, 21):
            plays.add(meta, 7 + i % 3, here)  # heavily played
            plays.add(meta, 2, f"spotify:album:demo{i}")  # ...and from the album too
        elif i in (5, 6, 7):
            continue  # due, and not played at all lately
        else:
            plays.add(meta, 1 + i % 3, here)
    if mix_removed:
        plays.add(_row_meta(mix_removed[0]), 4, "spotify:album:demo-removed")
    auto_here = f"spotify:playlist:{auto.playlist_id}"
    # The oldest songs (next to leave) include two favorites
    oldest = sorted(auto_rows, key=lambda r: r.added_at)
    for j, row in enumerate(auto_rows):
        meta = _row_meta(row)
        plays.add(meta, 8 if row in oldest[:2] else 1 + j % 2, auto_here)

    in_rotation = {r.track_id for r in (*mix_active, *mix_removed, *auto_rows)}
    metas = (track_meta(t) for t in catalog().data.get("tracks", []))
    others = [m for m in metas if m and m["track_id"] not in in_rotation]
    for k, meta in enumerate(others[:8]):
        # Played a lot months ago, hardly since: Rediscover
        plays.add(meta, 6 + k % 4, None, days=(100, 170))
    user.listening_since = now - timedelta(days=HISTORY_DAYS)
    user.listening_cursor = now

    for time_range in TIME_RANGES:
        ids = (catalog().signals.get("top_tracks") or {}).get(time_range) or []
        for rank, track in enumerate(catalog().resolve(ids)):
            meta = track_meta(track)
            if meta:
                db.add(TopTrackDB(user_id=user.id, time_range=time_range, rank=rank, track_id=meta["track_id"],
                                  song_key=song_key(meta["title"], meta.get("artists")), captured_at=now))
    user.top_tracks_captured_at = now
