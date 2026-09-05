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
from case_docket.application.evidence import (
    CreateClaimCommand,
    CreateEvidenceActorCommand,
    CreateEvidenceDocumentCommand,
    CreateEvidenceEventCommand,
    CreateEvidenceRelationCommand,
    CreateSourceReferenceCommand,
    EntityReferenceInput,
    EvidenceMembershipInput,
    RecordFindingCommand,
    ReviewEvidenceCommand,
    ReviewFindingCommand,
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
EVIDENCE_V1_PREFIX = f"{API_PREFIX}/evidence"

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


EvidenceRouteAction: TypeAlias = Literal[
    "actors",
    "documents",
    "events",
    "source_references",
    "claims",
    "relations",
    "findings",
    "finding_reviews",
    "reviews",
    "case_read_model",
    "timeline",
    "source_context",
]


@dataclass(frozen=True, slots=True)
class EvidenceRoute:
    action: EvidenceRouteAction
    resource_id: str | None = None


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


def match_evidence_route(path: str) -> EvidenceRoute | None:
    static_routes: dict[str, EvidenceRouteAction] = {
        f"{EVIDENCE_V1_PREFIX}/actors": "actors",
        f"{EVIDENCE_V1_PREFIX}/documents": "documents",
        f"{EVIDENCE_V1_PREFIX}/events": "events",
        f"{EVIDENCE_V1_PREFIX}/source-references": "source_references",
        f"{EVIDENCE_V1_PREFIX}/claims": "claims",
        f"{EVIDENCE_V1_PREFIX}/relations": "relations",
        f"{EVIDENCE_V1_PREFIX}/findings": "findings",
        f"{EVIDENCE_V1_PREFIX}/reviews": "reviews",
        f"{EVIDENCE_V1_PREFIX}/timeline": "timeline",
    }
    action = static_routes.get(path)
    if action is not None:
        return EvidenceRoute(action)
    prefixes: tuple[tuple[str, EvidenceRouteAction], ...] = (
        (f"{EVIDENCE_V1_PREFIX}/cases/", "case_read_model"),
        (f"{EVIDENCE_V1_PREFIX}/source-references/", "source_context"),
    )
    for prefix, routed_action in prefixes:
        if path.startswith(prefix):
            resource_id = path[len(prefix) :]
            if resource_id and "/" not in resource_id:
                return EvidenceRoute(routed_action, resource_id)
    finding_prefix = f"{EVIDENCE_V1_PREFIX}/findings/"
    if path.startswith(finding_prefix):
        tail = path[len(finding_prefix) :]
        if tail.endswith("/reviews") and tail.count("/") == 1:
            return EvidenceRoute(
                "finding_reviews",
                tail[: -len("/reviews")],
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
        representative_or_contact_person=_optional_string(data, "representative_or_contact_person"),
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
                tool_version=(_required_string(tool, "version") if tool is not None else None),
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
    for index, raw_reference in enumerate(_optional_array(data, "externalReferences")):
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


def parse_create_evidence_actor(payload: object) -> CreateEvidenceActorCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {"createdBy", "actorType", "displayName", "memberships", "reviewStatus", "notes"},
    )
    return CreateEvidenceActorCommand(
        created_by=_required_string(data, "createdBy"),
        actor_type=_required_string(data, "actorType"),
        display_name=_required_string(data, "displayName"),
        memberships=_evidence_memberships(data),
        review_status=_optional_string(data, "reviewStatus") or "unreviewed",
        notes=_optional_string(data, "notes"),
    )


def parse_create_evidence_document(payload: object) -> CreateEvidenceDocumentCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "createdBy",
            "title",
            "label",
            "documentType",
            "category",
            "source",
            "originFormat",
            "summary",
            "processRole",
            "classification",
            "reviewStatus",
            "isKey",
            "memberships",
            "fileIds",
        },
    )
    return CreateEvidenceDocumentCommand(
        created_by=_required_string(data, "createdBy"),
        title=_required_string(data, "title"),
        label=_optional_string(data, "label"),
        document_type=_optional_string(data, "documentType"),
        category=_optional_string(data, "category"),
        source=_optional_string(data, "source"),
        origin_format=_optional_string(data, "originFormat"),
        summary=_optional_string(data, "summary"),
        process_role=_optional_string(data, "processRole"),
        classification=_optional_string(data, "classification") or "unverified",
        review_status=_optional_string(data, "reviewStatus") or "unreviewed",
        is_key=_optional_bool(data, "isKey", False),
        memberships=_evidence_memberships(data),
        file_ids=_optional_string_array(data, "fileIds"),
    )


def parse_create_evidence_event(payload: object) -> CreateEvidenceEventCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "createdBy",
            "title",
            "eventType",
            "eventAt",
            "description",
            "workflowStatus",
            "classification",
            "reviewStatus",
            "processConsequence",
            "nextAction",
            "deadline",
            "memberships",
            "actorIds",
            "documentIds",
        },
    )
    return CreateEvidenceEventCommand(
        created_by=_required_string(data, "createdBy"),
        title=_required_string(data, "title"),
        event_type=_optional_string(data, "eventType"),
        event_at=_optional_string(data, "eventAt"),
        description=_optional_string(data, "description"),
        workflow_status=_optional_string(data, "workflowStatus"),
        classification=_optional_string(data, "classification") or "unverified",
        review_status=_optional_string(data, "reviewStatus") or "unreviewed",
        process_consequence=_optional_string(data, "processConsequence"),
        next_action=_optional_string(data, "nextAction"),
        deadline=_optional_string(data, "deadline"),
        memberships=_evidence_memberships(data),
        actor_ids=_optional_string_array(data, "actorIds"),
        document_ids=_optional_string_array(data, "documentIds"),
    )


def parse_create_source_reference(payload: object) -> CreateSourceReferenceCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "createdBy",
            "sourceEntity",
            "sourceFileId",
            "locationType",
            "location",
            "excerpt",
            "sha256",
            "reviewStatus",
            "note",
        },
    )
    return CreateSourceReferenceCommand(
        created_by=_required_string(data, "createdBy"),
        source_entity=_entity_reference(data, "sourceEntity"),
        source_file_id=_optional_string(data, "sourceFileId"),
        location_type=_required_string(data, "locationType"),
        location_value=_optional_string(data, "location"),
        excerpt=_optional_string(data, "excerpt"),
        source_sha256=_optional_string(data, "sha256"),
        review_status=_optional_string(data, "reviewStatus") or "unreviewed",
        note=_optional_string(data, "note"),
    )


def parse_create_claim(payload: object) -> CreateClaimCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "createdBy",
            "subject",
            "text",
            "classification",
            "reviewStatus",
            "assertedByActorIds",
            "basisDocumentIds",
            "sourceReferenceIds",
            "memberships",
            "uncertaintyNote",
            "processConsequence",
        },
    )
    return CreateClaimCommand(
        created_by=_required_string(data, "createdBy"),
        subject=_entity_reference(data, "subject"),
        text=_required_string(data, "text"),
        classification=_optional_string(data, "classification") or "unverified",
        review_status=_optional_string(data, "reviewStatus") or "unreviewed",
        asserted_by_actor_ids=_optional_string_array(data, "assertedByActorIds"),
        basis_document_ids=_optional_string_array(data, "basisDocumentIds"),
        source_reference_ids=_optional_string_array(data, "sourceReferenceIds"),
        memberships=_evidence_memberships(data),
        uncertainty_note=_optional_string(data, "uncertaintyNote"),
        process_consequence=_optional_string(data, "processConsequence"),
    )


def parse_create_evidence_relation(payload: object) -> CreateEvidenceRelationCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "createdBy",
            "from",
            "to",
            "relationType",
            "label",
            "classification",
            "reviewStatus",
            "basisDocumentIds",
            "sourceReferenceIds",
            "uncertaintyNote",
            "validFrom",
            "validTo",
        },
    )
    return CreateEvidenceRelationCommand(
        created_by=_required_string(data, "createdBy"),
        from_entity=_entity_reference(data, "from"),
        to_entity=_entity_reference(data, "to"),
        relation_type=_required_string(data, "relationType"),
        label=_optional_string(data, "label"),
        classification=_optional_string(data, "classification") or "unverified",
        review_status=_optional_string(data, "reviewStatus") or "unreviewed",
        basis_document_ids=_optional_string_array(data, "basisDocumentIds"),
        source_reference_ids=_optional_string_array(data, "sourceReferenceIds"),
        uncertainty_note=_optional_string(data, "uncertaintyNote"),
        valid_from=_optional_string(data, "validFrom"),
        valid_to=_optional_string(data, "validTo"),
    )


def parse_review_evidence(payload: object) -> ReviewEvidenceCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "subject",
            "decision",
            "newStatus",
            "actorId",
            "expectedVersion",
            "sourceReferenceIds",
            "note",
        },
    )
    return ReviewEvidenceCommand(
        subject=_entity_reference(data, "subject"),
        decision=_required_string(data, "decision"),
        new_status=_required_string(data, "newStatus"),
        actor_id=_required_string(data, "actorId"),
        expected_version=_required_integer(data, "expectedVersion"),
        source_reference_ids=_optional_string_array(data, "sourceReferenceIds"),
        note=_optional_string(data, "note"),
    )


def parse_record_finding(payload: object) -> RecordFindingCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "fingerprint",
            "findingType",
            "title",
            "description",
            "severity",
            "confidence",
            "detector",
            "processingRunId",
            "observationStatus",
            "subjects",
            "sourceReferenceIds",
            "details",
        },
    )
    detector = _object_at(data.get("detector"), "detector")
    _reject_unknown(detector, {"name", "version"})
    raw_subjects = _required_array(data, "subjects")
    subjects = tuple(
        _entity_reference_from_object(item, f"subjects[{index}]")
        for index, item in enumerate(raw_subjects)
    )
    details = _optional_object(data, "details")
    return RecordFindingCommand(
        fingerprint=_required_string(data, "fingerprint"),
        finding_type=_required_string(data, "findingType"),
        title=_required_string(data, "title"),
        description=_required_string(data, "description"),
        severity=_required_string(data, "severity"),
        confidence=_optional_number(data, "confidence"),
        detector_name=_required_string(detector, "name"),
        detector_version=_required_string(detector, "version"),
        processing_run_id=_optional_string(data, "processingRunId"),
        observation_status=_optional_string(data, "observationStatus") or "detected",
        subjects=subjects,
        source_reference_ids=_optional_string_array(data, "sourceReferenceIds"),
        details=details,
    )


def parse_review_finding(finding_id: str, payload: object) -> ReviewFindingCommand:
    data = _object(payload)
    _reject_unknown(
        data,
        {
            "decision",
            "newStatus",
            "actorId",
            "expectedVersion",
            "sourceReferenceIds",
            "note",
        },
    )
    return ReviewFindingCommand(
        finding_id=finding_id,
        decision=_required_string(data, "decision"),
        new_status=_required_string(data, "newStatus"),
        actor_id=_required_string(data, "actorId"),
        expected_version=_required_integer(data, "expectedVersion"),
        source_reference_ids=_optional_string_array(data, "sourceReferenceIds"),
        note=_optional_string(data, "note"),
    )


def _evidence_memberships(data: Mapping[str, object]) -> tuple[EvidenceMembershipInput, ...]:
    memberships: list[EvidenceMembershipInput] = []
    for index, raw in enumerate(_optional_array(data, "memberships")):
        item = _object_at(raw, f"memberships[{index}]")
        _reject_unknown(
            item,
            {
                "contextType",
                "contextId",
                "role",
                "isPrimary",
                "sourceReferenceId",
                "reviewStatus",
                "note",
            },
        )
        memberships.append(
            EvidenceMembershipInput(
                context_type=_required_string(item, "contextType"),
                context_id=_required_string(item, "contextId"),
                role=_required_string(item, "role"),
                is_primary=_optional_bool(item, "isPrimary", False),
                source_reference_id=_optional_string(item, "sourceReferenceId"),
                review_status=_optional_string(item, "reviewStatus") or "unreviewed",
                note=_optional_string(item, "note"),
            )
        )
    return tuple(memberships)


def _entity_reference(data: Mapping[str, object], field: str) -> EntityReferenceInput:
    return _entity_reference_from_object(data.get(field), field)


def _entity_reference_from_object(value: object, field: str) -> EntityReferenceInput:
    item = _object_at(value, field)
    _reject_unknown(item, {"type", "id"})
    return EntityReferenceInput(
        entity_type=_required_string(item, "type"),
        entity_id=_required_string(item, "id"),
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


def _optional_number(data: Mapping[str, object], field: str) -> float | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RequestValidationError("Поле має бути числом або null", {"field": field})
    return float(value)


def _required_integer(data: Mapping[str, object], field: str) -> int:
    if field not in data:
        raise RequestValidationError("Відсутнє обов’язкове поле", {"field": field})
    value = data[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RequestValidationError("Поле має бути integer", {"field": field})
    return value


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
