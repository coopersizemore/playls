"""Thin httpx wrapper over the Spotify Web API (post-Feb-2026 endpoints).

Errors are logged server-side and surface to clients as generic 502/429s.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...database.models.user import UserDB
from ..auth_service import AuthService

logger = logging.getLogger(__name__)

API_BASE = "https://api.spotify.com/v1"
PLAYLIST_ITEMS_PAGE_SIZE = 50  # max for GET /playlists/{id}/items
PLAYLIST_MUTATION_BATCH = 100  # max URIs per add/remove request
SEARCH_LIMIT_MAX = 10


class SpotifyAPIError(HTTPException):
    """A failed Spotify call. `upstream_status` lets callers react (e.g. 403/404 playlist)."""

    def __init__(self, upstream_status: int):
        self.upstream_status = upstream_status
        if upstream_status == 429:
            super().__init__(status_code=429, detail="Spotify rate limit reached, try again shortly")
        else:
            super().__init__(status_code=502, detail="Spotify request failed")


def _chunks(values: List[str], size: int):
    for i in range(0, len(values), size):
        yield values[i:i + size]


class SpotifyService:
    @staticmethod
    async def make_spotify_request(
        endpoint: str,
        user: UserDB,
        db: Session,
        method: str = "GET",
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Authenticated request; refreshes the Spotify token when expired or rejected once."""
        method = method.upper()
        url = f"{API_BASE}{endpoint}"
        access_token = await AuthService.ensure_valid_spotify_token(user, db)

        async with httpx.AsyncClient(timeout=20.0) as client:
            async def send(token: str) -> httpx.Response:
                return await client.request(
                    method, url, headers={"Authorization": f"Bearer {token}"}, json=data, params=params
                )

            response = await send(access_token)
            if response.status_code == 401:
                # Token was revoked or expired early: force a refresh and retry once
                access_token = await AuthService.ensure_valid_spotify_token(user, db, force_refresh=True)
                response = await send(access_token)

        if not response.is_success:
            # Spotify's body stays in the server log; clients get a generic message
            logger.warning(
                "Spotify API %s %s failed: %s %s", method, endpoint, response.status_code, response.text[:500]
            )
            raise SpotifyAPIError(response.status_code)

        return response.json() if response.content else {}

    @staticmethod
    async def get_user_playlists(user: UserDB, db: Session, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        return await SpotifyService.make_spotify_request(
            "/me/playlists", user, db, params={"limit": limit, "offset": offset}
        )

    @staticmethod
    async def get_playlist(
        playlist_id: str, user: UserDB, db: Session, fields: Optional[str] = None
    ) -> Dict[str, Any]:
        params = {"fields": fields} if fields else None
        return await SpotifyService.make_spotify_request(f"/playlists/{playlist_id}", user, db, params=params)

    @staticmethod
    async def get_playlist_items_page(
        playlist_id: str, user: UserDB, db: Session, limit: int = PLAYLIST_ITEMS_PAGE_SIZE, offset: int = 0
    ) -> Dict[str, Any]:
        """One page of playlist items (only for playlists the user owns or collaborates on)."""
        return await SpotifyService.make_spotify_request(
            f"/playlists/{playlist_id}/items",
            user,
            db,
            # from_token adds is_playable (unavailable tracks) and relinks to playable versions
            params={"limit": limit, "offset": offset, "market": "from_token"},
        )

    @staticmethod
    async def get_all_playlist_items(playlist_id: str, user: UserDB, db: Session) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = await SpotifyService.get_playlist_items_page(playlist_id, user, db, offset=offset)
            batch = page.get("items") or []
            items.extend(batch)
            offset += len(batch)
            if not page.get("next") or not batch:
                return items

    @staticmethod
    async def add_items_to_playlist(
        playlist_id: str, uris: List[str], user: UserDB, db: Session, position: Optional[int] = None
    ) -> Optional[str]:
        """Add URIs (batched by 100). Returns the final snapshot_id."""
        snapshot_id = None
        for i, batch in enumerate(_chunks(uris, PLAYLIST_MUTATION_BATCH)):
            data: Dict[str, Any] = {"uris": batch}
            if position is not None:
                data["position"] = position + i * PLAYLIST_MUTATION_BATCH
            result = await SpotifyService.make_spotify_request(
                f"/playlists/{playlist_id}/items", user, db, method="POST", data=data
            )
            snapshot_id = result.get("snapshot_id", snapshot_id)
        return snapshot_id

    @staticmethod
    async def remove_items_from_playlist(
        playlist_id: str, uris: List[str], user: UserDB, db: Session
    ) -> Optional[str]:
        """Remove every occurrence of each URI (batched by 100). Returns the final snapshot_id."""
        snapshot_id = None
        for batch in _chunks(uris, PLAYLIST_MUTATION_BATCH):
            result = await SpotifyService.make_spotify_request(
                f"/playlists/{playlist_id}/items",
                user,
                db,
                method="DELETE",
                data={"items": [{"uri": uri} for uri in batch]},
            )
            snapshot_id = result.get("snapshot_id", snapshot_id)
        return snapshot_id

    @staticmethod
    async def create_playlist(
        name: str, user: UserDB, db: Session, description: Optional[str] = None, public: bool = False
    ) -> Dict[str, Any]:
        # Always send a description: playlists created without one can show "null" in Spotify
        data: Dict[str, Any] = {"name": name, "public": public, "description": description or ""}
        return await SpotifyService.make_spotify_request("/me/playlists", user, db, method="POST", data=data)

    # ---------- listening signals (restock) ----------

    @staticmethod
    async def get_track(track_id: str, user: UserDB, db: Session) -> Dict[str, Any]:
        """One track (the batch GET /tracks endpoint was removed in Feb 2026)."""
        return await SpotifyService.make_spotify_request(f"/tracks/{track_id}", user, db)

    @staticmethod
    async def get_top_items(
        item_type: str, user: UserDB, db: Session, time_range: str = "medium_term", limit: int = 50
    ) -> Dict[str, Any]:
        """Top "tracks" or "artists". time_range: short_term (~4 weeks), medium_term (~6 months),
        long_term (~1 year). Scope: user-top-read."""
        return await SpotifyService.make_spotify_request(
            f"/me/top/{item_type}", user, db, params={"time_range": time_range, "limit": min(limit, 50)}
        )

    @staticmethod
    async def get_recently_played(user: UserDB, db: Session, limit: int = 50) -> Dict[str, Any]:
        """Last (up to) 50 plays. Scope: user-read-recently-played."""
        return await SpotifyService.make_spotify_request(
            "/me/player/recently-played", user, db, params={"limit": min(limit, 50)}
        )

    @staticmethod
    async def get_saved_tracks(user: UserDB, db: Session, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """Liked Songs, newest first. Scope: user-library-read."""
        return await SpotifyService.make_spotify_request(
            "/me/tracks", user, db, params={"limit": min(limit, 50), "offset": offset}
        )

    @staticmethod
    async def search(
        query: str,
        user: UserDB,
        db: Session,
        search_type: str = "track",
        limit: int = SEARCH_LIMIT_MAX,
        offset: int = 0,
    ) -> Dict[str, Any]:
        params = {"q": query, "type": search_type, "limit": min(limit, SEARCH_LIMIT_MAX), "offset": offset}
        return await SpotifyService.make_spotify_request("/search", user, db, params=params)
