"""Repository Layer (ADR-001, Рек.8) — бізнес-логіка не знає, де фізично зберігаються дані."""

from .base import Repository
from .migrations import (
    APPLICATION_SCHEMA_CEILING,
    APPLICATION_SCHEMA_FLOOR,
    MigrationError,
    MigrationRunner,
    NewerSchemaError,
    SchemaCompatibility,
    SchemaCompatibilityError,
)
from .sqlite_backup import (
    SQLiteBackupError,
    SQLiteIntegrityError,
    SQLiteSnapshotResult,
    SQLiteVerification,
    create_online_backup,
    restore_sqlite_snapshot,
    verify_sqlite_database,
)
from .sqlite_connection import (
    SQLiteBusyError,
    SQLiteCheckpointResult,
    SQLiteConnectionFactory,
    SQLiteConnectionPolicy,
    SQLiteConnectionSettings,
    SQLiteLifecycleError,
    checkpoint_wal,
    inspect_connection_settings,
)
from .sqlite_evidence_map_source import SQLiteEvidenceMapSourcePorts
from .sqlite_evidence import SQLiteEvidenceRepository
from .sqlite_intake import SQLiteIntakeRepository
from .sqlite_repository import SQLiteRepository
from .sqlite_storage import SQLiteManagedFileRepository
from .sqlite_uow import SQLiteUnitOfWork, SQLiteUnitOfWorkFactory
from .sqlite_workspace import SQLiteWorkspaceRepository

__all__ = [
    "APPLICATION_SCHEMA_CEILING",
    "APPLICATION_SCHEMA_FLOOR",
    "MigrationError",
    "MigrationRunner",
    "NewerSchemaError",
    "Repository",
    "SQLiteBackupError",
    "SQLiteBusyError",
    "SQLiteCheckpointResult",
    "SQLiteConnectionFactory",
    "SQLiteConnectionPolicy",
    "SQLiteConnectionSettings",
    "SQLiteIntegrityError",
    "SQLiteEvidenceRepository",
    "SQLiteEvidenceMapSourcePorts",
    "SQLiteIntakeRepository",
    "SQLiteLifecycleError",
    "SQLiteManagedFileRepository",
    "SQLiteRepository",
    "SQLiteSnapshotResult",
    "SQLiteUnitOfWork",
    "SQLiteUnitOfWorkFactory",
    "SQLiteVerification",
    "SQLiteWorkspaceRepository",
    "SchemaCompatibility",
    "SchemaCompatibilityError",
    "checkpoint_wal",
    "create_online_backup",
    "inspect_connection_settings",
    "restore_sqlite_snapshot",
    "verify_sqlite_database",
]
