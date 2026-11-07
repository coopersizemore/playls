# PlayLS: status and plan

The decisions behind this plan are in [DESIGN.md](DESIGN.md). Deployment steps are in [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md).

## Current state (Nov 2026)
- **Works:**
  - Spotify OAuth with a session cookie, CSRF check and encrypted tokens
  - Supabase Postgres, and the Vercel `api`/`web` config
  - Rotation CRUD, with ownership checks
  - Frontend login, plus a Rotation page that lists playlists
- **Not built:**
  - Playlist sync, the due queue, review actions (`/rotate`, `/songs` and `/song` are stubs)
  - The Review, Restock and History pages, which are still on mock data
- **Broken:**
  - `spotify_service.py` and `Rotation.js` still use the pre-Feb-2026 API (`/tracks`, `POST /users/{id}/playlists`, and the `user-read-email` scope).
  - "From existing" creates a new playlist instead of wrapping the one the user picked.
  - `Home.js` has a `useState` destructuring bug.

## Phase 0: setup
1. ~~Smoke-test locally, push, log in on prod~~ Done 2026-11-07.

## Phase 1: core rotation loop
2. **Schema.** Wipe the database (approved), add Alembic, and start from the target model in DESIGN.md (`rotation`, `rotation_track`, `review_event`, and `provider` columns).
3. **Spotify layer.** Move to the post-Feb-2026 endpoints (`/items`, `item`, `POST /me/playlists`) and drop `user-read-email`. Delete the recommendation code (`get_recommendations`, `GET /spotify/recommendations`, and the frontend calls).
4. **Rotation create.** "From existing" wraps the selected owned playlist, and "from scratch" creates one with `POST /me/playlists`. Enforce one rotation per playlist.
5. **Sync service.** Page through the playlist items, short-circuit on `snapshot_id`, diff, and reactivate tracks that come back. Flush pending removals first. Songs that were already in the playlist when the rotation was created get the one-time grace period.
6. **Due queue.** Add `GET /rotation/{id}/queue`, which syncs and then returns the tracks where `due_at <= now`. Add due counts per rotation for Home.
7. **Review API.** Add per-swipe `POST /rotation/{id}/review` (keep, skip, remove or undo; writes to the database only) and `POST /rotation/{id}/flush` (batch Spotify removals with `snapshot_id`).
8. **Frontend.**
   - Fix the Home bug and show real rotations with due counts.
   - Wire Review to the queue and the review API, with a `keepalive` flush on `pagehide`/`visibilitychange`.
   - Show History from `review_event`.
   - Hide Restock.
9. **Tests.** Cover due-date math, sync diffing (new, gone, re-added and duplicates), review state transitions, and flush (with the Spotify client mocked).
10. **Cleanup.**
    - Remove dead code: `services/db/services.py`, `example_routes.py`, and the commented-out block in `app.py`.
    - Remove the stale `AUTHENTICATION.md`/`auth_demo.py`.
    - Bring the test expectations up to date with the current FastAPI version.

## Phase 2: restock (after recommendations are designed)
- Replacing removed songs through search (paginated, max 10 results per page), a "bring back" option fed by removal history, and the manually curated PlayLS pick.
- A recommendation system that doesn't depend on the Spotify API (still to be designed).
- Stats derived from review history.

## Later / maybe
- Apple Music (blocked: the Apple API can't remove tracks from library playlists).
- Notifications, if a channel that makes sense turns up.
