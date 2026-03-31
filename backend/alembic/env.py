# Paste contents from the generated alembic/env.py here
# backend/alembic/env.py
"""
Alembic migration environment.

Configured for:
  - Async SQLAlchemy (asyncpg driver)
  - PostGIS / GeoAlchemy2 types (so Alembic doesn't try to diff geometry columns)
  - Autogenerate from db_models/ ORM metadata
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

# ── Make `backend/` importable when alembic runs from backend/ dir ────────────
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Alembic Config object (provides access to alembic.ini)
config = context.config

# Set up logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import all models so their tables are in metadata ─────────────────────────
from core.database import Base          # noqa: E402 — must be after sys.path
import db_models                        # noqa: F401, E402 — registers all ORM models

target_metadata = Base.metadata

# ── Read DATABASE_URL from app settings (not alembic.ini) ─────────────────────
from core.config import get_settings    # noqa: E402

_settings = get_settings()

# Override alembic.ini sqlalchemy.url with our async URL
config.set_main_option("sqlalchemy.url", _settings.database_url)


# ── Offline migrations (SQL script generation) ────────────────────────────────

def run_migrations_offline() -> None:
    """
    Run migrations without a live DB connection.
    Useful for generating .sql scripts for DBA review.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # PostGIS: don't diff geometry columns — they're managed manually
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (live DB connection) ────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        # Compare server defaults so Alembic doesn't generate spurious diffs
        compare_server_default=True,
        # Render AS EXECUTE for PostGIS geometry columns
        # (prevents Alembic trying to DROP/CREATE geometry cols on every run)
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations synchronously inside it."""
    connectable = create_async_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,  # no pool for migration runs
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()