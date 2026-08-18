from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import StorageIntegrityError, ValidationError
from .ports import (
    Clock,
    IdProvider,
    ManagedFileRecord,
    StagedOriginal,
    StorageInspection,
    StoragePort,
    UnitOfWorkFactory,
)


_FILE_KINDS = frozenset(
    {
        "content",
        "attachment",
        "signature",
        "ocr_text",
        "transcript",
        "metadata_snapshot",
        "derived",
        "unknown",
    }
)


@dataclass(frozen=True, slots=True)
class AcceptOriginalCommand:
    source_root: Path
    source_relative_path: str
    managed_name: str | None = None
    kind: str = "unknown"


@dataclass(frozen=True, slots=True)
class AcceptedOriginal:
    file_id: str
    original_name: str
    managed_name: str | None
    source_relative_path: str
    storage_reference: str
    bytes: int
    sha256: str
    duplicate_of_file_ids: tuple[str, ...]
    cleanup_pending: bool


@dataclass(frozen=True, slots=True)
class ReconciliationItem:
    file_id: str | None
    status: str
    action: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    items: tuple[ReconciliationItem, ...]

    @property
    def recovered(self) -> int:
        return sum(item.action == "recovered" for item in self.items)

    @property
    def failures(self) -> int:
        return sum(item.status in {"mismatch", "reference_unavailable", "error"} for item in self.items)


class OriginalStorageService:
    """Coordinates short DB transactions with staged filesystem finalization."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        storage: StoragePort,
        ids: IdProvider,
        clock: Clock,
    ):
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._ids = ids
        self._clock = clock

    def accept(self, command: AcceptOriginalCommand) -> AcceptedOriginal:
        self._validate_command(command)
        file_id = self._ids.new_id()
        created_at = self._clock.now()
        staged = self._storage.prepare(
            file_id=file_id,
            source_root=command.source_root,
            source_relative_path=command.source_relative_path,
            managed_name=command.managed_name,
            kind=command.kind,
            created_at=created_at,
        )
        record = self._record_from_staged(staged)

        with self._unit_of_work_factory(write=True) as unit_of_work:
            duplicate_ids = unit_of_work.files.find_by_sha256(staged.sha256)
            unit_of_work.files.add(record)
            unit_of_work.commit()

        self._storage.finalize(staged)
        inspection = self._storage.inspect(
            staged.storage_reference,
            expected_bytes=staged.bytes,
            expected_sha256=staged.sha256,
        )
        self._persist_inspection(file_id, inspection)
        if inspection.status != "verified":
            raise StorageIntegrityError(
                "Managed original не пройшов перевірку після finalize",
                {"file_id": file_id, "status": inspection.status},
            )

        cleanup_pending = not self._storage.complete(staged)
        return AcceptedOriginal(
            file_id=file_id,
            original_name=staged.original_name,
            managed_name=staged.managed_name,
            source_relative_path=staged.source_relative_path,
            storage_reference=staged.storage_reference,
            bytes=staged.bytes,
            sha256=staged.sha256,
            duplicate_of_file_ids=duplicate_ids,
            cleanup_pending=cleanup_pending,
        )

    def reconcile(self) -> ReconciliationReport:
        scan = self._storage.scan()
        items = [
            ReconciliationItem(None, "error", issue.kind, issue.detail)
            for issue in scan.issues
        ]
        known = self._records_by_id()
        processed: set[str] = set()

        for staged in scan.pending:
            processed.add(staged.file_id)
            record = known.get(staged.file_id)
            recovered = False
            if record is None:
                record = self._record_from_staged(staged)
                with self._unit_of_work_factory(write=True) as unit_of_work:
                    unit_of_work.files.add(record)
                    unit_of_work.commit()
                known[staged.file_id] = record
                recovered = True

            try:
                self._storage.finalize(staged)
                inspection = self._storage.inspect(
                    staged.storage_reference,
                    expected_bytes=staged.bytes,
                    expected_sha256=staged.sha256,
                )
                self._persist_inspection(staged.file_id, inspection)
                if inspection.status == "verified":
                    self._storage.complete(staged)
                items.append(
                    ReconciliationItem(
                        staged.file_id,
                        inspection.status,
                        "recovered" if recovered else "reconciled",
                        "Pending operation звірено з SQLite і managed bytes",
                    )
                )
            except Exception as exc:
                self._persist_state(
                    staged.file_id,
                    state="error",
                    integrity_status="error",
                    last_error=type(exc).__name__,
                )
                items.append(
                    ReconciliationItem(
                        staged.file_id,
                        "error",
                        "reconciliation_failed",
                        f"Finalize/verification завершився помилкою {type(exc).__name__}",
                    )
                )

        for file_id, record in known.items():
            if file_id in processed:
                continue
            inspection = self._storage.inspect(
                record.storage_reference,
                expected_bytes=record.bytes,
                expected_sha256=record.sha256,
            )
            self._persist_inspection(file_id, inspection)
            items.append(
                ReconciliationItem(
                    file_id,
                    inspection.status,
                    "verified" if inspection.status == "verified" else "integrity_failure",
                    "SQLite reference звірено з managed object",
                )
            )

        known_ids = set(known)
        pending_ids = {staged.file_id for staged in scan.pending}
        for file_id in scan.finalized_file_ids:
            if file_id in known_ids or file_id in pending_ids:
                continue
            items.append(
                ReconciliationItem(
                    file_id,
                    "error",
                    "orphan_finalized_object",
                    "Finalized bytes не прийнято без provenance manifest або SQLite record",
                )
            )

        return ReconciliationReport(tuple(items))

    def _records_by_id(self) -> dict[str, ManagedFileRecord]:
        with self._unit_of_work_factory() as unit_of_work:
            return {record.file_id: record for record in unit_of_work.files.list()}

    def _persist_inspection(self, file_id: str, inspection: StorageInspection) -> None:
        state = {
            "verified": "verified",
            "mismatch": "mismatch",
            "reference_unavailable": "reference_unavailable",
        }.get(inspection.status, "error")
        self._persist_state(
            file_id,
            state=state,
            integrity_status=state,
            last_error=None if state == "verified" else inspection.status,
        )

    def _persist_state(
        self,
        file_id: str,
        *,
        state: str,
        integrity_status: str,
        last_error: str | None,
    ) -> None:
        with self._unit_of_work_factory(write=True) as unit_of_work:
            unit_of_work.files.update_state(
                file_id,
                state=state,
                integrity_status=integrity_status,
                occurred_at=self._clock.now(),
                last_error=last_error,
            )
            unit_of_work.commit()

    @staticmethod
    def _record_from_staged(staged: StagedOriginal) -> ManagedFileRecord:
        return ManagedFileRecord(
            file_id=staged.file_id,
            layout_version=staged.layout_version,
            storage_key=staged.storage_key,
            storage_reference=staged.storage_reference,
            staging_reference=staged.staging_reference,
            original_name=staged.original_name,
            managed_name=staged.managed_name,
            source_relative_path=staged.source_relative_path,
            kind=staged.kind,
            bytes=staged.bytes,
            sha256=staged.sha256,
            source_created_ns=staged.source_created_ns,
            source_modified_ns=staged.source_modified_ns,
            state="prepared",
            integrity_status="not_checked",
            created_at=staged.created_at,
            updated_at=staged.created_at,
        )

    @staticmethod
    def _validate_command(command: AcceptOriginalCommand) -> None:
        if command.kind not in _FILE_KINDS:
            raise ValidationError("Непідтримуваний kind файла", {"kind": command.kind})
        if command.managed_name is not None and not command.managed_name.strip():
            raise ValidationError("Managed name не може бути порожнім")
