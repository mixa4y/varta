"""Application services and inward-facing contracts for VARTA."""

from .commands import AssignContactRoleCommand, CreateContactCommand, UpdateContactCommand
from .contacts import ContactService
from .dto import ContactContextDTO, ContactDTO, ContactRoleDTO
from .errors import (
    ApplicationError,
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from .originals import (
    AcceptOriginalCommand,
    AcceptedOriginal,
    OriginalStorageService,
    ReconciliationItem,
    ReconciliationReport,
)
from .ports import (
    Clock,
    ContactRepositoryPort,
    IdProvider,
    JobPort,
    JobRequest,
    ManagedFileRecord,
    ManagedFileRepositoryPort,
    StagedOriginal,
    StorageInspection,
    StoragePort,
    StorageScan,
    StorageScanIssue,
    StoredObject,
    UnitOfWork,
    UnitOfWorkFactory,
)
from .providers import SystemClock, UuidProvider
from .queries import GetContactQuery, GetContactsContextQuery, ListContactsQuery

__all__ = [
    "AcceptOriginalCommand",
    "AcceptedOriginal",
    "ApplicationError",
    "AssignContactRoleCommand",
    "Clock",
    "ConflictError",
    "ContactContextDTO",
    "ContactDTO",
    "ContactRepositoryPort",
    "ContactRoleDTO",
    "ContactService",
    "CreateContactCommand",
    "GetContactQuery",
    "GetContactsContextQuery",
    "IdProvider",
    "JobPort",
    "JobRequest",
    "ListContactsQuery",
    "ManagedFileRecord",
    "ManagedFileRepositoryPort",
    "NotFoundError",
    "OriginalStorageService",
    "ReconciliationItem",
    "ReconciliationReport",
    "StagedOriginal",
    "StorageInspection",
    "StorageIntegrityError",
    "StoragePort",
    "StorageScan",
    "StorageScanIssue",
    "StoredObject",
    "SystemClock",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "UpdateContactCommand",
    "UuidProvider",
    "ValidationError",
]
