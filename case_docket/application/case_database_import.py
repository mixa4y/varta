from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

from .case_database_import_ports import (
    CaseDatabaseSourcePort,
    CaseDatabaseImportReportRecord,
    CaseDatabaseSourceSnapshot,
    Clock,
    CorpusImportPort,
    CorpusInventoryPort,
    ImportReconciliationRepositoryPort,
    ImportRunRepositoryPort,
)
from .errors import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class PlanCaseDatabaseImportCommand:
    mapping_version: str


@dataclass(frozen=True, slots=True)
class ExecuteCaseDatabaseImportCommand:
    import_run_id: str
    expected_snapshot_sha256: str
    expected_corpus_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class ResumeCaseDatabaseImportCommand:
    import_run_id: str


@dataclass(frozen=True, slots=True)
class FinalizeCaseDatabaseImportCommand:
    import_run_id: str


@dataclass(frozen=True, slots=True)
class GetCaseDatabaseImportReportQuery:
    import_run_id: str


@dataclass(frozen=True, slots=True)
class RecordCaseDatabaseVerificationCommand:
    import_run_id: str
    verification_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class CaseDatabaseImportPlanDTO:
    import_run_id: str
    idempotency_key: str
    schema_sha256: str
    snapshot_sha256: str
    corpus_manifest_sha256: str
    table_counts: Mapping[str, int]
    corpus_discovered: int
    corpus_unreadable: int
    replayed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "importRunId": self.import_run_id,
            "idempotencyKey": self.idempotency_key,
            "schemaSha256": self.schema_sha256,
            "snapshotSha256": self.snapshot_sha256,
            "corpusManifestSha256": self.corpus_manifest_sha256,
            "tableCounts": dict(self.table_counts),
            "corpusDiscovered": self.corpus_discovered,
            "corpusUnreadable": self.corpus_unreadable,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class CaseDatabaseImportReportDTO:
    import_run_id: str
    status: str
    schema_sha256: str
    snapshot_sha256: str
    corpus_manifest_sha256: str | None
    entity_counts: Mapping[str, int]
    files: Mapping[str, int]
    links: Mapping[str, int]
    attachments: Mapping[str, int]
    profiles: Mapping[str, int]
    issues: Mapping[str, int]
    restart_verified: bool
    backup_verified: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "importRunId": self.import_run_id,
            "status": self.status,
            "schemaSha256": self.schema_sha256,
            "snapshotSha256": self.snapshot_sha256,
            "corpusManifestSha256": self.corpus_manifest_sha256,
            "entityCounts": dict(self.entity_counts),
            "files": dict(self.files),
            "links": dict(self.links),
            "attachments": dict(self.attachments),
            "profiles": dict(self.profiles),
            "issues": dict(self.issues),
            "restartVerified": self.restart_verified,
            "backupVerified": self.backup_verified,
        }


class CaseDatabaseImportService:
    """Local case/corpus import coordinator; SQLite owns all writes."""

    def __init__(
        self,
        snapshot_source: CaseDatabaseSourcePort,
        corpus_inventory: CorpusInventoryPort,
        corpus_import: CorpusImportPort,
        import_runs: ImportRunRepositoryPort,
        reconciliation: ImportReconciliationRepositoryPort,
        clock: Clock,
    ):
        self._snapshot_source = snapshot_source
        self._corpus_inventory = corpus_inventory
        self._corpus_import = corpus_import
        self._import_runs = import_runs
        self._reconciliation = reconciliation
        self._clock = clock

    def plan(self, command: PlanCaseDatabaseImportCommand) -> CaseDatabaseImportPlanDTO:
        mapping_version = self._required(command.mapping_version, "mapping_version")
        snapshot = self._snapshot_source.capture()
        corpus = self._corpus_inventory.inventory()
        if corpus.unreadable:
            raise ValidationError(
                "Corpus inventory містить unreadable entries",
                {"unreadable": corpus.unreadable},
            )
        plan = self._import_runs.plan(
            snapshot,
            corpus,
            mapping_version=mapping_version,
            occurred_at=self._clock.now(),
        )
        return CaseDatabaseImportPlanDTO(
            import_run_id=plan.import_run_id,
            idempotency_key=plan.idempotency_key,
            schema_sha256=snapshot.schema_sha256,
            snapshot_sha256=snapshot.snapshot_sha256,
            corpus_manifest_sha256=corpus.manifest_sha256,
            table_counts=dict(snapshot.table_counts),
            corpus_discovered=corpus.discovered,
            corpus_unreadable=corpus.unreadable,
            replayed=plan.replayed,
        )

    def execute(self, command: ExecuteCaseDatabaseImportCommand) -> CaseDatabaseImportReportDTO:
        import_run_id = self._required(command.import_run_id, "import_run_id")
        snapshot = self._snapshot_source.load()
        if not _constant_hash_equal(snapshot.snapshot_sha256, command.expected_snapshot_sha256):
            raise ConflictError("Snapshot hash не збігається з dry-run plan")
        report = self._import_runs.get_report(import_run_id)
        if report is None:
            raise NotFoundError("Import run не знайдено", {"resource": "airtable_import_run"})
        if not _constant_hash_equal(
            report.corpus_manifest_sha256 or "", command.expected_corpus_manifest_sha256
        ):
            raise ConflictError("Corpus manifest hash не збігається з dry-run plan")
        return self._execute_remaining(import_run_id, snapshot, report.corpus_manifest_sha256 or "")

    def _execute_remaining(
        self,
        import_run_id: str,
        snapshot: CaseDatabaseSourceSnapshot,
        expected_corpus_manifest_sha256: str,
    ) -> CaseDatabaseImportReportDTO:
        current_corpus = self._corpus_inventory.inventory()
        if current_corpus.unreadable:
            raise ConflictError("Corpus став unreadable після dry-run plan")
        if not _constant_hash_equal(
            current_corpus.manifest_sha256, expected_corpus_manifest_sha256
        ):
            raise ConflictError("Corpus змінився після dry-run plan")
        self._import_runs.execute(import_run_id, snapshot, occurred_at=self._clock.now())
        corpus_result = self._corpus_import.import_corpus(f"r05-corpus:{import_run_id}")
        after_import = self._corpus_inventory.inventory()
        if after_import != current_corpus:
            raise ConflictError("Corpus originals змінилися під час import")
        self._import_runs.record_corpus_result(
            import_run_id, corpus_result, occurred_at=self._clock.now()
        )
        return self._report(
            self._import_runs.reconcile_attachments(import_run_id, occurred_at=self._clock.now())
        )

    def resume(self, command: ResumeCaseDatabaseImportCommand) -> CaseDatabaseImportReportDTO:
        import_run_id = self._required(command.import_run_id, "import_run_id")
        snapshot = self._snapshot_source.load()
        report = self._import_runs.get_report(import_run_id)
        if report is None:
            raise NotFoundError("Import run не знайдено", {"resource": "airtable_import_run"})
        if not _constant_hash_equal(report.snapshot_sha256, snapshot.snapshot_sha256):
            raise ConflictError("Resume snapshot не відповідає planned snapshot")
        return self._execute_remaining(
            import_run_id,
            snapshot,
            report.corpus_manifest_sha256 or "",
        )

    def record_verification(
        self, command: RecordCaseDatabaseVerificationCommand
    ) -> CaseDatabaseImportReportDTO:
        import_run_id = self._required(command.import_run_id, "import_run_id")
        self._import_runs.record_verification(
            import_run_id,
            verification_evidence_sha256=self._required(
                command.verification_evidence_sha256,
                "verification_evidence_sha256",
            ),
            occurred_at=self._clock.now(),
        )
        return self.get_report(GetCaseDatabaseImportReportQuery(import_run_id))

    def finalize(self, command: FinalizeCaseDatabaseImportCommand) -> CaseDatabaseImportReportDTO:
        import_run_id = self._required(command.import_run_id, "import_run_id")
        issue_counts = self._reconciliation.open_issue_counts(import_run_id)
        if int(issue_counts.get("critical", 0)) != 0:
            raise ConflictError("Cutover заблоковано відкритими critical issues")
        return self._report(
            self._import_runs.finalize(import_run_id, occurred_at=self._clock.now())
        )

    def get_report(self, query: GetCaseDatabaseImportReportQuery) -> CaseDatabaseImportReportDTO:
        import_run_id = self._required(query.import_run_id, "import_run_id")
        report = self._import_runs.get_report(import_run_id)
        if report is None:
            raise NotFoundError("Import run не знайдено", {"resource": "airtable_import_run"})
        return self._report(report)

    @staticmethod
    def _report(record: CaseDatabaseImportReportRecord) -> CaseDatabaseImportReportDTO:
        return CaseDatabaseImportReportDTO(
            import_run_id=record.import_run_id,
            status=record.status,
            schema_sha256=record.schema_sha256,
            snapshot_sha256=record.snapshot_sha256,
            corpus_manifest_sha256=record.corpus_manifest_sha256,
            entity_counts=dict(record.entity_counts),
            files={
                "accepted": record.files_accepted,
                "duplicate": record.files_duplicate,
                "failed": record.files_failed,
                "skipped": record.files_skipped,
            },
            links={"resolved": record.links_resolved, "unresolved": record.links_unresolved},
            attachments={
                "matched": record.attachments_matched,
                "unmatched": record.attachments_unmatched,
            },
            profiles={
                "draft": record.profiles_draft,
                "active": record.profiles_active,
                "rejected": record.profiles_rejected,
            },
            issues={
                "critical": record.critical_issues,
                "warning": record.warning_issues,
                "info": record.info_issues,
            },
            restart_verified=record.restart_verified,
            backup_verified=record.backup_verified,
        )

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValidationError(f"{field} є обов'язковим", {"field": field})
        return normalized


def _constant_hash_equal(first: str, second: str) -> bool:
    if len(first) != 64 or len(second) != 64:
        return False
    return hashlib.sha256(first.encode()).digest() == hashlib.sha256(second.encode()).digest()
