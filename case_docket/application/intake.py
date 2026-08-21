from __future__ import annotations

import hashlib
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import ConflictError, NotFoundError, ValidationError
from .originals import AcceptOriginalCommand, OriginalStorageService
from .ports import (
    Clock,
    IdProvider,
    ImportBatchRecord,
    IntakeContextRecord,
    IntakeEntryRecord,
    IntakeSourceDiscovery,
    IntakeSourceEntry,
    IntakeSourcePort,
    IntakeUnitOfWorkFactory,
)


_BENIGN_SKIP_CODES = frozenset({"archive_directory"})


@dataclass(frozen=True, slots=True)
class IntakeCommand:
    source: Path
    idempotency_key: str
    source_uri: str | None = None


@dataclass(frozen=True, slots=True)
class ListIntakeInventoryQuery:
    batch_id: str | None = None


@dataclass(frozen=True, slots=True)
class IntakeEntryDTO:
    entry_id: str
    ordinal: int
    source_uri: str
    source_relative_path: str
    literal_name: str
    entry_kind: str
    status: str
    size_bytes: int | None
    source_created_at: str | None
    source_modified_at: str | None
    extension: str | None
    media_type: str | None
    type_hint: str | None
    file_id: str | None
    sha256: str | None
    storage_reference: str | None
    duplicate_of_file_ids: tuple[str, ...]
    warning_code: str | None
    warning_message: str | None
    error_code: str | None
    error_message: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "entryId": self.entry_id,
            "ordinal": self.ordinal,
            "sourceUri": self.source_uri,
            "sourceRelativePath": self.source_relative_path,
            "literalName": self.literal_name,
            "entryKind": self.entry_kind,
            "status": self.status,
            "sizeBytes": self.size_bytes,
            "sourceCreatedAt": self.source_created_at,
            "sourceModifiedAt": self.source_modified_at,
            "extension": self.extension,
            "mediaType": self.media_type,
            "typeHint": self.type_hint,
            "fileId": self.file_id,
            "sha256": self.sha256,
            "storageReference": self.storage_reference,
            "duplicateOfFileIds": list(self.duplicate_of_file_ids),
            "warning": self._message(self.warning_code, self.warning_message),
            "error": self._message(self.error_code, self.error_message),
        }

    @staticmethod
    def _message(code: str | None, message: str | None) -> dict[str, str] | None:
        return {"code": code, "message": message or ""} if code is not None else None


@dataclass(frozen=True, slots=True)
class IntakeBatchDTO:
    batch_id: str
    context_id: str
    idempotency_key: str
    source_uri: str
    requested_kind: str
    detected_kind: str | None
    status: str
    created_at: str
    updated_at: str
    completed_at: str | None
    error_code: str | None
    error_message: str | None
    entries: tuple[IntakeEntryDTO, ...]
    replayed: bool = False

    @property
    def counts(self) -> Mapping[str, int]:
        statuses = ("discovered", "accepted", "duplicate", "failed", "skipped")
        return {
            status: sum(entry.status == status for entry in self.entries)
            for status in statuses
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "batchId": self.batch_id,
            "intakeContextId": self.context_id,
            "idempotencyKey": self.idempotency_key,
            "sourceUri": self.source_uri,
            "requestedKind": self.requested_kind,
            "detectedKind": self.detected_kind,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "completedAt": self.completed_at,
            "error": IntakeEntryDTO._message(self.error_code, self.error_message),
            "counts": dict(self.counts),
            "entries": [entry.to_dict() for entry in self.entries],
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class IntakeInventoryDTO:
    batches: tuple[IntakeBatchDTO, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "authority": "sqlite",
            "count": len(self.batches),
            "batches": [batch.to_dict() for batch in self.batches],
        }


class IntakeService:
    """C06 input -> managed original -> SQLite -> authoritative read-back slice."""

    def __init__(
        self,
        unit_of_work_factory: IntakeUnitOfWorkFactory,
        originals: OriginalStorageService,
        source: IntakeSourcePort,
        ids: IdProvider,
        clock: Clock,
    ):
        self._unit_of_work_factory = unit_of_work_factory
        self._originals = originals
        self._source = source
        self._ids = ids
        self._clock = clock

    def intake(self, command: IntakeCommand) -> IntakeBatchDTO:
        key = self._validate_idempotency_key(command.idempotency_key)
        input_path = Path(os.path.abspath(os.fspath(command.source)))
        source_uri = command.source_uri or input_path.as_uri()
        if not source_uri.strip() or any(ord(character) < 32 for character in source_uri):
            raise ValidationError("Source URI не може бути порожнім або містити control characters")
        fingerprint = self._request_fingerprint(source_uri)

        existing = self._create_or_find_batch(key, fingerprint, source_uri)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ConflictError(
                    "Idempotency key вже використано для іншого intake request",
                    {"resource": "import_batch"},
                )
            return self._batch_dto(existing, replayed=True)

        batch = self._batch_by_idempotency_key(key)
        if batch is None:
            raise RuntimeError("Створений import batch не читається з SQLite")

        try:
            discovery = self._source.discover(input_path, source_uri)
            if discovery.detected_kind is not None:
                self._set_detected_kind(batch.batch_id, discovery.detected_kind)
            persisted = self._persist_discovery(batch.batch_id, discovery)
            if not persisted:
                self._set_batch_status(
                    batch.batch_id,
                    "failed",
                    discovery.error_code or "empty_input",
                    discovery.error_message or "Source input не містить entries",
                )
                return self._require_batch(batch.batch_id)

            self._set_batch_status(batch.batch_id, "processing")
            for source_entry, entry_id in persisted:
                if source_entry.terminal_status is not None:
                    self._transition_entry(
                        entry_id,
                        status=source_entry.terminal_status,
                        error_code=source_entry.error_code or "entry_skipped",
                        error_message=source_entry.error_message or "Entry не прийнято",
                    )
                    continue
                self._accept_entry(source_entry, entry_id)

            if not self._source.source_is_unchanged(discovery):
                self._record_source_changed(batch.batch_id, source_uri, persisted)
            self._finish_batch(
                batch.batch_id,
                preferred_error_code=discovery.error_code,
                preferred_error_message=discovery.error_message,
            )
        except Exception as exc:
            self._record_unexpected_batch_failure(batch.batch_id, exc)
            raise
        return self._require_batch(batch.batch_id)

    def inventory(self, query: ListIntakeInventoryQuery | None = None) -> IntakeInventoryDTO:
        requested = query or ListIntakeInventoryQuery()
        batches: tuple[ImportBatchRecord, ...]
        with self._unit_of_work_factory() as unit_of_work:
            if requested.batch_id is not None:
                batch = unit_of_work.intake.get_batch(requested.batch_id)
                if batch is None:
                    raise NotFoundError(
                        "Import batch не знайдено",
                        {"resource": "import_batch"},
                    )
                batches = (batch,)
            else:
                batches = unit_of_work.intake.list_batches()
            entries = {
                batch.batch_id: unit_of_work.intake.list_entries(batch.batch_id)
                for batch in batches
            }
        return IntakeInventoryDTO(
            tuple(self._to_batch_dto(batch, entries[batch.batch_id]) for batch in batches)
        )

    def _create_or_find_batch(
        self,
        key: str,
        fingerprint: str,
        source_uri: str,
    ) -> ImportBatchRecord | None:
        with self._unit_of_work_factory(write=True) as unit_of_work:
            existing = unit_of_work.intake.get_batch_by_idempotency_key(key)
            if existing is not None:
                return existing
            occurred_at = self._clock.now()
            context_id = self._ids.new_id()
            batch_id = self._ids.new_id()
            context = IntakeContextRecord(
                context_id=context_id,
                status="enumerating",
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            batch = ImportBatchRecord(
                batch_id=batch_id,
                context_id=context_id,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                source_uri=source_uri,
                requested_kind="auto",
                detected_kind=None,
                status="enumerating",
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            unit_of_work.intake.create_batch(context, batch)
            unit_of_work.commit()
        return None

    def _persist_discovery(
        self,
        batch_id: str,
        discovery: IntakeSourceDiscovery,
    ) -> list[tuple[IntakeSourceEntry, str]]:
        persisted: list[tuple[IntakeSourceEntry, str]] = []
        if not discovery.entries:
            return persisted
        with self._unit_of_work_factory(write=True) as unit_of_work:
            for source_entry in discovery.entries:
                entry_id = self._ids.new_id()
                occurred_at = self._clock.now()
                record = IntakeEntryRecord(
                    entry_id=entry_id,
                    batch_id=batch_id,
                    ordinal=source_entry.ordinal,
                    source_uri=source_entry.source_uri,
                    source_relative_path=source_entry.source_relative_path,
                    literal_name=source_entry.literal_name,
                    entry_kind=source_entry.entry_kind,
                    status="discovered",
                    size_bytes=source_entry.size_bytes,
                    source_created_at=source_entry.source_created_at,
                    source_modified_at=source_entry.source_modified_at,
                    extension=source_entry.extension,
                    media_type=source_entry.media_type,
                    type_hint=source_entry.type_hint,
                    file_id=None,
                    duplicate_of_file_ids=(),
                    warning_code=None,
                    warning_message=None,
                    error_code=None,
                    error_message=None,
                    sha256=None,
                    storage_reference=None,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
                unit_of_work.intake.add_entry(record)
                persisted.append((source_entry, entry_id))
            unit_of_work.commit()
        return persisted

    def _accept_entry(self, source_entry: IntakeSourceEntry, entry_id: str) -> None:
        try:
            with self._source.materialize(source_entry) as materialized:
                accepted = self._originals.accept(
                    AcceptOriginalCommand(
                        source_root=materialized.source_root,
                        source_relative_path=materialized.source_relative_path,
                        provenance_relative_path=materialized.provenance_relative_path,
                    )
                )
        except Exception as exc:
            error_code, error_message = self._entry_error(exc)
            self._transition_entry(
                entry_id,
                status="failed",
                error_code=error_code,
                error_message=error_message,
            )
            return

        duplicate_ids = accepted.duplicate_of_file_ids
        self._transition_entry(
            entry_id,
            status="duplicate" if duplicate_ids else "accepted",
            file_id=accepted.file_id,
            duplicate_of_file_ids=duplicate_ids,
            warning_code="storage_cleanup_pending" if accepted.cleanup_pending else None,
            warning_message=(
                "Managed original verified; staging cleanup потребує reconciliation"
                if accepted.cleanup_pending
                else None
            ),
        )

    def _record_source_changed(
        self,
        batch_id: str,
        source_uri: str,
        persisted: list[tuple[IntakeSourceEntry, str]],
    ) -> None:
        ordinal = max((entry.ordinal for entry, _ in persisted), default=-1) + 1
        occurred_at = self._clock.now()
        entry_id = self._ids.new_id()
        record = IntakeEntryRecord(
            entry_id=entry_id,
            batch_id=batch_id,
            ordinal=ordinal,
            source_uri=source_uri,
            source_relative_path="(source)",
            literal_name="(source)",
            entry_kind="special",
            status="discovered",
            size_bytes=None,
            source_created_at=None,
            source_modified_at=None,
            extension=None,
            media_type=None,
            type_hint="source_verification",
            file_id=None,
            duplicate_of_file_ids=(),
            warning_code=None,
            warning_message=None,
            error_code=None,
            error_message=None,
            sha256=None,
            storage_reference=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        with self._unit_of_work_factory(write=True) as unit_of_work:
            unit_of_work.intake.add_entry(record)
            unit_of_work.intake.transition_entry(
                entry_id,
                status="failed",
                occurred_at=self._clock.now(),
                error_code="source_changed_during_intake",
                error_message="Source fingerprint змінився під час intake",
            )
            unit_of_work.commit()

    def _finish_batch(
        self,
        batch_id: str,
        *,
        preferred_error_code: str | None,
        preferred_error_message: str | None,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            entries = unit_of_work.intake.list_entries(batch_id)
        accepted = [entry for entry in entries if entry.status in {"accepted", "duplicate"}]
        hard_problems = [
            entry
            for entry in entries
            if entry.status == "failed"
            or (entry.status == "skipped" and entry.error_code not in _BENIGN_SKIP_CODES)
        ]
        if accepted and not hard_problems:
            self._set_batch_status(batch_id, "succeeded")
            return
        error_code = preferred_error_code or (
            "entry_failures" if accepted else "no_entries_accepted"
        )
        error_message = preferred_error_message or (
            "Частина intake entries не прийнята"
            if accepted
            else "Жоден intake entry не прийнято"
        )
        self._set_batch_status(
            batch_id,
            "partial" if accepted else "failed",
            error_code,
            error_message,
        )

    def _record_unexpected_batch_failure(self, batch_id: str, error: Exception) -> None:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                batch = unit_of_work.intake.get_batch(batch_id)
                entries = unit_of_work.intake.list_entries(batch_id) if batch is not None else ()
            if batch is None or batch.status in {"succeeded", "partial", "failed"}:
                return
            status = "partial" if any(
                entry.status in {"accepted", "duplicate"} for entry in entries
            ) else "failed"
            self._set_batch_status(
                batch_id,
                status,
                "intake_operation_failed",
                f"Intake operation перервана помилкою {type(error).__name__}",
            )
        except Exception:
            return

    def _set_detected_kind(self, batch_id: str, detected_kind: str) -> None:
        with self._unit_of_work_factory(write=True) as unit_of_work:
            unit_of_work.intake.set_detected_kind(
                batch_id,
                detected_kind=detected_kind,
                occurred_at=self._clock.now(),
            )
            unit_of_work.commit()

    def _set_batch_status(
        self,
        batch_id: str,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._unit_of_work_factory(write=True) as unit_of_work:
            unit_of_work.intake.set_batch_status(
                batch_id,
                status=status,
                occurred_at=self._clock.now(),
                error_code=error_code,
                error_message=error_message,
            )
            unit_of_work.commit()

    def _transition_entry(
        self,
        entry_id: str,
        *,
        status: str,
        file_id: str | None = None,
        duplicate_of_file_ids: tuple[str, ...] = (),
        warning_code: str | None = None,
        warning_message: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._unit_of_work_factory(write=True) as unit_of_work:
            unit_of_work.intake.transition_entry(
                entry_id,
                status=status,
                occurred_at=self._clock.now(),
                file_id=file_id,
                duplicate_of_file_ids=duplicate_of_file_ids,
                warning_code=warning_code,
                warning_message=warning_message,
                error_code=error_code,
                error_message=error_message,
            )
            unit_of_work.commit()

    def _batch_by_idempotency_key(self, key: str) -> ImportBatchRecord | None:
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.intake.get_batch_by_idempotency_key(key)

    def _batch_dto(self, batch: ImportBatchRecord, *, replayed: bool) -> IntakeBatchDTO:
        with self._unit_of_work_factory() as unit_of_work:
            entries = unit_of_work.intake.list_entries(batch.batch_id)
        return self._to_batch_dto(batch, entries, replayed=replayed)

    def _require_batch(self, batch_id: str) -> IntakeBatchDTO:
        with self._unit_of_work_factory() as unit_of_work:
            batch = unit_of_work.intake.get_batch(batch_id)
            if batch is None:
                raise RuntimeError("Import batch зник після committed operation")
            entries = unit_of_work.intake.list_entries(batch_id)
        return self._to_batch_dto(batch, entries)

    @staticmethod
    def _to_batch_dto(
        batch: ImportBatchRecord,
        entries: tuple[IntakeEntryRecord, ...],
        *,
        replayed: bool = False,
    ) -> IntakeBatchDTO:
        return IntakeBatchDTO(
            batch_id=batch.batch_id,
            context_id=batch.context_id,
            idempotency_key=batch.idempotency_key,
            source_uri=batch.source_uri,
            requested_kind=batch.requested_kind,
            detected_kind=batch.detected_kind,
            status=batch.status,
            created_at=batch.created_at.isoformat(),
            updated_at=batch.updated_at.isoformat(),
            completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
            error_code=batch.last_error_code,
            error_message=batch.last_error_message,
            entries=tuple(
                IntakeEntryDTO(
                    entry_id=entry.entry_id,
                    ordinal=entry.ordinal,
                    source_uri=entry.source_uri,
                    source_relative_path=entry.source_relative_path,
                    literal_name=entry.literal_name,
                    entry_kind=entry.entry_kind,
                    status=entry.status,
                    size_bytes=entry.size_bytes,
                    source_created_at=entry.source_created_at,
                    source_modified_at=entry.source_modified_at,
                    extension=entry.extension,
                    media_type=entry.media_type,
                    type_hint=entry.type_hint,
                    file_id=entry.file_id,
                    sha256=entry.sha256,
                    storage_reference=entry.storage_reference,
                    duplicate_of_file_ids=entry.duplicate_of_file_ids,
                    warning_code=entry.warning_code,
                    warning_message=entry.warning_message,
                    error_code=entry.error_code,
                    error_message=entry.error_message,
                )
                for entry in entries
            ),
            replayed=replayed,
        )

    @staticmethod
    def _request_fingerprint(source_uri: str) -> str:
        payload = f"varta.intake.v1\0auto\0{source_uri}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValidationError("Idempotency key має бути непорожнім без outer whitespace")
        if len(value) > 200 or any(ord(character) < 32 for character in value):
            raise ValidationError("Idempotency key має непідтримуваний формат")
        return value

    @staticmethod
    def _entry_error(error: Exception) -> tuple[str, str]:
        if isinstance(error, (zipfile.BadZipFile, EOFError, RuntimeError)):
            return "archive_member_read_error", "ZIP member не вдалося прочитати повністю"
        name = type(error).__name__
        if "SourceChanged" in name:
            return "source_changed_during_intake", "Source entry змінився після discovery"
        if "UnsafePath" in name or "Reparse" in name:
            return "unsafe_source_path", "Source entry відхилено path/reparse policy"
        if "Integrity" in name:
            return "storage_integrity_error", "Managed original не пройшов integrity verification"
        if "Collision" in name:
            return "storage_collision", "Managed storage відхилив no-overwrite collision"
        if isinstance(error, OSError) or "StorageIO" in name:
            return "storage_io_error", "Original не вдалося зберегти через I/O failure"
        return "entry_accept_failed", f"Entry intake завершився помилкою {name}"
