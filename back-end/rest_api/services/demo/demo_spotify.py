"""Stand-in for SpotifyService for demo accounts (provider = 'demo'). It makes no network calls.

A demo playlist has no store of its own. Its contents are the rotation's own active and
pending rows, so a sync always agrees with the database. Its snapshot never changes, so
syncs short-circuit. Writes (add, remove, like, unlike) change nothing here: the services
update the rows right after a successful write, which is the playlist change. Before a
rotation has any rows, a sample playlist reads as its catalog tracks (the initial import).

Method names and signatures mirror SpotifyService; spotify_service dispatches here by name.
"""
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from rest_api.clock import utcnow
from rest_api.database.models.rotation import RotationDB
from rest_api.database.models.rotation_track import ACTIVE, PENDING_REMOVAL, RotationTrackDB
from rest_api.database.models.user import UserDB

from .catalog import NEW_PLAYLIST_PREFIX, catalog

PAGE = 50
SEARCH_LIMIT_MAX = 10


def _not_found():
    # Imported lazily: spotify_service imports this module
    from rest_api.services.spotify.spotify_service import SpotifyAPIError

    return SpotifyAPIError(404)


def _iso(dt) -> str | None:
    return dt.isoformat() + "Z" if dt is not None else None


def snapshot(playlist_id: str) -> str:
    return f"demo-{playlist_id}"


def _known_playlist(playlist_id: str) -> bool:
    return playlist_id in catalog().playlists or playlist_id.startswith(NEW_PLAYLIST_PREFIX)


def _cover(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return ((tracks[0].get("album") or {}).get("images") or [])[:1] if tracks else []


def _row_item(row: RotationTrackDB) -> dict[str, Any]:
    """A rotation row as a playlist item entry (the post-Feb-2026 shape the parser reads)."""
    album = {"name": row.album, "images": [{"url": row.image_url, "width": 300}] if row.image_url else []}
    artists = [{"name": n} for n in (row.artists or "").split(", ") if n]
    return {
        "added_at": _iso(row.added_at),
        "is_local": False,
        "item": {
            "id": row.track_id, "uri": row.uri, "type": "track", "name": row.title,
            "duration_ms": row.duration_ms, "is_playable": row.is_playable, "artists": artists, "album": album,
        },
    }


def sample_added_at(index: int):
    """When the i-th song of a sample playlist was 'added' (spread over the past few months)."""
    return utcnow() - timedelta(days=12 + index * 3)


def _page(items: list, offset: int, limit: int) -> dict[str, Any]:
    return {"items": items[offset:offset + limit], "total": len(items),
            "next": None if offset + limit >= len(items) else "more"}


class DemoSpotify:
    # ---- playlists ----
    @staticmethod
    async def get_user_playlists(user: UserDB, db: Session, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        cat = catalog()
        items = []
        for p in cat.playlists.values():
            tracks = cat.playlist_tracks(p["id"])
            items.append({
                "id": p["id"], "name": p["name"], "description": p.get("description") or "",
                "owner": {"id": user.spotify_id, "display_name": user.display_name},
                "collaborative": False, "public": False, "images": _cover(tracks),
                "items": {"total": len(tracks)}, "type": "playlist",
            })
        return _page(items, offset, limit)

    @staticmethod
    async def get_playlist(playlist_id: str, user: UserDB, db: Session, fields: str | None = None) -> dict[str, Any]:
        if not _known_playlist(playlist_id):
            raise _not_found()
        cat = catalog()
        p = cat.playlists.get(playlist_id) or {}
        # The rotation row is the demo playlist's store, so its name is the playlist's name
        # (sync copies the name from here, and renames change only the row)
        rotation = db.query(RotationDB.name).filter(
            RotationDB.owner_id == user.id, RotationDB.playlist_id == playlist_id
        ).first()
        name = (rotation.name if rotation is not None else None) or p.get("name") or "Playlist"
        return {
            "id": playlist_id, "name": name, "description": p.get("description") or "",
            "collaborative": False, "owner": {"id": user.spotify_id}, "snapshot_id": snapshot(playlist_id),
            "images": _cover(cat.playlist_tracks(playlist_id)),
        }

    @staticmethod
    async def get_all_playlist_items(playlist_id: str, user: UserDB, db: Session) -> list[dict[str, Any]]:
        if not _known_playlist(playlist_id):
            raise _not_found()
        rotation = db.query(RotationDB).filter(
            RotationDB.owner_id == user.id, RotationDB.playlist_id == playlist_id
        ).first()
        if rotation is not None:
            rows = db.query(RotationTrackDB).filter(RotationTrackDB.rotation_id == rotation.id)
            if rows.first() is not None:
                live = rows.filter(RotationTrackDB.status.in_((ACTIVE, PENDING_REMOVAL))).all()
                return [_row_item(r) for r in live]
        # Not imported yet: a sample playlist reads as its catalog tracks; a new one is empty
        return [
            {"added_at": _iso(sample_added_at(i)), "is_local": False, "item": t}
            for i, t in enumerate(catalog().playlist_tracks(playlist_id))
        ]

    @staticmethod
    async def get_playlist_items_page(
        playlist_id: str, user: UserDB, db: Session, limit: int = PAGE, offset: int = 0
    ) -> dict[str, Any]:
        return _page(await DemoSpotify.get_all_playlist_items(playlist_id, user, db), offset, limit)

    @staticmethod
    async def add_items_to_playlist(
        playlist_id: str, uris: list[str], user: UserDB, db: Session, position: int | None = None
    ) -> str | None:
        if not _known_playlist(playlist_id):
            raise _not_found()
        return snapshot(playlist_id)

    @staticmethod
    async def remove_items_from_playlist(playlist_id: str, uris: list[str], user: UserDB, db: Session) -> str | None:
        if not _known_playlist(playlist_id):
            raise _not_found()
        return snapshot(playlist_id)

    @staticmethod
    async def rename_playlist(playlist_id: str, name: str, user: UserDB, db: Session) -> None:
        if not _known_playlist(playlist_id):
            raise _not_found()

    @staticmethod
    async def create_playlist(
        name: str, user: UserDB, db: Session, description: str | None = None, public: bool = False
    ) -> dict[str, Any]:
        playlist_id = NEW_PLAYLIST_PREFIX + secrets.token_hex(6)
        return {"id": playlist_id, "name": name, "description": description or "",
                "snapshot_id": snapshot(playlist_id), "owner": {"id": user.spotify_id}, "images": []}

    # ---- library (no Liked Songs rotations in the demo; these feed the "For you" signals) ----
    @staticmethod
    def _liked(offset: int, limit: int) -> dict[str, Any]:
        liked = catalog().resolve(catalog().signals.get("liked") or [])
        start = utcnow()
        entries = [{"track": t, "added_at": _iso(start - timedelta(days=3 * i))} for i, t in enumerate(liked)]
        return _page(entries, offset, limit)

    @staticmethod
    async def get_saved_tracks_page(user: UserDB, db: Session, offset: int = 0, limit: int = PAGE) -> dict[str, Any]:
        return DemoSpotify._liked(offset, limit)

    @staticmethod
    async def get_all_saved_tracks(user: UserDB, db: Session, first: dict[str, Any] | None = None):
        page = DemoSpotify._liked(0, 10_000)
        return page["items"], page["total"]

    @staticmethod
    async def get_saved_tracks(user: UserDB, db: Session, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return DemoSpotify._liked(offset, min(limit, 50))

    @staticmethod
    async def save_to_library(uris: list[str], user: UserDB, db: Session) -> None:
        return None

    @staticmethod
    async def remove_from_library(uris: list[str], user: UserDB, db: Session) -> None:
        return None

    # ---- tracks, signals, search ----
    @staticmethod
    async def get_track(track_id: str, user: UserDB, db: Session) -> dict[str, Any]:
        track = catalog().track(track_id)
        if track is None:
            raise _not_found()
        return track

    @staticmethod
    async def get_top_items(
        item_type: str, user: UserDB, db: Session, time_range: str = "medium_term", limit: int = 50
    ) -> dict[str, Any]:
        signals = catalog().signals
        if item_type == "artists":
            return {"items": (signals.get("top_artists") or [])[:limit]}
        ids = (signals.get("top_tracks") or {}).get(time_range) or []
        return {"items": catalog().resolve(ids)[:limit]}

    @staticmethod
    async def get_recently_played(user: UserDB, db: Session, limit: int = 50) -> dict[str, Any]:
        tracks = catalog().resolve(catalog().signals.get("recent") or [])[:min(limit, 50)]
        start = utcnow()
        return {"items": [{"track": t, "played_at": _iso(start - timedelta(hours=2 * i))}
                          for i, t in enumerate(tracks)]}

    @staticmethod
    async def search(
        query: str, user: UserDB, db: Session, search_type: str = "track", limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        limit = min(limit, SEARCH_LIMIT_MAX)
        items = catalog().search(query)
        return {"tracks": {"items": items[offset:offset + limit], "total": len(items), "offset": offset,
                           "limit": limit, "next": "more" if offset + limit < len(items) else None}}
