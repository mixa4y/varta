from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application import (
    AssignContactRoleCommand,
    ConflictError,
    ContactService,
    CreateContactCommand,
    ListContactsQuery,
    UpdateContactCommand,
)
from case_docket.models.contact import Contact
from case_docket.repository import SQLiteRepository, SQLiteUnitOfWorkFactory


class SequenceIds:
    def __init__(self, *values: str):
        self.values = iter(values)

    def new_id(self) -> str:
        return next(self.values)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)


def _service(database: Path, *ids: str) -> ContactService:
    return ContactService(SQLiteUnitOfWorkFactory(database), SequenceIds(*ids), FixedClock())


def test_application_service_persists_contacts_across_real_sqlite_connections(tmp_path: Path) -> None:
    database = tmp_path / "varta.sqlite3"
    first = _service(database, "contact-1")

    created = first.create(
        CreateContactCommand(
            full_name="Синтетична Особа",
            participant_type="person",
            email="contact@example.invalid",
        )
    )
    updated = first.update(
        UpdateContactCommand(created.id, {"phone": "+000000000", "notes": "Синтетичні дані"})
    )

    reopened = _service(database)
    listed = reopened.list(ListContactsQuery("example.invalid"))

    assert updated.phone == "+000000000"
    assert listed == (updated,)


def test_uncommitted_sqlite_unit_of_work_rolls_back(tmp_path: Path) -> None:
    database = tmp_path / "varta.sqlite3"
    factory = SQLiteUnitOfWorkFactory(database)

    with factory() as unit_of_work:
        unit_of_work.contacts.add(
            Contact(id="contact-rollback", full_name="Синтетична Особа", participant_type="person")
        )

    assert _service(database).list(ListContactsQuery()) == ()


def test_duplicate_contact_role_becomes_application_conflict(tmp_path: Path) -> None:
    database = tmp_path / "varta.sqlite3"
    repository = SQLiteRepository(database)
    repository.insert(
        "cases",
        {"id": "case-synthetic", "case_number": "SYNTHETIC-CASE", "name": "Синтетична справа"},
    )
    repository.insert(
        "proceedings",
        {
            "id": "proceeding-synthetic",
            "proceeding_number": "SYNTHETIC-PROCEEDING",
            "name": "Синтетичне провадження",
        },
    )
    repository.close()

    service = _service(database, "contact-1", "role-1", "role-2")
    contact = service.create(
        CreateContactCommand(full_name="Синтетична Особа", participant_type="person")
    )
    command = AssignContactRoleCommand(
        contact_id=contact.id,
        case_id="case-synthetic",
        proceeding_id="proceeding-synthetic",
        role="Синтетична роль",
    )
    service.assign_role(command)

    with pytest.raises(ConflictError, match="уже існує"):
        service.assign_role(command)
