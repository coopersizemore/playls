"""Per-request state: timing totals, one shared Spotify HTTP client, and the client's visibility hint.

`RequestContextMiddleware` creates a `RequestContext` for every HTTP request. It is stored
in a ContextVar, so tasks started by `asyncio.gather` see the same object. When the
response starts, it adds a `Server-Timing` header (total, Spotify and DB time).
Code running outside a request (tests that call services directly, scripts) gets
`current() is None` and falls back to its own behavior.
"""
import asyncio
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx

from rest_api.clock import utcnow

logger = logging.getLogger(__name__)

SPOTIFY_TIMEOUT = 20.0
SLOW_REQUEST_MS = 1500  # requests slower than this are logged with their breakdown

# Set by the frontend on every request: milliseconds since the app was last shown
# (loaded, or brought back from the background). Lets a sync skip only when the
# previous sync happened after the user could have been editing in Spotify.
VISIBLE_FOR_HEADER = b"x-visible-for"


@dataclass
class RequestContext:
    started: float = field(default_factory=time.perf_counter)
    spotify_ms: float = 0.0
    spotify_calls: int = 0
    db_ms: float = 0.0
    db_queries: int = 0
    db_connect_ms: float = 0.0
    db_connects: int = 0
    _connect_started: Optional[float] = None
    # When the client was last shown (UTC, naive); None if the client didn't say
    visible_since: Optional[datetime] = None
    _client: Optional[httpx.AsyncClient] = None
    _refresh_lock: Optional[asyncio.Lock] = None

    def spotify_client(self) -> httpx.AsyncClient:
        """One client per request, so Spotify calls reuse the TLS connection."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=SPOTIFY_TIMEOUT)
        return self._client

    def refresh_lock(self) -> asyncio.Lock:
        # Concurrent Spotify calls in one request must not refresh the token twice
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        return self._refresh_lock

    def server_timing(self) -> str:
        total = (time.perf_counter() - self.started) * 1000
        return (
            f'total;dur={total:.0f}, '
            f'spotify;dur={self.spotify_ms:.0f};desc="{self.spotify_calls} calls", '
            f'db;dur={self.db_ms:.0f};desc="{self.db_queries} queries", '
            f'dbconnect;dur={self.db_connect_ms:.0f};desc="{self.db_connects} connections"'
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_current: ContextVar[Optional[RequestContext]] = ContextVar("playls_request_context", default=None)


def current() -> Optional[RequestContext]:
    return _current.get()


def _visible_since(headers) -> Optional[datetime]:
    for name, value in headers:
        if name == VISIBLE_FOR_HEADER:
            try:
                ms = int(value)
            except ValueError:
                return None
            # Negative or absurd values are ignored rather than trusted
            if 0 <= ms <= 365 * 24 * 3600 * 1000:
                return utcnow() - timedelta(milliseconds=ms)
            return None
    return None


class RequestContextMiddleware:
    """Pure ASGI middleware (BaseHTTPMiddleware would run the app in a separate task)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        ctx = RequestContext(visible_since=_visible_since(scope.get("headers") or []))
        token = _current.set(ctx)

        async def send_with_timing(message):
            if message["type"] == "http.response.start":
                timing = ctx.server_timing()
                message = {**message, "headers": [*message.get("headers", []), (b"server-timing", timing.encode())]}
                total = (time.perf_counter() - ctx.started) * 1000
                if total > SLOW_REQUEST_MS:
                    logger.info("Slow request %s %s: %s", scope.get("method"), scope.get("path"), timing)
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            await ctx.close()
            _current.reset(token)


def install_db_timing(engine) -> None:
    """Count queries, connections (NullPool opens one per checkout) and time spent in them, per request."""
    from sqlalchemy import event

    @event.listens_for(engine, "do_connect")
    def _before_connect(dialect, conn_rec, cargs, cparams):
        ctx = current()
        if ctx is not None:
            ctx._connect_started = time.perf_counter()

    @event.listens_for(engine, "connect")
    def _after_connect(dbapi_conn, conn_rec):
        ctx = current()
        if ctx is not None and ctx._connect_started is not None:
            ctx.db_connect_ms += (time.perf_counter() - ctx._connect_started) * 1000
            ctx.db_connects += 1
            ctx._connect_started = None

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("playls_query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("playls_query_start")
        if not starts:
            return
        elapsed = (time.perf_counter() - starts.pop()) * 1000
        ctx = current()
        if ctx is not None:
            ctx.db_ms += elapsed
            ctx.db_queries += 1
