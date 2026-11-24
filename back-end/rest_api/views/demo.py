"""Public demo (DESIGN.md, "Demo mode"): start, skip ahead, end.

Demo requests carry the X-PlayLS-Demo header and the playls_demo_session cookie; every
other route works for them as usual (AuthService.get_current_user_from_token).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..clock import real_utcnow
from ..database.config import get_db
from ..database.models.user import DEMO, UserDB
from ..services.auth_service import (
    CSRF_HEADER,
    DEMO_SESSION_COOKIE,
    AuthService,
    clear_demo_cookie,
    set_demo_cookie,
)
from ..services.demo import demo_service

router = APIRouter(prefix="/demo", tags=["demo"])

current_user_dep = Depends(AuthService.get_current_user_from_token)


def _require_demo(user: UserDB = current_user_dep) -> UserDB:
    if user.provider != DEMO:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


def _existing(request: Request, db: Session) -> UserDB | None:
    """The demo account the browser already has, if its cookie is still valid."""
    token = request.cookies.get(DEMO_SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = AuthService.verify_token(token)
        user_id = int(payload["sub"])
    except (HTTPException, KeyError, TypeError, ValueError):
        return None
    if not payload.get("demo"):
        return None
    user = db.get(UserDB, user_id)
    if user is None or user.provider != DEMO or demo_service.expires_at(user) <= real_utcnow():
        return None
    return user


def _client_ip(request: Request) -> str:
    """The caller's IP. Vercel sets x-real-ip and overwrites x-forwarded-for, so clients
    can't spoof them there (off Vercel they're only trusted for local dev)."""
    ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
    ip = ip.strip() or (request.client.host if request.client else "")
    return ip[:64] or "unknown"


def _state(user: UserDB) -> dict:
    return {
        "expires_at": demo_service.expires_at(user),
        "clock_offset_hours": user.demo_clock_offset_hours or 0,
    }


@router.post("/start")
async def start_demo(request: Request, db: Session = Depends(get_db)):
    """Start a demo (or resume the one this browser already has) and set the demo cookie."""
    if not request.headers.get(CSRF_HEADER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF header")
    user = _existing(request, db) or demo_service.start(db, demo_service.client_hash(_client_ip(request)))
    remaining = demo_service.expires_at(user) - real_utcnow()
    token = AuthService.create_access_token(data={"sub": str(user.id), "demo": True}, expires_delta=remaining)
    response = JSONResponse(jsonable_encoder(_state(user)))
    set_demo_cookie(response, token, request)
    return response


@router.post("/skip-ahead")
async def skip_ahead(db: Session = Depends(get_db), user: UserDB = Depends(_require_demo)):
    """Move the demo's clock forward a day: more songs come due and the daily limit resets."""
    demo_service.skip_ahead(db, user)
    return _state(user)


@router.post("/end")
async def end_demo(db: Session = Depends(get_db), user: UserDB = Depends(_require_demo)):
    """Delete the demo account now and clear its cookie."""
    demo_service.end(db, user)
    response = JSONResponse({"message": "Demo ended"})
    clear_demo_cookie(response)
    return response

