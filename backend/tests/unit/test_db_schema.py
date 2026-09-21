"""The baseline migration must describe exactly what the models describe.

``0001_initial`` is hand-maintained, so nothing stops it drifting from the two model
modules except this test. It renders the migration in Alembic's offline mode — real
DDL, no database — and compares the table, column, index and constraint names it
produces against ``Base.metadata``.
"""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import knori.db.models  # noqa: F401
import ros.persistence.models  # noqa: F401
from knori.core.config import BACKEND_ROOT
from ros.persistence.base import Base

MIGRATION = BACKEND_ROOT / "knori" / "db" / "migrations" / "versions" / "0001_initial.py"


@pytest.fixture(scope="module")
def baseline_sql() -> str:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "knori" / "db" / "migrations"))
    buffer = io.StringIO()
    config.output_buffer = buffer
    command.upgrade(config, "head", sql=True)
    return buffer.getvalue()


def test_migration_module_imports() -> None:
    spec = importlib.util.spec_from_file_location("baseline", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0001_initial"
    assert module.down_revision is None


def test_vector_extension_is_created_first(baseline_sql: str) -> None:
    extension = baseline_sql.index("CREATE EXTENSION IF NOT EXISTS vector")
    first_vector_column = baseline_sql.index("VECTOR(1536)")
    assert extension < first_vector_column


def test_every_table_is_created(baseline_sql: str) -> None:
    in_sql = set(re.findall(r"CREATE TABLE (\w+)", baseline_sql)) - {"alembic_version"}
    assert in_sql == set(Base.metadata.tables)


def test_every_column_is_created(baseline_sql: str) -> None:
    missing: dict[str, set[str]] = {}
    for table in Base.metadata.sorted_tables:
        body = re.search(rf"CREATE TABLE {table.name} \((.*?)\n\);", baseline_sql, re.S)
        assert body is not None, table.name
        rendered = set(re.findall(r"^\s{4}(\w+) ", body.group(1), re.M))
        gap = set(table.columns.keys()) - rendered
        if gap:
            missing[table.name] = gap
    assert missing == {}


def test_every_index_is_created(baseline_sql: str) -> None:
    in_sql = set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", baseline_sql))
    in_models = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert in_sql == in_models


def test_every_constraint_is_created(baseline_sql: str) -> None:
    in_sql = set(re.findall(r"CONSTRAINT (\w+)", baseline_sql)) - {"alembic_version_pkc"}
    in_models = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name
    }
    assert in_sql == in_models


def test_downgrade_drops_every_table() -> None:
    source = Path(MIGRATION).read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade()") :]
    dropped = set(re.findall(r"op\.drop_table\(\"(\w+)\"\)", downgrade))
    assert dropped == set(Base.metadata.tables)


def test_job_queue_partial_indexes_match_the_data_rules(baseline_sql: str) -> None:
    """One *queued* job per dedupe key, one *running* job per lock key (CLAUDE.md)."""
    assert (
        "CREATE UNIQUE INDEX uq_jobs_dedupe_queued ON jobs (dedupe_key) "
        "WHERE status = 'queued'" in baseline_sql
    )
    assert (
        "CREATE UNIQUE INDEX uq_jobs_lock_running ON jobs (lock_key) "
        "WHERE status = 'running'" in baseline_sql
    )


def test_no_postgres_enum_types(baseline_sql: str) -> None:
    """Status and kind columns are text + CHECK, never Postgres enums."""
    assert "CREATE TYPE" not in baseline_sql
