"""Database configuration and session management."""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

# Load back-end/.env for local runs; on Vercel env vars come from the project settings
backend_dir = Path(__file__).parent.parent.parent
load_dotenv(dotenv_path=backend_dir / ".env")

# Supabase Postgres connection string. On Vercel use the transaction pooler (port 6543).
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set (see back-end/env.example)")

# Supabase hands out postgresql:// URLs; point SQLAlchemy at the psycopg 3 driver
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "").lower() == "true",
    # Serverless functions shouldn't hold connections; Supabase's pooler does the pooling
    poolclass=NullPool,
    # The transaction pooler doesn't support prepared statements
    connect_args={"prepare_threshold": None},
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models
Base = declarative_base()

# Dependency to get database session
def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
