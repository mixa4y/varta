from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from case_docket.application import (
    AssignContactRoleCommand,
    ContactContextDTO,
    ContactDTO,
    ContactRoleDTO,
    ContactService,
    CreateContactCommand,
    GetContactQuery,
    GetContactsContextQuery,
    ListContactsQuery,
    NotFoundError,
    UpdateContactCommand,
    ValidationError,
)
from case_docket.models.contact import CaseParticipant, Contact


class SequenceIds:
    def __init__(self, *values: str):
        self.values = iter(values)

    def new_id(self) -> str:
        return next(self.values)


class FixedClock:
    value = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value


class MemoryContacts:
    def __init__(self):
        self.items: dict[str, ContactDTO] = {}
        self.role_times: list[datetime] = []

    def add(self, contact: Contact) -> None:
        self.items[contact.id] = self._dto(contact)

    def get(self, contact_id: str) -> ContactDTO | None:
        return self.items.get(contact_id)

    def list(self, search: str | None = None) -> tuple[ContactDTO, ...]:
        contacts = tuple(sorted(self.items.values(), key=lambda item: item.full_name))
        if not search:
            return contacts
        needle = search.casefold()
        return tuple(item for item in contacts if needle in item.full_name.casefold())

    def update(self, contact: Contact) -> None:
        current = self.items[contact.id]
        self.items[contact.id] = self._dto(contact, roles=current.roles)

    def context(self) -> ContactContextDTO:
        return ContactContextDTO(cases=(), proceedings=(), roles=("Синтетична роль",))

    def add_role(self, participant: CaseParticipant, occurred_at: datetime) -> None:
        current = self.items[participant.contact_id]
        role = ContactRoleDTO(
            id=participant.id,
            case_id=participant.case_id,
            proceeding_id=participant.proceeding_id,
            role=participant.role,
            active=participant.active,
            notes=participant.notes,
            created_at=occurred_at.isoformat(),
        )
        self.items[participant.contact_id] = self._replace_roles(current, (*current.roles, role))
        self.role_times.append(occurred_at)

    @staticmethod
    def _dto(contact: Contact, roles: tuple[ContactRoleDTO, ...] = ()) -> ContactDTO:
        return ContactDTO(
            id=contact.id,
            full_name=contact.full_name,
            participant_type=contact.participant_type,
            short_name=contact.short_name,
            active=contact.active,
            email=contact.email,
            phone=contact.phone,
            additional_phone=contact.additional_phone,
            address=contact.address,
            tax_id=contact.tax_id,
            edrpou=contact.edrpou,
            birth_or_registration_date=(
                contact.birth_or_registration_date.isoformat()
                if contact.birth_or_registration_date
                else None
            ),
            representative_or_contact_person=contact.representative_or_contact_person,
            notes=contact.notes,
            created_at="2026-01-02T03:04:00+00:00",
            roles=roles,
        )

    @staticmethod
    def _replace_roles(contact: ContactDTO, roles: tuple[ContactRoleDTO, ...]) -> ContactDTO:
        values = contact.to_dict()
        values.pop("roles")
        return ContactDTO(**values, roles=roles)


class FakeUnitOfWork:
    def __init__(self, contacts: MemoryContacts):
        self.contacts = contacts
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.committed:
            self.rollback()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeUnitOfWorkFactory:
    def __init__(self):
        self.contacts = MemoryContacts()
        self.created: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        unit_of_work = FakeUnitOfWork(self.contacts)
        self.created.append(unit_of_work)
        return unit_of_work


def test_contact_commands_use_fake_ports_and_commit() -> None:
    factory = FakeUnitOfWorkFactory()
    service = ContactService(factory, SequenceIds("contact-1", "role-1"), FixedClock())

    created = service.create(
        CreateContactCommand(
            full_name="  Синтетична Особа  ",
            participant_type="person",
            email="contact@example.invalid",
        )
    )
    updated = service.update(
        UpdateContactCommand(
            contact_id=created.id,
            changes={"short_name": "Синтетичний контакт", "active": False},
        )
    )
    role_id, with_role = service.assign_role(
        AssignContactRoleCommand(
            contact_id=created.id,
            case_id="case-synthetic",
            proceeding_id="proceeding-synthetic",
            role="Синтетична роль",
        )
    )

    assert created.id == "contact-1"
    assert created.full_name == "Синтетична Особа"
    assert updated.short_name == "Синтетичний контакт"
    assert updated.active is False
    assert role_id == "role-1"
    assert with_role.roles[0].role == "Синтетична роль"
    assert factory.contacts.role_times == [FixedClock.value]
    assert all(unit.committed for unit in factory.created)


def test_contact_queries_use_fake_ports_without_committing() -> None:
    factory = FakeUnitOfWorkFactory()
    factory.contacts.add(Contact(id="contact-1", full_name="Синтетична Особа", participant_type="person"))
    service = ContactService(factory, SequenceIds(), FixedClock())

    listed = service.list(ListContactsQuery("Особа"))
    fetched = service.get(GetContactQuery("contact-1"))
    context = service.context(GetContactsContextQuery())

    assert listed == (fetched,)
    assert context.roles == ("Синтетична роль",)
    assert all(not unit.committed and unit.rolled_back for unit in factory.created)


def test_domain_validation_happens_before_opening_unit_of_work() -> None:
    factory = FakeUnitOfWorkFactory()
    service = ContactService(factory, SequenceIds("contact-1"), FixedClock())

    with pytest.raises(ValidationError, match="Некоректний email"):
        service.create(
            CreateContactCommand(
                full_name="Синтетична Особа",
                participant_type="person",
                email="invalid-email",
            )
        )

    assert factory.created == []


def test_missing_contact_rolls_back_query_unit_of_work() -> None:
    factory = FakeUnitOfWorkFactory()
    service = ContactService(factory, SequenceIds(), FixedClock())

    with pytest.raises(NotFoundError, match="Контакт не знайдено"):
        service.get(GetContactQuery("missing-contact"))

    assert factory.created[-1].rolled_back is True


def test_update_accepts_typed_date_change() -> None:
    factory = FakeUnitOfWorkFactory()
    factory.contacts.add(Contact(id="contact-1", full_name="Синтетична Особа", participant_type="person"))
    service = ContactService(factory, SequenceIds(), FixedClock())

    result = service.update(
        UpdateContactCommand(
            "contact-1",
            {"birth_or_registration_date": date(2000, 1, 2)},
        )
    )

    assert result.birth_or_registration_date == "2000-01-02"
