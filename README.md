# PlayLS: a lazy Susan for playlists

[![Backend](https://github.com/coopersizemore/playls/actions/workflows/backend.yml/badge.svg)](https://github.com/coopersizemore/playls/actions/workflows/backend.yml)
[![Frontend](https://github.com/coopersizemore/playls/actions/workflows/frontend.yml/badge.svg)](https://github.com/coopersizemore/playls/actions/workflows/frontend.yml)

PlayLS keeps Spotify playlists fresh. A **rotation** wraps a playlist you own. Each song comes due for review N days after it was added (or after you last kept it), and you keep it, skip it or remove it. Removals are applied to the Spotify playlist.

Scope: personal use, in Spotify Development Mode (at most 5 allowlisted users). For product decisions see [DESIGN.md](docs/DESIGN.md), and for status and the roadmap see [PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## Stack
- **Frontend:** React 19 (CRA), MUI 7, react-router 7 (`playls_front_end/`)
- **Backend:** FastAPI, SQLAlchemy and psycopg 3 (`back-end/rest_api/`)
- **Database:** Supabase Postgres
- **Hosting:** Vercel, with two services on one domain (`/api/*` goes to FastAPI and everything else to React; see `vercel.json`)
- **Auth:** Spotify OAuth, then an httpOnly session cookie

## Local development
Prerequisites: Python 3.12, Node, the Vercel CLI, and a Spotify app whose redirect URI is `http://127.0.0.1:3000/api/auth/callback`.

```bash
# one-time
<path-to-python3.12> -m venv back-end/.venv
back-end/.venv/Scripts/pip install -r back-end/requirements-dev.txt   # (bin/ on macOS/Linux; dev adds pytest and ruff)
cp back-end/env.example back-end/.env                              # then fill in the values
(cd playls_front_end && npm install)

# run (from the repo root; don't activate the venv first)
vercel dev
```

Open **http://127.0.0.1:3000**, not `localhost`. The login cookies are tied to the host name.

The required env vars are listed in `back-end/env.example`. Local and production share one Supabase database.

## Tests
```bash
cd back-end && .venv/Scripts/python -m pytest        # bin/python on macOS/Linux
cd back-end && .venv/Scripts/python -m ruff check .  # lint (config in back-end/ruff.toml)
```

GitHub Actions runs the same lint and tests on every push to `main` (`.github/workflows/backend.yml`), and builds the frontend with lint warnings as errors (`.github/workflows/frontend.yml`; locally: `cd playls_front_end && CI=true npm run build`).

## Deployment
Every push to `main` deploys to Vercel production. Setup steps are in [DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md).
