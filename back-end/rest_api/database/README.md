# Database

The app uses Supabase Postgres through SQLAlchemy and psycopg 3. The connection settings are in `config.py`: it reads `DATABASE_URL` (the transaction pooler), uses `NullPool`, and sets `prepare_threshold=None`.

- `models/`: SQLAlchemy models. The target schema is described in [DESIGN.md](../../../docs/DESIGN.md#data-model-target).
- `encryption.py`: the `EncryptedText` column type (Fernet, keyed by `TOKEN_ENCRYPTION_KEY`) that stores Spotify tokens.
- `init_db.py`: run `python -m rest_api.database.init_db` from `back-end/` to create any missing tables and enable RLS. `--reset` drops everything first, and **this wipes prod**, because local and prod share the database.

Alembic migrations are planned (Phase 1, step 2 in PROJECT_STATUS.md).
