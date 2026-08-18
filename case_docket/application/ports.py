from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


@dataclass(frozen=True, slots=True)
class StoredObject:
    storage_key: str
    bytes: int
    sha256: str


class StoragePort(Protocol):
    """Managed-storage metadata boundary; byte ingestion belongs to C05/C06."""

    def describe(self, storage_key: str) -> StoredObject | None: ...


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
