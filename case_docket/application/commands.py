from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, TypeAlias


ContactFieldValue: TypeAlias = str | bool | date | None


@dataclass(frozen=True, slots=True)
class CreateContactCommand:
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
    birth_or_registration_date: date | None = None
    representative_or_contact_person: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateContactCommand:
    contact_id: str
    changes: Mapping[str, ContactFieldValue]


@dataclass(frozen=True, slots=True)
class AssignContactRoleCommand:
    contact_id: str
    case_id: str
    role: str
    proceeding_id: str | None = None
    active: bool = True
    notes: str | None = None
