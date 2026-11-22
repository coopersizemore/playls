"""Single source of "now" so all timestamps are naive UTC and tests can freeze time."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current time as naive UTC (all DB timestamp columns store naive UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """Convert an aware datetime to naive UTC; naive values are assumed to be UTC already."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
