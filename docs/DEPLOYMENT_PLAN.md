# Deployment plan: Supabase + Vercel

Scope: personal use and demos. That means one Supabase project, one Spotify app (Development Mode, at most 5 allowlisted users, and the owner needs Premium), a Vercel production deployment at **https://playls.vercel.app**, and local development with `vercel dev`. Local and prod share the one database.

Tags: **[YOU]** means it needs your accounts, dashboards or secrets. **[CLAUDE]** means Claude Code does it in the repo.

## Done
- [x] `vercel.json` with `api` (FastAPI under `/api`) and `web` (React) services on one domain **[CLAUDE]**
- [x] Postgres via `DATABASE_URL`; security hardening **[CLAUDE]**
- [x] Supabase project; transaction pooler `DATABASE_URL` in `back-end/.env` **[YOU]** (connection verified on 2026-11-07)
- [x] `SECRET_KEY` and `TOKEN_ENCRYPTION_KEY` in `back-end/.env` **[CLAUDE]**
- [x] `back-end/.env` cleaned up; `SPOTIFY_REDIRECT_URI=http://127.0.0.1:3000/api/auth/callback` **[YOU]**
- [x] Spotify dashboard redirect URIs: `http://127.0.0.1:3000/api/auth/callback` and `https://playls.vercel.app/api/auth/callback` **[YOU]**
- [x] Vercel project `playls` linked to the GitHub repo; production env vars set (`DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`) **[YOU]**
- [x] `back-end/.venv` on Python 3.12; Vercel CLI installed **[YOU]**
- [x] Local `vercel dev` login works. Windows needs Developer Mode on, because the Vercel CLI creates symlinks. **[YOU]**
- [x] Pending work committed and pushed; Git-connected prod deploys are live **[YOU]**
- [x] Prod login works at https://playls.vercel.app (2026-11-07) **[YOU]**
- [x] `CRON_SECRET` set in Vercel (Production) and redeployed. Vercel Cron calls `/api/cron/auto-restock` daily at 10:00 UTC (`vercel.json` `crons`) to turn over auto rotations, capture everyone's listening history and run the retention purges. If it's ever unset, the route is disabled. **[YOU]** (2026-11-27)
- [x] `ADMIN_SPOTIFY_IDS` set locally and in Vercel. These accounts can curate PlayLS picks at `/admin/picks` and see `/admin/stats`. **[YOU]** (2026-11-27)
- [x] Every account logged in again for the current scopes: the four playlist scopes plus `user-top-read`, `user-read-recently-played`, `user-library-read` and `user-library-modify`. Repeat this whenever scopes change. **[YOU]** (2026-11-27)
- [x] Manual verification on prod against real Spotify **[YOU]** (2026-11-27)

## Optional
- **[YOU]** Optionally tune demo mode with `DEMO_MAX_ACTIVE` (default 100) and `DEMO_MAX_PER_CLIENT` (live demos per IP, default 3). The demo needs `back-end/rest_api/services/demo/catalog.json`, which is built once with `back-end/scripts/build_demo_catalog.py` (it's already committed); without it `/api/demo/start` returns 503.
- **[YOU]** Add up to 4 more users in the Spotify dashboard (Settings → User Management).

## Ongoing workflow
- Develop locally with `vercel dev`. Every push to `main` deploys to production.
- Local and prod write to the **same database**.
- Schema: managed by Alembic. From `back-end/`, run `.venv/Scripts/alembic upgrade head`. Migrations aren't run on deploy, so apply them yourself **before** pushing code that needs them. The database is shared, so a migration applies to prod immediately. `alembic downgrade base` wipes prod.
- New env vars must be added in Vercel too, and they only take effect after a redeploy.
- `TOKEN_ENCRYPTION_KEY` must stay identical locally and in prod. If it changes, the stored Spotify tokens can't be decrypted.
- Custom domain (optional): add it in Vercel → Domains, add a matching Spotify redirect URI, and update `SPOTIFY_REDIRECT_URI`.
