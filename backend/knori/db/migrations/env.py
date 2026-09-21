"""Alembic environment: one history for the product tables and the ROS tables.

Both model packages are imported here so that ``Base.metadata`` describes the whole
database. ``ros`` still knows nothing about ``knori`` — this file is on the product
side of the boundary and is the only place the two halves meet.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

import knori.db.models  # noqa: F401  (registers the product tables)
import ros.persistence.models  # noqa: F401  (registers the ROS tables)
from knori.core.config import settings
from ros.persistence.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# configparser treats % as interpolation, and a URL-encoded password may contain one.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata

# Shared by offline and online runs so a --sql dump and a real upgrade cannot drift.
CONTEXT_OPTS: dict[str, Any] = {
    "target_metadata": target_metadata,
    "compare_type": True,
    "compare_server_default": True,
    "include_schemas": False,
    # Renders pgvector columns as pgvector.sqlalchemy.VECTOR(...) in new revisions.
    "user_module_prefix": "pgvector.sqlalchemy.",
}


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **CONTEXT_OPTS,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, **CONTEXT_OPTS)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
