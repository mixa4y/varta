"""Application services and inward-facing contracts for VARTA."""

from .commands import AssignContactRoleCommand, CreateContactCommand, UpdateContactCommand
from .contacts import ContactService
from .dto import ContactContextDTO, ContactDTO, ContactRoleDTO
from .errors import ApplicationError, ConflictError, NotFoundError, ValidationError
from .ports import (
    Clock,
    ContactRepositoryPort,
    IdProvider,
    JobPort,
    JobRequest,
    StoragePort,
    StoredObject,
    UnitOfWork,
    UnitOfWorkFactory,
)
from .providers import SystemClock, UuidProvider
from .queries import GetContactQuery, GetContactsContextQuery, ListContactsQuery

__all__ = [
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
    "NotFoundError",
    "StoragePort",
    "StoredObject",
    "SystemClock",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "UpdateContactCommand",
    "UuidProvider",
    "ValidationError",
]
