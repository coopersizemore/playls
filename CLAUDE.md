# PlayLS

Spotify "lazy susan": a rotation wraps a playlist the user owns, and songs come due for keep/skip/remove review every N days. Product spec: [mvp.txt](docs/mvp.txt), annotated with what's deferred or scrapped. **Owner decisions and semantics (source of truth, due-date math, batched removals, data model): [DESIGN.md](docs/DESIGN.md).** Phased build plan: [PROJECT_STATUS.md](docs/PROJECT_STATUS.md). The owner knows the product well, so don't explain it back; focus on the code.

Status: Phase 1 (core rotation loop) built Nov 2026. The architecture is settled (Supabase + Vercel + Spotify OAuth), so build within it. Scope is Spotify only, personal use (at most 5 users). Apple Music is a maybe-later, so keep track IDs provider-neutral and keep the `provider` columns, but build no abstraction layer.

## Layout
- `back-end/rest_api/` — FastAPI. Run from `back-end/` as `python -m rest_api.app` (port 8000). Package uses a mix of relative (`..`) and absolute (`rest_api.`) imports, so it only works from `back-end/` as the CWD.
  - `views/` routers: `auth`, `user`, `rotation`, `spotify` (all mounted in `app.py`).
  - `services/auth_service.py` — Spotify OAuth + app session (JWT via python-jose, HS256, 7 days, in an httpOnly cookie). `get_current_user_from_token` is the auth dependency (cookie + CSRF check).
  - `services/spotify/spotify_service.py` — thin httpx wrapper over the post-Feb-2026 Spotify API. Raises `SpotifyAPIError` (an `HTTPException` carrying `upstream_status`); on a 401 it force-refreshes the token and retries once.
  - `services/rotation_logic.py` — pure rules: due-date math (interval in hours; optional per-rotation grace period; NULL `added_at` = unknown), parsing playlist items, queue order. No DB/network; unit-tested.
  - `services/sync_service.py` — `flush_pending_removals` and `sync_rotation` (snapshot short-circuit, diff against `rotation_track`). Skips the diff if items come back but none parse, so a response-shape change can't mark everything removed.
  - `services/db/rotation_service.py` — rotation CRUD, summaries/due counts, queue (daily limit via `_todays_activity` over `review_event`), `apply_review`, history. `try_sync` is the best-effort wrapper routes use (returns `sync_ok`).
  - `services/restock_logic.py` (pure: bring-back weights, suggestion scoring, weighted sampling, blending) and `services/restock_service.py` (the four sources, the suggestion cache, add / Not now, pick creation). Rules are in DESIGN.md, "Restock".
  - `database/models/*` — SQLAlchemy: `UserDB`, `RotationDB`, `RotationTrackDB`, `ReviewEventDB`, `CuratedPickDB`, `RestockFeedbackDB`, `SuggestionCacheDB`. `models/*` are the Pydantic schemas (`extra="forbid"` on request bodies).
  - `database/config.py` connects to **Supabase Postgres** via `DATABASE_URL` (psycopg 3, `NullPool`, `prepare_threshold=None` for the transaction pooler). The user table is `users` (`user` is reserved in Postgres).
  - `database/encryption.py` — `EncryptedText` (Fernet, `TOKEN_ENCRYPTION_KEY`) for the Spotify tokens.
  - `clock.py` — `utcnow()`. All timestamps are **naive UTC**; use it instead of `datetime.utcnow()`.
- `back-end/alembic/` — migrations. Run `alembic upgrade head` from `back-end/` (with `.venv`). Local and prod share the DB, so a migration applies to prod. New tables must `ENABLE ROW LEVEL SECURITY` in their migration (no policies; this blocks Supabase's Data API). `alembic check` verifies models match migrations.
- `playls_front_end/` — CRA (react-scripts 5), React 19, MUI 7 (`Grid` uses the `size` prop), react-router 7, axios. Pages in `src/components/`: Home is the single dashboard (rotation cards plus create/edit/delete dialogs from `RotationDialogs.js`, which also holds `IntervalPicker`/`formatInterval`); then Review, Restock (deck tabs plus Search), History, Settings and AdminPicks. Shared chrome, `RequireAuth` and date helpers in `Layout.js`; API calls in `src/api.js` (`api.*`, `flushOnExit`, `errorMessage`). Auth state in `src/contexts/AuthContext.js` (asks `GET /api/auth/me` on load; it never sees a token).
- Root `start-*.bat`/`.sh` launch the dev servers.

## API (all under /api)
- `GET /user/me/rotations` (syncs each rotation; `?sync=false` skips) → summaries with `due_count`, `ready_today`, `reviewed_today`, `daily_limit`, `active_count`, `pending_removal_count`, `next_due_at`, `sync_ok`.
- `GET|PUT /user/me/settings` `{review_limit: int 1–1000 | null}` (null = no limit; default 50).
- Daily-limit endpoints take `tz_offset` (JS `getTimezoneOffset()`, minutes) so "today" is the user's local day. The frontend sends it automatically from `api.js`.
- `POST /rotation/` `{playlist_id?, name?, description?, interval_hours, grace_period}`: wraps an owned/collaborative playlist, or creates a private one via `POST /me/playlists` when `playlist_id` is omitted. Then runs the initial sync.
- `GET|PUT|DELETE /rotation/{id}`, `GET /rotation/{id}/queue[?more=true | ?all=true]` (syncs, then today's batch: `{tracks, due_count, daily_limit, reviewed_today, remaining_after_batch, limit_reached}`), `/tracks`, `POST /rotation/{id}/review` `{track_id, action: keep|super_keep|skip|remove|undo}`, `POST /rotation/{id}/flush`, `GET /rotation/{id}/history`, `POST /rotation/{id}/reset-due`, `GET /rotation/{id}/unplayable` (force-syncs), `POST /rotation/{id}/remove-unplayable`.
- `GET /spotify/playlists` (flattened, with `rotatable`/`rotation_id`), `GET /spotify/search` (limit ≤ 10).
- Restock, under `/rotation/{id}/restock/`: `GET deck/{bring_back|picks|suggested}[?refresh=true]` → `{source, items, missing_scopes}`; `GET search?q=&offset=`; `POST add`, `POST skip` and `POST block` ("stop suggesting") with `{track_id, source}`. Blocks are listed and undone via `GET /user/me/blocked-songs` and `DELETE /user/me/blocked-songs/{track_id}`.
- Admin (accounts in `ADMIN_SPOTIFY_IDS`; others get 404): `GET|POST /admin/picks`, `PUT|DELETE /admin/picks/{id}` (PUT edits note and dates; the window is `[starts_at, ends_at)`, and the admin page sends whole local days with the end date inclusive). `/auth/me` returns `is_admin` and `missing_scopes`.

## Routing and deployment (Vercel services)
- Root [vercel.json](vercel.json) defines two services: `api` (`back-end`, entrypoint `rest_api.app:app`) and `web` (`playls_front_end`, CRA with an SPA fallback). `/api` and `/api/*` route to `api`; everything else goes to `web`. There are no service bindings, because no service calls another server-side.
- Vercel passes the **full path** through, so all FastAPI routers are mounted with the `/api` prefix in `app.py`. New routers must be mounted the same way.
- The frontend always calls the relative `API_BASE = '/api'` (`src/api.js`). Never hardcode a backend host.
- Python is **3.12** (`back-end/.python-version`). `vercel dev` needs 3.12+, and on this Windows machine `python`/`python3` resolve to the Microsoft Store 3.11. In multi-service mode `vercel dev` only uses a venv at **`back-end/.venv`** (or `back-end/venv`); if none exists it creates one with that 3.11 and fails installing `vercel-runtime`. Keep `back-end/.venv` on 3.12 (`<Python312>\python.exe -m venv back-end/.venv`), and don't activate a venv before running `vercel dev`. `vercel dev` on Windows needs Developer Mode (the CLI creates symlinks).
- Local dev: `vercel dev` (single origin on :3000, the preferred option), or `npm start` plus `python -m rest_api.app`. The second option relies on the CRA `proxy` in `package.json` and needs `FRONTEND_URL` and an `SPOTIFY_REDIRECT_URI` on :8000 (see `env.example`).
- Env vars (see `back-end/env.example`):
  - Required: `DATABASE_URL`, `SECRET_KEY` (32+ chars; published placeholders are rejected), `TOKEN_ENCRYPTION_KEY` (must match everywhere sharing the DB). The app refuses to start without these. Also `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REDIRECT_URI` (must end in `/api/auth/callback` and match the Spotify dashboard).
  - Optional: `ADMIN_SPOTIFY_IDS` (comma-separated Spotify user IDs that can curate picks), `FRONTEND_URL` (empty means same origin, so the post-login redirect is the relative `/`), `ENABLE_API_DOCS` (Swagger at `/api/docs`, off by default), `SQL_ECHO`.

## Security model (keep it this way)
- Every `/api/user/*`, `/api/rotation/*` and `/api/spotify/*` route requires the session cookie (`playls_session`, httpOnly, SameSite=Lax, path `/api`). There's no Bearer-header auth. Non-GET requests also need an `X-Requested-With` header (CSRF), which `src/api.js` sets on axios globally and on the `keepalive` flush. Rotations are fetched with `rotation_service.get_owned_rotation`, and other users' rotations return 404.
- `owner_id`, `id`, `created_at` and other server-managed fields can't come from request bodies: request schemas use `extra="forbid"` (422).
- There's no route that lists users or returns `UserDB` rows. Those rows contain Spotify tokens, so never return them directly.
- OAuth `state` is round-tripped in an httpOnly `spotify_oauth_state` cookie (path `/api/auth`) and checked on callback. Scopes are the four playlist scopes plus `user-top-read`, `user-read-recently-played` and `user-library-read` (for suggestions). Granted scopes are stored in `users.granted_scopes`. Requests that need a missing scope are skipped, never failed.
- Spotify tokens are encrypted at rest (`EncryptedText`).
- Errors from Spotify and unexpected exceptions are logged server-side; clients get generic messages (502/429; `httpx.HTTPError` → 502 via a handler in `app.py`). Don't put `str(e)` or upstream response bodies in `detail`.
- `vercel.json` sets nosniff, frame-deny, referrer and permissions headers. There's no CSP yet, because the CRA inline runtime chunk and MUI's inline styles need care (and Review embeds `open.spotify.com` iframes).

## Auth flow
Frontend `GET /api/auth/login` → redirects to Spotify → Spotify redirects to `/api/auth/callback` → backend checks `state`, upserts the user (encrypted Spotify tokens in `users`), sets the `playls_session` cookie, and redirects to `FRONTEND_URL/` → `AuthContext` calls `/api/auth/me`. Failures redirect to `/login?error=auth_failed`. `POST /api/auth/logout` clears the cookie. Spotify access tokens refresh automatically in `ensure_valid_spotify_token`.

## Known gaps (verify before relying on these)
- Sessions can't be revoked server-side before their 7-day expiry (logout only clears the cookie). There's no rate limiting.
- Undo (`action: undo`) reverts the track's most recent keep, skip or remove by deleting that `review_event`; a keep's previous `last_kept_at` is stored on the event. A removal can only be undone while it's still pending (before the flush), otherwise 409. Older `undo` rows from before 0006 still exist and count −1 toward the daily tally.
- Concurrent syncs of the same rotation can hit the `(rotation_id, track_id)` unique constraint; `try_sync` rolls back and reports `sync_ok=false`, and the next sync recovers.
- Redirect URIs must be HTTPS or `http://127.0.0.1` (`localhost` isn't allowed).

## Spotify API constraints (Development Mode, after Feb 2026)
This app is in Development Mode: max 5 allowlisted users per Client ID, and the owner needs Premium. Extended quota is effectively unavailable. Build against the post-Feb-2026 API (changelog: developer.spotify.com/documentation/web-api/references/changes/february-2026):
- Playlist items are read with `market=from_token`. Every track then carries `is_playable` (with `restrictions.reason`, e.g. `market`). Spotify may also **relink** a track to a playable version with a different `id`, giving the original in `linked_from`. The parser keys on `linked_from` (the version actually in the playlist, and the URI to remove), so relinked tracks aren't treated as removed and re-added. Verified on a real 550-track playlist: 60 were relinked and 6 were unplayable.
- Playlist items: `GET|POST|DELETE /playlists/{id}/items` (the `/tracks` versions were removed). Items pages max out at **50**; add/remove take at most **100** URIs per request. The removal body is `{"items": [{"uri": ...}]}`. Response fields are renamed (`tracks` → `items`, `track` → `item`; parsing accepts both). Contents are only returned for playlists the user **owns or collaborates on**.
- Create playlist: `POST /me/playlists` (`POST /users/{id}/playlists` was removed).
- `GET /me/playlists` still works (item count is `items.total`; `tracks.total` is deprecated). `GET /users/{id}/playlists` was removed.
- `/me` no longer returns `email`, `country` or `product`.
- Search `limit` is max 10 (default 5), so paginate. Artist top tracks, batch "several" lookups, browse/new releases and `popularity` are gone. Per-type save endpoints moved to `/me/library`.
- Quota is shared across every Client ID on the developer account. Quota errors come back as 429 with `"reason": "QUOTA_EXCEEDED"`.

## Out of scope (owner decisions; see DESIGN.md)
Don't build these: skip detection, social or collaborative features, rotating playlists the user doesn't own, notifications. Restock and curated picks are built (see DESIGN.md).

## Recommendations are backlogged (owner decision)
Spotify's recommendation endpoints are gone. "For you" (restock) is the interim scorer, built from the user's own listening signals plus searches. A fuller recommendation system that doesn't depend on Spotify is still backlog, so don't expand "For you" into one without asking.

## Deployment target
Personal/demo scope: one Supabase project, one Spotify app, Vercel production on a `*.vercel.app` URL, and local dev with `vercel dev` (local and prod share the database). See [DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md).

## Testing
`cd back-end && .venv/Scripts/python -m pytest tests`. `tests/conftest.py` sets dummy env vars before importing the app and provides an in-memory SQLite `db`, a `FakeSpotify` (monkeypatched onto `SpotifyService`), and an authenticated `client`. So tests need no Supabase, `.env` or network. Files: `test_auth.py` (security), `test_rotation_logic.py` and `test_restock_logic.py` (pure rules), `test_rotation_flow.py` and `test_restock_flow.py` (end to end through the API). There are no frontend tests; verify the frontend with `npx react-scripts build` (from `playls_front_end/`).

## Working notes
- `back-end/.env` holds real secrets. Never print or commit it.
- Docs live in `docs/`; this file must stay at the repo root so Claude Code auto-loads it.
- Every model must be imported in `database/models/__init__.py`, or `relationship()` string lookups fail at runtime.
