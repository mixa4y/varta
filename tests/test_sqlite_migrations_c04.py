from __future__ import annotations

import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from case_docket.repository import (
    APPLICATION_SCHEMA_CEILING,
    APPLICATION_SCHEMA_FLOOR,
    MigrationRunner,
    NewerSchemaError,
    SQLiteConnectionPolicy,
    SQLiteRepository,
    SchemaCompatibilityError,
)


MIGRATIONS = Path(__file__).resolve().parents[1] / "case_docket" / "repository" / "migrations"


def _schema_fingerprint(connection: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]), str(row[2] or ""))
        for row in connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
    )


def _create_previous_v2_fixture(database: Path, migrations: Path) -> None:
    migrations.mkdir()
    for name in ("0001_airtable_sql.sql", "0002_evidence_map_domain.sql"):
        shutil.copyfile(MIGRATIONS / name, migrations / name)
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    MigrationRunner(
        connection,
        migrations,
        schema_floor=1,
        schema_ceiling=2,
    ).migrate()
    connection.execute(
        """
        INSERT INTO cases(id, case_number, name, created_at, updated_at, legacy_payload)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "case-synthetic-upgrade",
            "SYNTHETIC-UPGRADE",
            "Синтетична справа для upgrade",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "{}",
        ),
    )
    connection.close()


def test_fresh_database_reaches_scoped_schema_ceiling(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "fresh.sqlite3")
    compatibility = repository.schema_compatibility()
    migrations = MigrationRunner(repository._conn).discover()

    assert APPLICATION_SCHEMA_FLOOR == 2
    assert APPLICATION_SCHEMA_CEILING == 8
    assert compatibility.current_version == APPLICATION_SCHEMA_CEILING
    assert compatibility.pending_versions == ()
    assert [migration.version for migration in migrations] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [migration.scope for migration in migrations] == [
        "legacy",
        "evidence",
        "system",
        "intake",
        "case",
        "evidence",
        "intake",
        "intake",
    ]
    repository.close()


def test_previous_v2_fixture_upgrades_additively_and_matches_fresh_schema(
    tmp_path: Path,
) -> None:
    upgraded_path = tmp_path / "upgraded.sqlite3"
    _create_previous_v2_fixture(upgraded_path, tmp_path / "migrations-v2")

    upgraded = SQLiteRepository(upgraded_path)
    preserved = upgraded.get("cases", "case-synthetic-upgrade")
    upgraded_fingerprint = _schema_fingerprint(upgraded._conn)
    versions = [
        int(row[0])
        for row in upgraded._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]

    fresh = SQLiteRepository(tmp_path / "fresh.sqlite3")
    fresh_fingerprint = _schema_fingerprint(fresh._conn)

    assert versions == [1, 2, 3, 4, 5, 6, 7, 8]
    assert preserved is not None
    assert preserved["name"] == "Синтетична справа для upgrade"
    assert upgraded_fingerprint == fresh_fingerprint
    upgraded.close()
    fresh.close()


def test_newer_database_is_rejected_before_writable_repository_mode(tmp_path: Path) -> None:
    database = tmp_path / "newer.sqlite3"
    repository = SQLiteRepository(database)
    repository.close()
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute(
        """
        INSERT INTO schema_migrations(version, name, checksum, applied_at)
        VALUES (9, 'system_future', ?, '2026-01-01T00:00:00+00:00')
        """,
        ("f" * 64,),
    )
    connection.close()

    with pytest.raises(NewerSchemaError, match="новішу schema version 9"):
        SQLiteRepository(database)


def test_invalid_schema_history_has_clear_compatibility_error(tmp_path: Path) -> None:
    database = tmp_path / "invalid.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
    )
    connection.close()

    with pytest.raises(SchemaCompatibilityError, match="Некоректна структура"):
        SQLiteRepository(database)


def test_concurrent_fresh_startup_serializes_migrations(tmp_path: Path) -> None:
    database = tmp_path / "concurrent-start.sqlite3"
    policy = SQLiteConnectionPolicy(busy_timeout_ms=2_000, wal_autocheckpoint_pages=32)

    def initialize() -> int:
        repository = SQLiteRepository(database, connection_policy=policy)
        try:
            return repository.schema_compatibility().current_version
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        versions = list(executor.map(lambda _: initialize(), range(2)))

    assert versions == [APPLICATION_SCHEMA_CEILING, APPLICATION_SCHEMA_CEILING]
    connection = sqlite3.connect(database)
    history = connection.execute(
        "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version ORDER BY version"
    ).fetchall()
    connection.close()
    assert history == [
        (1, 1),
        (2, 1),
        (3, 1),
        (4, 1),
        (5, 1),
        (6, 1),
        (7, 1),
        (8, 1),
    ]
