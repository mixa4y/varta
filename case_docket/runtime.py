from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from case_docket.application import (
    IntakeService,
    OriginalStorageService,
    SystemClock,
    UuidProvider,
)
from case_docket.intake import FilesystemIntakeSource
from case_docket.repository import SQLiteUnitOfWorkFactory
from case_docket.storage import ManagedFilesystem


@dataclass(frozen=True, slots=True)
class IntakeRuntime:
    database_path: Path
    unit_of_work_factory: SQLiteUnitOfWorkFactory
    filesystem: ManagedFilesystem
    original_storage_service: OriginalStorageService
    intake_service: IntakeService


class WorkspaceDatabaseConflictError(RuntimeError):
    """Both legacy and target DBs exist, so C06 cannot choose authority silently."""


def build_intake_runtime(workspace_root: Path) -> IntakeRuntime:
    """Compose C06 adapters while preserving an existing legacy DB path in place."""

    workspace = workspace_root.resolve()
    filesystem = ManagedFilesystem(workspace)
    target_database = filesystem.layout.zone("database") / "varta.sqlite3"
    legacy_database = workspace / ".caseflow" / "varta.sqlite3"
    if legacy_database.exists() and target_database.exists():
        raise WorkspaceDatabaseConflictError(
            "Legacy і target SQLite одночасно існують; потрібен C09/C15 reconciliation gate"
        )
    database_path = legacy_database if legacy_database.exists() else target_database
    factory = SQLiteUnitOfWorkFactory(database_path)
    ids = UuidProvider()
    clock = SystemClock()
    originals = OriginalStorageService(factory, filesystem, ids, clock)
    source = FilesystemIntakeSource(filesystem.layout.zone("temp") / "intake")
    intake = IntakeService(factory, originals, source, ids, clock)
    return IntakeRuntime(
        database_path=database_path,
        unit_of_work_factory=factory,
        filesystem=filesystem,
        original_storage_service=originals,
        intake_service=intake,
    )
