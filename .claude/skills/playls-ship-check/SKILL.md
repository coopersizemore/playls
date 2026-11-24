---
name: playls-ship-check
description: Pre-push and post-deploy checklist for the PlayLS repo (FastAPI + React on Vercel, shared Supabase DB). Use it before saying any PlayLS change is done, before the user commits or pushes, after writing an Alembic migration, after touching requirements/config files in back-end/, and whenever production misbehaves after a deploy ("login is 500", "the API is down", "it worked locally"). It covers the checks CI doesn't: the Vercel build quirks and the shared production database.
---

# PlayLS: ship check

Local and production share **one Supabase database**, and every push to `main` deploys to production. Vercel does **not** wait for CI. So verify before the user pushes, and confirm the deployment afterwards.

## Before saying "done"
Run these from the repo, using the venv Python. On this Windows machine, bare `python` is the Microsoft Store 3.11 stub.

```bash
cd back-end && .venv/Scripts/python -m ruff check .          # lint (rules in back-end/ruff.toml)
cd back-end && .venv/Scripts/python -m pytest -q             # hermetic: SQLite + FakeSpotify, no network
cd back-end && .venv/Scripts/python -m alembic check         # models match the migrations
cd playls_front_end && CI=true npx react-scripts build       # ESLint warnings fail the build, as in CI
```

Report the actual results. If something can't be verified locally (the browser UI, real Spotify), say so.

## Migrations (they apply to production immediately)
- **Prefer additive changes:** nullable columns, new tables, new indexes. The currently deployed code keeps working against the new schema, so it's safe to apply before pushing.
- **RLS on new tables:** every new table must run `ALTER TABLE "<t>" ENABLE ROW LEVEL SECURITY` in its migration, with no policies. That blocks Supabase's Data API.
- **Destructive or breaking changes** (dropping or renaming columns, NOT NULL without a default): stop and agree on an order with the user. Usually that's: deploy code that tolerates both schemas, then migrate, then remove the old path.
- **After writing one:**
  - Run `alembic upgrade head`, then `alembic check`.
  - Register any new model in `rest_api/database/models/__init__.py`.

## Vercel traps (each of these has broken this app before)
- **Never add `back-end/pyproject.toml`.** Vercel's Python builder then installs dependencies from it instead of `requirements.txt`, deploys with no packages, and every route fails with `FUNCTION_INVOCATION_FAILED` / `ModuleNotFoundError`. Tool config lives in `ruff.toml` and `pytest.ini`.
- **Runtime dependencies go in `back-end/requirements.txt`.** Dev-only tools (pytest, ruff) go in `requirements-dev.txt`.
- **Python 3.12** comes from `back-end/.python-version`. `vercel dev` uses `back-end/.venv`, which must stay on 3.12.
- **The `/api` prefix:** Vercel passes the full path, so every router is mounted with it. The frontend only ever calls relative `/api`.
- **`.bat` files need CRLF line endings.** Python's `write_text` turns them into LF, so restore CRLF if you script edits to them.

## After the user pushes
```bash
curl -s https://playls.vercel.app/api                            # expect {"message": "PlayLS API is running"}
vercel ls playls --environment production                        # is the new deployment Ready?
vercel inspect <deployment-id> --logs | grep -iE "install|python|error"   # build log: "requirements.txt"?
vercel logs --deployment <deployment-url> --since 30m             # runtime tracebacks
```
- **`FUNCTION_INVOCATION_FAILED` on every route** means the function crashed while importing, usually missing dependencies or an import error. The runtime log has the traceback.
- **To restore service fast:** offer Vercel Instant Rollback to the last good deployment, but don't do it without the user's go-ahead. That old code then runs against the new schema, which is fine for additive migrations.

## Don't
- Print or commit `back-end/.env`; it holds real secrets.
- Commit or push unless asked. The user commits often, so don't tell them changes are "uncommitted" without checking `git status`.
