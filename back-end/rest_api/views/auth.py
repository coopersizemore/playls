import logging
import os
import secrets
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from ..database.config import get_db
from ..database.models.user import UserDB
from ..models.user import User
from ..services.auth_service import (
    SpotifyOAuthService,
    AuthService,
    clear_session_cookie,
    is_https,
    set_session_cookie,
)
from ..services.db import user_service as us

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

# Empty means same origin (Vercel): redirects become relative paths like /login
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

# OAuth state is round-tripped through this cookie to block login CSRF
STATE_COOKIE = "spotify_oauth_state"
STATE_COOKIE_PATH = "/api/auth"


def _login_failed() -> RedirectResponse:
    response = RedirectResponse(url=f"{FRONTEND_URL}/login?error=auth_failed")
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    return response


@router.get("/login")
async def spotify_login(request: Request):
    """
    Initiate Spotify OAuth flow
    Returns the authorization URL that frontend should redirect user to
    """
    auth_url, state = SpotifyOAuthService.get_auth_url()

    response = JSONResponse({
        "auth_url": auth_url,
        "message": "Redirect user to auth_url to complete Spotify login"
    })
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        path=STATE_COOKIE_PATH,
        httponly=True,
        secure=is_https(request),
        samesite="lax",  # sent on Spotify's top-level redirect back to us
    )
    return response

@router.get("/callback")
async def spotify_callback(
    request: Request,
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Handle Spotify OAuth callback
    This endpoint is called by Spotify after user authorizes the app
    """
    expected_state = request.cookies.get(STATE_COOKIE)
    if error or not code or not expected_state or not secrets.compare_digest(state, expected_state):
        return _login_failed()

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

        # Check if user already exists
        existing_user = db.query(UserDB).filter(UserDB.spotify_id == spotify_id).first()
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        if existing_user:
            existing_user.access_token = access_token
            if refresh_token:
                existing_user.refresh_token = refresh_token
            existing_user.token_expires_at = token_expires_at
            existing_user.display_name = display_name
            db.commit()
            db.refresh(existing_user)
            user = existing_user
        else:
            new_user_data = User(
                spotify_id=spotify_id,
                display_name=display_name,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at
            )
            user = us.create_user(db, new_user_data)

        # The app session lives in an httpOnly cookie, never in the URL
        jwt_token = AuthService.create_access_token(
            data={"sub": str(user.id), "spotify_id": user.spotify_id}
        )
        response = RedirectResponse(url=f"{FRONTEND_URL}/")
        response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
        set_session_cookie(response, jwt_token, request)
        return response

    except Exception:
        logger.exception("Error during Spotify callback")
        return _login_failed()


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
        "created_at": current_user.created_at
    }

@router.post("/logout")
async def logout():
    """
    Log out by clearing the session cookie (works even if the session already expired)
    """
    response = JSONResponse({"message": "Logged out successfully"})
    clear_session_cookie(response)
    return response
