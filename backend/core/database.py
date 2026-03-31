# Paste contents from the generated core/database.py here
# backend/core/database.py
"""
Async SQLAlchemy engine, session factory, and declarative base.

PostGIS extension is enabled via the Alembic migration (not here),
but GeoAlchemy2 types are registered on import so the ORM models
can use Geometry columns directly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import get_settings

settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
#
# pool_pre_ping=True: validate connection before checkout (Supabase drops
# idle connections after ~5 min on free tier).
# pool_size + max_overflow: keep Render free tier memory usage low.

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=not settings.is_production,  # SQL logging in dev only
    future=True,
)

# ── Session factory ───────────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep attributes accessible after commit
    autoflush=False,
    autocommit=False,
)


# ── Base class for all ORM models ─────────────────────────────────────────────

class Base(DeclarativeBase):
    """
    Shared declarative base. All db_models/ files inherit from this.
    Import: from core.database import Base
    """
    pass


# ── Dependency injection helper (FastAPI) ─────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a database session per request.

    Usage in route:
        @router.get("/")
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Context manager (scheduler / background tasks) ────────────────────────────

@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Use in non-FastAPI contexts like the APScheduler daily job:

        async with get_db_context() as db:
            result = await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Startup / shutdown helpers ────────────────────────────────────────────────

async def init_db() -> None:
    """
    Called on application startup (main.py lifespan).
    Verifies the database connection is reachable and PostGIS is installed.
    Does NOT create tables — that's Alembic's job.
    """
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        # Verify PostGIS is available (installed by Alembic migration)
        result = await conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='postgis')")
        )
        postgis_ok = result.scalar()
        if not postgis_ok:
            raise RuntimeError(
                "PostGIS extension not installed. "
                "Run: alembic upgrade head"
            )


async def close_db() -> None:
    """Called on application shutdown."""
    await engine.dispose()