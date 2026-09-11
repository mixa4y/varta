from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import NotFoundError, ValidationError
from .profile import CaseProfileService, GetCaseProfileQuery


@dataclass(frozen=True, slots=True)
class GetContactCardQuery:
    case_id: str
    profile_version: str
    contact_id: str


@dataclass(frozen=True, slots=True)
class GetDocumentCardQuery:
    case_id: str
    profile_version: str
    document_id: str


@dataclass(frozen=True, slots=True)
class ListCaseChronologyQuery:
    case_id: str
    profile_version: str


@dataclass(frozen=True, slots=True)
class GetEntityNeighborhoodQuery:
    case_id: str
    profile_version: str
    entity_type: str
    entity_id: str
    depth: int = 1


@dataclass(frozen=True, slots=True)
class ContactIdentifierDTO:
    identifier_id: str
    identifier_type: str
    normalized_value: str
    display_value: str
    source_reference_id: str | None
    review_status: str


@dataclass(frozen=True, slots=True)
class ContactRoleDTO:
    role_id: str
    role: str | None
    proceeding_id: str | None
    active: bool
    review_status: str


@dataclass(frozen=True, slots=True)
class ContactCardDTO:
    case_id: str
    profile_version: str
    contact_id: str
    full_name: str
    short_name: str | None
    participant_type: str
    identifiers: tuple[ContactIdentifierDTO, ...]
    roles: tuple[ContactRoleDTO, ...]
    proceeding_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    actor_ids: tuple[str, ...]
    source_reference_ids: tuple[str, ...]
    review_status: str
    version: int
    merge_split_review_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentFileDTO:
    file_id: str
    document_file_id: str | None
    role: str | None
    sequence_number: int | None
    size_bytes: int | None
    sha256: str | None
    integrity_status: str
    review_status: str


@dataclass(frozen=True, slots=True)
class AttachmentReferenceDTO:
    attachment_reference_id: str
    attachment_id: str
    file_id: str | None
    match_status: str
    match_method: str | None


@dataclass(frozen=True, slots=True)
class DocumentCardDTO:
    case_id: str
    profile_version: str
    document_id: str
    title: str | None
    document_type: str | None
    classification: str
    review_status: str
    version: int
    files: tuple[DocumentFileDTO, ...]
    attachments: tuple[AttachmentReferenceDTO, ...]
    proceeding_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    actor_ids: tuple[str, ...]
    incoming_document_ids: tuple[str, ...]
    outgoing_document_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    compliance_flag_ids: tuple[str, ...]
    version_match_ids: tuple[str, ...]
    source_reference_ids: tuple[str, ...]
    review_decision_ids: tuple[str, ...]
    reconciliation_statuses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChronologyItemDTO:
    entity_type: str
    entity_id: str
    occurred: str | None
    date_role: str
    precision: str
    timezone: str | None
    title: str | None
    description: str | None
    proceeding_ids: tuple[str, ...]
    actor_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    source_reference_ids: tuple[str, ...]
    classification: str
    review_status: str
    ordering_key: str


@dataclass(frozen=True, slots=True)
class CaseChronologyDTO:
    case_id: str
    profile_version: str
    dated: tuple[ChronologyItemDTO, ...]
    undated: tuple[ChronologyItemDTO, ...]


@dataclass(frozen=True, slots=True)
class NeighborhoodNodeDTO:
    entity_type: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class NeighborhoodEdgeDTO:
    edge_id: str
    edge_kind: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relation_type: str
    classification: str
    review_status: str
    basis_document_ids: tuple[str, ...]
    source_reference_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntityNeighborhoodDTO:
    case_id: str
    profile_version: str
    root: NeighborhoodNodeDTO
    depth: int
    nodes: tuple[NeighborhoodNodeDTO, ...]
    edges: tuple[NeighborhoodEdgeDTO, ...]


class CaseReadModelRepositoryPort(Protocol):
    def get_contact_card(
        self, case_id: str, profile_version: str, contact_id: str
    ) -> ContactCardDTO | None: ...

    def get_document_card(
        self, case_id: str, profile_version: str, document_id: str
    ) -> DocumentCardDTO | None: ...

    def list_chronology(self, case_id: str, profile_version: str) -> CaseChronologyDTO: ...

    def get_neighborhood(
        self,
        case_id: str,
        profile_version: str,
        entity_type: str,
        entity_id: str,
        depth: int,
    ) -> EntityNeighborhoodDTO | None: ...


class CaseReadModelService:
    def __init__(
        self,
        profile_service: CaseProfileService,
        repository: CaseReadModelRepositoryPort,
    ):
        self._profile_service = profile_service
        self._repository = repository

    def get_contact_card(self, query: GetContactCardQuery) -> ContactCardDTO:
        case_id, version = self._context(query.case_id, query.profile_version)
        contact_id = self._required(query.contact_id, "contact_id")
        result = self._repository.get_contact_card(case_id, version, contact_id)
        if result is None:
            raise NotFoundError("Контакт не знайдено у вказаній справі", {"resource": "contact"})
        return result

    def get_document_card(self, query: GetDocumentCardQuery) -> DocumentCardDTO:
        case_id, version = self._context(query.case_id, query.profile_version)
        document_id = self._required(query.document_id, "document_id")
        result = self._repository.get_document_card(case_id, version, document_id)
        if result is None:
            raise NotFoundError("Документ не знайдено у вказаній справі", {"resource": "document"})
        return result

    def list_chronology(self, query: ListCaseChronologyQuery) -> CaseChronologyDTO:
        case_id, version = self._context(query.case_id, query.profile_version)
        return self._repository.list_chronology(case_id, version)

    def get_neighborhood(self, query: GetEntityNeighborhoodQuery) -> EntityNeighborhoodDTO:
        case_id, version = self._context(query.case_id, query.profile_version)
        entity_type = self._required(query.entity_type, "entity_type")
        entity_id = self._required(query.entity_id, "entity_id")
        if query.depth < 1 or query.depth > 3:
            raise ValidationError("depth має бути в межах 1..3", {"field": "depth"})
        result = self._repository.get_neighborhood(
            case_id, version, entity_type, entity_id, query.depth
        )
        if result is None:
            raise NotFoundError("Entity не знайдено у вказаній справі", {"resource": entity_type})
        return result

    def _context(self, case_id: str, profile_version: str) -> tuple[str, str]:
        actual_case = self._required(case_id, "case_id")
        actual_version = self._required(profile_version, "profile_version")
        self._profile_service.get(GetCaseProfileQuery(actual_case, actual_version))
        return actual_case, actual_version

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValidationError(f"{field} є обов'язковим", {"field": field})
        return normalized
