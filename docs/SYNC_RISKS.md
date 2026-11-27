# Spotify ↔ PlayLS: tradeoffs and edge cases

Written 2026-11-24, after the latency pass and the sync claim. This is a review from reading the code; none of it has been seen happen in real use. Each item gives what happens, how bad it is, and what would fix it.

**Status (checked against the code 2026-11-27):** only 2.3 (renames) is fixed, plus the count check for Liked Songs only (4.6). `Server-Timing` has been read on prod, but no numbers are recorded here yet. Every other item, including the whole suggested order in §6, is still open.

Severity: **High** = can silently lose or corrupt review state. **Medium** = wrong for a while, or needs a manual fix. **Low** = cosmetic, slower, or self-healing.

## How the two sides relate (short version)
- **Spotify is the source of truth for what's in a playlist.** PlayLS stores a copy (`rotation_track`) plus everything Spotify doesn't know: review history, keep anchors, super keeps, pending removals, restock feedback, blocks.
- **Song identity is the track id actually stored in the playlist.** That's `linked_from.id` when Spotify relinks. Duplicate copies collapse to one row, anchored on the earliest `added_at`.
- **A sync** (`sync_rotation`):
  1. Checks the playlist's `snapshot_id`.
  2. Flushes pending removals.
  3. If the snapshot differs from the stored one, re-reads every item, re-checks the snapshot, and diffs.
  4. Our own writes store the snapshot they produce, when the rows were in sync just before.
- **When syncs run:**
  - On page loads. Manual rotations skip the sync if one ran in the last 2 minutes and after the app was last shown.
  - In the background on Home.
  - From the daily cron, for auto rotations.
  - Every sync, flush and restock add runs under a 60-second per-rotation lease (`sync_claimed_until`).

## 1. Latency-change tradeoffs most likely to cause trouble later

1. **A stored snapshot can hide a change indefinitely (High, rare).**
   - **What happens:** two things can leave PlayLS believing it's current when it isn't, and it only re-reads when the snapshot changes again:
     - Snapshot adoption: a Spotify edit lands between PlayLS's snapshot check and its own write, so the write's snapshot gets stored as ours.
     - A full read that returns fewer items than exist, but with an unchanged snapshot (see 2.1).
   - **Also missed:** `is_playable` changes, which don't change the snapshot. They're only refreshed on full reads, so "unavailable" badges and auto rotate-out order (unplayable songs leave first) can be stale for weeks.
   - **Fix:** force a full read when the last one is older than about 24 hours (a `last_full_read_at` column), or have the daily cron force-sync every rotation. That caps any hidden drift at a day.

2. **The 60-second lease vs. long operations (Medium).**
   - **What happens:** the lease doesn't renew. A sync that runs past 60 seconds can be taken over by a second request, and both then run at once. The races the claim was meant to stop come back:
     - a pending removal coming back as "re-added"
     - an auto rotation filling twice
   - **What could take that long:**
     - a big playlist re-read that hits 429 waits (up to 8 s)
     - an auto restock gathering For you signals (15–20 calls in a row)
     - Supabase being slow
   - **Timeouts:** `vercel.json` doesn't set `maxDuration`, so the platform default applies. A function killed mid-sync leaves its lease for up to 60 s, and writes it already sent to Spotify without the matching database commit (see 3.3).
   - **Fixes:**
     - Renew the lease between phases, or size it for the worst case.
     - Set an explicit `maxDuration`.
     - Log when a sync runs past about 45 s.

3. **Waiting on someone else's lease (Medium, visible to the user).**
   - **What happens:** a request waits up to 10 s, then carries on with stored data. A lease left by a crashed function causes:
     - 10-second page loads, with stale data and no warning, for up to a minute
     - Restock adds returning 409
     - Review's flush-on-exit leaving removals pending
   - **Fix:** a lease that's been held a long time should show "Updating…" in the UI rather than a silent wait.

4. **Reusing a recent sync, on desktop (Medium).**
   - **What happens:** the visibility rule assumes you have to leave the PlayLS tab to edit in Spotify. On a desktop with the Spotify app next to a visible browser window, the tab never goes hidden, so edits stay invisible for up to 2 minutes. The same goes for edits made on another device.
   - **Caveat:** only manual rotations reuse syncs.
   - **Fixes:**
     - Treat window focus or blur as "shown" too.
     - Add a manual "refresh" action.

5. **Full reads that keep getting interrupted (Medium, edge).**
   - **What happens:** if the playlist changes during every full read, every read is applied as "additions only." Removals in Spotify are then never detected, so the rows drift. Two causes:
     - another app or automation editing it constantly
     - a very large playlist read slowly under 429 waits
   - **Fix:** after N partial reads in a row, do a full read under a short retry loop, or accept a diff whose before and after snapshots match only after a retry.

6. **Retrying writes after 429 (Low).**
   - **Rests on an assumption:** a 429 means Spotify didn't act on the request. That's the standard meaning, but it isn't verified for every endpoint.
   - **Timeouts aren't retried, but they're a real duplicate risk:** an `httpx` timeout on an add may still have been applied. Retrying the add from the UI then adds the song twice. It shows up as one row, and a later removal drops both copies.

7. **Home's per-rotation background syncs (Low).**
   - It sends N+1 requests, each possibly hitting a cold start.
   - A rotation with a slow auto restock keeps its card locked the whole time.
   - It uses the same Spotify quota as before, just at the same moment instead of spread out.

8. **More database connections (Low, measure).** NullPool opens a new connection after every commit. The claim adds commits (claim, release, and every 0.5 s poll while waiting), and each opens a connection. Watch `dbconnect` in `Server-Timing`. That's fine at 5 users; it's the first thing to revisit if connections show up in the numbers.

9. **The `Server-Timing` header is on for every response (Low).** It only reveals timings to the signed-in user. Turn it off, or keep it to admins, if that ever matters.

## 2. Reading Spotify (sync)

1. **A full read that silently returns too few items (High).**
   - **Two ways it happens:** a page comes back 200 but empty, or `total` overstates or understates what the pages return. Either way, the songs that should have been on that page are missing from the read.
   - **Why the existing guards miss it:**
     - The snapshot recheck doesn't catch it, because nothing changed.
     - The "nothing parsed" guard only catches a read where every item fails to parse.
   - **Result:**
     - The diff marks the missing songs "removed in Spotify."
     - The next full read sees them again and takes the re-added path, which wipes their kept and super-kept state.
     - Auto rotations may also refill the slots.
   - **Worst case:** an empty read of a non-empty playlist marks everything removed.
   - **Fix:** skip the diff (and log it) when the number of items received doesn't match page 1's `total`, or when a read comes back empty but the rotation has active rows and the snapshot says the playlist isn't new.

2. **A playlist deleted, unfollowed, or no longer accessible (Medium).**
   - A rotation whose playlist returns 403 or 404 shows "Couldn't reach Spotify" forever. Nothing marks the rotation as broken or offers to delete it.
   - "Deleting" a playlist in Spotify only unfollows it, and the API probably still serves it to its owner. If so, PlayLS keeps rotating a playlist you can't see anymore. This hasn't been verified.
   - Collaborators who lose access get 403s.
   - **Fix:** after repeated 403/404s, show "This playlist is gone" with a delete option.

3. **Renames and covers (Low). Fixed 2026-11-24.** The image and the name are both refreshed on every sync: Spotify's name wins, and a rename in PlayLS renames the Spotify playlist first (owner only). Demo and Liked Songs rotations keep their PlayLS names.

4. **Relinking and market changes (Low–Medium).**
   - Identity stays stable as long as the playlist keeps holding the same original id.
   - **Travel:** `market=from_token` follows the account's country, so songs can flip to unplayable. "Remove unavailable" would then remove songs that play fine at home, and auto rotations rotate unplayable songs out first.
   - **A song added twice under two different ids** (original and relinked) becomes two separate rows.

5. **Local files, podcast episodes, and unavailable (null) items are ignored (Low).**
   - They're never reviewed.
   - Auto rotations' song counts leave them out, so the Spotify playlist is bigger than `target_size`.
   - A playlist with only these skips the diff every time, so the snapshot is never stored, which means a full re-read on every sync (slow, but correct).

6. **`added_at` semantics (Low).** Removing a song and re-adding it in Spotify between two syncs never shows up as a removal. It just gets a new `added_at`, which moves the due date for songs that were never kept. Reordering doesn't change `added_at`.

7. **Re-adding a removed song in Spotify resets it (by design).** Its kept state and super keep are wiped, and it starts fresh from the new `added_at`. That's correct, but surprising if you added it back by accident.

## 3. Writing to Spotify (flush, restock, auto restocks)

1. **Removals stuck as pending (High for auto rotations).**
   - **What happens:** if flushes keep failing (revoked token, quota, playlist gone), removals stay pending indefinitely.
   - **Manual rotations:** the songs are still in Spotify, so you keep hearing songs you removed.
   - **Auto rotations:** `maintain` does nothing while anything is pending, so the rotation stops turning over or refilling, with no sign in the UI beyond "Removing" chips.
   - **Fix:**
     - Show a "N removals waiting to reach Spotify" warning with a retry.
     - Consider letting `maintain` run anyway, counting pending songs as gone.

2. **A write that reaches Spotify, then a database commit that fails (Medium).**
   - **Add** (restock or auto): the song is on Spotify, but its row and events were rolled back.
     - The next sync imports it as an external add, with no `auto_added` event and no restock feedback.
     - Retrying a manual restock add duplicates it on Spotify.
   - **Rotate-out:** removed from Spotify, but rows still active. The next full read marks them "removed in Spotify" instead of "rotated out." The return cooldown still applies, since it only looks at `removed_at`, but History shows the wrong reason.
   - **Flush:** safe. A retry removes URIs that are already gone, which does nothing.
   - **Fix:** write the database rows as pending before the Spotify call and confirm them after, so a crash leaves a record to reconcile.

3. **Removal is by URI, not by position (by design).** It's immune to reordering, but it always drops every copy, which the owner has accepted.

4. **The 10,000-item playlist limit (Low).** Adds to a full playlist fail with a generic 502. That's irrelevant for auto rotations (200 at most), and possible but unlikely for big manual ones.

5. **Restock adds use `get_track` without a market.** Songs come back unrelinked, so an added song can be unplayable in your market. The next sync's `is_playable` reveals it.

## 4. Who owns the playlist, and other PlayLS-side relationships

1. **Two PlayLS users rotating one collaborative playlist (Medium).** Rotations are unique per owner, not per playlist. Each user's removals show up as "removed in Spotify" for the other, and each claim only guards that user's rotation, not the playlist. Nothing stops this setup.
2. **Editing an auto rotation's playlist by hand (Low, surprising).**
   - Songs you add push it over the target, and the next rotation trims the excess by its leaving order, oldest first, so your new songs survive and older ones go.
   - Songs you remove are refilled on the next sync.
3. **Deleting a rotation or your account leaves the Spotify playlist untouched (by design).** Wrapping the same playlist again starts from scratch: no history, and every song is treated as new, subject to the grace period.
4. **Things that don't take the sync claim:**
   - **Reviews:** a keep or remove landing during a sync's diff is last-write-wins on the row. The worst case is a pending removal on a song that just left Spotify; the flush then does nothing and marks it removed. Harmless.
   - **Settings edits during `maintain`:** that rotation uses the old target. Harmless.
   - **Deletes during a sync:** the sync's commits may fail and roll back. Harmless.
5. **Bring back and the 4-week cooldown** key on PlayLS's `removed_at`. Songs removed in Spotify count too, with the time PlayLS noticed, not when you actually removed them.
6. **Liked Songs rotations** (DESIGN.md, "Liked Songs rotations"):
   - **No snapshot (Low, mitigated).** The page-1 fingerprint assumes Liked Songs is strictly newest first. That ordering was verified on a real library (2026-11-27). If Spotify ever changes it, a like plus an unlike outside page 1 is missed until the daily full read.
   - **Every PlayLS write forces a full read (Low, cost).** Unlikes and likes return no snapshot, so the next sync reads the whole library (up to 100 requests at the 5,000-song cap).
   - **The mass-removal guard can stall (Low).** If you really unlike more than 25% of the library at once in Spotify, every sync re-reads and applies additions only. Those songs stay "active" in PlayLS, and removing them in Review is a harmless no-op unlike. The guard logs `sync.liked_partial_mass_removal`.
   - **An unlike is lossy (by design, warned in the UI).** Re-liking resets Spotify's like date, so the song's due clock restarts from the new `added_at`.
   - **Count-check guard:** the liked path refuses to diff when the items read don't match `total` (item 2.1). It's applied only to Liked Songs for now, so playlist sync behaviour is unchanged.

## 5. Account, tokens and quota

1. **Revoked app access or a dead refresh token (Medium).**
   - Every sync fails, and the cron fails silently for that user. Auto rotations stop turning over.
   - The UI only shows "Couldn't reach Spotify." There's no "reconnect Spotify" prompt unless scopes are missing.
   - Removing a user from the Development Mode allowlist looks the same (403s).
   - **Fix:** detect a failed refresh (`invalid_grant`) and send the user through login again.
2. **Quota exhausted (Medium).**
   - It's shared across every app on the developer account, so it can be used up by something other than PlayLS.
   - PlayLS doesn't remember being rate-limited between requests. Every page load tries Spotify again, gets a fast 429, and shows stale data with a warning. That's correct but noisy, and the cron fails for the day.
   - **Fix:** store a "rate limited until" time (per user or global) and skip Spotify until then.
3. **Concurrent token refresh across requests (Low).** Within a request, the refresh lock makes sure only one call refreshes. Two separate requests (Home's parallel syncs) can still both refresh at once. Spotify usually keeps refresh tokens valid, so the second one probably works, but if Spotify ever rotates them strictly, one session could store a dead token.

## 6. Suggested order if any of this gets picked up
1. Add the count and empty-read guard (2.1). It's cheap, and it's the most direct way to lose kept state.
2. Force a full read daily (1.1). It caps every "stale forever" case: adopted snapshots, `is_playable`, partial reads.
3. Show stuck pending removals in the UI, and let `maintain` cope with them (3.1).
4. Show a "reconnect Spotify" prompt on refresh failure (5.1), and a "playlist is gone" state (2.2).
5. Measure `Server-Timing` on prod before tuning the claim lease and waits (1.2, 1.3, 1.8).
