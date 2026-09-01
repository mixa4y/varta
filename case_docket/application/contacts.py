from __future__ import annotations

from datetime import date

from case_docket.models.contact import CaseParticipant, Contact

from .commands import AssignContactRoleCommand, CreateContactCommand, UpdateContactCommand
from .dto import ContactContextDTO, ContactDTO
from .errors import NotFoundError, ValidationError
from .ports import Clock, IdProvider, UnitOfWorkFactory
from .queries import GetContactQuery, GetContactsContextQuery, ListContactsQuery


_CONTACT_FIELDS = {
    "full_name",
    "participant_type",
    "short_name",
    "active",
    "email",
    "phone",
    "additional_phone",
    "address",
    "tax_id",
    "edrpou",
    "birth_or_registration_date",
    "representative_or_contact_person",
    "notes",
}


class ContactService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        id_provider: IdProvider,
        clock: Clock,
    ):
        self._unit_of_work_factory = unit_of_work_factory
        self._id_provider = id_provider
        self._clock = clock

    def create(self, command: CreateContactCommand) -> ContactDTO:
        contact = self._build_contact(
            contact_id=self._id_provider.new_id(),
            full_name=command.full_name,
            participant_type=command.participant_type,
            short_name=command.short_name,
            active=command.active,
            email=command.email,
            phone=command.phone,
            additional_phone=command.additional_phone,
            address=command.address,
            tax_id=command.tax_id,
            edrpou=command.edrpou,
            birth_or_registration_date=command.birth_or_registration_date,
            representative_or_contact_person=command.representative_or_contact_person,
            notes=command.notes,
        )
        with self._unit_of_work_factory(write=True) as unit_of_work:
            unit_of_work.contacts.add(contact)
            result = unit_of_work.contacts.get(contact.id)
            if result is None:
                raise RuntimeError("Contact repository did not return a newly added contact")
            unit_of_work.commit()
            return result

    def update(self, command: UpdateContactCommand) -> ContactDTO:
        unknown = set(command.changes) - _CONTACT_FIELDS
        if unknown:
            raise ValidationError(
                "Невідомі поля контакту",
                {"fields": sorted(unknown)},
            )
        with self._unit_of_work_factory(write=True) as unit_of_work:
            current = unit_of_work.contacts.get(self._require_id(command.contact_id))
            if current is None:
                raise NotFoundError(
                    "Контакт не знайдено",
                    {"resource": "contact"},
                )
            values: dict[str, object] = {
                "full_name": current.full_name,
                "participant_type": current.participant_type,
                "short_name": current.short_name,
                "active": current.active,
                "email": current.email,
                "phone": current.phone,
                "additional_phone": current.additional_phone,
                "address": current.address,
                "tax_id": current.tax_id,
                "edrpou": current.edrpou,
                "birth_or_registration_date": self._date_or_none(
                    current.birth_or_registration_date
                ),
                "representative_or_contact_person": current.representative_or_contact_person,
                "notes": current.notes,
            }
            values.update(command.changes)
            contact = self._build_contact(contact_id=current.id, **values)
            unit_of_work.contacts.update(contact)
            result = unit_of_work.contacts.get(contact.id)
            if result is None:
                raise RuntimeError("Contact repository lost an updated contact")
            unit_of_work.commit()
            return result

    def assign_role(self, command: AssignContactRoleCommand) -> tuple[str, ContactDTO]:
        contact_id = self._require_id(command.contact_id)
        case_id = self._required_text(command.case_id, "case_id")
        role = self._required_text(command.role, "role")
        participant_id = self._id_provider.new_id()
        participant = CaseParticipant(
            id=participant_id,
            contact_id=contact_id,
            case_id=case_id,
            proceeding_id=self._optional_text(command.proceeding_id),
            role=role,
            active=command.active,
            notes=command.notes,
        )
        with self._unit_of_work_factory(write=True) as unit_of_work:
            if unit_of_work.contacts.get(contact_id) is None:
                raise NotFoundError(
                    "Контакт не знайдено",
                    {"resource": "contact"},
                )
            unit_of_work.contacts.add_role(participant, self._clock.now())
            result = unit_of_work.contacts.get(contact_id)
            if result is None:
                raise RuntimeError("Contact repository lost a role owner")
            unit_of_work.commit()
            return participant_id, result

    def list(self, query: ListContactsQuery) -> tuple[ContactDTO, ...]:
        search = query.search.strip() if query.search else None
        if search and len(search) > 200:
            raise ValidationError(
                "Пошуковий запит задовгий",
                {"field": "q", "max_length": 200},
            )
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.contacts.list(search or None)

    def get(self, query: GetContactQuery) -> ContactDTO:
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.contacts.get(self._require_id(query.contact_id))
            if result is None:
                raise NotFoundError(
                    "Контакт не знайдено",
                    {"resource": "contact"},
                )
            return result

    def context(self, query: GetContactsContextQuery) -> ContactContextDTO:
        del query
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.contacts.context()

    @staticmethod
    def _build_contact(contact_id: str, **values: object) -> Contact:
        try:
            return Contact(id=contact_id, **values)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValidationError(str(exc), {"resource": "contact"}) from exc

    @staticmethod
    def _require_id(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 200:
            raise ValidationError("Некоректний ідентифікатор контакту", {"field": "contact_id"})
        return normalized

    @staticmethod
    def _required_text(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValidationError("Обов’язкове поле не може бути порожнім", {"field": field})
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @staticmethod
    def _date_or_none(value: str | None) -> date | None:
        return date.fromisoformat(value) if value else None
