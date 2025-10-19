from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from ..database.config import get_db
from ..database.models.user import UserDB
from ..services.auth_service import AuthService
from ..services.spotify.spotify_service import SpotifyService

router = APIRouter(prefix="/spotify", tags=["spotify"])

@router.get("/profile")
async def get_user_profile(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Get current user's Spotify profile"""
    try:
        profile = await SpotifyService.get_user_profile(current_user, db)
        return profile
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/playlists")
async def get_user_playlists(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Get current user's Spotify playlists"""
    try:
        playlists = await SpotifyService.get_user_playlists(current_user, db, limit, offset)
        return playlists
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/playlist/{playlist_id}")
async def get_playlist(
    playlist_id: str,
    fields: Optional[str] = None,
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Get a specific playlist"""
    try:
        playlist = await SpotifyService.get_playlist(playlist_id, current_user, db, fields)
        return playlist
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/playlist/{playlist_id}/tracks")
async def get_playlist_tracks(
    playlist_id: str,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    fields: Optional[str] = None,
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Get tracks from a specific playlist"""
    try:
        tracks = await SpotifyService.get_playlist_tracks(
            playlist_id, current_user, db, limit, offset, fields
        )
        return tracks
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/playlist/{playlist_id}/tracks")
async def add_tracks_to_playlist(
    playlist_id: str,
    track_uris: List[str],
    position: Optional[int] = None,
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Add tracks to a playlist"""
    try:
        result = await SpotifyService.add_tracks_to_playlist(
            playlist_id, track_uris, current_user, db, position
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/playlist/{playlist_id}/tracks")
async def remove_tracks_from_playlist(
    playlist_id: str,
    track_uris: List[str],
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Remove tracks from a playlist"""
    try:
        result = await SpotifyService.remove_tracks_from_playlist(
            playlist_id, track_uris, current_user, db
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/playlist")
async def create_playlist(
    name: str,
    description: Optional[str] = None,
    public: bool = False,
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Create a new playlist"""
    try:
        playlist = await SpotifyService.create_playlist(
            name, current_user, db, description, public
        )
        return playlist
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/recommendations")
async def get_recommendations(
    seed_artists: Optional[str] = Query(None, description="Comma-separated artist IDs"),
    seed_genres: Optional[str] = Query(None, description="Comma-separated genre names"),
    seed_tracks: Optional[str] = Query(None, description="Comma-separated track IDs"),
    limit: int = Query(20, ge=1, le=100),
    min_danceability: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_danceability: Optional[float] = Query(None, ge=0.0, le=1.0),
    target_danceability: Optional[float] = Query(None, ge=0.0, le=1.0),
    min_energy: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_energy: Optional[float] = Query(None, ge=0.0, le=1.0),
    target_energy: Optional[float] = Query(None, ge=0.0, le=1.0),
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Get song recommendations"""
    try:
        # Parse comma-separated values
        seed_artists_list = seed_artists.split(",") if seed_artists else None
        seed_genres_list = seed_genres.split(",") if seed_genres else None
        seed_tracks_list = seed_tracks.split(",") if seed_tracks else None
        
        # Build audio features dict
        audio_features = {}
        if min_danceability is not None:
            audio_features["min_danceability"] = min_danceability
        if max_danceability is not None:
            audio_features["max_danceability"] = max_danceability
        if target_danceability is not None:
            audio_features["target_danceability"] = target_danceability
        if min_energy is not None:
            audio_features["min_energy"] = min_energy
        if max_energy is not None:
            audio_features["max_energy"] = max_energy
        if target_energy is not None:
            audio_features["target_energy"] = target_energy
        
        recommendations = await SpotifyService.get_recommendations(
            current_user, db, seed_artists_list, seed_genres_list, 
            seed_tracks_list, limit, **audio_features
        )
        return recommendations
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/search")
async def search_spotify(
    q: str = Query(..., description="Search query"),
    type: str = Query("track", description="Search type: track, artist, album, playlist"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    market: str = Query("US", description="Market code"),
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """Search Spotify catalog"""
    try:
        results = await SpotifyService.search(
            q, current_user, db, type, limit, offset, market
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))