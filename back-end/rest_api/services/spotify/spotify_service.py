"""Thin httpx wrapper over the Spotify Web API (post-Feb-2026 endpoints).

Errors are logged server-side and surface to clients as generic 502/429s.
"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ... import request_context
from ...database.models.user import UserDB
from .. import health
from ..auth_service import AuthService

logger = logging.getLogger(__name__)

API_BASE = "https://api.spotify.com/v1"
PLAYLIST_ITEMS_PAGE_SIZE = 50  # max for GET /playlists/{id}/items
PLAYLIST_MUTATION_BATCH = 100  # max URIs per add/remove request
LIBRARY_MUTATION_BATCH = 40  # max URIs per PUT/DELETE /me/library
SEARCH_LIMIT_MAX = 10
# Playlist pages fetched at once after the first; kept low for the shared rate limit
PLAYLIST_PAGE_CONCURRENCY = 4

# Rate limits (429): wait and retry when Spotify asks for a short pause. Quota errors and long
# pauses fail right away (with Retry-After passed on to the client), so a page never hangs.
RATE_LIMIT_RETRIES = 2
RATE_LIMIT_MAX_WAIT = 5.0  # longest single Retry-After we'll wait out
RATE_LIMIT_BUDGET = 8.0  # total waiting per request (or per call, outside a request)
RATE_LIMIT_DEFAULT_WAIT = 1.0  # when Spotify sends no Retry-After


class SpotifyAPIError(HTTPException):
    """A failed Spotify call. `upstream_status` lets callers react (e.g. 403/404 playlist)."""

    def __init__(self, upstream_status: int, retry_after: int | None = None, quota: bool = False):
        self.upstream_status = upstream_status
        self.retry_after = retry_after
        if upstream_status == 429:
            headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
            detail = (
                "PlayLS has used up its Spotify request quota for now. Try again later."
                if quota else "Spotify rate limit reached, try again shortly"
            )
            super().__init__(status_code=429, detail=detail, headers=headers)
        else:
            super().__init__(status_code=502, detail="Spotify request failed")


@asynccontextmanager
async def _client():
    """The request's shared client (connection reuse), or a one-off one outside a request."""
    ctx = request_context.current()
    if ctx is not None:
        yield ctx.spotify_client()
        return
    async with httpx.AsyncClient(timeout=request_context.SPOTIFY_TIMEOUT) as client:
        yield client


async def _refresh_after_401(user: UserDB, db: Session, rejected_token: str) -> str:
    """Force a token refresh, unless a concurrent call in this request already did."""
    ctx = request_context.current()
    if ctx is None:
        return await AuthService.ensure_valid_spotify_token(user, db, force_refresh=True)
    async with ctx.refresh_lock():
        if user.access_token != rejected_token:
            return user.access_token
        return await AuthService.ensure_valid_spotify_token(user, db, force_refresh=True)


def _retry_after_seconds(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    try:
        return max(0, int(float(value))) if value is not None else None
    except ValueError:
        return None


def _is_quota_error(response: httpx.Response) -> bool:
    # Development Mode quota (shared across the account's apps); waiting seconds won't help
    return "QUOTA_EXCEEDED" in response.text


def _rate_limit_wait(response: httpx.Response, waited: float) -> float | None:
    """Seconds to wait before retrying a 429, or None to give up."""
    if _is_quota_error(response):
        return None
    retry_after = _retry_after_seconds(response)
    wait = float(retry_after) if retry_after is not None else RATE_LIMIT_DEFAULT_WAIT
    if wait > RATE_LIMIT_MAX_WAIT or waited + wait > RATE_LIMIT_BUDGET:
        return None
    return wait


def _chunks(values: list[str], size: int):
    for i in range(0, len(values), size):
        yield values[i:i + size]


async def _read_all_pages(
    fetch_page: Callable[[int], Awaitable[dict[str, Any]]], first: dict[str, Any]
) -> list[dict[str, Any]]:
    """Every item of a paged list (a playlist or Liked Songs), given its first page. The
    first page gives the total, then the rest are fetched a few at a time. (The first call
    also refreshes the token if needed, so the concurrent ones don't race to refresh it.)"""
    items: list[dict[str, Any]] = list(first.get("items") or [])
    total = first.get("total")
    if not first.get("next") or not items:
        return items
    if not isinstance(total, int):
        # No total to plan with: fall back to reading page by page
        offset = len(items)
        while True:
            page = await fetch_page(offset)
            batch = page.get("items") or []
            items.extend(batch)
            offset += len(batch)
            if not page.get("next") or not batch:
                return items

    limit = asyncio.Semaphore(PLAYLIST_PAGE_CONCURRENCY)

    async def fetch(offset: int) -> list[dict[str, Any]]:
        async with limit:
            page = await fetch_page(offset)
            return page.get("items") or []

    tasks = [asyncio.ensure_future(fetch(o)) for o in range(len(items), total, PLAYLIST_ITEMS_PAGE_SIZE)]
    try:
        pages = await asyncio.gather(*tasks)
    except BaseException:
        # One page failed: stop the others (the request's client closes soon) and
        # surface the original error, e.g. SpotifyAPIError
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    for batch in pages:
        items.extend(batch)
    return items


class SpotifyService:
    @staticmethod
    async def make_spotify_request(
        endpoint: str,
        user: UserDB,
        db: Session,
        method: str = "GET",
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Authenticated request; refreshes the Spotify token when expired or rejected once."""
        method = method.upper()
        url = f"{API_BASE}{endpoint}"
        access_token = await AuthService.ensure_valid_spotify_token(user, db)
        ctx = request_context.current()
        started = time.perf_counter()

        async with _client() as client:
            async def send(token: str) -> httpx.Response:
                return await client.request(
                    method, url, headers={"Authorization": f"Bearer {token}"}, json=data, params=params
                )

            local_waited = 0.0
            try:
                for attempt in range(RATE_LIMIT_RETRIES + 1):
                    response = await send(access_token)
                    if response.status_code == 401:
                        health.count("spotify.token_refresh")
                        # Token was revoked or expired early: refresh and retry once
                        access_token = await _refresh_after_401(user, db, access_token)
                        response = await send(access_token)
                    if response.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
                        break
                    # A 429 is rejected before Spotify acts on it, so retrying a write is safe
                    waited = ctx.rate_limit_waited if ctx is not None else local_waited
                    wait = _rate_limit_wait(response, waited)
                    if wait is None:
                        break
                    logger.info("Spotify rate limited %s %s; retrying in %.1fs", method, endpoint, wait)
                    health.count("spotify.retry")
                    if ctx is not None:
                        ctx.rate_limit_waited += wait
                    local_waited += wait
                    await asyncio.sleep(wait)
            finally:
                if ctx is not None:
                    ctx.spotify_ms += (time.perf_counter() - started) * 1000
                    ctx.spotify_calls += 1

        if not response.is_success:
            # Spotify's body stays in the server log; clients get a generic message
            logger.warning(
                "Spotify API %s %s failed: %s %s", method, endpoint, response.status_code, response.text[:500]
            )
            if response.status_code == 429:
                quota = _is_quota_error(response)
                health.count("spotify.quota_exceeded" if quota else "spotify.rate_limited")
                raise SpotifyAPIError(429, retry_after=_retry_after_seconds(response), quota=quota)
            health.count(f"spotify.error_{response.status_code}")
            raise SpotifyAPIError(response.status_code)

        return response.json() if response.content else {}

    @staticmethod
    async def get_user_playlists(user: UserDB, db: Session, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await SpotifyService.make_spotify_request(
            "/me/playlists", user, db, params={"limit": limit, "offset": offset}
        )

    @staticmethod
    async def get_playlist(
        playlist_id: str, user: UserDB, db: Session, fields: str | None = None
    ) -> dict[str, Any]:
        params = {"fields": fields} if fields else None
        return await SpotifyService.make_spotify_request(f"/playlists/{playlist_id}", user, db, params=params)

    @staticmethod
    async def get_playlist_items_page(
        playlist_id: str, user: UserDB, db: Session, limit: int = PLAYLIST_ITEMS_PAGE_SIZE, offset: int = 0
    ) -> dict[str, Any]:
        """One page of playlist items (only for playlists the user owns or collaborates on)."""
        return await SpotifyService.make_spotify_request(
            f"/playlists/{playlist_id}/items",
            user,
            db,
            # from_token adds is_playable (unavailable tracks) and relinks to playable versions
            params={"limit": limit, "offset": offset, "market": "from_token"},
        )

    @staticmethod
    async def get_all_playlist_items(playlist_id: str, user: UserDB, db: Session) -> list[dict[str, Any]]:
        """Every item, in playlist order. The first page gives the total, then the rest are fetched
        a few at a time. (The first call also refreshes the token if needed, so the concurrent
        ones don't race to refresh it.)

        Pages are read by offset from the live playlist, so a change mid-read can skip or repeat
        an item; sync_service re-checks the snapshot afterwards for that reason.
        """
        async def page(offset: int) -> dict[str, Any]:
            return await SpotifyService.get_playlist_items_page(playlist_id, user, db, offset=offset)

        return await _read_all_pages(page, await page(0))

    # ---------- Liked Songs (the user's library) ----------

    @staticmethod
    async def get_saved_tracks_page(
        user: UserDB, db: Session, offset: int = 0, limit: int = PLAYLIST_ITEMS_PAGE_SIZE
    ) -> dict[str, Any]:
        """One page of Liked Songs, newest first, with is_playable (market=from_token).
        Scope: user-library-read. The library has no snapshot_id."""
        return await SpotifyService.make_spotify_request(
            "/me/tracks", user, db, params={"limit": min(limit, 50), "offset": offset, "market": "from_token"}
        )

    @staticmethod
    async def get_all_saved_tracks(
        user: UserDB, db: Session, first: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Every Liked Songs entry, newest first, and the first page's total. `first` reuses an
        already-read first page. Like playlists, pages are offsets into a live list."""
        async def page(offset: int) -> dict[str, Any]:
            return await SpotifyService.get_saved_tracks_page(user, db, offset=offset)

        if first is None:
            first = await page(0)
        total = first.get("total")
        return await _read_all_pages(page, first), total if isinstance(total, int) else None

    @staticmethod
    async def save_to_library(uris: list[str], user: UserDB, db: Session) -> None:
        """Like tracks (PUT /me/library, at most 40 URIs per request; idempotent).
        Scope: user-library-modify."""
        for batch in _chunks(uris, LIBRARY_MUTATION_BATCH):
            await SpotifyService.make_spotify_request(
                "/me/library", user, db, method="PUT", params={"uris": ",".join(batch)}
            )

    @staticmethod
    async def remove_from_library(uris: list[str], user: UserDB, db: Session) -> None:
        """Unlike tracks (DELETE /me/library, at most 40 URIs per request; idempotent).
        Scope: user-library-modify."""
        for batch in _chunks(uris, LIBRARY_MUTATION_BATCH):
            await SpotifyService.make_spotify_request(
                "/me/library", user, db, method="DELETE", params={"uris": ",".join(batch)}
            )

    @staticmethod
    async def add_items_to_playlist(
        playlist_id: str, uris: list[str], user: UserDB, db: Session, position: int | None = None
    ) -> str | None:
        """Add URIs (batched by 100). Returns the final snapshot_id."""
        snapshot_id = None
        for i, batch in enumerate(_chunks(uris, PLAYLIST_MUTATION_BATCH)):
            data: dict[str, Any] = {"uris": batch}
            if position is not None:
                data["position"] = position + i * PLAYLIST_MUTATION_BATCH
            result = await SpotifyService.make_spotify_request(
                f"/playlists/{playlist_id}/items", user, db, method="POST", data=data
            )
            snapshot_id = result.get("snapshot_id", snapshot_id)
        return snapshot_id

    @staticmethod
    async def remove_items_from_playlist(
        playlist_id: str, uris: list[str], user: UserDB, db: Session
    ) -> str | None:
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
        name: str, user: UserDB, db: Session, description: str | None = None, public: bool = False
    ) -> dict[str, Any]:
        # Always send a description: playlists created without one can show "null" in Spotify
        data: dict[str, Any] = {"name": name, "public": public, "description": description or ""}
        return await SpotifyService.make_spotify_request("/me/playlists", user, db, method="POST", data=data)

    # ---------- listening signals (restock) ----------

    @staticmethod
    async def get_track(track_id: str, user: UserDB, db: Session) -> dict[str, Any]:
        """One track (the batch GET /tracks endpoint was removed in Feb 2026)."""
        return await SpotifyService.make_spotify_request(f"/tracks/{track_id}", user, db)

    @staticmethod
    async def get_top_items(
        item_type: str, user: UserDB, db: Session, time_range: str = "medium_term", limit: int = 50
    ) -> dict[str, Any]:
        """Top "tracks" or "artists". time_range: short_term (~4 weeks), medium_term (~6 months),
        long_term (~1 year). Scope: user-top-read."""
        return await SpotifyService.make_spotify_request(
            f"/me/top/{item_type}", user, db, params={"time_range": time_range, "limit": min(limit, 50)}
        )

    @staticmethod
    async def get_recently_played(user: UserDB, db: Session, limit: int = 50) -> dict[str, Any]:
        """Last (up to) 50 plays. Scope: user-read-recently-played."""
        return await SpotifyService.make_spotify_request(
            "/me/player/recently-played", user, db, params={"limit": min(limit, 50)}
        )

    @staticmethod
    async def get_saved_tracks(user: UserDB, db: Session, limit: int = 50, offset: int = 0) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
        params = {"q": query, "type": search_type, "limit": min(limit, SEARCH_LIMIT_MAX), "offset": offset}
        return await SpotifyService.make_spotify_request("/search", user, db, params=params)
