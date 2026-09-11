from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .migrations import MigrationRunner, SchemaCompatibility
from .sqlite_connection import (
    SQLiteBusyError,
    SQLiteConnectionFactory,
    SQLiteConnectionPolicy,
)


class SQLiteBackupError(RuntimeError):
    """Raised when a DB-only snapshot or restore candidate is incomplete or invalid."""


class SQLiteIntegrityError(SQLiteBackupError):
    """Raised when SQLite integrity or foreign-key verification fails."""


@dataclass(frozen=True, slots=True)
class SQLiteVerification:
    path: Path
    schema: SchemaCompatibility
    integrity_check: tuple[str, ...]
    foreign_key_violations: tuple[tuple[object, ...], ...]


@dataclass(frozen=True, slots=True)
class SQLiteSnapshotResult:
    path: Path
    schema_version: int
    size_bytes: int
    sha256: str
    integrity_check: tuple[str, ...]


def verify_sqlite_database(
    database_path: Path,
    *,
    connection_policy: SQLiteConnectionPolicy | None = None,
    require_current: bool = True,
) -> SQLiteVerification:
    path = Path(database_path)
    if not path.is_file():
        raise SQLiteBackupError(f"SQLite database не знайдено: {path}")
    policy = connection_policy or SQLiteConnectionPolicy()
    connection = SQLiteConnectionFactory(path, policy).connect()
    try:
        schema = MigrationRunner(connection).assert_supported(
            require_current=require_current
        )
        integrity = tuple(
            str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()
        )
        foreign_keys = tuple(
            tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
        )
    except sqlite3.Error as exc:
        raise SQLiteBackupError(f"Не вдалося перевірити SQLite database: {exc}") from exc
    finally:
        connection.close()
    if integrity != ("ok",):
        raise SQLiteIntegrityError(f"SQLite integrity_check failed: {integrity}")
    if foreign_keys:
        raise SQLiteIntegrityError(
            f"SQLite foreign_key_check виявив {len(foreign_keys)} порушень"
        )
    return SQLiteVerification(
        path=path,
        schema=schema,
        integrity_check=integrity,
        foreign_key_violations=foreign_keys,
    )


def create_online_backup(
    source_path: Path,
    destination_path: Path,
    *,
    connection_policy: SQLiteConnectionPolicy | None = None,
    pages: int = 256,
    sleep_seconds: float = 0.01,
) -> SQLiteSnapshotResult:
    """Create and verify a consistent SQLite snapshot without filesystem originals."""

    return _copy_with_sqlite_backup_api(
        source_path,
        destination_path,
        connection_policy=connection_policy,
        pages=pages,
        sleep_seconds=sleep_seconds,
        operation="online backup",
    )


def restore_sqlite_snapshot(
    snapshot_path: Path,
    destination_path: Path,
    *,
    connection_policy: SQLiteConnectionPolicy | None = None,
) -> SQLiteSnapshotResult:
    """Restore only the DB snapshot into a new target; C15 owns the full bundle."""

    return _copy_with_sqlite_backup_api(
        snapshot_path,
        destination_path,
        connection_policy=connection_policy,
        pages=256,
        sleep_seconds=0.01,
        operation="restore",
    )


def _copy_with_sqlite_backup_api(
    source_path: Path,
    destination_path: Path,
    *,
    connection_policy: SQLiteConnectionPolicy | None,
    pages: int,
    sleep_seconds: float,
    operation: str,
) -> SQLiteSnapshotResult:
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if not source.is_file():
        raise SQLiteBackupError(f"SQLite source не знайдено: {source}")
    if source == destination:
        raise SQLiteBackupError("SQLite source і destination мають бути різними")
    if destination.exists():
        raise SQLiteBackupError(f"SQLite destination вже існує: {destination}")
    if pages < 1:
        raise ValueError("pages має бути додатним")
    if sleep_seconds < 0:
        raise ValueError("sleep_seconds не може бути від’ємним")

    policy = connection_policy or SQLiteConnectionPolicy()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = SQLiteConnectionFactory(source, policy).connect()
        MigrationRunner(source_connection).assert_supported(require_current=True)
        target_connection = sqlite3.connect(
            partial,
            timeout=policy.busy_timeout_ms / 1_000,
            isolation_level=None,
            check_same_thread=True,
        )
        started = time.monotonic()

        def progress(status: int, remaining: int, total: int) -> None:
            del remaining, total
            if status in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                elapsed = time.monotonic() - started
                if elapsed >= policy.busy_timeout_ms / 1_000:
                    raise SQLiteBusyError(operation, policy.busy_timeout_ms)

        source_connection.backup(
            target_connection,
            pages=pages,
            progress=progress,
            sleep=sleep_seconds,
        )
        target_connection.close()
        target_connection = None
        source_connection.close()
        source_connection = None

        verification = verify_sqlite_database(
            partial,
            connection_policy=policy,
            require_current=True,
        )
        if destination.exists():
            raise SQLiteBackupError(f"SQLite destination з’явився під час {operation}")
        partial.rename(destination)
        return SQLiteSnapshotResult(
            path=destination,
            schema_version=verification.schema.current_version,
            size_bytes=destination.stat().st_size,
            sha256=_sha256(destination),
            integrity_check=verification.integrity_check,
        )
    except (SQLiteBackupError, SQLiteBusyError):
        raise
    except sqlite3.Error as exc:
        raise SQLiteBackupError(f"SQLite {operation} failed: {exc}") from exc
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        _remove_partial(partial)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_partial(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)
