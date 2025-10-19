import os
import httpx
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from ..database.config import get_db
from ..database.models.user import UserDB
from ..models.user import User

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Spotify OAuth Configuration
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/auth/callback")

# Security scheme
security = HTTPBearer()

class SpotifyOAuthService:
    """Service for handling Spotify OAuth authentication"""
    
    @staticmethod
    def get_auth_url() -> tuple[str, str]:
        """Generate Spotify OAuth authorization URL with state parameter"""
        state = secrets.token_urlsafe(32)
        
        scopes = [
            "playlist-read-private",
            "playlist-modify-private", 
            "playlist-modify-public",
            "user-read-private",
            "user-read-email",
            "user-library-read",
            "user-library-modify"
        ]
        
        auth_url = (
            "https://accounts.spotify.com/authorize?"
            f"response_type=code&"
            f"client_id={SPOTIFY_CLIENT_ID}&"
            f"redirect_uri={SPOTIFY_REDIRECT_URI}&"
            f"scope={'+'.join(scopes)}&"
            f"state={state}"
        )
        
        return auth_url, state
    
    @staticmethod
    async def exchange_code_for_tokens(code: str) -> dict:
        """Exchange authorization code for access and refresh tokens"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": SPOTIFY_REDIRECT_URI,
                    "client_id": SPOTIFY_CLIENT_ID,
                    "client_secret": SPOTIFY_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Failed to exchange code for tokens: {response.text}"
                )
            
            return response.json()
    
    @staticmethod
    async def get_spotify_user_info(access_token: str) -> dict:
        """Get user information from Spotify API"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to get user info from Spotify: {response.text}"
                )
            
            return response.json()
    
    @staticmethod
    async def refresh_access_token(refresh_token: str) -> dict:
        """Refresh Spotify access token using refresh token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": SPOTIFY_CLIENT_ID,
                    "client_secret": SPOTIFY_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="Failed to refresh access token"
                )
            
            return response.json()


class AuthService:
    """Service for JWT token management and user authentication"""
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> dict:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id: int = payload.get("sub")
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    @staticmethod
    def get_current_user_from_token(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db)
    ) -> UserDB:
        """Get current authenticated user from JWT token"""
        payload = AuthService.verify_token(credentials.credentials)
        user_id = payload.get("sub")
        
        user = db.query(UserDB).filter(UserDB.id == user_id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        return user
    
    @staticmethod
    async def ensure_valid_spotify_token(user: UserDB, db: Session) -> str:
        """Ensure user has valid Spotify access token, refresh if needed"""
        if not user.access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No Spotify access token available"
            )
        
        # Check if token is expired (with 5 minute buffer)
        if user.token_expires_at and user.token_expires_at <= datetime.utcnow() + timedelta(minutes=5):
            if not user.refresh_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access token expired and no refresh token available"
                )
            
            # Refresh the token
            token_data = await SpotifyOAuthService.refresh_access_token(user.refresh_token)
            
            # Update user with new token
            user.access_token = token_data["access_token"]
            user.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            
            # Update refresh token if provided
            if "refresh_token" in token_data:
                user.refresh_token = token_data["refresh_token"]
            
            db.commit()
            db.refresh(user)
        
        return user.access_token