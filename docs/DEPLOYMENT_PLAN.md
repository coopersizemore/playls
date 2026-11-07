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

## Optional
- **[YOU]** Add up to 4 more users in the Spotify dashboard (Settings → User Management).

## Ongoing workflow
- Develop locally with `vercel dev`. Every push to `main` deploys to production.
- Local and prod write to the **same database**.
- Schema: the Phase 1 schema change wipes the database once (approved; the existing data is test data). After that, every change goes through Alembic migrations. `init_db --reset` wipes prod.
- New env vars must be added in Vercel too, and they only take effect after a redeploy.
- `TOKEN_ENCRYPTION_KEY` must stay identical locally and in prod. If it changes, the stored Spotify tokens can't be decrypted.
- Custom domain (optional): add it in Vercel → Domains, add a matching Spotify redirect URI, and update `SPOTIFY_REDIRECT_URI`.
