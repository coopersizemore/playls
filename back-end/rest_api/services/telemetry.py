"""Usage analytics capture (opt-in) and the 6-month retention purge.

Review and Restock attach an optional `telemetry` object to the requests they already make.
It's parsed leniently: anything invalid is dropped, so analytics can never break a decision.
Nothing is written unless the user opted in (users.analytics_consent is True), and recording
is best-effort (errors are logged, never raised). See docs/MONITORING_PLAN.md.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from rest_api.clock import utcnow
from rest_api.database.models.analytics_event import DECISION, SESSION_END, UNDO, AnalyticsEventDB
from rest_api.database.models.health_event import HealthEventDB
from rest_api.database.models.rotation import MANUAL, RotationDB
from rest_api.database.models.rotation_track import RotationTrackDB
from rest_api.database.models.user import UserDB
from rest_api.services import rotation_logic

logger = logging.getLogger(__name__)

RETENTION_DAYS = 180
MAX_DECISION_MS = 10 * 60 * 1000  # longer than this: they listened to it all, or walked away
MAX_ELAPSED_MS = 6 * 60 * 60 * 1000
UUID = r"^[0-9a-fA-F-]{36}$"


class Telemetry(BaseModel):
    """What the client measured around one decision. Every field is optional."""
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(..., pattern=UUID)
    decision_ms: int | None = Field(None, ge=0)
    session_elapsed_ms: int | None = Field(None, ge=0)
    input: Literal["swipe", "button", "key"] | None = None
    revisit: bool | None = None
    position: int | None = Field(None, ge=0, le=100_000)
    tz_offset: int | None = Field(None, ge=-840, le=840)  # JS getTimezoneOffset()


class SessionEndIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., pattern=UUID)
    surface: Literal["review", "restock"]
    rotation_id: int | None = None
    ended: Literal["done", "stopped", "left", "exhausted"]
    decisions: int = Field(0, ge=0, le=100_000)
    session_elapsed_ms: int = Field(0, ge=0)
    tz_offset: int | None = Field(None, ge=-840, le=840)
    source: Literal["bring_back", "picks", "suggested", "search"] | None = None


def enabled(user: UserDB) -> bool:
    return user.analytics_consent is True


def parse(raw: Any) -> Telemetry | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Telemetry.model_validate(raw)
    except ValidationError:
        return None


def _clamp(value: int | None, high: int) -> int | None:
    return None if value is None else min(value, high)


def _local(now: datetime, tz_offset: int | None) -> tuple[int | None, int | None]:
    if tz_offset is None:
        return None, None
    local = now - timedelta(minutes=tz_offset)
    return local.hour, local.weekday()


def song_context(track: RotationTrackDB | None, rotation: RotationDB, now: datetime) -> dict[str, int | None]:
    """The song's state just before a review decision: how long it has been in rotation since it
    was added or last kept, and (manual rotations) how many days past due it is."""
    if track is None:
        return {"song_age_days": None, "overdue_days": None}
    anchor = track.last_kept_at or track.added_at
    age = (now - anchor).days if anchor else None
    overdue = None
    if rotation.kind == MANUAL:
        due = rotation_logic.due_at(track, rotation)
        overdue = max(0, (now - due).days) if due else None
    return {"song_age_days": age, "overdue_days": overdue}


def _write(db: Session, event: AnalyticsEventDB) -> None:
    try:
        db.add(event)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Couldn't record an analytics event", exc_info=True)


def record_decision(
    db: Session, user: UserDB, rotation: RotationDB, surface: str, action: str, raw: Any,
    source: str | None = None, song: dict[str, int | None] | None = None, now: datetime | None = None,
) -> None:
    """A review or restock decision (action "undo" is recorded as an undo)."""
    if not enabled(user):
        return
    t = parse(raw)
    if t is None:
        return
    now = now or utcnow()
    hour, weekday = _local(now, t.tz_offset)
    _write(db, AnalyticsEventDB(
        user_id=user.id, rotation_id=rotation.id, rotation_kind=rotation.kind, surface=surface,
        kind=UNDO if action == "undo" else DECISION, session_id=t.session_id,
        action=None if action == "undo" else action, source=source,
        decision_ms=_clamp(t.decision_ms, MAX_DECISION_MS),
        session_elapsed_ms=_clamp(t.session_elapsed_ms, MAX_ELAPSED_MS),
        input=t.input, revisit=t.revisit, position=t.position,
        local_hour=hour, local_weekday=weekday, created_at=now,
        **(song or {}),
    ))


def record_session_end(db: Session, user: UserDB, data: SessionEndIn, now: datetime | None = None) -> None:
    if not enabled(user):
        return
    rotation = None
    if data.rotation_id is not None:
        rotation = db.query(RotationDB).filter(
            RotationDB.id == data.rotation_id, RotationDB.owner_id == user.id
        ).first()
    now = now or utcnow()
    hour, weekday = _local(now, data.tz_offset)
    _write(db, AnalyticsEventDB(
        user_id=user.id, rotation_id=rotation.id if rotation else None,
        rotation_kind=rotation.kind if rotation else None, surface=data.surface, kind=SESSION_END,
        session_id=data.session_id, source=data.source, ended=data.ended, decisions=data.decisions,
        session_elapsed_ms=_clamp(data.session_elapsed_ms, MAX_ELAPSED_MS),
        local_hour=hour, local_weekday=weekday, created_at=now,
    ))


def set_consent(db: Session, user: UserDB, consent: bool) -> None:
    """Opting out also deletes what was recorded for this user."""
    user.analytics_consent = consent
    user.analytics_consent_at = utcnow()
    if not consent:
        db.query(AnalyticsEventDB).filter(AnalyticsEventDB.user_id == user.id).delete(synchronize_session=False)
    db.commit()


def purge(db: Session, now: datetime | None = None) -> int:
    """Delete analytics and health rows older than RETENTION_DAYS. Returns how many went."""
    cutoff = (now or utcnow()) - timedelta(days=RETENTION_DAYS)
    gone = db.query(AnalyticsEventDB).filter(AnalyticsEventDB.created_at < cutoff).delete(synchronize_session=False)
    gone += db.query(HealthEventDB).filter(HealthEventDB.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return gone

