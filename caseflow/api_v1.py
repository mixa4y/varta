from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Mapping, TypeAlias, cast

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
from case_docket.application.workspace import (
    AddDocumentMembershipsCommand,
    AddFileMembershipsCommand,
    CandidateSourceInput,
    ConfirmCaseBootstrapCommand,
    CreateWorkspaceCaseCommand,
    CreateWorkspaceProceedingCommand,
    ExternalReferenceInput,
    RegisterCandidateSourcesCommand,
    SelectActiveCaseCommand,
)


API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
CONTACTS_V1_PREFIX = f"{API_PREFIX}/contacts"
CONTACTS_COMPATIBILITY_PREFIX = "/api/contacts"
INTAKE_V1_PREFIX = f"{API_PREFIX}/intake"
WORKSPACE_V1_PREFIX = f"{API_PREFIX}/workspace"

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


@dataclass(frozen=True, slots=True)
class IntakeRoute:
    action: Literal["collection", "inventory", "detail"]
    batch_id: str | None = None


WorkspaceRouteAction: TypeAlias = Literal[
    "cases",
    "proceedings",
    "active_case",
    "bootstrap_reviews",
    "bootstrap_candidates",
    "bootstrap_confirm",
    "memberships",
    "document_memberships",
]


@dataclass(frozen=True, slots=True)
class WorkspaceRoute:
    action: WorkspaceRouteAction
    intake_case_id: str | None = None


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


def match_intake_route(path: str) -> IntakeRoute | None:
    if path == INTAKE_V1_PREFIX:
        return IntakeRoute("collection")
    if path == f"{INTAKE_V1_PREFIX}/inventory":
        return IntakeRoute("inventory")
    prefix = f"{INTAKE_V1_PREFIX}/batches/"
    if path.startswith(prefix):
        batch_id = path[len(prefix) :]
        if batch_id and "/" not in batch_id:
            return IntakeRoute("detail", batch_id)
    return None


def match_workspace_route(path: str) -> WorkspaceRoute | None:
    static_routes: dict[str, WorkspaceRouteAction] = {
        f"{WORKSPACE_V1_PREFIX}/cases": "cases",
        f"{WORKSPACE_V1_PREFIX}/proceedings": "proceedings",
        f"{WORKSPACE_V1_PREFIX}/active-case": "active_case",
        f"{WORKSPACE_V1_PREFIX}/bootstrap-reviews": "bootstrap_reviews",
        f"{WORKSPACE_V1_PREFIX}/memberships": "memberships",
        f"{WORKSPACE_V1_PREFIX}/document-memberships": "document_memberships",
    }
    action = static_routes.get(path)
    if action is not None:
        return WorkspaceRoute(action)
    prefix = f"{WORKSPACE_V1_PREFIX}/bootstrap-reviews/"
    if not path.startswith(prefix):
        return None
    tail = path[len(prefix) :]
    if tail.endswith("/candidates") and tail.count("/") == 1:
        return WorkspaceRoute(
            "bootstrap_candidates",
            tail[: -len("/candidates")],
        )
    if tail.endswith("/confirm") and tail.count("/") == 1:
        return WorkspaceRoute(
            "bootstrap_confirm",
            tail[: -len("/confirm")],
        )
    return None


def parse_idempotency_key(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RequestValidationError(
            "Idempotency-Key має бути непорожнім без outer whitespace",
            {"header": "Idempotency-Key"},
        )
    if len(value) > 200 or any(ord(character) < 32 for character in value):
        raise RequestValidationError(
            "Idempotency-Key має непідтримуваний формат",
            {"header": "Idempotency-Key"},
        )
    return value


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


def parse_register_candidate_sources(
    intake_case_id: str,
    payload: object,
) -> RegisterCandidateSourcesCommand:
    data = _object(payload)
    _reject_unknown(data, {"actorId", "sources"})
    raw_sources = _required_array(data, "sources")
    sources: list[CandidateSourceInput] = []
    for index, raw_source in enumerate(raw_sources):
        source = _object_at(raw_source, f"sources[{index}]")
        _reject_unknown(
            source,
            {
                "text",
                "detectionSource",
                "sourceLocation",
                "evidenceBasis",
                "confidence",
                "tool",
                "externalReference",
            },
        )
        tool = _optional_object(source, "tool")
        if tool is not None:
            _reject_unknown(tool, {"name", "version"})
        external = _optional_object(source, "externalReference")
        if external is not None:
            _reject_unknown(external, {"system", "kind", "value"})
        sources.append(
            CandidateSourceInput(
                text=_required_string(source, "text"),
                detection_source=_required_string(source, "detectionSource"),
                source_location=_required_string(source, "sourceLocation"),
                evidence_basis=_required_string(source, "evidenceBasis"),
                confidence=_required_number(source, "confidence"),
                tool_name=_required_string(tool, "name") if tool is not None else None,
                tool_version=(
                    _required_string(tool, "version") if tool is not None else None
                ),
                external_reference_system=(
                    _required_string(external, "system") if external is not None else None
                ),
                external_reference_kind=(
                    _required_string(external, "kind") if external is not None else None
                ),
                external_reference_value=(
                    _required_string(external, "value") if external is not None else None
                ),
            )
        )
    return RegisterCandidateSourcesCommand(
        intake_case_id=intake_case_id,
        sources=tuple(sources),
        actor_id=_optional_string(data, "actorId") or "system:candidate-detector",
    )


def parse_confirm_case_bootstrap(
    intake_case_id: str,
    payload: object,
) -> ConfirmCaseBootstrapCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "actorId",
            "candidateId",
            "manualCaseNumber",
            "caseId",
            "createCaseName",
            "proceedingIds",
            "note",
        },
    )
    return ConfirmCaseBootstrapCommand(
        intake_case_id=intake_case_id,
        actor_id=_required_string(data, "actorId"),
        candidate_id=_optional_string(data, "candidateId"),
        manual_case_number=_optional_string(data, "manualCaseNumber"),
        case_id=_optional_string(data, "caseId"),
        create_case_name=_optional_string(data, "createCaseName"),
        proceeding_ids=_optional_string_array(data, "proceedingIds"),
        note=_optional_string(data, "note"),
    )


def parse_create_workspace_case(payload: object) -> CreateWorkspaceCaseCommand:
    data = _object(payload)
    _reject_unknown(data, {"actorId", "caseNumber", "name", "externalReferences"})
    references: list[ExternalReferenceInput] = []
    for index, raw_reference in enumerate(
        _optional_array(data, "externalReferences")
    ):
        reference = _object_at(raw_reference, f"externalReferences[{index}]")
        _reject_unknown(
            reference,
            {"system", "kind", "value", "evidenceBasis", "sourceLocation"},
        )
        references.append(
            ExternalReferenceInput(
                system=_required_string(reference, "system"),
                kind=_required_string(reference, "kind"),
                value=_required_string(reference, "value"),
                evidence_basis=_required_string(reference, "evidenceBasis"),
                source_location=_optional_string(reference, "sourceLocation"),
            )
        )
    return CreateWorkspaceCaseCommand(
        actor_id=_required_string(data, "actorId"),
        case_number=_optional_string(data, "caseNumber"),
        name=_optional_string(data, "name"),
        external_references=tuple(references),
    )


def parse_create_workspace_proceeding(payload: object) -> CreateWorkspaceProceedingCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {"actorId", "caseIds", "proceedingNumber", "name", "relationshipKind"},
    )
    return CreateWorkspaceProceedingCommand(
        actor_id=_required_string(data, "actorId"),
        case_ids=_required_string_array(data, "caseIds"),
        proceeding_number=_optional_string(data, "proceedingNumber"),
        name=_optional_string(data, "name"),
        relationship_kind=_optional_string(data, "relationshipKind") or "membership",
    )


def parse_add_file_memberships(payload: object) -> AddFileMembershipsCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {"fileId", "actorId", "caseIds", "proceedingIds", "role", "note"},
    )
    return AddFileMembershipsCommand(
        file_id=_required_string(data, "fileId"),
        actor_id=_required_string(data, "actorId"),
        case_ids=_optional_string_array(data, "caseIds"),
        proceeding_ids=_optional_string_array(data, "proceedingIds"),
        role=_optional_string(data, "role") or "evidence",
        note=_optional_string(data, "note"),
    )


def parse_add_document_memberships(payload: object) -> AddDocumentMembershipsCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {"documentId", "actorId", "caseIds", "proceedingIds", "role", "note"},
    )
    return AddDocumentMembershipsCommand(
        document_id=_required_string(data, "documentId"),
        actor_id=_required_string(data, "actorId"),
        case_ids=_optional_string_array(data, "caseIds"),
        proceeding_ids=_optional_string_array(data, "proceedingIds"),
        role=_optional_string(data, "role") or "evidence",
        note=_optional_string(data, "note"),
    )


def parse_select_active_case(payload: object) -> SelectActiveCaseCommand:
    data = _object(payload)
    _reject_unknown(data, {"preferenceId", "actorId", "activeCaseId"})
    return SelectActiveCaseCommand(
        preference_id=_required_string(data, "preferenceId"),
        actor_id=_required_string(data, "actorId"),
        active_case_id=_optional_string(data, "activeCaseId"),
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


def _object_at(payload: object, field: str) -> dict[str, object]:
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise RequestValidationError("Поле має бути object", {"field": field})
    return cast(dict[str, object], payload)


def _optional_object(
    data: Mapping[str, object],
    field: str,
) -> dict[str, object] | None:
    value = data.get(field)
    if value is None:
        return None
    return _object_at(value, field)


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


def _required_number(data: Mapping[str, object], field: str) -> float:
    if field not in data:
        raise RequestValidationError("Відсутнє обов’язкове поле", {"field": field})
    value = data[field]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RequestValidationError("Поле має бути числом", {"field": field})
    return float(value)


def _required_array(data: Mapping[str, object], field: str) -> list[object]:
    if field not in data:
        raise RequestValidationError("Відсутнє обов’язкове поле", {"field": field})
    value = data[field]
    if not isinstance(value, list):
        raise RequestValidationError("Поле має бути array", {"field": field})
    return value


def _optional_array(data: Mapping[str, object], field: str) -> list[object]:
    value = data.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise RequestValidationError("Поле має бути array", {"field": field})
    return value


def _required_string_array(data: Mapping[str, object], field: str) -> tuple[str, ...]:
    return _string_array(_required_array(data, field), field)


def _optional_string_array(data: Mapping[str, object], field: str) -> tuple[str, ...]:
    return _string_array(_optional_array(data, field), field)


def _string_array(values: list[object], field: str) -> tuple[str, ...]:
    if not all(isinstance(value, str) for value in values):
        raise RequestValidationError("Array має містити лише рядки", {"field": field})
    return tuple(cast(str, value) for value in values)


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
