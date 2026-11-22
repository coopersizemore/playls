# PlayLS design decisions

Owner decisions as of Nov 2026. [PROJECT_STATUS.md](PROJECT_STATUS.md) has the build plan, and [mvp.txt](mvp.txt) has the original product spec, annotated.

## Scope
- **Spotify only, personal use.** Build for Spotify Development Mode (at most 5 allowlisted users). Nothing gets designed for public scale.
- **Architecture stays:** Supabase Postgres, Vercel (`api` + `web` services on one domain), Spotify OAuth, and the session cookie.
- **Apple Music may be added later, but not now.** The Apple Music API can't remove tracks from library playlists (confirmed), so the core "remove" action can't work there as designed. The only prep is a `provider` column and provider-neutral track IDs (see Data model). There's no provider abstraction layer.

## Feature decisions
| Feature | Decision |
|---|---|
| Recommendations (by song, artist, genre or taste) | **Deferred.** They'll be built later on a system that doesn't depend on the Spotify API. The old Spotify recommendation code has been removed. |
| Restock (replacing removed songs) | **Phase 2**, after recommendations are designed. Until then, users add songs in Spotify directly, and the next sync picks them up. |
| Curated "PlayLS pick" | **Manual curation**, in Phase 2 alongside restock. |
| Skip detection, "most skipped" stats | **Scrapped.** The API has no skip data. |
| Rotating playlists the user doesn't own | **Scrapped.** The API only returns contents for playlists the user owns or collaborates on. |
| Social features / collaborative rotations | **Scrapped for now.** |
| Notifications (email or push) | **Not planned.** Neither works here (`/me` returns no email, and there's no mobile app). Due songs show up when the user opens the app (a badge or count on Home). |
| Stats | Only stats derivable from PlayLS's own review history (for example, longest kept or most kept). |

## Core semantics
- **Spotify is always the source of truth** for what's in a playlist. The database stores rotation metadata and review history, and never playlist contents that Spotify contradicts.
- **Sync** happens whenever a rotation is opened or its queue is loaded. It pages through `GET /playlists/{id}/items` and skips the rest of the sync if `snapshot_id` hasn't changed. Then it diffs against the database:
  - A track that's new in Spotify gets a row, anchored on Spotify's `added_at`.
  - A track that's gone from Spotify is marked `removed` (`removed_by = external`).
  - A track that comes back after a removal is reactivated with the new `added_at`, and its review anchor is reset.
- **Interval (N):** stored in hours (`interval_hours`, 1 hour to 365 days). The UI offers presets plus a custom amount in hours, days or weeks.
- **Due date:** computed when read, not stored, so changes to the interval or the grace period apply immediately to every song not yet kept.
  - **After a keep:** due at the keep date + N.
  - **Grace period on** (per-rotation option, default on): due at `max(added_at, rotation.created_at)` + N.
    - Songs already in the playlist when the rotation was created first come due at creation + N.
    - Songs added later come due at `added_at` + N.
  - **Grace period off:** due at `added_at` + N, so older songs can be due immediately.
    - If Spotify doesn't report `added_at`, the song is due at rotation creation.
    - Spotify doesn't expose playlist creation dates, so each song's own add date is the only anchor available.
- **Review actions:**
  - **Keep:** sets `last_kept_at = now`, so the song comes due again N days later.
  - **Skip:** leaves the song in the playlist with its due date unchanged. It's held back for the rest of the user's local day and offered again tomorrow. It still counts toward the daily limit.
  - **Remove:** takes the song out of the Spotify playlist and marks it `removed` (`removed_by = user`).
- **Daily review limit** (owner decision, 2026-11-22): this keeps a big backlog from arriving all at once.
  - **Setting:** `users.review_limit`, default **50**, range 1–1000, or **NULL for no limit**. Changed in Settings.
  - **Scope:** per rotation, per day. The day resets at the user's local midnight, using the browser's offset sent as `tz_offset`.
  - **Today's batch:** the most overdue due songs, excluding songs skipped today, up to `limit − reviewed_today`.
  - **What counts:** keep, skip and remove each count toward `reviewed_today`, and an undo refunds one.
  - **When the allowance runs out:** the user sees "Done for today" with an opt-in **"Review N more"** button (`?more=true`), which serves another full batch right away. Otherwise the next batch comes the next day.
  - **Home:** shows `ready_today` (what Review will offer now) next to the total `due_count`.
- **Batching removals:** the user can review any number of songs per session.
  - Each swipe is saved to the backend as soon as it happens, which only writes to the database, so a decision is never lost.
  - Spotify removals are sent in batches of up to 100 URIs per DELETE (`DELETE /playlists/{id}/items`; no `snapshot_id`, since removal by URI drops every copy anyway). A batch is triggered when the user leaves the Review page or app (a `fetch` with `keepalive` on `pagehide`/`visibilitychange`; `sendBeacon` can't send the CSRF header). Pending removals are also flushed before every sync, so a flush that gets interrupted is retried next time.
  - Until a removal reaches Spotify, sync treats that track as removed and doesn't reactivate it.
  - Undo is allowed while a removal is still pending.
- **Duplicates:** removing by URI deletes **every copy** of a track from the playlist. The database keeps one row per `(rotation, track)`. *This decision should be revisited.*
- **One rotation per playlist** per user.
- **Creating a rotation:** "from existing" wraps an owned playlist and asks whether to apply the grace period. "From scratch" creates an empty playlist with `POST /me/playlists` (still supported), and the user adds songs to it in Spotify until restock arrives in Phase 2.
- **Removed songs** are recorded only in PlayLS history (`review_event` and the `removed` rows); there's no "rotated out" archive playlist in Spotify. In Phase 2, the user can bring them back through PlayLS.

## Data model (Alembic revisions 0001–0002)
- `users`: adds `provider` (default `'spotify'`); `email` dropped.
- `rotation`:
  - `id`, `owner_id`, `provider`, `playlist_id` (required; unique together with `owner_id`), `name`, `interval_hours`, `grace_period`
  - `snapshot_id`, `last_synced_at`, `created_at`
- `rotation_track`, which replaces `song`:
  - Keys: a surrogate `id`, unique on `(rotation_id, track_id)`. `track_id` is the provider's ID, and `uri` is stored for removal.
  - Track metadata: `title`, `artists`, `album`, `image_url`, `duration_ms`
  - Review state: `added_at` (from Spotify; NULL if unknown), `last_kept_at`, `status` (`active` | `pending_removal` | `removed`), `removed_at`, `removed_by` (`user` | `external`)
- `review_event`: `id`, `rotation_track_id`, `action` (`keep` | `skip` | `remove` | `undo`), `created_at`. Removed songs stay in this history so they can be reused in Phase 2 (for example, a "bring back" option in restock).
- Alembic manages the schema from here on (the one-time wipe was done 2026-11-07). All timestamps are naive UTC.
- Sync only imports tracks; local files and podcast episodes in a playlist are ignored. A missing `added_at` (very old playlists) is stored as NULL; see the due-date rules for how it's handled.

## Decisions to revisit
- Daily limit is per rotation, so several big rotations can still add up to several × N in one day.
- Removing every duplicate copy of a track (above).
- Whether to add any provider abstraction if Apple comes back into scope.
- Notifications, if a channel that makes sense ever turns up.
