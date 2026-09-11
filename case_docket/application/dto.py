from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContactRoleDTO:
    id: str
    case_id: str
    role: str
    proceeding_id: str | None = None
    active: bool = True
    notes: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "proceeding_id": self.proceeding_id,
            "role": self.role,
            "active": self.active,
            "notes": self.notes,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ContactDTO:
    id: str
    full_name: str
    participant_type: str
    short_name: str | None = None
    active: bool = True
    email: str | None = None
    phone: str | None = None
    additional_phone: str | None = None
    address: str | None = None
    tax_id: str | None = None
    edrpou: str | None = None
    birth_or_registration_date: str | None = None
    representative_or_contact_person: str | None = None
    notes: str | None = None
    created_at: str | None = None
    roles: tuple[ContactRoleDTO, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "short_name": self.short_name,
            "participant_type": self.participant_type,
            "active": self.active,
            "email": self.email,
            "phone": self.phone,
            "additional_phone": self.additional_phone,
            "address": self.address,
            "tax_id": self.tax_id,
            "edrpou": self.edrpou,
            "birth_or_registration_date": self.birth_or_registration_date,
            "representative_or_contact_person": self.representative_or_contact_person,
            "notes": self.notes,
            "created_at": self.created_at,
            "roles": [role.to_dict() for role in self.roles],
        }


@dataclass(frozen=True, slots=True)
class CaseOptionDTO:
    id: str
    case_number: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "case_number": self.case_number, "name": self.name}


@dataclass(frozen=True, slots=True)
class ProceedingOptionDTO:
    id: str
    proceeding_number: str | None = None
    name: str | None = None
    case_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "proceeding_number": self.proceeding_number,
            "name": self.name,
            "caseIds": list(self.case_ids),
        }


@dataclass(frozen=True, slots=True)
class ContactContextDTO:
    cases: tuple[CaseOptionDTO, ...]
    proceedings: tuple[ProceedingOptionDTO, ...]
    roles: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "cases": [item.to_dict() for item in self.cases],
            "proceedings": [item.to_dict() for item in self.proceedings],
            "roles": list(self.roles),
        }
