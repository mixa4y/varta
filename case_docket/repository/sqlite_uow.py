from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Self

from case_docket.application.dto import (
    CaseOptionDTO,
    ContactContextDTO,
    ContactDTO,
    ContactRoleDTO,
    ProceedingOptionDTO,
)
from case_docket.application.errors import ConflictError, NotFoundError, ValidationError
from case_docket.application.ports import ContactRepositoryPort, ManagedFileRepositoryPort
from case_docket.models.contact import CaseParticipant, Contact

from .sqlite_connection import SQLiteConnectionPolicy
from .sqlite_repository import SQLiteRepository
from .sqlite_storage import SQLiteManagedFileRepository


class SQLiteContactRepository(ContactRepositoryPort):
    """Typed contacts adapter over the existing SQLite repository."""

    def __init__(self, repository: SQLiteRepository):
        self._repository = repository

    def add(self, contact: Contact) -> None:
        try:
            self._repository.create_contact(contact.to_record())
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc) from exc

    def get(self, contact_id: str) -> ContactDTO | None:
        record = self._repository.get_contact(contact_id)
        return self._contact_dto(record) if record is not None else None

    def list(self, search: str | None = None) -> tuple[ContactDTO, ...]:
        return tuple(self._contact_dto(record) for record in self._repository.list_contacts(search))

    def update(self, contact: Contact) -> None:
        fields = contact.to_record()
        fields.pop("id", None)
        try:
            self._repository.update_contact(contact.id, fields)
        except KeyError as exc:
            raise NotFoundError("Контакт не знайдено", {"resource": "contact"}) from exc
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc) from exc

    def context(self) -> ContactContextDTO:
        context = self._repository.contacts_context()
        cases = tuple(
            CaseOptionDTO(
                id=str(item["id"]),
                case_number=self._optional_string(item.get("case_number")),
                name=self._optional_string(item.get("name")),
            )
            for item in self._mapping_items(context.get("cases"))
        )
        proceedings = tuple(
            ProceedingOptionDTO(
                id=str(item["id"]),
                proceeding_number=self._optional_string(item.get("proceeding_number")),
                name=self._optional_string(item.get("name")),
                case_ids=tuple(str(value) for value in self._sequence(item.get("caseIds"))),
            )
            for item in self._mapping_items(context.get("proceedings"))
        )
        roles = tuple(str(value) for value in self._sequence(context.get("roles")))
        return ContactContextDTO(cases=cases, proceedings=proceedings, roles=roles)

    def add_role(self, participant: CaseParticipant, occurred_at: datetime) -> None:
        record: dict[str, object] = {
            "id": participant.id,
            "contact_id": participant.contact_id,
            "case_id": participant.case_id,
            "proceeding_id": participant.proceeding_id,
            "role": participant.role,
            "active": participant.active,
            "notes": participant.notes,
            "created_at": occurred_at.isoformat(),
        }
        try:
            self._repository.assign_contact_role(record)
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc) from exc

    @classmethod
    def _contact_dto(cls, record: Mapping[str, Any]) -> ContactDTO:
        roles = tuple(
            ContactRoleDTO(
                id=str(role["id"]),
                case_id=str(role["case_id"]),
                proceeding_id=cls._optional_string(role.get("proceeding_id")),
                role=str(role["role"]),
                active=bool(role.get("active", True)),
                notes=cls._optional_string(role.get("notes")),
                created_at=cls._optional_string(role.get("created_at")),
            )
            for role in cls._mapping_items(record.get("roles"))
        )
        return ContactDTO(
            id=str(record["id"]),
            full_name=str(record["full_name"]),
            participant_type=str(record["participant_type"]),
            short_name=cls._optional_string(record.get("short_name")),
            active=bool(record.get("active", True)),
            email=cls._optional_string(record.get("email")),
            phone=cls._optional_string(record.get("phone")),
            additional_phone=cls._optional_string(record.get("additional_phone")),
            address=cls._optional_string(record.get("address")),
            tax_id=cls._optional_string(record.get("tax_id")),
            edrpou=cls._optional_string(record.get("edrpou")),
            birth_or_registration_date=cls._optional_string(
                record.get("birth_or_registration_date")
            ),
            representative_or_contact_person=cls._optional_string(
                record.get("representative_or_contact_person")
            ),
            notes=cls._optional_string(record.get("notes")),
            created_at=cls._optional_string(record.get("created_at")),
            roles=roles,
        )

    @staticmethod
    def _integrity_error(error: sqlite3.IntegrityError) -> ConflictError | ValidationError:
        message = str(error)
        if "FOREIGN KEY" in message:
            return ValidationError(
                "Пов’язану справу або провадження не знайдено",
                {"resource": "contact_role"},
            )
        if "UNIQUE" in message:
            return ConflictError(
                "Такий запис уже існує",
                {"resource": "contact_or_role"},
            )
        return ConflictError("Конфлікт збереження контакту", {"resource": "contact"})

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _sequence(value: object) -> tuple[object, ...]:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return ()

    @classmethod
    def _mapping_items(cls, value: object) -> tuple[Mapping[str, Any], ...]:
        return tuple(item for item in cls._sequence(value) if isinstance(item, Mapping))


class SQLiteUnitOfWork:
    """Short-lived connection and explicit transaction for one application operation."""

    def __init__(
        self,
        database_path: Path,
        *,
        write: bool = False,
        connection_policy: SQLiteConnectionPolicy | None = None,
        migrations_path: Path | None = None,
        airtable_schema_path: Path | None = None,
        initialize: bool = True,
    ):
        self._database_path = database_path
        self._write = write
        self._connection_policy = connection_policy or SQLiteConnectionPolicy()
        self._migrations_path = migrations_path
        self._airtable_schema_path = airtable_schema_path
        self._initialize = initialize
        self._repository: SQLiteRepository | None = None
        self._contacts: SQLiteContactRepository | None = None
        self._files: SQLiteManagedFileRepository | None = None
        self._finished = False
        self._entered = False

    @property
    def contacts(self) -> ContactRepositoryPort:
        if self._contacts is None or self._finished:
            raise RuntimeError("Unit of Work is not active")
        return self._contacts

    @property
    def files(self) -> ManagedFileRepositoryPort:
        if self._files is None or self._finished:
            raise RuntimeError("Unit of Work is not active")
        return self._files

    def __enter__(self) -> Self:
        if self._entered:
            raise RuntimeError("Unit of Work cannot be entered twice")
        self._entered = True
        repository = SQLiteRepository(
            self._database_path,
            auto_commit=False,
            connection_policy=self._connection_policy,
            migrations_path=self._migrations_path,
            airtable_schema_path=self._airtable_schema_path,
            initialize=self._initialize,
        )
        try:
            repository.begin(write=self._write)
        except Exception:
            repository.close()
            raise
        self._repository = repository
        self._contacts = SQLiteContactRepository(repository)
        self._files = SQLiteManagedFileRepository(repository)
        self._finished = False
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if not self._finished:
                self.rollback()
        finally:
            if self._repository is not None:
                self._repository.close()
            self._repository = None
            self._contacts = None
            self._files = None

    def commit(self) -> None:
        repository = self._active_repository()
        repository.commit()
        self._finished = True

    def rollback(self) -> None:
        repository = self._active_repository()
        repository.rollback()
        self._finished = True

    def _active_repository(self) -> SQLiteRepository:
        if self._repository is None or self._finished:
            raise RuntimeError("Unit of Work is not active")
        return self._repository


@dataclass(slots=True)
class SQLiteUnitOfWorkFactory:
    database_path: Path
    connection_policy: SQLiteConnectionPolicy = SQLiteConnectionPolicy()
    migrations_path: Path | None = None
    airtable_schema_path: Path | None = None
    _initialized: bool = field(default=False, init=False, repr=False)
    _prepare_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def prepare(self) -> None:
        if self._initialized:
            return
        with self._prepare_lock:
            if self._initialized:
                return
            repository = SQLiteRepository(
                self.database_path,
                connection_policy=self.connection_policy,
                migrations_path=self.migrations_path,
                airtable_schema_path=self.airtable_schema_path,
            )
            repository.close()
            self._initialized = True

    def __call__(self, *, write: bool = False) -> SQLiteUnitOfWork:
        self.prepare()
        return SQLiteUnitOfWork(
            self.database_path,
            write=write,
            connection_policy=self.connection_policy,
            migrations_path=self.migrations_path,
            airtable_schema_path=self.airtable_schema_path,
            initialize=False,
        )
