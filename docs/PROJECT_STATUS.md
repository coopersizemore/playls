# PlayLS: status and plan

The decisions behind this plan are in [DESIGN.md](DESIGN.md). Deployment steps are in [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md).

## Current state (Nov 2026)
Phase 0 and Phase 1 are built. The core loop works end to end:
- create a rotation (from an owned or collaborative playlist, or a new private playlist)
- sync with Spotify
- show due counts on Home
- review songs (keep / skip / remove / undo)
- send batched removals to Spotify
- show History

The backend has 63 tests (SQLite plus a fake Spotify). The frontend builds cleanly.

**Not yet verified against real Spotify**, because the database was wiped for the new schema. Do a manual pass on prod after logging in again (see "Verify Phase 1" below).

## Phase 0: setup (done 2026-11-07)
1. ~~Smoke-test locally, push, log in on prod~~

## Phase 1: core rotation loop (built 2026-11-07)
2. ~~**Schema.**~~ Done: the database was wiped, Alembic added (`back-end/alembic/`, revision `0001`), and the tables are `users`, `rotation`, `rotation_track` and `review_event`, with RLS on.
3. ~~**Spotify layer.**~~ Done: `/items` endpoints, `POST /me/playlists`, the four playlist scopes only, and the recommendation code deleted. DELETE requests now actually send their body, and a 401 forces a token refresh.
4. ~~**Rotation create.**~~ Done: wraps owned or collaborative playlists, or creates a new one. One rotation per playlist (409).
5. ~~**Sync service.**~~ Done: snapshot short-circuit, diff (new / gone / re-added), pending removals flushed first, and grace period applied.
6. ~~**Due queue.**~~ Done: `GET /rotation/{id}/queue`, plus due counts on `GET /user/me/rotations`.
7. ~~**Review API.**~~ Done: per-swipe `POST /rotation/{id}/review` and `POST /rotation/{id}/flush`.
8. ~~**Frontend.**~~ Done: Home, Manage Rotations (create, edit interval, delete), Review (embedded Spotify player, keyboard shortcuts, undo, `keepalive` flush on leave), History and Settings (log out, delete account). Restock is removed until Phase 2.
9. ~~**Tests.**~~ Done.
10. ~~**Cleanup.**~~ Done: removed the dead code, the commented-out endpoints in `app.py`, `init_db.py` and the CRA boilerplate test.

### Verify Phase 1 (manual, on prod or `vercel dev`)
- Log in, then create a rotation from a real playlist. Its song count should match Spotify, and the due count should be 0 with the grace period on (or reflect each song's add date with it off).
- Create one with a 1-day interval on a scratch playlist. Change `created_at` in Supabase to an earlier date (or wait a day), then review: keep one song, remove one, skip one.
- Leave the Review page. The removed song should disappear from the Spotify playlist.
- Remove a song directly in Spotify, then reload Home. The song count should drop.

## Post-Phase-1 changes (2026-11-22)
- **Optional grace period:** a per-rotation setting, on by default and editable. When it's off, songs come due from their own `added_at`; songs with an unknown add date are due immediately.
- **Finer interval control:** the interval is stored in hours (migration `0002`). The picker has presets plus a custom amount in hours, days or weeks.
- **Daily review limit:** up to N songs per rotation per day, most overdue first (default 50, or no limit; set in Settings). After a batch there's an opt-in "Review N more" button. Skipped songs now come back the next day. Migration `0003`.
- **Home and Manage Rotations merged:** Home is now the single dashboard (create, edit and delete live in a card menu). The `/rotation` page is gone, and the dialogs are in `RotationDialogs.js`.

## Phase 2: restock (built 2026-11-22)
- Restock page for each rotation, with four tabs: **Bring back**, **PlayLS picks**, **For you** (scored from your listening plus searches seeded by your top artists and albums) and **Search**. The first three are swipe decks with Add / Not now.
- Admin page for curating picks (`/admin/picks`, for accounts in `ADMIN_SPOTIFY_IDS`). Migration `0004`.
- **To do by hand:** set `ADMIN_SPOTIFY_IDS` locally and in Vercel, then log in again to grant the new Spotify scopes.

## Auto rotations (built 2026-11-23)
- A new rotation kind, created from scratch, that keeps its playlist at a target size (30/50/100/200) and rotates a share of it out on a schedule (default: 50 songs, 20%, weekly). It restocks from For you, occasional PlayLS picks, and songs that rotated out 4+ weeks ago. Rules are in DESIGN.md, "Auto rotations". Migration `0009` (applied).
- Runs whenever the app syncs the rotation, and from a daily Vercel cron.
- **To do by hand:** set `CRON_SECRET` in Vercel (Production), then redeploy. Without it the cron route stays disabled, and auto rotations only turn over when you open the app.

## Latency pass (2026-11-24)
- Added a `Server-Timing` header on every API response: total, Spotify, DB and DB-connection time. It's visible in the browser's Network tab under Timing, and requests over 1.5 s are logged.
- Spotify calls in a request share one connection. Playlist pages after the first are fetched 4 at a time.
- Manual rotations reuse a sync from the last 2 minutes, but only if it happened after the app was last shown.
- Home renders stored data first, then syncs each rotation in parallel.
- PlayLS's own playlist writes (flush, restock add, auto rotate-out and fill) store the snapshot Spotify returns, so the next sync short-circuits instead of re-reading the playlist.
- Spotify 429s are retried when the requested pause is short. Otherwise, and for quota errors, the client gets the error with `Retry-After`.
- Details are in DESIGN.md, "Sync shortcuts and guards".
- **Next:** read the `Server-Timing` numbers on prod before doing more. In particular, check `dbconnect`: NullPool opens a new connection after every commit.

## Sync races (found and fixed 2026-11-24)
Both were found by reading the code; neither was observed in practice. Details are in DESIGN.md, "Sync shortcuts and guards".
- **Overlapping syncs of one rotation** (Home + Review, cron + app, two tabs): duplicate inserts, a pending removal coming back as "re-added", and auto rotations filling twice.
  - Fixed with a per-rotation sync claim: `rotation.sync_claimed_until` (migration `0010`, applied), a 60-second lease.
  - Every sync, flush, restock add and auto maintenance takes it, waiting up to 10 s.
- **The playlist changing during a full read** (an offset shift hides a song, which is then wrongly marked removed): fixed by re-checking the snapshot after the read and applying additions only if it changed.

## Next
- Stats derived from review history.
- A recommendation system that doesn't depend on the Spotify API ("For you" is the current stand-in).
- Saving recently-played snapshots to build a longer listening history.

## Later / maybe
- A rotation detail page that uses `GET /rotation/{id}/tracks`.
- Apple Music (blocked: the Apple API can't remove tracks from library playlists).
- Notifications, if a channel that makes sense turns up.
