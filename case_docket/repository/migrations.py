from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


APPLICATION_SCHEMA_FLOOR = 2
APPLICATION_SCHEMA_CEILING = 7

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_SCOPED_MIGRATION_START = 3
_MIGRATION_SCOPES = {"system", "intake", "case", "evidence"}
_HISTORY_COLUMNS = {"version", "name", "checksum", "applied_at"}


class MigrationError(RuntimeError):
    """Raised when migration history is invalid or a migration cannot be applied."""


class SchemaCompatibilityError(MigrationError):
    """Raised when a database history is not safe for this application schema range."""


class NewerSchemaError(SchemaCompatibilityError):
    """Raised when a database was written by a newer application schema."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    scope: str
    path: Path
    sql: str
    checksum: str


@dataclass(frozen=True, slots=True)
class AppliedMigration:
    version: int
    name: str
    checksum: str


@dataclass(frozen=True, slots=True)
class SchemaCompatibility:
    current_version: int
    application_floor: int
    application_ceiling: int
    pending_versions: tuple[int, ...]

    @property
    def is_current(self) -> bool:
        return self.current_version == self.application_ceiling

    @property
    def is_application_compatible(self) -> bool:
        return self.application_floor <= self.current_version <= self.application_ceiling


class MigrationRunner:
    def __init__(
        self,
        connection: sqlite3.Connection,
        directory: Path | None = None,
        *,
        schema_floor: int | None = None,
        schema_ceiling: int | None = None,
        enforce_scopes: bool | None = None,
    ):
        bundled_directory = directory is None
        self.connection = connection
        self.directory = directory or Path(__file__).with_name("migrations")
        self.schema_floor = (
            APPLICATION_SCHEMA_FLOOR if schema_floor is None and bundled_directory else schema_floor
        )
        self.schema_ceiling = (
            APPLICATION_SCHEMA_CEILING
            if schema_ceiling is None and bundled_directory
            else schema_ceiling
        )
        self.enforce_scopes = bundled_directory if enforce_scopes is None else enforce_scopes

    def discover(self) -> list[Migration]:
        if not self.directory.is_dir():
            raise MigrationError(f"Каталог migrations недоступний: {self.directory}")
        migrations: list[Migration] = []
        for path in sorted(self.directory.glob("*.sql")):
            match = _MIGRATION_NAME.fullmatch(path.name)
            if match is None:
                raise MigrationError(f"Некоректна назва migration: {path.name}")
            version = int(match.group("version"))
            name = match.group("name")
            raw = path.read_bytes()
            try:
                sql = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            except UnicodeDecodeError as exc:
                raise MigrationError(f"Migration {path.name} має бути UTF-8") from exc
            migrations.append(
                Migration(
                    version=version,
                    name=name,
                    scope=self._scope(version, name),
                    path=path,
                    sql=sql,
                    checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                )
            )
        return self._validate_catalog(migrations)

    def inspect(self) -> SchemaCompatibility:
        migrations = self.discover()
        migration_by_version = {migration.version: migration for migration in migrations}
        applied = self._read_history()
        versions = [migration.version for migration in applied]
        ceiling = self._ceiling(migrations)
        floor = self._floor(ceiling)

        if versions and versions[-1] > ceiling:
            raise NewerSchemaError(
                "База має новішу schema version "
                f"{versions[-1]}; застосунок підтримує не вище {ceiling}"
            )
        if versions != list(range(1, len(versions) + 1)):
            raise SchemaCompatibilityError(
                f"Некоректна послідовність schema_migrations: {versions or 'empty'}"
            )
        for recorded in applied:
            migration = migration_by_version.get(recorded.version)
            if migration is None:
                raise SchemaCompatibilityError(
                    f"Migration {recorded.version:04d} відсутня у package"
                )
            if recorded.name != migration.name:
                raise SchemaCompatibilityError(
                    f"Migration {recorded.version:04d} має несумісне ім’я в історії"
                )
            if recorded.checksum != migration.checksum:
                raise SchemaCompatibilityError(
                    f"Migration {recorded.version:04d} була змінена після застосування"
                )

        current = versions[-1] if versions else 0
        pending = tuple(
            migration.version for migration in migrations if migration.version > current
        )
        return SchemaCompatibility(
            current_version=current,
            application_floor=floor,
            application_ceiling=ceiling,
            pending_versions=pending,
        )

    def assert_supported(self, *, require_current: bool = False) -> SchemaCompatibility:
        compatibility = self.inspect()
        if require_current and not compatibility.is_current:
            raise SchemaCompatibilityError(
                "База потребує migration: "
                f"schema {compatibility.current_version}, "
                f"потрібна {compatibility.application_ceiling}"
            )
        if not require_current and not compatibility.is_application_compatible:
            raise SchemaCompatibilityError(
                "Schema version поза application range: "
                f"{compatibility.current_version} not in "
                f"{compatibility.application_floor}..{compatibility.application_ceiling}"
            )
        return compatibility

    def migrate(self) -> list[int]:
        migrations = self.discover()
        self._ensure_history_table()
        compatibility = self.inspect()
        pending = set(compatibility.pending_versions)
        completed: list[int] = []
        for migration in migrations:
            if migration.version not in pending:
                continue
            if self._apply(migration):
                completed.append(migration.version)
        self.assert_supported(require_current=True)
        return completed

    def _validate_catalog(self, migrations: list[Migration]) -> list[Migration]:
        if not migrations:
            raise MigrationError(f"Каталог migrations порожній: {self.directory}")
        versions = [migration.version for migration in migrations]
        if len(versions) != len(set(versions)):
            raise MigrationError("Номери migration мають бути унікальними")
        ceiling = self.schema_ceiling if self.schema_ceiling is not None else max(versions)
        expected = list(range(1, ceiling + 1))
        if versions != expected:
            raise MigrationError(
                f"Package migrations має містити безперервні versions {expected}; є {versions}"
            )
        floor = self.schema_floor if self.schema_floor is not None else 1
        if not 1 <= floor <= ceiling:
            raise MigrationError(f"Некоректний application schema range {floor}..{ceiling}")
        return migrations

    def _read_history(self) -> list[AppliedMigration]:
        entry = self.connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'schema_migrations'"
        ).fetchone()
        if entry is None:
            return []
        if str(entry[0]) != "table":
            raise SchemaCompatibilityError("schema_migrations має бути SQLite table")
        columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(schema_migrations)")
        }
        missing = _HISTORY_COLUMNS - columns
        if missing:
            raise SchemaCompatibilityError(
                f"Некоректна структура schema_migrations; відсутні {sorted(missing)}"
            )
        try:
            rows = self.connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
        except sqlite3.Error as exc:
            raise SchemaCompatibilityError(
                f"Не вдалося прочитати schema_migrations: {exc}"
            ) from exc
        applied: list[AppliedMigration] = []
        for row in rows:
            try:
                version = int(row[0])
                name = str(row[1])
                checksum = str(row[2])
            except (TypeError, ValueError) as exc:
                raise SchemaCompatibilityError(
                    "schema_migrations містить некоректний запис"
                ) from exc
            if version < 1 or not name or len(checksum) != 64:
                raise SchemaCompatibilityError(
                    f"schema_migrations містить некоректний запис version={version}"
                )
            applied.append(AppliedMigration(version, name, checksum))
        return applied

    def _ensure_history_table(self) -> None:
        entry = self.connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'schema_migrations'"
        ).fetchone()
        if entry is not None:
            self._read_history()
            return
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise MigrationError(f"Не вдалося створити schema_migrations: {exc}") from exc

    def _apply(self, migration: Migration) -> bool:
        applied_at = datetime.now(timezone.utc).isoformat()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != migration.name or str(existing[1]) != migration.checksum:
                    raise SchemaCompatibilityError(
                        f"Migration {migration.version:04d} змінилася під час concurrent startup"
                    )
                self.connection.commit()
                return False
            for statement in self._statements(migration):
                self.connection.execute(statement)
            self.connection.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (migration.version, migration.name, migration.checksum, applied_at),
            )
            self.connection.commit()
            return True
        except SchemaCompatibilityError:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
        except (sqlite3.Error, MigrationError) as exc:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise MigrationError(
                f"Не вдалося застосувати migration "
                f"{migration.version:04d}_{migration.name}: {exc}"
            ) from exc

    @staticmethod
    def _statements(migration: Migration) -> tuple[str, ...]:
        statements: list[str] = []
        buffer = ""
        for line in migration.sql.splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                if MigrationRunner._contains_sql(buffer):
                    statements.append(buffer.strip())
                buffer = ""
        if MigrationRunner._contains_sql(buffer):
            raise MigrationError(f"Migration {migration.path.name} містить incomplete SQL")
        return tuple(statements)

    @staticmethod
    def _contains_sql(value: str) -> bool:
        return any(
            stripped and not stripped.startswith("--")
            for stripped in (line.strip() for line in value.splitlines())
        )

    def _scope(self, version: int, name: str) -> str:
        if version == 1:
            return "legacy"
        scope = name.split("_", 1)[0]
        if self.enforce_scopes and version >= _SCOPED_MIGRATION_START:
            if scope not in _MIGRATION_SCOPES:
                raise MigrationError(
                    f"Migration {version:04d}_{name} не має scope "
                    f"{sorted(_MIGRATION_SCOPES)}"
                )
        return scope if scope in _MIGRATION_SCOPES else "custom"

    def _ceiling(self, migrations: list[Migration]) -> int:
        return self.schema_ceiling if self.schema_ceiling is not None else migrations[-1].version

    def _floor(self, ceiling: int) -> int:
        del ceiling
        return self.schema_floor if self.schema_floor is not None else 1
