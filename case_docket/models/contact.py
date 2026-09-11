from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PARTICIPANT_TYPES = {"person", "organization"}


@dataclass(slots=True)
class Contact:
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
    birth_or_registration_date: date | None = None
    representative_or_contact_person: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        self.full_name = self.full_name.strip()
        if not self.full_name:
            raise ValueError("full_name не може бути порожнім")
        if self.participant_type not in _PARTICIPANT_TYPES:
            raise ValueError("participant_type має бути person або organization")
        if self.email and not _EMAIL_RE.match(self.email):
            raise ValueError("Некоректний email")
        if self.participant_type == "person" and self.edrpou:
            raise ValueError("ЄДРПОУ застосовується лише до організації")

    def to_record(self) -> dict[str, object]:
        data = asdict(self)
        if self.birth_or_registration_date:
            data["birth_or_registration_date"] = self.birth_or_registration_date.isoformat()
        return data


@dataclass(slots=True)
class CaseParticipant:
    id: str
    contact_id: str
    case_id: str
    role: str
    proceeding_id: str | None = None
    active: bool = True
    notes: str | None = None
