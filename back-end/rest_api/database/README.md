# Database

The app uses Supabase Postgres through SQLAlchemy and psycopg 3. The connection settings are in `config.py`: it reads `DATABASE_URL` (the transaction pooler), uses `NullPool`, and sets `prepare_threshold=None`.

- `models/`: SQLAlchemy models (`users`, `rotation`, `rotation_track`, `review_event`), described in [DESIGN.md](../../../docs/DESIGN.md). Every model must be imported in `models/__init__.py`.
- `encryption.py`: the `EncryptedText` column type (Fernet, keyed by `TOKEN_ENCRYPTION_KEY`) that stores Spotify tokens.
- Migrations live in `back-end/alembic/`. Run `.venv/Scripts/alembic upgrade head` from `back-end/`. Create new ones with `alembic revision --autogenerate -m "..."`, review the result, and add `ENABLE ROW LEVEL SECURITY` for new tables. `alembic check` confirms the models match the migrations. Local and prod share the database, so migrations apply to prod.
