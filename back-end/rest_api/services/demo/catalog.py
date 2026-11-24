"""The bundled demo catalog (catalog.json, built once by scripts/build_demo_catalog.py).

Shape:
    tracks:    Spotify-shaped track objects (id, uri, name, duration_ms, artists[{id, name}],
               album{id, name, album_type, artists, images})
    playlists: [{id, name, description, track_ids}]: sample playlists a demo account owns
    signals:   {top_tracks: {short_term|medium_term|long_term: [ids]}, top_artists: [{id, name}],
                recent: [ids], liked: [ids]}: listening signals for the "For you" deck
"""
import json
import re
from functools import cached_property
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("catalog.json")
PLAYLIST_PREFIX = "demo-sample-"
NEW_PLAYLIST_PREFIX = "demo-new-"

_FIELD = re.compile(r'(\w+):"([^"]*)"')


class Catalog:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    @cached_property
    def tracks(self) -> dict[str, dict[str, Any]]:
        return {t["id"]: t for t in self.data.get("tracks", []) if t.get("id")}

    @cached_property
    def playlists(self) -> dict[str, dict[str, Any]]:
        return {p["id"]: p for p in self.data.get("playlists", [])}

    @property
    def signals(self) -> dict[str, Any]:
        return self.data.get("signals") or {}

    def track(self, track_id: str) -> dict[str, Any] | None:
        return self.tracks.get(track_id)

    def resolve(self, ids: list[str]) -> list[dict[str, Any]]:
        return [self.tracks[i] for i in ids if i in self.tracks]

    def playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        p = self.playlists.get(playlist_id)
        return self.resolve(p["track_ids"]) if p else []

    def search(self, query: str) -> list[dict[str, Any]]:
        """Case-insensitive match over title, artists and album. Understands the field filters
        restock sends (artist:"X", album:"Y"); other words must all appear somewhere."""
        fields = {k.lower(): v.lower().strip() for k, v in _FIELD.findall(query)}
        words = _FIELD.sub(" ", query).lower().split()
        if not fields and not words:
            return []
        out = []
        for t in self.tracks.values():
            title = (t.get("name") or "").lower()
            artists = " ".join(a.get("name", "") for a in t.get("artists") or []).lower()
            album = ((t.get("album") or {}).get("name") or "").lower()
            if "artist" in fields and fields["artist"] not in artists:
                continue
            if "album" in fields and fields["album"] not in album:
                continue
            if "track" in fields and fields["track"] not in title:
                continue
            haystack = f"{title} {artists} {album}"
            if all(w in haystack for w in words):
                out.append(t)
        return out


_catalog: Catalog | None = None


def catalog() -> Catalog:
    """The catalog, loaded on first use (an empty one if catalog.json hasn't been built yet)."""
    global _catalog
    if _catalog is None:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.exists() else {}
        _catalog = Catalog(data)
    return _catalog


def set_catalog(data: dict[str, Any] | None) -> None:
    """Replace the loaded catalog (tests); None reloads catalog.json on next use."""
    global _catalog
    _catalog = Catalog(data) if data is not None else None
