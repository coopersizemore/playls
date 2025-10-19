import httpx
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from ...database.models.user import UserDB
from ...database.config import get_db
from ..auth_service import AuthService

class SpotifyService:
    """Service for interacting with Spotify Web API"""
    
    @staticmethod
    async def make_spotify_request(
        endpoint: str,
        user: UserDB,
        db: Session,
        method: str = "GET",
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Make authenticated request to Spotify API
        Automatically handles token refresh if needed
        """
        # Ensure valid access token
        access_token = await AuthService.ensure_valid_spotify_token(user, db)
        
        url = f"https://api.spotify.com/v1{endpoint}"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            if method.upper() == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = await client.post(url, headers=headers, json=data, params=params)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=headers, json=data, params=params)
            elif method.upper() == "DELETE":
                response = await client.delete(url, headers=headers, params=params)
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported HTTP method: {method}")
            
            if response.status_code == 401:
                # Token might be expired, try to refresh once more
                access_token = await AuthService.ensure_valid_spotify_token(user, db)
                headers = {"Authorization": f"Bearer {access_token}"}
                
                # Retry the request
                if method.upper() == "GET":
                    response = await client.get(url, headers=headers, params=params)
                elif method.upper() == "POST":
                    response = await client.post(url, headers=headers, json=data, params=params)
                elif method.upper() == "PUT":
                    response = await client.put(url, headers=headers, json=data, params=params)
                elif method.upper() == "DELETE":
                    response = await client.delete(url, headers=headers, params=params)
            
            if not response.is_success:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Spotify API error: {response.text}"
                )
            
            return response.json() if response.content else {}
    
    @staticmethod
    async def get_user_profile(
        user: UserDB,
        db: Session
    ) -> Dict[str, Any]:
        """Get current user's Spotify profile"""
        return await SpotifyService.make_spotify_request("/me", user, db)
    
    @staticmethod
    async def get_user_playlists(
        user: UserDB,
        db: Session,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get current user's playlists"""
        params = {"limit": limit, "offset": offset}
        return await SpotifyService.make_spotify_request("/me/playlists", user, db, params=params)
    
    @staticmethod
    async def get_playlist(
        playlist_id: str,
        user: UserDB,
        db: Session,
        fields: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get a specific playlist"""
        params = {"fields": fields} if fields else None
        return await SpotifyService.make_spotify_request(f"/playlists/{playlist_id}", user, db, params=params)
    
    @staticmethod
    async def get_playlist_tracks(
        playlist_id: str,
        user: UserDB,
        db: Session,
        limit: int = 100,
        offset: int = 0,
        fields: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get tracks from a specific playlist"""
        params = {
            "limit": limit,
            "offset": offset
        }
        if fields:
            params["fields"] = fields
        
        return await SpotifyService.make_spotify_request(
            f"/playlists/{playlist_id}/tracks", 
            user, 
            db, 
            params=params
        )
    
    @staticmethod
    async def add_tracks_to_playlist(
        playlist_id: str,
        track_uris: List[str],
        user: UserDB,
        db: Session,
        position: Optional[int] = None
    ) -> Dict[str, Any]:
        """Add tracks to a playlist"""
        data = {"uris": track_uris}
        if position is not None:
            data["position"] = position
        
        return await SpotifyService.make_spotify_request(
            f"/playlists/{playlist_id}/tracks",
            user,
            db,
            method="POST",
            data=data
        )
    
    @staticmethod
    async def remove_tracks_from_playlist(
        playlist_id: str,
        track_uris: List[str],
        user: UserDB,
        db: Session
    ) -> Dict[str, Any]:
        """Remove tracks from a playlist"""
        tracks = [{"uri": uri} for uri in track_uris]
        data = {"tracks": tracks}
        
        return await SpotifyService.make_spotify_request(
            f"/playlists/{playlist_id}/tracks",
            user,
            db,
            method="DELETE",
            data=data
        )
    
    @staticmethod
    async def create_playlist(
        name: str,
        user: UserDB,
        db: Session,
        description: Optional[str] = None,
        public: bool = False
    ) -> Dict[str, Any]:
        """Create a new playlist"""
        user_profile = await SpotifyService.get_user_profile(user, db)
        user_id = user_profile["id"]
        
        data = {
            "name": name,
            "public": public
        }
        if description:
            data["description"] = description
        
        return await SpotifyService.make_spotify_request(
            f"/users/{user_id}/playlists",
            user,
            db,
            method="POST",
            data=data
        )
    
    @staticmethod
    async def get_recommendations(
        user: UserDB,
        db: Session,
        seed_artists: Optional[List[str]] = None,
        seed_genres: Optional[List[str]] = None,
        seed_tracks: Optional[List[str]] = None,
        limit: int = 20,
        **audio_features
    ) -> Dict[str, Any]:
        """Get song recommendations based on seed data"""
        params = {"limit": limit}
        
        if seed_artists:
            params["seed_artists"] = ",".join(seed_artists)
        if seed_genres:
            params["seed_genres"] = ",".join(seed_genres)  
        if seed_tracks:
            params["seed_tracks"] = ",".join(seed_tracks)
        
        # Add audio feature parameters (danceability, energy, etc.)
        for key, value in audio_features.items():
            if key.startswith(('min_', 'max_', 'target_')):
                params[key] = value
        
        return await SpotifyService.make_spotify_request(
            "/recommendations",
            user,
            db,
            params=params
        )
    
    @staticmethod
    async def search(
        query: str,
        user: UserDB,
        db: Session,
        search_type: str = "track",
        limit: int = 20,
        offset: int = 0,
        market: str = "US"
    ) -> Dict[str, Any]:
        """Search for tracks, artists, albums, or playlists"""
        params = {
            "q": query,
            "type": search_type,
            "limit": limit,
            "offset": offset,
            "market": market
        }
        
        return await SpotifyService.make_spotify_request(
            "/search",
            user,
            db,
            params=params
        )