from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Protocol, Self

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
