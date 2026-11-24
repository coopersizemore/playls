---
name: playls-sync-safety
description: Rules for changing anything in PlayLS that reads from or writes to a Spotify playlist: sync_rotation, flushes, restock adds/undo, auto-rotation maintain, the cron, or new Spotify calls. Use it before editing back-end/rest_api/services/sync_service.py, rotation_service.try_sync, restock_service writes, auto_restock_service, or spotify_service, and whenever a task mentions syncing, "songs disappearing", "kept state lost", duplicate adds, races or stale data, so that changes keep the guarantees that protect review history.
---

# PlayLS: sync and playlist-write safety

Spotify is the source of truth for **what's in a playlist**. PlayLS owns everything Spotify doesn't know: keeps, super keeps, pending removals, history and restock feedback. The worst bug is losing that state silently. That's what a false "removed in Spotify" does: the song is re-added later with its kept state wiped. Read `docs/SYNC_RISKS.md` (edge cases with severities) before a non-trivial change.

## Invariants to keep
1. **The sync claim wraps every sync and every PlayLS write to a playlist.**
   - Use `sync_claim(db, rotation)`, a 60-second lease on `rotation.sync_claimed_until`.
   - `try_sync`, the flush route, remove-unplayable, restock add/undo and `maintain` already take it, and it's re-entrant within a task.
   - For user actions that can't fall back to stored data, use `claim_or_409`.
   - Don't use Postgres advisory locks: through Supabase's transaction pooler they end at every commit.
2. **Writes go through `write_adopting_snapshot`.** It stores Spotify's returned `snapshot_id` only when the rows matched Spotify just before the write. Never store a write's snapshot unconditionally, or an outside change gets hidden.
3. **Full reads are re-checked.** `sync_rotation` re-reads `snapshot_id` after reading the items. If it changed, it applies **additions only** (`partial=True`) and keeps the old snapshot. Keep this when refactoring.
4. **An empty or unparseable read never wipes rows.** Today there's a guard for "items came back but none parsed". `SYNC_RISKS.md` 2.1 recommends also refusing to diff when the item count doesn't match the first page's `total`; add that if you touch the read path.
5. **Recent-sync reuse is manual rotations only.** `recently_synced` reuses a sync from the last 2 minutes, only after the app was last shown (the `X-Visible-For` header). Auto rotations always sync, because `maintain` must run on fresh rows.
6. **`maintain` (auto rotations) runs only after a successful sync,** inside the same claim, and skips while removals are pending. The rotate-out claim is the conditional update on `last_rotated_at`, and it's released if Spotify fails.
7. **Count notable outcomes** with `health.count("<area>.<event>")` (sync, claim, spotify, auto, cron), so they show on the admin dashboard. Counters are free and never raise.
8. **Timestamps are naive UTC** (`rest_api.clock.utcnow`). Spotify `added_at` strings go through the existing parsers.

## Writing a change
- **Ordering:** check the snapshot, then do the Spotify write, then make the DB change, then commit.
  - If the DB commit can fail after Spotify accepted the write, think about what the next sync will see.
  - Removals are idempotent. Adds are not: a retried add duplicates the song.
- **Spotify calls:** share the request's HTTP client (`spotify_service` does this automatically through `request_context`). Cap concurrency at about 4. Let the existing 429/401 handling work, and don't add your own retry loops.
- **Errors to clients:** generic ones only (`SpotifyAPIError` → 502/429, with no `str(e)` in `detail`).

## Tests to add (`back-end/tests`, using the fixtures and `tests/helpers.py`)
- **The fake:** `FakeSpotify` bumps a version and returns `"<id>-v<n>"` snapshots, so you can assert on `count_calls(spotify, "get_items")` and the like.
- **Races:** cover them with `claim_elsewhere`-style setup (set `sync_claimed_until`) and the `no_wait` fixture pattern in `test_sync_claim.py`.
- **Mid-read changes:** monkeypatch `SpotifyService.get_all_playlist_items` to mutate the fake playlist during the read (see `test_latency.py`).
- **Real HTTP behaviour** (429, retries): `httpx.MockTransport` through `spotify_service._client`.

## After the change
- Update `docs/SYNC_RISKS.md`: mark items fixed, or add new edge cases.
- Update `docs/DESIGN.md` ("Sync shortcuts and guards") if a rule changed.
- Run the `playls-ship-check` skill.
