"""The database connection: one async engine, one session factory, two ways in.

Request handlers take :func:`get_session` as a FastAPI dependency. Jobs, scripts and
anything else outside a request use :func:`session_scope`.

Neither helper commits behind your back inside a request: services commit explicitly,
because a Recognition write and its ``jobs`` row must land in the *same* transaction
(CLAUDE.md → Data rules). ``session_scope`` does commit on a clean exit, which is what
a job handler wants.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from knori.core.config import settings


def _create_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(
        url or settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=5,
        pool_recycle=1800,
        # asyncpg caches prepared statements per connection; pgbouncer is not in the
        # stack, so the default is fine and left alone.
    )


engine: AsyncEngine = _create_engine()

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Rolls back if the handler raised; never commits for you."""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transaction for jobs and scripts: commit on success, roll back on any error."""
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def ping() -> bool:
    """True when the database answers. Used by ``/readyz``; never raises."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    # asyncpg raises its own types (bad password, unknown database) straight out of
    # connect(), so SQLAlchemyError alone is not enough for a probe that must not raise.
    except Exception:
        return False
    return True


async def dispose() -> None:
    """Close every pooled connection. Called from the app and worker shutdown hooks."""
    await engine.dispose()
