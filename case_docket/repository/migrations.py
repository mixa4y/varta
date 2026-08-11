from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when migration history is invalid or a migration cannot be applied."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


class MigrationRunner:
    def __init__(self, connection: sqlite3.Connection, directory: Path | None = None):
        self.connection = connection
        self.directory = directory or Path(__file__).with_name("migrations")

    def discover(self) -> list[Migration]:
        migrations: list[Migration] = []
        for path in sorted(self.directory.glob("*.sql")):
            match = _MIGRATION_NAME.fullmatch(path.name)
            if match is None:
                raise MigrationError(f"Некоректна назва migration: {path.name}")
            raw = path.read_bytes()
            sql = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            canonical_bytes = sql.encode("utf-8")
            migrations.append(
                Migration(
                    version=int(match.group("version")),
                    name=match.group("name"),
                    path=path,
                    sql=sql,
                    checksum=hashlib.sha256(canonical_bytes).hexdigest(),
                )
            )
        versions = [migration.version for migration in migrations]
        if len(versions) != len(set(versions)):
            raise MigrationError("Номери migration мають бути унікальними")
        return migrations

    def migrate(self) -> list[int]:
        self._ensure_history_table()
        applied = {
            int(row["version"]): str(row["checksum"])
            for row in self.connection.execute(
                "SELECT version, checksum FROM schema_migrations"
            ).fetchall()
        }
        completed: list[int] = []
        for migration in self.discover():
            recorded_checksum = applied.get(migration.version)
            if recorded_checksum is not None:
                if recorded_checksum != migration.checksum:
                    raise MigrationError(
                        f"Migration {migration.version:04d} була змінена після застосування"
                    )
                continue
            self._apply(migration)
            completed.append(migration.version)
        return completed

    def _ensure_history_table(self) -> None:
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

    def _apply(self, migration: Migration) -> None:
        applied_at = datetime.now(timezone.utc).isoformat()
        history_sql = (
            "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES ("
            f"{migration.version}, "
            f"{self._quote(migration.name)}, "
            f"{self._quote(migration.checksum)}, "
            f"{self._quote(applied_at)});"
        )
        script = f"BEGIN IMMEDIATE;\n{migration.sql}\n{history_sql}\nCOMMIT;"
        try:
            self.connection.executescript(script)
        except sqlite3.Error as exc:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise MigrationError(
                f"Не вдалося застосувати migration {migration.version:04d}_{migration.name}: {exc}"
            ) from exc

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
