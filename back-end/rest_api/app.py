from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
import httpx
import os
from typing import Optional
import secrets
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="PlayLS API", version="1.0.0")

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Spotify OAuth configuration
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")

# In-memory storage for demo (use database in production)
user_tokens = {}
user_rotations = {}

@app.get("/")
async def root():
    return {"message": "PlayLS API is running"}

# @app.get("/auth/login")
# async def spotify_login():
#     """Initiate Spotify OAuth flow"""
#     state = secrets.token_urlsafe(32)
    
#     auth_url = (
#         f"https://accounts.spotify.com/authorize?"
#         f"response_type=code&"
#         f"client_id={SPOTIFY_CLIENT_ID}&"
#         f"redirect_uri={REDIRECT_URI}&"
#         f"scope=playlist-read-private playlist-modify-private user-read-private&"
#         f"state={state}"
#     )
    
#     return {"auth_url": auth_url, "state": state}

# @app.get("/auth/callback")
# async def spotify_callback(code: str, state: str):
#     """Handle Spotify OAuth callback"""
#     try:
#         # Exchange code for access token
#         async with httpx.AsyncClient() as client:
#             token_response = await client.post(
#                 "https://accounts.spotify.com/api/token",
#                 data={
#                     "grant_type": "authorization_code",
#                     "code": code,
#                     "redirect_uri": REDIRECT_URI,
#                     "client_id": SPOTIFY_CLIENT_ID,
#                     "client_secret": SPOTIFY_CLIENT_SECRET,
#                 }
#             )
            
#             if token_response.status_code != 200:
#                 raise HTTPException(status_code=400, detail="Failed to get access token")
            
#             token_data = token_response.json()
#             access_token = token_data["access_token"]
#             refresh_token = token_data.get("refresh_token")
            
#             # Get user info
#             user_response = await client.get(
#                 "https://api.spotify.com/v1/me",
#                 headers={"Authorization": f"Bearer {access_token}"}
#             )
            
#             if user_response.status_code != 200:
#                 raise HTTPException(status_code=400, detail="Failed to get user info")
            
#             user_data = user_response.json()
#             user_id = user_data["id"]
            
#             # Store tokens
#             user_tokens[user_id] = {
#                 "access_token": access_token,
#                 "refresh_token": refresh_token,
#                 "expires_at": token_data.get("expires_in", 3600)
#             }
            
#             return {
#                 "user_id": user_id,
#                 "access_token": access_token,
#                 "message": "Login successful"
#             }
            
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=str(e))

# @app.get("/user/playlists")
# async def get_user_playlists(user_id: str):
#     """Get user's playlists"""
#     if user_id not in user_tokens:
#         raise HTTPException(status_code=401, detail="User not authenticated")
    
#     access_token = user_tokens[user_id]["access_token"]
    
#     async with httpx.AsyncClient() as client:
#         response = await client.get(
#             "https://api.spotify.com/v1/me/playlists",
#             headers={"Authorization": f"Bearer {access_token}"}
#         )
        
#         if response.status_code != 200:
#             raise HTTPException(status_code=400, detail="Failed to get playlists")
        
#         return response.json()

# @app.get("/playlist/{playlist_id}/tracks")
# async def get_playlist_tracks(playlist_id: str, user_id: str):
#     """Get tracks from a specific playlist"""
#     if user_id not in user_tokens:
#         raise HTTPException(status_code=401, detail="User not authenticated")
    
#     access_token = user_tokens[user_id]["access_token"]
    
#     async with httpx.AsyncClient() as client:
#         response = await client.get(
#             f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
#             headers={"Authorization": f"Bearer {access_token}"}
#         )
        
#         if response.status_code != 200:
#             raise HTTPException(status_code=400, detail="Failed to get playlist tracks")
        
#         return response.json()

# @app.post("/rotation/create")
# async def create_rotation(user_id: str, playlist_id: str, rotation_interval: int = 30):
#     """Create a new rotation for a playlist"""
#     if user_id not in user_tokens:
#         raise HTTPException(status_code=401, detail="User not authenticated")
    
#     rotation_id = f"{user_id}_{playlist_id}_{secrets.token_urlsafe(8)}"
    
#     user_rotations[rotation_id] = {
#         "user_id": user_id,
#         "playlist_id": playlist_id,
#         "rotation_interval": rotation_interval,
#         "created_at": "2024-01-01T00:00:00Z",  # Use proper datetime
#         "songs_to_review": [],
#         "removed_songs": [],
#         "added_songs": []
#     }
    
#     return {"rotation_id": rotation_id, "message": "Rotation created successfully"}

# @app.get("/rotation/{rotation_id}/review")
# async def get_songs_to_review(rotation_id: str):
#     """Get songs that need to be reviewed for a rotation"""
#     if rotation_id not in user_rotations:
#         raise HTTPException(status_code=404, detail="Rotation not found")
    
#     rotation = user_rotations[rotation_id]
#     return {"songs_to_review": rotation["songs_to_review"]}

# @app.post("/rotation/{rotation_id}/review")
# async def review_song(rotation_id: str, song_id: str, action: str):
#     """Review a song (keep or remove)"""
#     if rotation_id not in user_rotations:
#         raise HTTPException(status_code=404, detail="Rotation not found")
    
#     if action not in ["keep", "remove"]:
#         raise HTTPException(status_code=400, detail="Action must be 'keep' or 'remove'")
    
#     rotation = user_rotations[rotation_id]
    
#     # Remove from songs_to_review
#     rotation["songs_to_review"] = [s for s in rotation["songs_to_review"] if s["id"] != song_id]
    
#     if action == "remove":
#         rotation["removed_songs"].append({"id": song_id, "removed_at": "2024-01-01T00:00:00Z"})
    
#     return {"message": f"Song {action}ed successfully"}

# @app.get("/recommendations")
# async def get_recommendations(user_id: str, seed_tracks: Optional[str] = None, seed_artists: Optional[str] = None):
#     """Get song recommendations"""
#     if user_id not in user_tokens:
#         raise HTTPException(status_code=401, detail="User not authenticated")
    
#     access_token = user_tokens[user_id]["access_token"]
    
#     params = {
#         "limit": 20,
#         "market": "US"
#     }
    
#     if seed_tracks:
#         params["seed_tracks"] = seed_tracks
#     if seed_artists:
#         params["seed_artists"] = seed_artists
    
#     async with httpx.AsyncClient() as client:
#         response = await client.get(
#             "https://api.spotify.com/v1/recommendations",
#             headers={"Authorization": f"Bearer {access_token}"},
#             params=params
#         )
        
#         if response.status_code != 200:
#             raise HTTPException(status_code=400, detail="Failed to get recommendations")
        
#         return response.json()

from .views import rotation
from .views import user
from .views import auth
from .views import spotify

app.include_router(auth.router)
app.include_router(user.router)
app.include_router(rotation.router)
app.include_router(spotify.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)