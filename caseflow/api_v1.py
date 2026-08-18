from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Mapping, cast

from case_docket.application.commands import (
    AssignContactRoleCommand,
    ContactFieldValue,
    CreateContactCommand,
    UpdateContactCommand,
)
from case_docket.application.errors import (
    ApplicationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)


API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
CONTACTS_V1_PREFIX = f"{API_PREFIX}/contacts"
CONTACTS_COMPATIBILITY_PREFIX = "/api/contacts"

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
_OPTIONAL_STRING_FIELDS = {
    "short_name",
    "email",
    "phone",
    "additional_phone",
    "address",
    "tax_id",
    "edrpou",
    "representative_or_contact_person",
    "notes",
}


class RequestValidationError(Exception):
    code = "request_validation_error"

    def __init__(self, message: str, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ContactRoute:
    action: Literal["collection", "context", "detail", "roles"]
    versioned: bool
    contact_id: str | None = None


def match_contact_route(path: str) -> ContactRoute | None:
    for prefix, versioned in (
        (CONTACTS_V1_PREFIX, True),
        (CONTACTS_COMPATIBILITY_PREFIX, False),
    ):
        if path == prefix:
            return ContactRoute("collection", versioned)
        if path == f"{prefix}/context":
            return ContactRoute("context", versioned)
        if not path.startswith(f"{prefix}/"):
            continue
        tail = path[len(prefix) + 1 :]
        if tail.endswith("/roles") and tail.count("/") == 1:
            return ContactRoute("roles", versioned, tail[: -len("/roles")])
        if "/" not in tail and tail:
            return ContactRoute("detail", versioned, tail)
    return None


def parse_create_contact(payload: object) -> CreateContactCommand:
    data = _object(payload)
    _reject_unknown(data, _CONTACT_FIELDS)
    return CreateContactCommand(
        full_name=_required_string(data, "full_name"),
        participant_type=_required_string(data, "participant_type"),
        short_name=_optional_string(data, "short_name"),
        active=_optional_bool(data, "active", True),
        email=_optional_string(data, "email"),
        phone=_optional_string(data, "phone"),
        additional_phone=_optional_string(data, "additional_phone"),
        address=_optional_string(data, "address"),
        tax_id=_optional_string(data, "tax_id"),
        edrpou=_optional_string(data, "edrpou"),
        birth_or_registration_date=_optional_date(data, "birth_or_registration_date"),
        representative_or_contact_person=_optional_string(
            data, "representative_or_contact_person"
        ),
        notes=_optional_string(data, "notes"),
    )


def parse_update_contact(contact_id: str, payload: object) -> UpdateContactCommand:
    data = _object(payload)
    _reject_unknown(data, _CONTACT_FIELDS)
    if not data:
        raise RequestValidationError(
            "Потрібне хоча б одне поле для оновлення",
            {"field": "body"},
        )
    changes = {field: _contact_field(data, field) for field in data}
    return UpdateContactCommand(contact_id=contact_id, changes=changes)


def parse_assign_contact_role(
    contact_id: str,
    payload: object,
) -> AssignContactRoleCommand:
    data = _object(payload)
    allowed = {"case_id", "proceeding_id", "role", "active", "notes"}
    _reject_unknown(data, allowed)
    return AssignContactRoleCommand(
        contact_id=contact_id,
        case_id=_required_string(data, "case_id"),
        proceeding_id=_optional_string(data, "proceeding_id"),
        role=_required_string(data, "role"),
        active=_optional_bool(data, "active", True),
        notes=_optional_string(data, "notes"),
    )


def error_status(error: ApplicationError | RequestValidationError) -> int:
    if isinstance(error, NotFoundError):
        return 404
    if isinstance(error, ConflictError):
        return 409
    if isinstance(error, (ValidationError, RequestValidationError)):
        return 422
    return 500


def error_envelope(
    code: str,
    message: str,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "ok": False,
        "apiVersion": API_VERSION,
        "error": {
            "code": code,
            "message": message,
            "details": dict(details or {}),
        },
    }


def application_error_envelope(
    error: ApplicationError | RequestValidationError,
) -> dict[str, object]:
    return error_envelope(error.code, error.message, error.details)


def success_envelope(payload: Mapping[str, object]) -> dict[str, object]:
    return {"ok": True, "apiVersion": API_VERSION, **payload}


def _object(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise RequestValidationError("JSON body має бути object", {"field": "body"})
    return cast(dict[str, object], payload)


def _reject_unknown(data: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RequestValidationError("Невідомі поля запиту", {"fields": unknown})


def _required_string(data: Mapping[str, object], field: str) -> str:
    if field not in data:
        raise RequestValidationError("Відсутнє обов’язкове поле", {"field": field})
    value = data[field]
    if not isinstance(value, str):
        raise RequestValidationError("Поле має бути рядком", {"field": field})
    return value


def _optional_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestValidationError("Поле має бути рядком або null", {"field": field})
    return value


def _optional_bool(data: Mapping[str, object], field: str, default: bool) -> bool:
    if field not in data:
        return default
    value = data[field]
    if not isinstance(value, bool):
        raise RequestValidationError("Поле має бути boolean", {"field": field})
    return value


def _optional_date(data: Mapping[str, object], field: str) -> date | None:
    raw = _optional_string(data, field)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise RequestValidationError(
            "Дата має формат YYYY-MM-DD",
            {"field": field},
        ) from exc


def _contact_field(data: Mapping[str, object], field: str) -> ContactFieldValue:
    if field in _OPTIONAL_STRING_FIELDS:
        return _optional_string(data, field)
    if field in {"full_name", "participant_type"}:
        return _required_string(data, field)
    if field == "active":
        return _optional_bool(data, field, True)
    if field == "birth_or_registration_date":
        return _optional_date(data, field)
    raise RequestValidationError("Невідоме поле запиту", {"field": field})
