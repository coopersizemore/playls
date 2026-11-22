from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..clock import utcnow
from ..database.config import get_db
from ..database.models.curated_pick import CuratedPickDB
from ..database.models.user import UserDB
from ..models.restock import PickIn, PickOut, PickUpdate
from ..services import restock_service as restock
from ..services.auth_service import require_admin

# Curating PlayLS picks. Only accounts listed in ADMIN_SPOTIFY_IDS; everyone else gets 404.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _out(pick: CuratedPickDB, now) -> PickOut:
    active = (pick.starts_at is None or pick.starts_at <= now) and (pick.ends_at is None or pick.ends_at > now)
    return PickOut(
        id=pick.id, track_id=pick.track_id, uri=pick.uri, title=pick.title, artists=pick.artists,
        album=pick.album, image_url=pick.image_url, note=pick.note, starts_at=pick.starts_at,
        ends_at=pick.ends_at, created_at=pick.created_at, active=active,
    )


@router.get("/picks", response_model=list[PickOut])
async def list_picks(db: Session = Depends(get_db)):
    now = utcnow()
    picks = db.query(CuratedPickDB).order_by(CuratedPickDB.created_at.desc(), CuratedPickDB.id.desc())
    return [_out(p, now) for p in picks]


@router.post("/picks", response_model=PickOut, status_code=201)
async def create_pick(data: PickIn, db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    pick = await restock.create_pick(db, admin, data.track_id, data.note, data.starts_at, data.ends_at)
    return _out(pick, utcnow())


@router.put("/picks/{pick_id}", response_model=PickOut)
async def update_pick(pick_id: int, data: PickUpdate, db: Session = Depends(get_db)):
    """Edit a pick's note and active dates (to change the song, delete and re-add)."""
    pick = db.get(CuratedPickDB, pick_id)
    if pick is None:
        raise HTTPException(status_code=404, detail="Pick not found")
    pick = restock.update_pick(db, pick, data.model_dump(exclude_unset=True))
    return _out(pick, utcnow())


@router.delete("/picks/{pick_id}", status_code=204)
async def delete_pick(pick_id: int, db: Session = Depends(get_db)):
    pick = db.get(CuratedPickDB, pick_id)
    if pick is None:
        raise HTTPException(status_code=404, detail="Pick not found")
    db.delete(pick)
    db.commit()
