"""Scheduled jobs, called by Vercel Cron (see vercel.json "crons").

Vercel sends `Authorization: Bearer $CRON_SECRET` when the CRON_SECRET env var is set.
Without CRON_SECRET the route is disabled (404), so it can never run unauthenticated.
"""
import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database.config import get_db
from ..services.auto_restock_service import run_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cron", tags=["cron"], include_in_schema=False)


def _check_secret(authorization: str | None) -> None:
    secret = os.getenv("CRON_SECRET", "")
    if not secret:
        raise HTTPException(status_code=404, detail="Not Found")
    expected = f"Bearer {secret}"
    if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/auto-restock")
async def auto_restock(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Rotate out and restock every auto rotation that's due (daily)."""
    _check_secret(authorization)
    stats = await run_all(db)
    logger.info("Cron auto-restock: %s", stats)
    return stats
