# Plan: admin monitoring dashboard

Status: **built 2026-11-24** (Phases 1–3, plus app health). The owner's decisions are in §9, and where the build differs from this plan is noted there.

**Goal:** an admin-only page showing how PlayLS is used:
- how long review sessions last
- how long each decision takes
- the mix of keep, super keep, remove and skip
- how restocking goes

It's for tuning defaults and spotting friction, not for tracking individuals.

## 1. Metrics

Every metric is shown for a chosen range (7 / 30 / 90 days) and can be split by rotation kind (manual / auto).

| Area | Metric | Definition |
|---|---|---|
| Review sessions | Sessions | Visits to the Review page with at least one decision |
| | Session length | From opening Review to the last decision. Shown as median and p90, since the mean is skewed by people listening along |
| | Songs per session | Decisions per session (a revisited song counts once) |
| | How sessions end | Finished the batch / "Stop for now" / left the page |
| | "Review more" uptake | Share of sessions that went past the daily limit |
| Decisions | Decision time | From the card appearing to the decision, as median and p90. Revisits are excluded, and anything over 10 minutes is capped (someone listened to the whole song or walked away) |
| | Decision mix | Keep / super keep / remove / skip as shares, per week |
| | Input method | Swipe vs button vs keyboard |
| | Changed mind | Share of decisions later undone or changed (Back, then a different choice) |
| Restock | Add rate by source | Adds ÷ cards shown, for Bring back, PlayLS picks, For you and Search |
| | Not now / Stop suggesting rates | Same base |
| | Undone adds | Adds taken back with Undo |
| | Time per card | As for decision time |
| Usage | Active users | Users with at least one session per week |
| | Rotations | Count by kind, and average size |

**Optional, in a later phase: app health.** This reuses the latency work:
- sync failures and Spotify 429s per day
- `Server-Timing` p50/p95 per route
- requests that waited on the sync claim

## 2. What can and can't come from existing data

- **Available now:**
  - The decision mix, from `review_event.action`.
  - Restock add vs Not now by source, from `restock_feedback`.
  - Activity over time.
- **Can only be estimated:**
  - Sessions, by splitting at 30-minute gaps (the same rule History uses).
  - Decision time, from the gaps between consecutive events. That's inaccurate: the first card of a session can't be measured, and the gaps include listening.
- **Missing entirely:**
  - Real sessions and card-shown times.
  - Input method.
  - Changes of mind: undo deletes the event.
  - Data from deleted rotations: their events cascade away.

So the dashboard needs its own append-only record. The existing rows can feed a one-time estimated backfill of the decision mix (optional; see §7).

## 3. Capturing the data

### Storage: one append-only table, `analytics_event` (migration 0013, with RLS enabled like every table)

| Column | Notes |
|---|---|
| `id` | |
| `user_id` | FK, `ON DELETE CASCADE`, so "Delete account" removes it, as promised |
| `rotation_id` | FK, `ON DELETE SET NULL`, so stats survive deleting a rotation |
| `rotation_kind` | Copied at write time, so splitting by kind still works after a delete |
| `session_id` | A UUID from the client, one per Review or Restock page visit |
| `kind` | `review_decision`, `review_undo`, `restock_decision`, `restock_undo` or `session_end` |
| `action` | Keep, remove, skip, add, not now… |
| `source` | Restock only |
| `decision_ms` | Clamped to 0–600,000 |
| `session_elapsed_ms` | ms since the page opened (clamped) |
| `input` | `swipe`, `button` or `key` |
| `revisit` | bool |
| `position` | The card's index in the batch |
| `created_at` | Server time; this one is authoritative |

Indexes go on `created_at` and `(user_id, created_at)`. The `track_id` isn't stored, since song-level detail isn't needed for these metrics. Nothing here ever updates or deletes a row, apart from the account-delete cascade.

### Write path: piggyback on the calls that already happen
- `POST /rotation/{id}/review` and `POST /rotation/{id}/restock/{add|skip|block|undo}` accept an optional `telemetry` object: `{session_id, decision_ms, session_elapsed_ms, input, revisit, position}`.
- The schema validates it: UUID pattern, clamped ranges, enums, and `extra="forbid"` as usual.
- The server writes the analytics row in the same transaction as the decision.
- An old client, or a request without `telemetry`, behaves exactly as now. Telemetry never affects the decision itself.
- A bad telemetry value is dropped, not answered with a 422, so analytics can never break reviewing.
- **Session end:** Review's existing flush-on-exit and "Done" call add `{session_id, ended: "done" | "stopped" | "left"}`. Restock gets the same through a `keepalive` beacon on `pagehide`. If an end event goes missing (closed tab, offline), the session still counts: its length comes from the largest `session_elapsed_ms`.

### Client side (`Review.js`, `Restock.js`)
- `crypto.randomUUID()` on mount.
- `performance.now()` when each card renders. The timer pauses while the tab is hidden, so time away isn't counted.
- The decision handlers pass the elapsed time and input method along.

This is about 60 lines, plus a tiny shared helper (e.g. `src/telemetry.js`).

### Alternatives considered
- **A separate `/api/analytics` endpoint with batching:** more requests, plus a retry/queue to maintain. Piggybacking costs nothing extra in requests.
- **Third-party analytics (PostHog, Mixpanel, Vercel Web Analytics):**
  - Vercel's only does page views.
  - The others would send your friends' listening behavior to another company, which is overkill for 5 users.
  - Rejected for privacy and scope.

## 4. Admin-only access: secure, and it makes sense

It reuses the existing curation gate exactly:
- **Backend:** a new router under `/api/admin/stats` with `dependencies=[Depends(require_admin)]`. Accounts not in `ADMIN_SPOTIFY_IDS` get **404**, as with picks.
  - It fails closed: if the env var is unset, nobody sees it.
  - The admin check sits on top of the normal session-cookie auth and CSRF rules.
- **Read-only:** GET endpoints only. They return **aggregates only**: counts, percentiles and histograms, never raw events, tokens or `UserDB` rows.
- **Errors:** generic, following the existing "no `str(e)` in `detail`" rule.
- **Frontend:**
  - The route is `/admin/stats` behind `RequireAuth`.
  - The ☰ menu shows "Usage stats" under "Curate picks" only when `user.is_admin`.
  - The page is **lazy-loaded** (`React.lazy`), so regular users never download its code or charting library.
- **Privacy:**
  - **Per-user data:** by default the dashboard shows all users combined, plus "you vs everyone else". Per-user rows would identify your friends' habits, so that's an open decision (§9).
  - **Disclosure:** one sentence in Settings → Account and in the help guide, saying "PlayLS records anonymous timing of reviews to improve the app".
  - **Account deletion** removes the data.

## 5. API

`GET /api/admin/stats?days=30&kind=all|manual|auto` returns one JSON payload. Five users and about 10k events a year make this a trivial query.

```jsonc
{
  "range": {"from": "...", "to": "..."},
  "sessions": {"count": 42, "median_s": 95, "p90_s": 410, "songs_median": 12,
               "ended": {"done": 30, "stopped": 8, "left": 4}, "review_more_share": 0.1,
               "length_histogram": [{"bucket": "0-1m", "n": 9}, ...]},
  "decisions": {"count": 520, "median_ms": 4100, "p90_ms": 21000,
                "mix": {"keep": 0.62, "super_keep": 0.05, "remove": 0.25, "skip": 0.08},
                "mix_by_week": [{"week": "2026-11-16", "keep": 80, "remove": 31, ...}],
                "time_histogram": [...], "input": {"swipe": 0.7, "button": 0.2, "key": 0.1},
                "changed_mind_share": 0.04},
  "restock": {"by_source": [{"source": "suggested", "shown": 300, "add": 41, "not_now": 120, "undo": 3}],
              "time_median_ms": 6000},
  "usage": {"active_users_by_week": [...], "rotations": {"manual": 3, "auto": 1}},
  "you": { /* the same session and decision summaries, for the admin's own account */ }
}
```

The aggregation goes in `services/analytics_service.py`:
- **Pure functions** compute percentiles and histograms in Python. That keeps them testable on SQLite, which lacks `percentile_cont`.
- **One query** fetches the range's rows.

## 6. Dashboard page (`AdminStats.js`)
- **Header:** range chips (7 / 30 / 90 days) and a kind filter.
- **KPI tiles:** sessions, median session length, median decision time, keep rate and remove rate, each compared with the previous period.
- **Charts:**
  - decision mix per week (stacked bars)
  - decision-time distribution (histogram, with a median marker)
  - session-length distribution
  - restock add rate by source (bars)
  - how sessions end (a small bar)
- **Small tables:** input method, changed-mind rate, active users per week.
- **Library:** `@mui/x-charts`. It matches MUI 7 and the theme tokens, so dark mode works for free, and it's lazy-loaded with the page. Load the `dataviz` skill when building this.
- **Empty and low-data states:** with fewer than ~20 sessions, it shows "Not enough data yet" instead of misleading percentiles.

## 7. Backfill (optional)

A one-off read of the existing `review_event` and `restock_feedback` rows, shown in the dashboard as **estimated** and visually separate:
- weekly decision mix
- restock add rate by source
- estimated sessions, from 30-minute gaps

Decision time isn't backfilled, because the gaps would be misleading.

## 8. Phases

| Phase | Work | Estimate |
|---|---|---|
| 1. Capture | Migration 0013, the telemetry schema and write path (review and restock routes), the client timing helper and its wiring in Review/Restock, the session-end signal, a disclosure line, and tests. The tests cover: a decision with and without telemetry, bad telemetry dropped, undo recorded, account deletion cascading, and rotation deletion keeping stats | ~1 day |
| 2. Stats API | `analytics_service` (pure aggregation and tests) and `GET /api/admin/stats` (with a 404 test for non-admins) | ~½ day |
| 3. Dashboard | Lazy-loaded `/admin/stats` page, the menu entry, charts, and empty states | ~1 day |
| 4. Later / optional | Estimated backfill; app-health metrics (sync failures, 429s, Server-Timing percentiles recorded by `request_context`); a retention purge in the daily cron | ~½–1 day |

Data only starts accumulating once Phase 1 ships, so it's worth deploying Phase 1 on its own first. By the time the dashboard exists there will be real data to look at.

## 9. Decisions (owner, 2026-11-24) and what was built
1. **Per-user breakdown:** all opted-in users are combined, plus a "You vs everyone else" table. No per-user rows.
2. **Consent:** users are asked and can say no.
   - **Storage:** `users.analytics_consent` (NULL = not asked yet).
   - **Asking:** Home shows a one-time prompt (Allow / No thanks), and Settings → Privacy has a switch.
   - **Enforcement:** nothing is recorded without consent. The client doesn't send telemetry, and the server checks again.
   - **Opting out** deletes that user's recorded usage data.
   - **Health data** has no user column, so it's recorded regardless. The consent text says so.
3. **Retention: 6 months** (`telemetry.RETENTION_DAYS = 180`). It's purged by the daily cron and each time the dashboard loads.
4. **Scope:** everything in §1, plus app health and these extra user insights:
   - **Song age:** remove rate by how long the song had been in the playlist or since its last keep. Useful for choosing default intervals.
   - **Position in the batch:** remove rate and decision time by position (fatigue).
   - **Timing:** a weekday × hour heatmap of when people review, in local time.
   - **Habits:**
     - sessions opened without deciding
     - days overdue when reviewed
     - sessions per person per week
     - days between sessions
     - input method
     - how sessions end
   - **Account setup:** which settings people change, rotation overrides, and consent counts.
5. **No backfill:** the dashboard starts fresh.

**Differences from the plan above:**
- **Health table:** health is a separate `health_event` table, filled by the request middleware (`services/health.py`).
  - Errors, 429s, slow requests and any request with counters are always recorded. Other requests are sampled at 25%, and latency percentiles use only the sample.
  - **Counters recorded:**
    - sync outcomes
    - claim waits and timeouts
    - Spotify 429s, retries, token refreshes and errors by status
    - auto rotate-out, fill and shortfall
    - cron runs
- **Restock sessions:** end as `exhausted` (reached the end of the deck) or `left`. Review sessions end as `done` (finished), `stopped` ("Stop for now") or `left`.
- **Dashboard:** `/admin/stats` (`AdminStats.js`) is lazy-loaded with `@mui/x-charts` (pinned 8.29.3).
  - Charts use the validated dataviz reference palette (slots 1–4), with separate light and dark steps, plus a sequential blue for the heatmap.
  - Every chart has a table view.
