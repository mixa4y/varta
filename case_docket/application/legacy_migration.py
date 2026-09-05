"""Application boundary for controlled read-only legacy migration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar


ReportT = TypeVar("ReportT")
ReportT_co = TypeVar("ReportT_co", covariant=True)


@dataclass(frozen=True, slots=True)
class LegacyDryRunCommand:
    source: Path
    source_key: str | None = None


@dataclass(frozen=True, slots=True)
class LegacyImportCommand:
    source: Path
    backup_destination: Path
    actor: str = "system:legacy-import"
    source_key: str | None = None


class LegacyMigrationAdapterPort(Protocol[ReportT_co]):
    def dry_run(self, command: LegacyDryRunCommand) -> ReportT_co: ...

    def import_snapshot(self, command: LegacyImportCommand) -> ReportT_co: ...


@dataclass(frozen=True, slots=True)
class LegacyMigrationService(Generic[ReportT]):
    """Use-case service; adapters own source parsing and SQLite persistence."""

    adapter: LegacyMigrationAdapterPort[ReportT]

    def preview(self, command: LegacyDryRunCommand) -> ReportT:
        return self.adapter.dry_run(command)

    def migrate(self, command: LegacyImportCommand) -> ReportT:
        return self.adapter.import_snapshot(command)
