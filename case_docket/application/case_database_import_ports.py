from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class CaseDatabaseSourceSnapshot:
    source_identity_sha256: str
    schema_sha256: str
    snapshot_sha256: str
    captured_start: str
    captured_end: str
    table_counts: Mapping[str, int]
    payload: Mapping[str, object]
    selected_case_record_id: str

    @property
    def record_count(self) -> int:
        return sum(self.table_counts.values())


@dataclass(frozen=True, slots=True)
class CorpusInventoryEntry:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CorpusInventorySummary:
    manifest_sha256: str
    discovered: int
    files: int
    directories: int
    unreadable: int
    entries: tuple[CorpusInventoryEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class CorpusImportResult:
    accepted: int
    duplicate: int
    failed: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ImportRunPlanRecord:
    import_run_id: str
    idempotency_key: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class CaseDatabaseImportReportRecord:
    import_run_id: str
    status: str
    schema_sha256: str
    snapshot_sha256: str
    corpus_manifest_sha256: str | None
    entity_counts: Mapping[str, int]
    files_accepted: int
    files_duplicate: int
    files_failed: int
    files_skipped: int
    links_resolved: int
    links_unresolved: int
    attachments_matched: int
    attachments_unmatched: int
    profiles_draft: int
    profiles_active: int
    profiles_rejected: int
    critical_issues: int
    warning_issues: int
    info_issues: int
    restart_verified: bool
    backup_verified: bool


class CaseDatabaseSourcePort(Protocol):
    def capture(self) -> CaseDatabaseSourceSnapshot: ...

    def load(self) -> CaseDatabaseSourceSnapshot: ...


class CorpusInventoryPort(Protocol):
    def inventory(self) -> CorpusInventorySummary: ...


class CorpusImportPort(Protocol):
    def import_corpus(self, idempotency_key: str) -> CorpusImportResult: ...


class ImportRunRepositoryPort(Protocol):
    def plan(
        self,
        snapshot: CaseDatabaseSourceSnapshot,
        corpus: CorpusInventorySummary,
        *,
        mapping_version: str,
        occurred_at: datetime,
    ) -> ImportRunPlanRecord: ...

    def execute(
        self,
        import_run_id: str,
        snapshot: CaseDatabaseSourceSnapshot,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord: ...

    def resume(
        self,
        import_run_id: str,
        snapshot: CaseDatabaseSourceSnapshot,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord: ...

    def finalize(
        self,
        import_run_id: str,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord: ...

    def get_report(self, import_run_id: str) -> CaseDatabaseImportReportRecord | None: ...

    def record_verification(
        self,
        import_run_id: str,
        *,
        verification_evidence_sha256: str,
        occurred_at: datetime,
    ) -> None: ...

    def record_corpus_result(
        self,
        import_run_id: str,
        result: CorpusImportResult,
        *,
        occurred_at: datetime,
    ) -> None: ...

    def reconcile_attachments(
        self,
        import_run_id: str,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord: ...


class ImportReconciliationRepositoryPort(Protocol):
    def open_issue_counts(self, import_run_id: str) -> Mapping[str, int]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
