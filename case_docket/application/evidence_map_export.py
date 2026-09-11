from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RecordEvidenceMapExportCommand:
    export_id: str
    case_id: str
    case_profile_id: str
    schema_version: str
    product_version: str
    export_profile: str
    source_revision: str | None
    source_snapshot_sha256: str
    generated_by: str
    generated_at: str
    data_cutoff: str | None = None
    limitations: tuple[str, ...] = ()
    sealed: bool = False
    status: str = "valid"


@dataclass(frozen=True, slots=True)
class EvidenceMapExportAudit:
    export_id: str
    case_id: str
    case_profile_id: str
    schema_version: str
    product_version: str
    export_profile: str
    source_revision: str | None
    source_snapshot_sha256: str
    status: str
    sealed: bool
    generated_by: str
    generated_at: str
    data_cutoff: str | None
    limitations: tuple[str, ...]


class EvidenceMapExportAuditPort(Protocol):
    def record_validated(
        self, command: RecordEvidenceMapExportCommand
    ) -> EvidenceMapExportAudit: ...

    def get(self, export_id: str) -> EvidenceMapExportAudit | None: ...


class EvidenceMapExportAuditError(ValueError):
    pass
