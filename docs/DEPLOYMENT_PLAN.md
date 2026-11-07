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

## Remaining
1. **[YOU]** Run `vercel dev` from the repo root, open http://127.0.0.1:3000, and log in with Spotify. This smoke-tests the local setup.
2. **[CLAUDE]** Commit the pending work and push to `main` (when you ask). That push redeploys production.
3. **[YOU]** If Vercel isn't connected to Git (check Settings → Git), run `vercel --prod` instead. On 2026-11-07, prod `/api/*` returned 500; the deployments were 26 days old, older than the env vars, which only take effect on a new deploy. Log in at https://playls.vercel.app. If it still returns 500, check the function logs in Vercel → Deployments → Logs.
4. **[YOU]** Optionally, add up to 4 more users in the Spotify dashboard (Settings → User Management).

## Ongoing workflow
- Develop locally with `vercel dev`. Every push to `main` deploys to production.
- Local and prod write to the **same database**.
- Schema: the Phase 1 schema change wipes the database once (approved; the existing data is test data). After that, every change goes through Alembic migrations. `init_db --reset` wipes prod.
- New env vars must be added in Vercel too, and they only take effect after a redeploy.
- `TOKEN_ENCRYPTION_KEY` must stay identical locally and in prod. If it changes, the stored Spotify tokens can't be decrypted.
- Custom domain (optional): add it in Vercel → Domains, add a matching Spotify redirect URI, and update `SPOTIFY_REDIRECT_URI`.
