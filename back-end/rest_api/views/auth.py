from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from ..database.config import get_db
from ..database.models.user import UserDB
from ..models.user import User
from ..services.auth_service import SpotifyOAuthService, AuthService
from ..services.db import user_service as us

router = APIRouter(prefix="/auth", tags=["authentication"])

FRONTEND_URL = "http://localhost:3000"

@router.get("/login")
async def spotify_login():
    """
    Initiate Spotify OAuth flow
    Returns the authorization URL that frontend should redirect user to
    """
    try:
        auth_url, state = SpotifyOAuthService.get_auth_url()
        return {
            "auth_url": auth_url,
            "state": state,
            "message": "Redirect user to auth_url to complete Spotify login"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate auth URL: {str(e)}"
        )

@router.get("/callback")
async def spotify_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Handle Spotify OAuth callback
    This endpoint is called by Spotify after user authorizes the app
    """
    try:
        # Exchange code for tokens
        token_data = await SpotifyOAuthService.exchange_code_for_tokens(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        
        # Get user info from Spotify
        spotify_user_data = await SpotifyOAuthService.get_spotify_user_info(access_token)
        spotify_id = spotify_user_data["id"]
        display_name = spotify_user_data.get("display_name", "")
        email = spotify_user_data.get("email")
        
        # Check if user already exists
        existing_user = db.query(UserDB).filter(UserDB.spotify_id == spotify_id).first()
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        if existing_user:
            existing_user.access_token = access_token
            existing_user.refresh_token = refresh_token
            existing_user.token_expires_at = token_expires_at
            existing_user.display_name = display_name
            existing_user.email = email
            db.commit()
            db.refresh(existing_user)
            user = existing_user
        else:
            new_user_data = User(
                spotify_id=spotify_id,
                display_name=display_name,
                email=email,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at
            )
            user = us.create_user(db, new_user_data)
        
        # Create JWT for your app
        jwt_token = AuthService.create_access_token(
            data={"sub": str(user.id), "spotify_id": user.spotify_id}
        )

        # 🔁 Redirect to your frontend callback route
        redirect_url = f"{FRONTEND_URL}/callback?token={jwt_token}&user_id={user.id}"
        return RedirectResponse(url=redirect_url)
    
    except Exception as e:
        print(f"Error during Spotify callback: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/login?error=auth_failed")


@router.get("/me")
async def get_current_user(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token)
):
    """
    Get current authenticated user information
    """
    return {
        "id": current_user.id,
        "spotify_id": current_user.spotify_id,
        "display_name": current_user.display_name,
        "email": current_user.email,
        "created_at": current_user.created_at
    }

@router.post("/refresh")
async def refresh_token(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """
    Refresh user's Spotify access token
    """
    try:
        if not current_user.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No refresh token available"
            )
        
        # Refresh Spotify token
        token_data = await SpotifyOAuthService.refresh_access_token(current_user.refresh_token)
        
        # Update user with new tokens
        current_user.access_token = token_data["access_token"]
        current_user.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
        
        if "refresh_token" in token_data:
            current_user.refresh_token = token_data["refresh_token"]
        
        db.commit()
        db.refresh(current_user)
        
        # Create new JWT token
        jwt_token = AuthService.create_access_token(
            data={"sub": str(current_user.id), "spotify_id": current_user.spotify_id}
        )
        
        return {
            "access_token": jwt_token,
            "token_type": "bearer",
            "message": "Token refreshed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh token: {str(e)}"
        )

@router.post("/logout")
async def logout(
    current_user: UserDB = Depends(AuthService.get_current_user_from_token),
    db: Session = Depends(get_db)
):
    """
    Logout user by clearing their stored tokens
    """
    try:
        # Clear user tokens (optional - depends on your security requirements)
        # current_user.access_token = None
        # current_user.refresh_token = None
        # current_user.token_expires_at = None
        # db.commit()
        
        return {"message": "Logged out successfully"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )