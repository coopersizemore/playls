---
name: playls-add-metric
description: How to add a usage or health metric to the PlayLS admin monitoring dashboard (/admin/stats) without breaking consent, privacy or chart rules. Use it when the user wants to track, measure, count or chart something new about how PlayLS is used or how it performs ("how often do people...", "track X", "add a chart for...", "is Y slow?"), or when touching telemetry.py, health.py, analytics_service.py or AdminStats.js.
---

# PlayLS: adding a dashboard metric

The design and the owner's decisions are in `docs/MONITORING_PLAN.md`. In short:
- **Usage data** is opt-in (`users.analytics_consent`), stored in `analytics_event`, and shown only **aggregated**. The exception is "You vs everyone else", which shows the admin's own numbers.
- **Health data** has **no user column**, is stored in `health_event`, and is recorded for everyone.
- **Retention:** both are kept 6 months (`telemetry.purge`).
- **Access:** the endpoint is admin-only (`require_admin`; everyone else gets a 404).

## First: can existing data answer it?
Check `analytics_service.py` (its summaries already cover sessions, decisions, restock, usage and health) and the columns of `analytics_event` / `health_event`. Often it's a new aggregation over existing rows, and nothing new needs capturing.

## Capturing something new
- **App behaviour or performance:**
  - Call `health.count("<area>.<event>", n)` at the point where it happens. It's free, never raises, and is a no-op outside a request.
  - Add the key to `HEALTH_GROUPS` in `analytics_service.py` so the dashboard shows it.
- **A user's choices or timing:**
  - Extend the optional `telemetry` object, or add a nullable column to `analytics_event` (a migration with RLS already on; see `playls-ship-check`).
  - Server-derived facts (like `song_age_days`) are better computed in the route, from the row's state *before* the change, than trusted from the client.
  - Telemetry is parsed leniently. Invalid values are **dropped, never answered with a 422**, so analytics can't break a decision.
  - Check `telemetry.enabled(user)` before computing anything expensive.
  - On the client, extend `startSession(...).decision(...)` in `src/telemetry.js`. It already returns nothing without consent.
- **Privacy:**
  - Don't store track ids, search text, playlist names or anything that identifies songs.
  - Don't return raw events or per-user rows from `/admin/stats`; the tests check that `session_id` never appears.
  - If you collect something new, update the consent wording (`USAGE_DATA_TEXT` in `SettingsControls.js`) and the plan doc.

## Aggregating
- Add a **pure** function in `analytics_service.py` that takes row-like objects and returns JSON-ready values. Use the existing `percentile`, `histogram` and bucket helpers.
- Percentiles are computed in Python (SQLite tests have no `percentile_cont`).
- Latency comes only from `sampled` health rows; counts come from all rows.
- Unit-test it with `SimpleNamespace` rows in `test_analytics.py`, plus one endpoint test.

## Showing it (`AdminStats.js`)
- **Form:**
  - **A single number** → a `Stat` tile, with the previous period if it's comparable.
  - **A distribution or comparison** → `BarChart` (`@mui/x-charts`) inside `ChartCard`.
  - **Two measures with different units** → two charts or a table, never a dual axis.
- **Table view:** every `ChartCard` passes a `table`. Values must never be reachable only through a tooltip.
- **Colours** come from `SERIES` / `HEAT`: the validated categorical slots in fixed order, with separate light and dark steps.
  - A single series uses slot 1.
  - For more than 4 categorical series, load the `dataviz` skill and run its palette validator before adding colours.
- **Filters:** the existing one-row range and kind filters scope everything. Don't add filters inside a chart.

Then run `playls-ship-check`, and open `/admin/stats` in both colour modes to check for label collisions.
