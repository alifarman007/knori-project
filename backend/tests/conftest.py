"""Shared pytest fixtures.

Two kinds of test live here. Unit tests never touch Postgres and must run on a laptop
with Docker switched off. Integration tests (``@pytest.mark.integration``) need a
database; when it is unreachable they are **skipped, never failed**, so a red test run
always means real breakage.

``asyncio_mode = "auto"`` in ``pyproject.toml`` means async tests need no decorator.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from knori.core.config import Settings, get_settings

CONNECT_TIMEOUT_SECONDS = 3.0

# Fixed namespace so a "fake user" keeps the same id across a test run and across
# machines — it makes a failure message reproducible.
_FAKE_NAMESPACE = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")

# One probe per URL per test session. Cached here rather than in a session-scoped
# fixture, because the probe has to run on the *test's* event loop.
_REACHABLE: dict[str, bool] = {}


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """anyio-style tests run on asyncio, the same loop the app uses."""
    return "asyncio"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def database_url(settings: Settings) -> str:
    return settings.database_url


def new_id() -> uuid.UUID:
    """A fresh id for a row that is never written to the database."""
    return uuid.uuid4()


def fake_user_id(name: str = "test-user") -> uuid.UUID:
    """Deterministic user id for unit tests: same name in, same uuid out."""
    return uuid.uuid5(_FAKE_NAMESPACE, name)


@pytest.fixture
def user_id() -> uuid.UUID:
    return fake_user_id()


@pytest.fixture
def other_user_id() -> uuid.UUID:
    """A second user, for the cross-user 404 checks every endpoint owes us."""
    return fake_user_id("other-user")


async def database_is_reachable(url: str) -> bool:
    """True when this URL answers ``SELECT 1``. Never raises, answers once per URL."""
    cached = _REACHABLE.get(url)
    if cached is not None:
        return cached
    engine = create_async_engine(url, pool_pre_ping=False)
    reachable = True
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    # asyncpg raises its own exception types out of connect(); any of them means
    # "no usable database", and a missing database must skip, never fail.
    except Exception:
        reachable = False
    finally:
        await engine.dispose()
    _REACHABLE[url] = reachable
    return reachable


async def require_database(url: str) -> None:
    if not await database_is_reachable(url):
        where = url.rsplit("@", 1)[-1]
        pytest.skip(f"Postgres is not reachable at {where} - start it with `make up`")


@pytest.fixture
async def db_connection(database_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection wrapped in a transaction that is always rolled back."""
    await require_database(database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield connection
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """Session joined to the rolled-back transaction: tests never leave rows behind."""
    session = AsyncSession(
        bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Stop a test that monkeypatches the environment leaking into the next one."""
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _dispose_app_engine() -> AsyncIterator[None]:
    """Give every test a fresh connection pool.

    Tests that drive the ASGI app use the module-level engine in
    ``knori.db.session``. pytest-asyncio closes its event loop after each test, so
    any connection still pooled would belong to a loop that no longer exists and the
    next test would fail with "Event loop is closed". Disposing is cheap: an engine
    that never connected has nothing to close.
    """
    yield
    from knori.db import session as app_session

    await app_session.dispose()
