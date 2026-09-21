"""Write ``docs/schema.sql`` from the live database. Run by ``make schema``.

The file is the reviewable artefact of a migration: a PR that changes a model must
change ``docs/schema.sql`` too, so the diff shows what actually happens to the
database rather than only what the Python models say.

``pg_dump --schema-only`` is used when it is on PATH, because its output is exactly
what an operator would get by hand. Without it the script reflects the database and
renders the DDL itself — close enough to review, and it keeps Windows machines with
no Postgres client tools working.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pgvector.sqlalchemy  # noqa: F401  (teaches reflection about `vector` columns)
from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from knori.core.config import REPO_ROOT, settings

DEFAULT_OUTPUT = REPO_ROOT / "docs" / "schema.sql"

HEADER = """-- KnoRI database schema — GENERATED, do not edit by hand.
-- Regenerate with:  make schema   (backend/knori/scripts/dump_schema.py)
-- Source of truth: backend/knori/db/models.py + backend/ros/persistence/models.py,
-- applied through backend/knori/db/migrations/versions/.
"""

UNREACHABLE = """Could not reach Postgres at {host}:{port}/{database}.

Start it first:
    docker compose -f deploy/compose.yml up -d db     (or: make up)
then re-run this command. Nothing was written."""


class DumpError(RuntimeError):
    """A failure we can explain to the operator without a traceback."""


def _pg_env(url_str: str) -> dict[str, str]:
    """libpq environment for pg_dump — keeps the password out of the process list."""
    url = make_url(url_str)
    env = dict(os.environ)
    env.update(
        {
            "PGHOST": url.host or "localhost",
            "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database or "knori",
            "PGCONNECT_TIMEOUT": "5",
        }
    )
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


def _dump_with_pg_dump(url_str: str) -> str:
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise DumpError("pg_dump not found")
    try:
        completed = subprocess.run(
            [
                pg_dump,
                "--schema-only",
                "--no-owner",
                "--no-privileges",
                "--no-comments",
                "--schema=public",
            ],
            env=_pg_env(url_str),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DumpError(f"pg_dump could not run: {exc}") from exc
    if completed.returncode != 0:
        raise DumpError(completed.stderr.strip() or "pg_dump failed")
    return completed.stdout


def _render(connection: Connection) -> str:
    metadata = MetaData()
    metadata.reflect(bind=connection)
    dialect = postgresql.dialect()
    parts: list[str] = ["CREATE EXTENSION IF NOT EXISTS vector;\n"]
    for table in metadata.sorted_tables:
        parts.append(f"{CreateTable(table).compile(dialect=dialect)};".strip() + "\n")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(f"{CreateIndex(index).compile(dialect=dialect)};".strip() + "\n")
    return "\n".join(parts)


async def _dump_by_reflection(url_str: str) -> str:
    engine = create_async_engine(url_str)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_render)
    finally:
        await engine.dispose()


def _reachable_message(url_str: str) -> str:
    url = make_url(url_str)
    return UNREACHABLE.format(
        host=url.host or "localhost", port=url.port or 5432, database=url.database or "knori"
    )


def dump(output: Path, *, prefer_pg_dump: bool = True) -> Path:
    """Write the schema to ``output``. Raises :class:`DumpError` with a clear message."""
    sync_url = settings.sync_database_url()
    body: str | None = None
    if prefer_pg_dump:
        try:
            body = _dump_with_pg_dump(sync_url)
        except DumpError as exc:
            print(f"pg_dump unavailable ({exc}); falling back to reflection.", file=sys.stderr)
    if body is None:
        try:
            body = asyncio.run(_dump_by_reflection(settings.database_url))
        # asyncpg raises its own exceptions straight out of connect(), so they are not
        # all SQLAlchemyError. A CLI must explain the problem, not print a traceback.
        except Exception as exc:
            raise DumpError(f"{_reachable_message(settings.database_url)}\n\n({exc})") from exc
    if "CREATE TABLE" not in body:
        raise DumpError("The database has no tables yet. Run `make migrate` first.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HEADER + "\n" + body.strip() + "\n", encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate docs/schema.sql.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-pg-dump", action="store_true", help="always reflect, never shell out")
    args = parser.parse_args(argv)
    try:
        written = dump(args.output, prefer_pg_dump=not args.no_pg_dump)
    except DumpError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
