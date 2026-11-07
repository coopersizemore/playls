# PlayLS

Spotify "lazy susan": a rotation wraps a playlist the user owns, and songs come due for keep/skip/remove review every N days. Product spec: [mvp.txt](docs/mvp.txt), annotated with what's deferred or scrapped. **Owner decisions and semantics (source of truth, due-date math, batched removals, data model): [DESIGN.md](docs/DESIGN.md).** Phased build plan: [PROJECT_STATUS.md](docs/PROJECT_STATUS.md). The owner knows the product well, so don't explain it back; focus on the code.

Status: unfinished prototype. The architecture is settled (Supabase + Vercel + Spotify OAuth), so build within it. Scope is Spotify only, personal use (at most 5 users). Apple Music is a maybe-later, so keep track IDs provider-neutral and add a `provider` column, but build no abstraction layer. The internal code structure (services, models) is still provisional.

## Layout
- `back-end/rest_api/` — FastAPI. Run from `back-end/` as `python -m rest_api.app` (port 8000). Package uses a mix of relative (`..`) and absolute (`rest_api.`) imports, so it only works from `back-end/` as the CWD.
  - `views/` routers: `auth`, `user`, `rotation`, `spotify` (all mounted in `app.py`). `example_routes.py` is fully commented out.
  - `services/auth_service.py` — Spotify OAuth + app session (JWT via python-jose, HS256, 7 days, in an httpOnly cookie). `get_current_user_from_token` is the auth dependency (cookie + CSRF check).
  - `database/encryption.py` — `EncryptedText` column type (Fernet, `TOKEN_ENCRYPTION_KEY`) used for the Spotify tokens on `UserDB`.
  - `services/spotify/spotify_service.py` — thin httpx wrapper over the Spotify Web API; auto-refreshes the stored Spotify token.
  - `services/db/{user,rotation}_service.py` — live CRUD. `services/db/services.py` is dead (it references fields that don't exist).
  - `database/models/*` are the SQLAlchemy models (`UserDB`, `RotationDB`, `SongDB`); `models/*` are the Pydantic schemas.
  - `database/config.py` connects to **Supabase Postgres** via `DATABASE_URL`, using the psycopg 3 driver, `NullPool`, and `prepare_threshold=None` for the transaction pooler. It raises if `DATABASE_URL` is unset. The user table is `users` (`user` is reserved in Postgres).
  - `python -m rest_api.database.init_db` creates missing tables and enables RLS (no policies), which blocks Supabase's Data API. `--reset` drops everything first. There's no Alembic yet.
- `playls_front_end/` — CRA (react-scripts 5), React 19, MUI 7, react-router 7, axios. Pages are in `src/components/`, and auth state is in `src/contexts/AuthContext.js` (asks `GET /api/auth/me` on load; it never sees a token).
- Root `start-*.bat`/`.sh` launch the dev servers. `back-end/AUTHENTICATION.md` and `auth_demo.py` are untracked generated docs and a demo script that describe the **old** Bearer-token flow, so they're stale.

## Routing and deployment (Vercel services)
- Root [vercel.json](vercel.json) defines two services: `api` (`back-end`, entrypoint `rest_api.app:app`) and `web` (`playls_front_end`, CRA with an SPA fallback). `/api` and `/api/*` route to `api`; everything else goes to `web`. There are no service bindings, because no service calls another server-side.
- Vercel passes the **full path** through, so all FastAPI routers are mounted with the `/api` prefix in `app.py`. New routers must be mounted the same way.
- The frontend always calls the relative `API_BASE = '/api'` (`src/api.js`). Never hardcode a backend host.
- Python is **3.12** (`back-end/.python-version`). `vercel dev` needs 3.12+, and on this Windows machine `python`/`python3` resolve to the Microsoft Store 3.11. In multi-service mode `vercel dev` only uses a venv at **`back-end/.venv`** (or `back-end/venv`); if none exists it creates one with that 3.11 and fails installing `vercel-runtime`. Keep `back-end/.venv` on 3.12 (`<Python312>\python.exe -m venv back-end/.venv`), and don't activate a venv before running `vercel dev`.
- Local dev: `vercel dev` (single origin on :3000, the preferred option), or `npm start` plus `python -m rest_api.app`. The second option relies on the CRA `proxy` in `package.json` and needs `FRONTEND_URL` and an `SPOTIFY_REDIRECT_URI` on :8000 (see `env.example`).
- Env vars (see `back-end/env.example`):
  - Required: `DATABASE_URL`, `SECRET_KEY` (32+ chars; published placeholders are rejected), `TOKEN_ENCRYPTION_KEY` (must match everywhere sharing the DB). The app refuses to start without these. Also `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REDIRECT_URI` (must end in `/api/auth/callback` and match the Spotify dashboard).
  - Optional: `FRONTEND_URL` (empty means same origin, so the post-login redirect is the relative `/`), `ENABLE_API_DOCS` (Swagger at `/api/docs`, off by default), `SQL_ECHO`.

## Security model (keep it this way)
- Every `/api/user/*`, `/api/rotation/*` and `/api/spotify/*` route requires the session cookie (`playls_session`, httpOnly, SameSite=Lax, path `/api`). There's no Bearer-header auth. Non-GET requests also need an `X-Requested-With` header (CSRF), which `src/api.js` sets on axios globally. Rotations are fetched with `rotation_service.get_owned_rotation`, and other users' rotations return 404.
- `owner_id`, `id` and `created_at` are server-managed (`SERVER_MANAGED_FIELDS`) and never taken from request bodies.
- There's no route that lists users or returns `UserDB` rows. Those rows contain Spotify tokens, so never return them directly.
- OAuth `state` is round-tripped in an httpOnly `spotify_oauth_state` cookie (path `/api/auth`) and checked on callback.
- Spotify tokens are encrypted at rest (`EncryptedText`).
- Errors from Spotify and unexpected exceptions are logged server-side; clients get generic messages (502/429). Don't put `str(e)` or upstream response bodies in `detail`.
- `vercel.json` sets nosniff, frame-deny, referrer and permissions headers. There's no CSP yet, because the CRA inline runtime chunk and MUI's inline styles need care.

## Auth flow
Frontend `GET /api/auth/login` → redirects to Spotify → Spotify redirects to `/api/auth/callback` → backend checks `state`, upserts the user (encrypted Spotify tokens in `users`), sets the `playls_session` cookie, and redirects to `FRONTEND_URL/` → `AuthContext` calls `/api/auth/me`. Failures redirect to `/login?error=auth_failed`. `POST /api/auth/logout` clears the cookie. Spotify access tokens refresh automatically in `ensure_valid_spotify_token`.

## Known gaps and bugs (verify before relying on these)
- Core rotation logic is not implemented. `/rotation/{id}/rotate`, `/songs`, `/song` add/remove are `pass`. Nothing syncs playlist tracks into `song`, and nothing computes which songs are due.
- `SongDB.id` is the Spotify track ID and is the sole PK, so a track can't be in two rotations.
- Sessions can't be revoked server-side before their 7-day expiry (logout only clears the cookie). There's no rate limiting.
- Frontend: `Home.js` destructures `useState` with `{}` instead of `[]` (bug). `Review`, `Restock` and `History` use mock data, and they call a nonexistent `/recommendations?user_id=` route.
- Redirect URIs must be HTTPS or `http://127.0.0.1` (`localhost` isn't allowed).

## Spotify API constraints (Development Mode, after Feb 2026)
This app is in Development Mode: max 5 allowlisted users per Client ID, and the owner needs Premium. Extended quota is effectively unavailable. Build against the post-Feb-2026 API (changelog: developer.spotify.com/documentation/web-api/references/changes/february-2026):
- Playlist items: `/playlists/{id}/tracks` → `/playlists/{id}/items`. Response fields are renamed (`tracks` → `items`, `track` → `item`). Contents are only returned for playlists the user **owns or collaborates on**. `spotify_service.py` and `Rotation.js` (`playlist.tracks.total`) still use the old names.
- Create playlist: `POST /users/{id}/playlists` was removed, so use `POST /me/playlists`. `create_playlist` is currently broken.
- `GET /me/playlists` still works. `GET /users/{id}/playlists` was removed.
- `/me` no longer returns `email`, `country` or `product`. Don't depend on `UserDB.email`, and drop the `user-read-email` scope.
- Search `limit` is max 10 (default 5), so paginate. Artist top tracks, batch "several" lookups, browse/new releases and `popularity` are gone. Per-type save endpoints moved to `/me/library`.
- Quota is shared across every Client ID on the developer account. Quota errors come back as 429 with `"reason": "QUOTA_EXCEEDED"`.

## Out of scope (owner decisions; see DESIGN.md)
Don't build these: skip detection, social or collaborative features, rotating playlists the user doesn't own, notifications. Restock and the manually curated pick are Phase 2.

## Recommendations are backlogged (owner decision)
They'll eventually be built on a system that doesn't depend on the Spotify API.
Song recommendations are a backlog task. Don't build or extend them. Plan to scrap the existing recommendation code at some point: `SpotifyService.get_recommendations`, `GET /spotify/recommendations`, and the `/recommendations` calls in `Review.js`/`Restock.js`. Replacing removed songs should rely on search and manual adds for now.

## Deployment target
Personal/demo scope: one Supabase project, one Spotify app, Vercel production on a `*.vercel.app` URL, and local dev with `vercel dev` (local and prod share the database). See [DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md).

## Testing
`cd back-end && python -m pytest tests` runs `tests/test_auth.py` (untracked). It sets dummy `DATABASE_URL`/`SECRET_KEY` before importing the app, so it needs no DB or `.env`. The tests expect 403 for missing auth, which is FastAPI 0.104 behavior; newer versions return 401. There are no frontend tests beyond the CRA default.

## Working notes
- `back-end/.env` holds real secrets. Never print or commit it.
- Docs live in `docs/`; this file must stay at the repo root so Claude Code auto-loads it.
- Every model must be imported in `database/models/__init__.py`, or `relationship()` string lookups fail at runtime.
