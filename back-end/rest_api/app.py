import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rest_api.request_context import RequestContextMiddleware

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Interactive docs are off unless explicitly enabled (e.g. locally or on the dev deployment)
_docs_enabled = os.getenv("ENABLE_API_DOCS", "").lower() == "true"
app = FastAPI(
    title="PlayLS API",
    version="1.0.0",
    docs_url="/api/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _docs_enabled else None,
)

# CORS is only needed when the frontend runs on a different origin (e.g. a standalone
# React dev server). On Vercel both services share one domain.
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL] if FRONTEND_URL else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Server-Timing"],
)
# Outermost: times the whole request and owns the per-request Spotify client
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(httpx.HTTPError)
async def spotify_network_error(request: Request, exc: httpx.HTTPError):
    # Timeouts / connection failures talking to Spotify; details stay in the server log
    logger.warning("Upstream HTTP error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=502, content={"detail": "Spotify request failed"})


@app.get("/api")
async def root():
    return {"message": "PlayLS API is running"}


from .views import admin, auth, cron, restock, rotation, spotify, user  # noqa: E402

# Vercel forwards the full request path, so every route lives under /api
API_PREFIX = "/api"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(user.router, prefix=API_PREFIX)
app.include_router(rotation.router, prefix=API_PREFIX)
app.include_router(spotify.router, prefix=API_PREFIX)
app.include_router(restock.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(cron.router, prefix=API_PREFIX)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
