from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn


_SYNCHRONOUS_LEVELS = {
    "OFF": 0,
    "NORMAL": 1,
    "FULL": 2,
    "EXTRA": 3,
}
_CHECKPOINT_MODES = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
_CONFIGURATION_LOCK_GUARD = threading.Lock()
_CONFIGURATION_LOCKS: dict[str, threading.Lock] = {}


class SQLiteLifecycleError(RuntimeError):
    """Raised when a SQLite connection cannot satisfy the VARTA policy."""


class SQLiteBusyError(SQLiteLifecycleError):
    """A bounded SQLite lock wait expired; the operation was not reported as success."""

    def __init__(self, operation: str, timeout_ms: int):
        super().__init__(
            f"SQLite зайнята під час '{operation}'; bounded wait {timeout_ms} ms вичерпано"
        )
        self.operation = operation
        self.timeout_ms = timeout_ms


@dataclass(frozen=True, slots=True)
class SQLiteConnectionPolicy:
    busy_timeout_ms: int = 5_000
    wal_autocheckpoint_pages: int = 1_000
    synchronous: str = "NORMAL"

    def __post_init__(self) -> None:
        if not 1 <= self.busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms має бути в межах 1..60000")
        if not 1 <= self.wal_autocheckpoint_pages <= 1_000_000:
            raise ValueError("wal_autocheckpoint_pages має бути в межах 1..1000000")
        normalized = self.synchronous.upper()
        if normalized not in _SYNCHRONOUS_LEVELS:
            raise ValueError(
                f"Непідтримуваний SQLite synchronous mode: {self.synchronous}"
            )
        object.__setattr__(self, "synchronous", normalized)


@dataclass(frozen=True, slots=True)
class SQLiteConnectionSettings:
    foreign_keys: bool
    busy_timeout_ms: int
    journal_mode: str
    synchronous: int
    wal_autocheckpoint_pages: int


@dataclass(frozen=True, slots=True)
class SQLiteCheckpointResult:
    busy: bool
    wal_pages: int
    checkpointed_pages: int


@dataclass(frozen=True, slots=True)
class SQLiteConnectionFactory:
    database_path: Path
    policy: SQLiteConnectionPolicy = SQLiteConnectionPolicy()

    def connect(self) -> sqlite3.Connection:
        database_path = Path(self.database_path)
        if str(database_path) != ":memory:":
            database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(
                database_path,
                timeout=self.policy.busy_timeout_ms / 1_000,
                isolation_level=None,
                check_same_thread=True,
            )
            connection.row_factory = sqlite3.Row
            with _configuration_lock(database_path):
                self._configure(connection, in_memory=str(database_path) == ":memory:")
            return connection
        except sqlite3.OperationalError as exc:
            if "connection" in locals():
                connection.close()
            if is_sqlite_busy_error(exc):
                raise SQLiteBusyError("connection setup", self.policy.busy_timeout_ms) from exc
            raise SQLiteLifecycleError(f"Не вдалося відкрити SQLite: {exc}") from exc
        except Exception:
            if "connection" in locals():
                connection.close()
            raise

    def _configure(self, connection: sqlite3.Connection, *, in_memory: bool) -> None:
        connection.execute(f"PRAGMA busy_timeout = {self.policy.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")

        current_journal = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        expected_journal = "memory" if in_memory else "wal"
        if not in_memory and current_journal != "wal":
            current_journal = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()

        connection.execute(f"PRAGMA synchronous = {self.policy.synchronous}")
        connection.execute(
            f"PRAGMA wal_autocheckpoint = {self.policy.wal_autocheckpoint_pages}"
        )
        settings = inspect_connection_settings(connection)
        expected_synchronous = _SYNCHRONOUS_LEVELS[self.policy.synchronous]
        failures: list[str] = []
        if not settings.foreign_keys:
            failures.append("foreign_keys=OFF")
        if settings.busy_timeout_ms != self.policy.busy_timeout_ms:
            failures.append(f"busy_timeout={settings.busy_timeout_ms}")
        if current_journal != expected_journal or settings.journal_mode != expected_journal:
            failures.append(f"journal_mode={settings.journal_mode}")
        if settings.synchronous != expected_synchronous:
            failures.append(f"synchronous={settings.synchronous}")
        if settings.wal_autocheckpoint_pages != self.policy.wal_autocheckpoint_pages:
            failures.append(f"wal_autocheckpoint={settings.wal_autocheckpoint_pages}")
        if failures:
            raise SQLiteLifecycleError(
                "SQLite connection policy не застосовано: " + ", ".join(failures)
            )


def inspect_connection_settings(connection: sqlite3.Connection) -> SQLiteConnectionSettings:
    return SQLiteConnectionSettings(
        foreign_keys=bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
        busy_timeout_ms=int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
        journal_mode=str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
        synchronous=int(connection.execute("PRAGMA synchronous").fetchone()[0]),
        wal_autocheckpoint_pages=int(
            connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
        ),
    )


def checkpoint_wal(
    connection: sqlite3.Connection,
    mode: str = "PASSIVE",
) -> SQLiteCheckpointResult:
    normalized = mode.upper()
    if normalized not in _CHECKPOINT_MODES:
        raise ValueError(f"Непідтримуваний WAL checkpoint mode: {mode}")
    row = connection.execute(f"PRAGMA wal_checkpoint({normalized})").fetchone()
    return SQLiteCheckpointResult(
        busy=bool(row[0]),
        wal_pages=int(row[1]),
        checkpointed_pages=int(row[2]),
    )


def is_sqlite_busy_error(error: sqlite3.Error) -> bool:
    message = str(error).casefold()
    return "locked" in message or "busy" in message


def raise_bounded_busy(
    error: sqlite3.OperationalError,
    *,
    operation: str,
    policy: SQLiteConnectionPolicy,
) -> NoReturn:
    if is_sqlite_busy_error(error):
        raise SQLiteBusyError(operation, policy.busy_timeout_ms) from error
    raise error


def _configuration_lock(database_path: Path) -> threading.Lock:
    key = ":memory:" if str(database_path) == ":memory:" else str(database_path.resolve())
    with _CONFIGURATION_LOCK_GUARD:
        return _CONFIGURATION_LOCKS.setdefault(key, threading.Lock())
