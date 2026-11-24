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
| Restock (adding songs) | **Built (2026-11-22)**: four sources. See "Restock" below. |
| Curated "PlayLS pick" | **Built**: curated by admins (`ADMIN_SPOTIFY_IDS`) in-app and shared by all users. |
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
- **Sync shortcuts and guards (2026-11-24, for latency):**
  - **Recent syncs are reused (manual rotations only).** A manual rotation isn't checked against Spotify again if both hold:
    - its last sync was under 2 minutes ago (`FRESH_SYNC_SECONDS`);
    - that sync happened after the app was last shown (the frontend's `X-Visible-For` header).
    - Returning to PlayLS, for example from editing the playlist in Spotify, always re-checks.
    - Pending removals are still flushed.
    - Requests without the header (the cron) and auto rotations always sync.
  - **A full read is double-checked.** Pages are read by offset from the live playlist, a few at a time. Afterwards the snapshot is fetched again. If it changed during the read, only new songs and metadata are applied: nothing is marked removed or reactivated, and the old snapshot is kept so the next sync reads it again.
  - **One sync at a time per rotation.** A sync claim (`rotation.sync_claimed_until`, a 60-second lease taken with a conditional UPDATE) is held around every sync (including auto maintenance), every flush, and every restock add.
    - A request waits up to 10 s for another request's claim. If it's still held, the request carries on without syncing:
      - Pages read what's stored, with `sync_ok` true, since the other request is syncing.
      - A flush leaves the removals pending for that sync or the next one.
      - A restock add returns 409 ("try again in a moment").
    - The claim is re-entrant within a request (a flush that goes on to `maintain`). Only the holder's own lease is released. A function that dies mid-sync blocks others for at most 60 s.
    - Not advisory locks: through Supabase's transaction pooler they would end at every commit.
  - **Our own writes keep the snapshot current.** Right before PlayLS writes to the playlist, it checks that Spotify's snapshot still matches the stored one. In a sync, it uses the check it just made. If so, it stores the snapshot Spotify returns from the write, so the next sync short-circuits instead of re-reading.
    - If the playlist had changed in Spotify, nothing is stored, and the next sync reads it in full.
    - A change made in Spotify in the instant between that check and the write would be missed until the playlist changes again.
  - **Spotify 429s** are retried after `Retry-After` when the pause is 5 s or less (at most 2 retries and 8 s of waiting per request; 1 s if no header). Quota errors (`QUOTA_EXCEEDED`) and longer pauses fail at once: the client gets a 429 with `Retry-After`, and a sync just reports `sync_ok=false`.
  - **Home shows stored data first.** It loads `?sync=false`, then syncs each rotation in its own request and updates each card as its result arrives. An auto rotation's card (open, Review, Restock) stays locked until its sync finishes, so opening it can't start a second restock.
- **Interval (N):** stored in hours (`interval_hours`, 1 hour to 365 days). The UI offers presets plus a custom amount in hours, days or weeks.
- **Due date:** computed when read, not stored, so changes to the interval or the grace period apply immediately to every song not yet kept.
  - **After a keep:** due at the keep date + N.
  - **After a super keep:** due at the keep date + **3 × N**. `rotation_track.keep_multiplier` is set to 3, so if N changes later the wait is still three intervals. A plain keep, a reset or a fresh start sets it back to 1.
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
  - **What counts:** keep, skip and remove each count toward `reviewed_today`. Undoing an action deletes its event, so it stops counting.
  - **When the allowance runs out:** the user sees "Done for today" with an opt-in **"Review N more"** button (`?more=true`), which serves another full batch right away. Otherwise the next batch comes the next day.
  - **Home:** shows `ready_today` (what Review will offer now) next to the total `due_count`.
- **Batching removals:** the user can review any number of songs per session.
  - Each swipe is saved to the backend as soon as it happens, which only writes to the database, so a decision is never lost.
  - Spotify removals are sent in batches of up to 100 URIs per DELETE (`DELETE /playlists/{id}/items`; no `snapshot_id`, since removal by URI drops every copy anyway). A batch is triggered when the user leaves the Review page or app (a `fetch` with `keepalive` on `pagehide`/`visibilitychange`; `sendBeacon` can't send the CSRF header). Pending removals are also flushed before every sync, so a flush that gets interrupted is retried next time.
  - Until a removal reaches Spotify, sync treats that track as removed and doesn't reactivate it.
  - **Navigating a batch** (Review page):
    - **Keep, Super keep and Remove** decide and move to the next song.
    - **Back** (Backspace / Z) and **Skip / Next** (↓) move through the batch, so earlier songs can be revisited. A revisited song shows its decision.
    - **Skip** on an undecided song records a skip. On a decided song the button reads "Next" and just moves forward.
    - **Changing a decision:** picking a different action on a decided song undoes the old one server-side (the API's `undo`), then applies the new one.
    - **Removal toast:** after a removal, an "Undo" toast reverts it and returns to that song.
    - **Limit:** a removal can only be changed until the flush reaches Spotify. After that, History or Restock offers "Add back".
- **Duplicates:** removing by URI deletes **every copy** of a track from the playlist. The database keeps one row per `(rotation, track)`. *This decision should be revisited.*
- **One rotation per playlist** per user.
- **Super keep** (review action `super_keep`, star button, ↑ key): a keep that doesn't ask again for three intervals. It counts toward the daily limit like any review. Undo restores the previous `last_kept_at` and `keep_multiplier`, which are stored on the event.
- **Stop suggesting** (the Bring back deck's "Stop suggesting this song"): adds a `restock_block` row for the user and track.
  - The song gets a score of 0 in **every** restock deck (Bring back, picks, For you) and is never offered again.
  - It stays in rotation History, and manual Search and History's "Add back" still work.
  - **Undo:** a toast right after blocking, or Settings → "Songs you've stopped suggesting" → Resume suggesting (`DELETE /user/me/blocked-songs/{track_id}`).
- **Rotation menu actions:**
  - **Review all songs** (`queue?all=true`): every active song, soonest due first, with no daily limit. Keeping a song that isn't due yet pushes its next review out a full interval.
  - **Reset all songs to not due** (after a confirmation): sets every active song's `last_kept_at` to now. This isn't recorded as review events, so it doesn't affect History or the daily limit, and it can't be undone.
  - **Remove unavailable songs** (after a confirmation that lists them): the preview force-syncs, because availability can change without the playlist's snapshot changing. Removal then marks the songs `pending_removal` and flushes right away. This is a cleanup, not a review: no review events, and Bring back never offers unplayable songs.
- **Availability:** `rotation_track.is_playable` is refreshed on every full read of the playlist (see the Spotify notes in CLAUDE.md about relinking). Review shows an "Unavailable on Spotify" chip on those songs.
- **New playlists** are created with an empty description (`""`), never omitted. Playlists created without one can show "null" in Spotify.
- **Creating a rotation:** "from existing" wraps an owned playlist and asks whether to apply the grace period. "From scratch" creates an empty playlist with `POST /me/playlists` (still supported), and the user adds songs to it in Spotify until restock arrives in Phase 2.
- **Removed songs** are recorded only in PlayLS history (`review_event` and the `removed` rows); there's no "rotated out" archive playlist in Spotify. In Phase 2, the user can bring them back through PlayLS.

## Restock (owner decisions, 2026-11-22)
Restocking is open-ended, per rotation: there's a Restock page for each rotation, reached from its Home card or from the end of a review session that removed songs. It has four tabs. The first three are swipe decks of up to 30 songs (Add / Not now, with a player); Search is a list.
- **Adding a song** writes it to the Spotify playlist right away (`POST /playlists/{id}/items`). It also upserts the `rotation_track` row as `active`, with `added_at = now`, so the song comes due one interval later. Spotify stays the source of truth, and the next sync reconciles anything else.
- **Not now** (`restock_feedback.action = skip`) hides the song for the rest of the user's local day. It also lowers the song's weight in every source, by a penalty that fades: a fresh skip halves the weight, and each skip's effect halves every **30 days** (`weight × 0.5^Σ 0.5^(age_days/30)`). After 30 days a single skip costs about ×0.71, and after 90 days about ×0.92.
- **Deck order** is a weighted random sample (Efraimidis–Spirakis), seeded per user, rotation, source and day. Heavier songs usually come first, but lighter ones still show up, and reloading the same day doesn't reshuffle.

Sources:
1. **Bring back:** songs removed from *this* rotation, whether removed by the user or externally.
   - Weight is 0.1 right after removal and rises linearly to 1.0 at **90 days**.
   - The fading Not now penalty applies, and each past keep adds 10% (up to +50%).
2. **PlayLS picks:** active `curated_pick` rows (inside their optional start/end window), newest first.
   - Songs the user has passed on sink to the back.
   - Songs already in the rotation are hidden.
3. **For you:** listening signals collected from Spotify into `suggestion_cache`, refreshed every 6 hours or on demand (about 15–20 calls):
   - top tracks for all three windows
   - top artists
   - the last 50 plays
   - the newest 200 Liked Songs, plus one random deeper page
   - searches seeded by the top 5 artists and the 3 most-played albums ("discoveries")

   Scoring (`restock_logic.score_suggestion`; the reason shown is the largest contributor):
   - Top tracks: short-term ×3, medium-term ×2, long-term ×1, scaled by rank.
   - Recent plays: +0.6 each, up to 3.
   - Liked: +1, or +1.5 if liked in the last 60 days.
   - By a top artist: up to +1.5.
   - Discovery novelty: +1.2.
   - Adjustments: the fading Not now penalty, and ×0.6 if the song is already in another of the user's rotations.

   Excluded: songs that are in, or were ever in, this rotation (those belong to Bring back). The deck blends known songs and discoveries about 2:1.
4. **Search:** Spotify track search (10 per page, `offset` ≤ 1000), with songs already in the rotation flagged.

Suggestions need `user-top-read`, `user-read-recently-played` and `user-library-read`.
- The scopes granted at login are stored in `users.granted_scopes`.
- `/auth/me` returns `missing_scopes`, and the For you tab offers a Reconnect button. Accounts from before this change have to log in again.
- Sources without a granted scope are skipped, and any one failing source is skipped rather than failing the whole deck.

## Auto rotations (owner decisions, 2026-11-23)
A second kind of rotation (`rotation.kind = 'auto'`), created only from scratch (a new private playlist). PlayLS keeps the playlist at a target size and turns part of it over on a schedule.
- **Settings:**
  - Target size: 30, 50, 100 or 200.
  - Rotate-out share: 10 / 20 / 30 / 50% in the UI (the API takes 5–100).
  - How often: reuses `interval_hours`.
  - Default: 50 songs, 20%, weekly. All three can be edited later.
- **Creation:** the initial sync's restock fills the playlist to the target. If the For you pool is too small, it fills as far as it can and tops up later.
- **Each rotation** (`next_rotation_at = (last_rotated_at or created_at) + interval`):
  - Rotates out `round(target × percent)` songs (at least 1), plus any songs over the target, then restocks back up to the target.
  - A missed rotation runs once, not once per missed period.
  - The rotation is claimed with a conditional update on `last_rotated_at`, so concurrent requests or the cron can't run it twice. On a Spotify failure the claim is released and the next sync retries.
- **Who leaves:**
  - Unavailable songs first, then the oldest.
  - Age counts from `added_at`, or from `last_kept_at` once kept. After a super keep the clock runs 3× slower.
  - Songs kept since the last rotation are protected from the next one. A protected song pushes the next-oldest one out instead, so the percentage still holds.
- **Reviewing is optional:**
  - The review queue is the group leaving at the next rotation.
  - Keep: protects the song.
  - Remove: frees a slot, which is refilled right after the flush.
  - Skip: works as usual.
  - "Reset all to not due" isn't offered, since it would protect every song.
  - Track `due_at` is the projected leave time: the next group at the next rotation, then one group per interval after.
- **Restock mix** for N empty slots:
  - Each slot has a 10% chance of being a live PlayLS pick.
  - About 20% of slots are bring-back songs (weighted by the bring-back rules).
  - The rest are For you (the same scorer and 2:1 known/discovery blend).
  - A shortfall in one source spills into the others.
  - Excluded: blocked songs, songs currently in the rotation, and songs removed from it in the last **4 weeks** (the return cooldown, which also applies to picks).
- **When it runs:**
  - After every successful sync of an auto rotation (`try_sync` → `try_maintain`), so it catches up whenever the app opens it.
  - After a flush that removed songs.
  - From a daily Vercel cron (`GET /api/cron/auto-restock`, `vercel.json` `crons`) that syncs and maintains every auto rotation, so the playlist changes even if the owner only listens in Spotify.
  - The cron route requires `Authorization: Bearer $CRON_SECRET`, and returns 404 when `CRON_SECRET` is unset.
- **History:**
  - System events `rotated_out` and `auto_added` are written to `review_event`.
  - They never count toward the daily limit and can't be undone.
  - Rotated-out rows get `removed_by = 'rotation'`.

## Data model (Alembic revisions 0001–0009)
- `users`: adds `provider` (default `'spotify'`); `email` dropped.
- `rotation`:
  - `id`, `owner_id`, `provider`, `playlist_id` (required; unique together with `owner_id`), `name`, `image_url` (playlist cover, refreshed on every sync), `interval_hours`, `grace_period`
  - `snapshot_id`, `last_synced_at`, `created_at`
  - Auto rotations (0009): `kind` (`manual` | `auto`), `target_size`, `rotate_percent`, `last_rotated_at`
- `rotation_track`, which replaces `song`:
  - Keys: a surrogate `id`, unique on `(rotation_id, track_id)`. `track_id` is the provider's ID, and `uri` is stored for removal.
  - Track metadata: `title`, `artists`, `album`, `image_url`, `duration_ms`, `is_playable`
  - Review state: `added_at` (from Spotify; NULL if unknown), `last_kept_at`, `keep_multiplier` (1, or 3 after a super keep), `status` (`active` | `pending_removal` | `removed`), `removed_at`, `removed_by` (`user` | `external` | `rotation`)
- `restock_block`: `user_id`, `track_id` (unique together), display metadata, `created_at`.
- `curated_pick`: track metadata plus `note`, optional `starts_at`/`ends_at`, and `created_by`.
- `restock_feedback`: `user_id`, `rotation_id`, `track_id`, `source` (`bring_back` | `picks` | `suggested` | `search`), `action` (`add` | `skip`), `created_at`.
- `suggestion_cache`: one row per user, `{candidates: {track_id: {meta, features}}, missing_scopes}` as JSON, plus `created_at`.
- `users.granted_scopes`: the space-separated OAuth scopes from the last login.
- `review_event`: `id`, `rotation_track_id`, `action` (`keep` | `super_keep` | `skip` | `remove`; system `rotated_out` | `auto_added`; legacy `undo` rows only), `previous_last_kept_at` / `previous_keep_multiplier` (keeps only, for undo), `created_at`. An undone action's row is deleted. Removed songs stay in this history so they can be reused in Phase 2 (for example, a "bring back" option in restock).
- Alembic manages the schema from here on (the one-time wipe was done 2026-11-07). All timestamps are naive UTC.
- Sync only imports tracks; local files and podcast episodes in a playlist are ignored. A missing `added_at` (very old playlists) is stored as NULL; see the due-date rules for how it's handled.

## Decisions to revisit
- Recently played only covers the last 50 plays. Saving snapshots (on each visit, or from a daily cron) would give a longer listening history.
- Daily limit is per rotation, so several big rotations can still add up to several × N in one day.
- Removing every duplicate copy of a track (above).
- Whether to add any provider abstraction if Apple comes back into scope.
- Notifications, if a channel that makes sense ever turns up.
