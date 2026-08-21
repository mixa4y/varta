from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ContextManager, Mapping, Protocol, Self

from case_docket.models.contact import CaseParticipant, Contact

from .dto import ContactContextDTO, ContactDTO


class ContactRepositoryPort(Protocol):
    def add(self, contact: Contact) -> None: ...

    def get(self, contact_id: str) -> ContactDTO | None: ...

    def list(self, search: str | None = None) -> tuple[ContactDTO, ...]: ...

    def update(self, contact: Contact) -> None: ...

    def context(self) -> ContactContextDTO: ...

    def add_role(self, participant: CaseParticipant, occurred_at: datetime) -> None: ...


class UnitOfWork(Protocol):
    @property
    def contacts(self) -> ContactRepositoryPort: ...

    @property
    def files(self) -> ManagedFileRepositoryPort: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, *, write: bool = False) -> UnitOfWork: ...


@dataclass(frozen=True, slots=True)
class StoredObject:
    file_id: str
    storage_key: str
    storage_reference: str
    bytes: int
    sha256: str
    readonly: bool


@dataclass(frozen=True, slots=True)
class StagedOriginal:
    file_id: str
    layout_version: int
    storage_key: str
    storage_reference: str
    staging_reference: str
    original_name: str
    managed_name: str | None
    source_relative_path: str
    kind: str
    bytes: int
    sha256: str
    source_created_ns: int | None
    source_modified_ns: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StorageInspection:
    status: str
    actual_bytes: int | None
    actual_sha256: str | None
    readonly: bool | None


@dataclass(frozen=True, slots=True)
class StorageScanIssue:
    kind: str
    relative_reference: str
    detail: str


@dataclass(frozen=True, slots=True)
class StorageScan:
    pending: tuple[StagedOriginal, ...]
    finalized_file_ids: tuple[str, ...]
    issues: tuple[StorageScanIssue, ...]


class StoragePort(Protocol):
    """Managed original byte boundary implemented by the C05 filesystem adapter."""

    def prepare(
        self,
        *,
        file_id: str,
        source_root: Path,
        source_relative_path: str,
        provenance_relative_path: str | None,
        managed_name: str | None,
        kind: str,
        created_at: datetime,
    ) -> StagedOriginal: ...

    def finalize(self, staged: StagedOriginal) -> StoredObject: ...

    def inspect(
        self,
        storage_reference: str,
        *,
        expected_bytes: int,
        expected_sha256: str,
    ) -> StorageInspection: ...

    def scan(self) -> StorageScan: ...

    def complete(self, staged: StagedOriginal) -> bool: ...


@dataclass(frozen=True, slots=True)
class ManagedFileRecord:
    file_id: str
    layout_version: int
    storage_key: str
    storage_reference: str
    staging_reference: str
    original_name: str
    managed_name: str | None
    source_relative_path: str
    kind: str
    bytes: int
    sha256: str
    source_created_ns: int | None
    source_modified_ns: int
    state: str
    integrity_status: str
    created_at: datetime
    updated_at: datetime
    last_error: str | None = None


class ManagedFileRepositoryPort(Protocol):
    def add(self, record: ManagedFileRecord) -> None: ...

    def get(self, file_id: str) -> ManagedFileRecord | None: ...

    def list(self) -> tuple[ManagedFileRecord, ...]: ...

    def find_by_sha256(self, sha256: str) -> tuple[str, ...]: ...

    def update_state(
        self,
        file_id: str,
        *,
        state: str,
        integrity_status: str,
        occurred_at: datetime,
        last_error: str | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class IntakeContextRecord:
    context_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ImportBatchRecord:
    batch_id: str
    context_id: str
    idempotency_key: str
    request_fingerprint: str
    source_uri: str
    requested_kind: str
    detected_kind: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True, slots=True)
class IntakeEntryRecord:
    entry_id: str
    batch_id: str
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
    duplicate_of_file_ids: tuple[str, ...]
    warning_code: str | None
    warning_message: str | None
    error_code: str | None
    error_message: str | None
    sha256: str | None
    storage_reference: str | None
    created_at: datetime
    updated_at: datetime


class IntakeRepositoryPort(Protocol):
    def create_batch(
        self,
        context: IntakeContextRecord,
        batch: ImportBatchRecord,
    ) -> None: ...

    def get_batch(self, batch_id: str) -> ImportBatchRecord | None: ...

    def get_batch_by_idempotency_key(self, key: str) -> ImportBatchRecord | None: ...

    def list_batches(self) -> tuple[ImportBatchRecord, ...]: ...

    def set_detected_kind(
        self,
        batch_id: str,
        *,
        detected_kind: str,
        occurred_at: datetime,
    ) -> None: ...

    def set_batch_status(
        self,
        batch_id: str,
        *,
        status: str,
        occurred_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    def add_entry(self, entry: IntakeEntryRecord) -> None: ...

    def transition_entry(
        self,
        entry_id: str,
        *,
        status: str,
        occurred_at: datetime,
        file_id: str | None = None,
        duplicate_of_file_ids: tuple[str, ...] = (),
        warning_code: str | None = None,
        warning_message: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    def list_entries(self, batch_id: str) -> tuple[IntakeEntryRecord, ...]: ...


class IntakeUnitOfWork(Protocol):
    @property
    def intake(self) -> IntakeRepositoryPort: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class IntakeUnitOfWorkFactory(Protocol):
    def __call__(self, *, write: bool = False) -> IntakeUnitOfWork: ...


@dataclass(frozen=True, slots=True)
class IntakeSourceEntry:
    ordinal: int
    source_uri: str
    source_relative_path: str
    literal_name: str
    entry_kind: str
    size_bytes: int | None
    source_created_at: str | None
    source_modified_at: str | None
    extension: str | None
    media_type: str | None
    type_hint: str | None
    terminal_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    materialization_token: object | None = None


@dataclass(frozen=True, slots=True)
class IntakeSourceDiscovery:
    detected_kind: str | None
    entries: tuple[IntakeSourceEntry, ...]
    error_code: str | None = None
    error_message: str | None = None
    verification_token: object | None = None


@dataclass(frozen=True, slots=True)
class MaterializedIntakeEntry:
    source_root: Path
    source_relative_path: str
    provenance_relative_path: str


class IntakeSourcePort(Protocol):
    def discover(self, source: Path, source_uri: str) -> IntakeSourceDiscovery: ...

    def materialize(
        self,
        entry: IntakeSourceEntry,
    ) -> ContextManager[MaterializedIntakeEntry]: ...

    def source_is_unchanged(self, discovery: IntakeSourceDiscovery) -> bool: ...


@dataclass(frozen=True, slots=True)
class JobRequest:
    contract_version: int
    kind: str
    input_ids: tuple[str, ...]
    parameters: Mapping[str, object]


class JobPort(Protocol):
    """Durable/isolated job boundary; lifecycle implementation belongs to C10."""

    def submit(self, request: JobRequest) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdProvider(Protocol):
    def new_id(self) -> str: ...
