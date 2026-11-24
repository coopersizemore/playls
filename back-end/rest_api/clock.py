"""Single source of "now" so all timestamps are naive UTC and tests can freeze time.

Demo accounts can "skip ahead" (services/demo): during their requests `utcnow()` runs that
many hours ahead, so every rule that reads the clock (due dates, the daily limit, sync
leases) moves forward together. `real_utcnow()` ignores the offset.
"""
from datetime import UTC, datetime, timedelta


def real_utcnow() -> datetime:
    """The actual current time as naive UTC, ignoring any demo clock offset."""
    return datetime.now(UTC).replace(tzinfo=None)


def _offset_hours() -> int:
    # Imported lazily: request_context imports this module
    from rest_api import request_context

    ctx = request_context.current()
    return ctx.clock_offset_hours if ctx is not None else 0


def utcnow() -> datetime:
    """Current time as naive UTC (all DB timestamp columns store naive UTC)."""
    now = real_utcnow()
    offset = _offset_hours()
    return now + timedelta(hours=offset) if offset else now


def to_naive_utc(value: datetime) -> datetime:
    """Convert an aware datetime to naive UTC; naive values are assumed to be UTC already."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value
