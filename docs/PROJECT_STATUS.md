# PlayLS: status and plan

The decisions behind this plan are in [DESIGN.md](DESIGN.md). Deployment steps are in [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md).

## Current state (2026-11-27)
Phases 0–2 are built, and so is everything listed below through listening history (2026-11-25). The app covers:
- manual rotations over an owned or collaborative playlist, a new private playlist, or Liked Songs
- auto rotations that keep a playlist at a target size and turn it over on a schedule
- review (keep / super keep / skip / remove / undo, with Back and Next) under a daily limit, with batched removals
- restock from five sources (Bring back, PlayLS picks, For you, Rediscover, Search), with undo and "stop suggesting"
- a listening history that shapes review order, auto rotations and Bring back, plus a monthly recap per rotation
- account settings and per-rotation overrides
- a demo mode for people who aren't allowlisted
- an admin dashboard with opt-in usage analytics and app health

Health checks:
- **Tests:** 298 backend tests pass (SQLite plus a fake Spotify). CI runs ruff and pytest, and checks that the frontend builds with no warnings.
- **Schema:** Alembic is at `0017` (head), applied to the shared database.
- **Verified against real Spotify (2026-11-27):** the Phase 1 pass below, plus spot checks of restock add and undo, an auto rotation turning over, a Liked Songs rotation, and listening capture and import.

## Phase 0: setup (done 2026-11-07)
1. ~~Smoke-test locally, push, log in on prod~~

## Phase 1: core rotation loop (built 2026-11-07)
2. ~~**Schema.**~~ Done: the database was wiped, Alembic added (`back-end/alembic/`, revision `0001`), and the tables are `users`, `rotation`, `rotation_track` and `review_event`, with RLS on.
3. ~~**Spotify layer.**~~ Done: `/items` endpoints, `POST /me/playlists`, the four playlist scopes only, and the recommendation code deleted. DELETE requests now actually send their body, and a 401 forces a token refresh.
4. ~~**Rotation create.**~~ Done: wraps owned or collaborative playlists, or creates a new one. One rotation per playlist (409).
5. ~~**Sync service.**~~ Done: snapshot short-circuit, diff (new / gone / re-added), pending removals flushed first, and grace period applied.
6. ~~**Due queue.**~~ Done: `GET /rotation/{id}/queue`, plus due counts on `GET /user/me/rotations`.
7. ~~**Review API.**~~ Done: per-swipe `POST /rotation/{id}/review` and `POST /rotation/{id}/flush`.
8. ~~**Frontend.**~~ Done: Home, Manage Rotations, Review, History and Settings.
9. ~~**Tests.**~~ Done.
10. ~~**Cleanup.**~~ Done.

### Verify Phase 1 (manual, on prod; done 2026-11-27)
- Log in, then create a rotation from a real playlist. Its song count should match Spotify, and the due count should be 0 with the grace period on (or reflect each song's add date with it off).
- Create one with a 1-day interval on a scratch playlist. Change `created_at` in Supabase to an earlier date (or wait a day), then review: keep one song, remove one, skip one.
- Leave the Review page. The removed song should disappear from the Spotify playlist.
- Remove a song directly in Spotify, then reload Home. The song count should drop.

## Post-Phase-1 changes (2026-11-22)
- **Optional grace period**, per rotation, on by default.
- **Finer interval control:** stored in hours (migration `0002`), with presets plus a custom amount.
- **Daily review limit** (migration `0003`), with an opt-in "Review N more".
- **Home and Manage Rotations merged** into one dashboard; the dialogs are in `RotationDialogs.js`.
- Playlist covers (`0005`), review session summaries in History, undoing a keep (`0006`), unplayable-song detection and "remove unavailable" (`0007`).
- **Super keep** (3× the interval), **blocked songs**, and Back / Next through a review without answering (`0008`).
- Light theme and a visual overhaul to match the Figma wireframes; dark mode added later.

## Phase 2: restock (built 2026-11-22)
- A Restock page for each rotation: **Bring back**, **PlayLS picks**, **For you** and **Search** (Rediscover added 2026-11-25). The decks are swipe cards with Add / Not now.
- An admin page for curating picks (`/admin/picks`, for accounts in `ADMIN_SPOTIFY_IDS`), with editable notes and dates. Migration `0004`.
- **Undo** for adds and Not now (`0011`). An add is taken back out of the playlist and the row restored.
- Fixed: restock was suggesting songs already in the rotation.

## Auto rotations (built 2026-11-23)
- A rotation kind that keeps its playlist at a target size and turns a share of it over on a schedule (default 50 songs, 20%, weekly). Migration `0009`.
- Runs after every sync of the rotation and from the daily Vercel cron (10:00 UTC).

## Latency pass and sync races (2026-11-24)
- `Server-Timing` on every response; shared Spotify connections; parallel page reads; Home renders stored data and then syncs each rotation in parallel; manual rotations reuse a recent sync; PlayLS's own writes store Spotify's snapshot; short 429 pauses are retried.
- **Sync claim** (`0010`): a 60-second per-rotation lease around every sync and playlist write. It fixes overlapping syncs (duplicate inserts, removals coming back as "re-added", auto rotations filling twice).
- **Mid-read check:** if the snapshot changes during a full read, only additions are applied.
- Tradeoffs and Spotify edge cases are in [SYNC_RISKS.md](SYNC_RISKS.md). Most are still open (see "Open items").

## Built 2026-11-24
- **Preferences** (`0012`): account settings (Reviewing, Restocking, Appearance) and per-rotation overrides under "More options". Rules are in DESIGN.md, "Preferences".
- **Monitoring** (`0013`): `/admin/stats` with opt-in usage analytics (6-month retention) and app health for every request. Plan and decisions: [MONITORING_PLAN.md](MONITORING_PLAN.md). The owner decided against a backfill.
- **Liked Songs rotations** (`0014`): one per user, manual only, up to 5,000 songs. Removals unlike and restock adds like. Needs the `user-library-modify` scope.
- **Demo mode** (`0015`, `0016`): `/demo` runs on a seeded fake library with no Spotify calls. It has skip-ahead, a 24-hour expiry, and limits on live demos overall and per IP. Health monitoring leaves out some routes.
- **Rotation names follow Spotify:** every sync copies the playlist's name, and a rename in PlayLS renames the Spotify playlist first.
- **UI:** a rotation page with Current songs (sortable, shaded by how soon each song comes due) and History tabs; History loads more; the Help guide; Review and Restock fit on one screen on mobile and laptop.
- **Tooling:** CI workflows for the backend and frontend, and project skills in `.claude/skills/`. An accidental `back-end/pyproject.toml` broke a deploy; it's now banned in CLAUDE.md.

## Listening history (built 2026-11-25, migration `0017`)
Rules are in DESIGN.md, "Listening history".
- **Capture:** the latest 50 plays and daily top tracks, saved when the app opens or becomes visible (at most every 15 minutes) and by the daily cron. It can be turned off in Settings, which deletes the history.
- **Shown** in Review, Current songs, History and Restock: play counts, badges, and plays before and after each review.
- **Guides behavior:** review order (`listening` by default), the heavy-listening setting, auto-rotation holds and the top-X% shield, and Bring back weights.
- **Restock outcomes:** whether songs added in the last 90 days have been played.
- **Rediscover deck:** songs played a lot a few months ago but not lately (manual rotations; needs about two months of history).
- **Extended Streaming History import:** Spotify's export, uploaded from Settings. It's the only source of skip data.
- **Monthly recap:** a lazy-loaded page per rotation, with a chart and a table.

## Open items

### Done by hand (2026-11-27)
- The "Verify Phase 1" pass on prod, and spot checks of the newer features with a real account.
- `ADMIN_SPOTIFY_IDS` and `CRON_SECRET` set in Vercel (Production), and redeployed. The daily cron is live.
- Every account logged in again to grant the newer scopes.
- Liked Songs confirmed to come back strictly newest first on a real library (SYNC_RISKS 4.6).
- `Server-Timing` read on prod. The numbers aren't recorded in the docs yet.

### Sync hardening (from [SYNC_RISKS.md](SYNC_RISKS.md) §6; none built yet)
1. A count and empty-read guard for playlist syncs (2.1). Liked Songs already has one.
2. Force a full read at least once a day (1.1).
3. Show stuck pending removals in the UI, and let `maintain` cope with them (3.1).
4. A "reconnect Spotify" prompt when a token refresh fails (5.1), and a "playlist is gone" state (2.2).
5. Tune the claim lease and waits against the prod `Server-Timing` numbers (1.2, 1.3, 1.8). That includes an explicit `maxDuration` in `vercel.json`.

### Next
- A recommendation system that doesn't depend on the Spotify API ("For you" is the current stand-in). Ask the owner before expanding "For you" into one.

### Later / maybe
- The decisions listed in DESIGN.md, "Decisions to revisit".
- Notifications, if a channel that makes sense turns up.

### Out of scope
- **Apple Music** (owner decision, 2026-11-27): its API can't remove tracks from library playlists, so the core remove action can't work.
