from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database.config import get_db
from ..database.models.user import UserDB
from ..services.auth_service import AuthService
from ..services.db import rotation_service as rs
from ..services.spotify.spotify_service import SEARCH_LIMIT_MAX, SpotifyService

router = APIRouter(
    prefix="/spotify",
    tags=["spotify"],
    dependencies=[Depends(AuthService.get_current_user_from_token)],
)

current_user_dep = Depends(AuthService.get_current_user_from_token)

MAX_PLAYLIST_PAGES = 20  # 20 x 50 = 1000 playlists


class PlaylistOut(BaseModel):
    id: str
    name: str
    image_url: str | None
    total_items: int | None
    owner_name: str | None
    # Only playlists the user owns or collaborates on expose their contents
    rotatable: bool
    rotation_id: int | None


def _item_total(playlist: dict) -> int | None:
    # Feb 2026: "items" replaces "tracks" on playlist objects
    for key in ("items", "tracks"):
        value = playlist.get(key)
        if isinstance(value, dict) and value.get("total") is not None:
            return value["total"]
    return None


@router.get("/playlists", response_model=list[PlaylistOut])
async def get_user_playlists(db: Session = Depends(get_db), user: UserDB = current_user_dep):
    """All of the user's playlists, flagged with whether they can be rotated."""
    rotation_by_playlist = {r.playlist_id: r.id for r in rs.get_user_rotations(db, user.id)}
    results: list[PlaylistOut] = []
    offset = 0
    for _ in range(MAX_PLAYLIST_PAGES):
        page = await SpotifyService.get_user_playlists(user, db, limit=50, offset=offset)
        items = [p for p in page.get("items") or [] if p]
        for p in items:
            owner = p.get("owner") or {}
            images = p.get("images") or []
            results.append(PlaylistOut(
                id=p["id"],
                name=p.get("name") or "Untitled",
                image_url=images[0].get("url") if images else None,
                total_items=_item_total(p),
                owner_name=owner.get("display_name") or owner.get("id"),
                rotatable=owner.get("id") == user.spotify_id or bool(p.get("collaborative")),
                rotation_id=rotation_by_playlist.get(p["id"]),
            ))
        offset += len(items)
        if not page.get("next") or not items:
            break
    return results


@router.get("/search")
async def search_spotify(
    q: str = Query(..., min_length=1, max_length=200),
    type: str = Query("track", pattern="^(track|artist|album)$"),
    limit: int = Query(SEARCH_LIMIT_MAX, ge=1, le=SEARCH_LIMIT_MAX),
    offset: int = Query(0, ge=0, le=1000),
    db: Session = Depends(get_db),
    user: UserDB = current_user_dep,
):
    """Search the catalog (Phase 2 restock). Spotify caps limit at 10."""
    return await SpotifyService.search(q, user, db, type, limit, offset)
