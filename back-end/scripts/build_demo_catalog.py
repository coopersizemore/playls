"""Build the demo catalog (rest_api/services/demo/catalog.json) from your own Spotify account.

Run once, from back-end/ with .venv and a real .env (it reads the shared database for your
Spotify token and calls Spotify as you):

    .venv/Scripts/python -m scripts.build_demo_catalog PLAYLIST_ID PLAYLIST_ID PLAYLIST_ID

Pass three or more playlists you own or collaborate on:
  - the first becomes the seeded "Daily Mix" (needs at least 40 playable songs);
  - the second seeds the auto rotation (needs at least 30);
  - the rest are offered in the demo's "wrap a playlist" picker.
Your top tracks, top artists, recent plays and recent likes become the "For you" signals.

Only display metadata is kept (track, artist and album names and ids, cover URLs and
durations). No user ids, play times or like dates are written. Commit the output.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from rest_api.database.config import SessionLocal  # noqa: E402
from rest_api.database.models import UserDB  # noqa: E402
from rest_api.services.demo.catalog import CATALOG_PATH, PLAYLIST_PREFIX  # noqa: E402
from rest_api.services.spotify.spotify_service import SpotifyService as ss  # noqa: E402

MIN_SIZES = (40, 30)
MAX_PER_PLAYLIST = 60


def _artist(a: dict) -> dict:
    return {"id": a.get("id"), "name": a.get("name")}


def trim(track: dict | None) -> dict | None:
    """A playable Spotify track object, reduced to the fields PlayLS reads."""
    if not track or track.get("type", "track") != "track" or not track.get("id") or track.get("is_local"):
        return None
    if track.get("is_playable") is False:
        return None
    album = track.get("album") or {}
    return {
        "id": track["id"],
        "uri": track.get("uri") or f"spotify:track:{track['id']}",
        "type": "track",
        "name": track.get("name"),
        "duration_ms": track.get("duration_ms"),
        "artists": [_artist(a) for a in track.get("artists") or [] if a.get("name")],
        "album": {
            "id": album.get("id"),
            "name": album.get("name"),
            "album_type": album.get("album_type"),
            "artists": [_artist(a) for a in album.get("artists") or [] if a.get("name")],
            "images": [
                {"url": i.get("url"), "width": i.get("width"), "height": i.get("height")}
                for i in album.get("images") or [] if i.get("url")
            ],
        },
    }


async def build(user: UserDB, db, playlist_ids: list[str]) -> dict:
    tracks: dict[str, dict] = {}

    def keep(raw) -> str | None:
        t = trim(raw)
        if t is None:
            return None
        tracks.setdefault(t["id"], t)
        return t["id"]

    playlists = []
    for n, pid in enumerate(playlist_ids, start=1):
        meta = await ss.get_playlist(pid, user, db, fields="name,description")
        ids = []
        entries, _total = await ss.get_all_playlist_items(pid, user, db)
        for entry in entries:
            tid = keep(entry.get("item") or entry.get("track"))
            if tid and tid not in ids:
                ids.append(tid)
        ids = ids[:MAX_PER_PLAYLIST]
        if n <= len(MIN_SIZES) and len(ids) < MIN_SIZES[n - 1]:
            sys.exit(f"Playlist {n} ({meta.get('name')}) has {len(ids)} playable songs; it needs {MIN_SIZES[n - 1]}")
        playlists.append({
            "id": f"{PLAYLIST_PREFIX}{n}",
            "name": (meta.get("name") or f"Playlist {n}")[:100],
            "description": meta.get("description") or "",
            "track_ids": ids,
        })
        print(f"  {playlists[-1]['name']}: {len(ids)} songs")

    top_tracks = {}
    for window in ("short_term", "medium_term", "long_term"):
        page = await ss.get_top_items("tracks", user, db, time_range=window, limit=50)
        top_tracks[window] = [tid for tid in map(keep, page.get("items") or []) if tid]
    artists_page = await ss.get_top_items("artists", user, db, time_range="medium_term", limit=20)
    top_artists = [_artist(a) for a in artists_page.get("items") or [] if a.get("id") and a.get("name")]
    recent_page = await ss.get_recently_played(user, db, limit=50)
    recent = [tid for tid in (keep(e.get("track")) for e in recent_page.get("items") or []) if tid]
    liked_page = await ss.get_saved_tracks(user, db, limit=50)
    liked = [tid for tid in (keep(e.get("track")) for e in liked_page.get("items") or []) if tid]

    return {
        "tracks": list(tracks.values()),
        "playlists": playlists,
        "signals": {
            "top_tracks": top_tracks,
            "top_artists": top_artists,
            "recent": list(dict.fromkeys(recent)),
            "liked": liked,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("playlist_ids", nargs="+", help="3+ Spotify playlist ids, in order")
    parser.add_argument("--spotify-id", help="Whose account to read (default: the first ADMIN_SPOTIFY_IDS entry)")
    parser.add_argument("--out", default=str(CATALOG_PATH), help="Output path")
    args = parser.parse_args()
    if len(args.playlist_ids) < 3:
        parser.error("pass at least three playlists")
    spotify_id = args.spotify_id or (os.getenv("ADMIN_SPOTIFY_IDS", "").split(",")[0].strip())
    if not spotify_id:
        parser.error("set ADMIN_SPOTIFY_IDS or pass --spotify-id")

    db = SessionLocal()
    try:
        user = db.query(UserDB).filter(UserDB.spotify_id == spotify_id).one_or_none()
        if user is None:
            sys.exit("No PlayLS account for that Spotify id; log in to PlayLS once first")
        catalog = asyncio.run(build(user, db, args.playlist_ids))
    finally:
        db.close()

    Path(args.out).write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(catalog['tracks'])} tracks and {len(catalog['playlists'])} playlists to {args.out}")


if __name__ == "__main__":
    main()
