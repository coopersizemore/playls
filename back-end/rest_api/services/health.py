"""App health: per-request timing and counters for the admin dashboard.

`count("sync.full_read")` adds to the current request's counters (a no-op outside a request).
At the end of each /api request, RequestContextMiddleware calls `record_request`. That writes
one `health_event` row when the request is worth keeping:
- always: errors (5xx), Spotify-style 429s, slow requests, and any request with counters;
- otherwise: a random SAMPLE_RATE share, flagged `sampled` (latency percentiles use only these,
  so they stay unbiased).
No user is stored. Recording is best-effort: it never raises, and it runs off the event loop.
"""
import json
import logging
import random
import re
from collections.abc import Callable

from sqlalchemy.orm import Session

from rest_api import request_context
from rest_api.clock import real_utcnow

logger = logging.getLogger(__name__)

SAMPLE_RATE = 0.25
SLOW_MS = 1500

# Tests point this at their database; None = the app's SessionLocal
session_factory: Callable[[], Session] | None = None

_ID_SEGMENT = re.compile(r"^(\d+|[A-Za-z0-9]{16,})$")


def count(name: str, n: int = 1) -> None:
    ctx = request_context.current()
    if ctx is not None and n:
        ctx.counters[name] = ctx.counters.get(name, 0) + n


def route_template(scope) -> str:
    """The route's template (/api/rotation/{rotation_id}), so rows group by endpoint, not by id."""
    route = scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path[:120]
    parts = [("{id}" if _ID_SEGMENT.match(p) else p) for p in (scope.get("path") or "").split("/")]
    return "/".join(parts)[:120]


def should_record(status: int, duration_ms: float, counters: dict, rand: float) -> tuple[bool, bool]:
    """(record it, it's part of the random sample)."""
    sampled = rand < SAMPLE_RATE
    always = status >= 500 or status == 429 or duration_ms >= SLOW_MS or bool(counters)
    return always or sampled, sampled


def record_request(ctx, scope, status: int, duration_ms: float, rand: float | None = None) -> None:
    path = scope.get("path") or ""
    if not path.startswith("/api/"):
        return
    try:
        record, sampled = should_record(status, duration_ms, ctx.counters, random.random() if rand is None else rand)
        if not record:
            return
        from rest_api.database.models.health_event import HealthEventDB

        row = HealthEventDB(
            method=(scope.get("method") or "")[:8], route=route_template(scope), status=status,
            duration_ms=round(duration_ms), spotify_ms=round(ctx.spotify_ms), spotify_calls=ctx.spotify_calls,
            db_ms=round(ctx.db_ms), db_queries=ctx.db_queries, db_connects=ctx.db_connects, sampled=sampled,
            created_at=real_utcnow(),  # never a demo account's skipped-ahead clock
            counters=json.dumps(ctx.counters, sort_keys=True) if ctx.counters else None,
        )
        factory = session_factory
        if factory is None:
            from rest_api.database.config import SessionLocal
            factory = SessionLocal
        db = factory()
        try:
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("Couldn't record request health", exc_info=True)
