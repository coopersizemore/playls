"""Shared test helpers: Spotify payload builders and API shortcuts.

Test files import from here (not from conftest or from each other). conftest.py holds the
fixtures (db, user, the fake Spotify, the authenticated client).
"""
from datetime import timedelta

from rest_api.clock import utcnow
from rest_api.database.models import ReviewEventDB, RotationDB, RotationTrackDB, UserDB

# ---------- Spotify payloads ----------

def spotify_item(track_id, added_days_ago=None, name=None, local=False, kind="track"):
    """A playlist item entry in the post-Feb-2026 shape."""
    added = None
    if added_days_ago is not None:
        added = (utcnow() - timedelta(days=added_days_ago)).isoformat() + "Z"
    return {
        "added_at": added,
        "is_local": local,
        "item": {
            "id": None if local else track_id,
            "uri": f"spotify:{kind}:{track_id}",
            "type": kind,
            "name": name or f"Song {track_id}",
            "duration_ms": 200000,
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "album": {"name": "Album", "images": [{"url": "big", "width": 640}, {"url": "small", "width": 300}]},
        },
    }


def track_object(track_id, name=None, artists=(("Artist A", "art_a"),), album=("Album", "alb_1")):
    """A full Spotify track object."""
    return {
        "id": track_id, "uri": f"spotify:track:{track_id}", "type": "track", "name": name or f"Song {track_id}",
        "duration_ms": 200000, "artists": [{"name": n, "id": i} for n, i in artists],
        "album": {"name": album[0], "id": album[1], "album_type": "album",
                  "artists": [{"name": artists[0][0], "id": artists[0][1]}],
                  "images": [{"url": "img", "width": 300}]},
    }


# ---------- rotations ----------

def make_rotation(client, spotify, items, interval_days=30, playlist_id="p1", grace=True, **kw):
    spotify.add_playlist(playlist_id, items, **kw)
    r = client.post("/api/rotation/", json={
        "playlist_id": playlist_id, "interval_hours": interval_days * 24, "grace_period": grace,
    })
    assert r.status_code == 201, r.text
    return r.json()


def liked_entry(track_id, added_days_ago=10):
    """A Liked Songs entry for FakeSpotify.liked: (track object, added_at)."""
    return track_object(track_id), (utcnow() - timedelta(days=added_days_ago)).isoformat() + "Z"


def grant_library_write(db, user):
    user.granted_scopes = (user.granted_scopes or "") + " user-library-modify"
    db.commit()


def make_liked_rotation(client, spotify, db, user, n=5, interval_days=30, grace=True):
    """A Liked Songs rotation over n liked songs l0..l{n-1} (l0 newest)."""
    grant_library_write(db, user)
    spotify.liked[:] = [liked_entry(f"l{i}", added_days_ago=10 + i) for i in range(n)]
    r = client.post("/api/rotation/", json={
        "liked_songs": True, "interval_hours": interval_days * 24, "grace_period": grace,
    })
    assert r.status_code == 201, r.text
    return r.json()


def new_rotation_id(client, spotify, items, playlist_id="p1"):
    """A manual rotation with the API's defaults (30 days, grace period on); returns its id."""
    return make_rotation(client, spotify, items, playlist_id=playlist_id)["id"]


def many_old_songs(n):
    # Distinct ages so "most overdue first" is well defined: s000 is the oldest
    return [spotify_item(f"s{i:03d}", 400 - i) for i in range(n)]


def backdate_rotation(db, rotation_id, days):
    """Pretend the rotation was created `days` ago (so the grace period has run out)."""
    rot = db.get(RotationDB, rotation_id)
    rot.created_at = utcnow() - timedelta(days=days)
    db.commit()


def shift_events(db, days):
    """Move every review event `days` into the past (simulates a new day)."""
    for event in db.query(ReviewEventDB):
        event.created_at -= timedelta(days=days)
    db.commit()


def set_account(db, **values):
    """Set account settings directly (e.g. review_limit=5)."""
    user = db.query(UserDB).one()
    for name, value in values.items():
        setattr(user, name, value)
    db.commit()


def review(client, rid, track_id, action):
    """POST a review decision (keep / super_keep / skip / remove / undo); returns the response."""
    return client.post(f"/api/rotation/{rid}/review", json={"track_id": track_id, "action": action})


def restock_action(client, rid, verb, track_id, source):
    """POST a restock action (add / skip / undo / block); returns the response."""
    return client.post(f"/api/rotation/{rid}/restock/{verb}", json={"track_id": track_id, "source": source})


def count_calls(spotify, kind):
    """How many times the fake Spotify saw this call ("get_playlist", "get_items", "add", ...)."""
    return sum(1 for c in spotify.calls if c[0] == kind)


# ---------- auto rotations ----------

def stock_signals(spotify, n, prefix="s"):
    tracks = [track_object(f"{prefix}{i:03}", artists=((f"Artist{i}", f"ar{i}"),)) for i in range(n)]
    for t in tracks:
        spotify.catalog[t["id"]] = t
    spotify.top[("tracks", "short_term")] = tracks[:50]
    spotify.top[("tracks", "medium_term")] = tracks[50:100]
    spotify.top[("tracks", "long_term")] = tracks[100:150]
    return tracks


def create_auto(client, **body):
    r = client.post("/api/rotation/", json={"kind": "auto", "name": "Fresh", **body})
    assert r.status_code == 201, r.text
    return r.json()


def active_rows(db, rid):
    return db.query(RotationTrackDB).filter_by(rotation_id=rid, status="active").all()


def make_due(db, rid, days=8):
    rotation = db.get(RotationDB, rid)
    rotation.created_at -= timedelta(days=days)
    if rotation.last_rotated_at:
        rotation.last_rotated_at -= timedelta(days=days)
    db.commit()


# ---------- demo mode ----------

DEMO_HEADERS = {"X-Requested-With": "XMLHttpRequest", "X-PlayLS-Demo": "1"}


def demo_catalog(n=90):
    """A small synthetic demo catalog: 3 sample playlists (40, 30, 10 songs) plus signals."""
    tracks = [
        track_object(f"d{i:03}", name=f"Demo Song {i}", artists=((f"Band {i % 12}", f"band{i % 12}"),),
                     album=(f"Record {i % 20}", f"rec{i % 20}"))
        for i in range(n)
    ]
    ids = [t["id"] for t in tracks]
    return {
        "tracks": tracks,
        "playlists": [
            {"id": "demo-sample-1", "name": "Daily Mix", "description": "Sample", "track_ids": ids[:40]},
            {"id": "demo-sample-2", "name": "Road Trip", "description": "", "track_ids": ids[40:70]},
            {"id": "demo-sample-3", "name": "Late Night", "description": "", "track_ids": ids[70:80]},
        ],
        "signals": {
            "top_tracks": {"short_term": ids[60:75], "medium_term": ids[70:85], "long_term": ids[80:90]},
            "top_artists": [{"id": f"band{i}", "name": f"Band {i}"} for i in range(5)],
            "recent": ids[75:90],
            "liked": ids[50:90],
        },
    }


def start_demo(client):
    """Start a demo on a TestClient (which keeps the demo cookie); returns the response JSON."""
    r = client.post("/api/demo/start", headers=DEMO_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()
