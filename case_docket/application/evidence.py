from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .errors import ConflictError, NotFoundError, ValidationError
from .evidence_ports import (
    ClaimRecord,
    CompatibilityReviewRecord,
    EntityReferenceRecord,
    EvidenceActorRecord,
    EvidenceDocumentRecord,
    EvidenceEventRecord,
    EvidenceMembershipRecord,
    EvidenceRelationRecord,
    EvidenceRepositoryPort,
    EvidenceUnitOfWorkFactory,
    FindingRecord,
    ReviewDecisionRecord,
    SourceContextRecord,
    SourceReferenceRecord,
    TimelineRecord,
)
from .ports import Clock, IdProvider


_ENTITY_TYPES = {
    "case",
    "proceeding",
    "actor",
    "file",
    "document",
    "event",
    "claim",
    "relation",
    "source_reference",
}
_REVIEWABLE_ENTITY_TYPES = {
    "actor",
    "document",
    "event",
    "claim",
    "relation",
    "source_reference",
}
_SOURCE_ENTITY_TYPES = {
    "case",
    "proceeding",
    "actor",
    "file",
    "document",
    "event",
    "claim",
    "relation",
}
_CLAIM_SUBJECT_TYPES = {
    "case",
    "proceeding",
    "actor",
    "file",
    "document",
    "event",
    "relation",
}
_RELATION_ENDPOINT_TYPES = {
    "case",
    "proceeding",
    "actor",
    "file",
    "document",
    "event",
    "claim",
}
_ACTOR_TYPES = {"person", "organization", "court", "authority", "unknown"}
_CLASSIFICATIONS = {
    "confirmed_fact",
    "party_position",
    "user_position",
    "court_reasoning",
    "legal_conclusion",
    "contradiction",
    "open_question",
    "unverified",
}
_REVIEW_STATUSES = {
    "unreviewed",
    "manual_review_required",
    "in_review",
    "confirmed",
    "rejected",
    "resolved",
    "superseded",
}
_FINDING_REVIEW_STATUSES = _REVIEW_STATUSES | {"open", "acknowledged", "false_positive"}
_DECISIONS = {
    "confirm",
    "reject",
    "request_review",
    "resolve",
    "supersede",
    "merge",
    "split",
}
_FINDING_DECISIONS = _DECISIONS | {"acknowledge", "reopen", "false_positive"}
_LOCATION_TYPES = {
    "document",
    "page",
    "paragraph",
    "cell",
    "timecode",
    "bounding_box",
    "metadata",
    "whole_file",
    "manual_note",
}
_FINDING_SEVERITIES = {"critical", "high", "medium", "low", "info", "unknown"}
_FINDING_OBSERVATIONS = {"detected", "not_detected", "error", "unknown"}
_DOCUMENT_WORK_STATUSES = {"completed", "in_progress", "waiting", "needs_review"}
_LEGACY_FINDING_STATUSES = {"open", "acknowledged", "resolved", "false_positive"}
_MACHINE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HEX_FINGERPRINT = re.compile(r"^[A-Fa-f0-9]{16,128}$")
_SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class EntityReferenceInput:
    entity_type: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class EvidenceMembershipInput:
    context_type: str
    context_id: str
    role: str
    is_primary: bool = False
    source_reference_id: str | None = None
    review_status: str = "unreviewed"
    note: str | None = None


@dataclass(frozen=True, slots=True)
class CreateEvidenceActorCommand:
    created_by: str
    actor_type: str
    display_name: str
    memberships: tuple[EvidenceMembershipInput, ...] = ()
    review_status: str = "unreviewed"
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class CreateEvidenceDocumentCommand:
    created_by: str
    title: str
    label: str | None = None
    document_type: str | None = None
    category: str | None = None
    source: str | None = None
    origin_format: str | None = None
    summary: str | None = None
    process_role: str | None = None
    classification: str = "unverified"
    review_status: str = "unreviewed"
    is_key: bool = False
    memberships: tuple[EvidenceMembershipInput, ...] = ()
    file_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateEvidenceEventCommand:
    created_by: str
    title: str
    event_type: str | None = None
    event_at: str | None = None
    description: str | None = None
    workflow_status: str | None = None
    classification: str = "unverified"
    review_status: str = "unreviewed"
    process_consequence: str | None = None
    next_action: str | None = None
    deadline: str | None = None
    memberships: tuple[EvidenceMembershipInput, ...] = ()
    actor_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateSourceReferenceCommand:
    created_by: str
    source_entity: EntityReferenceInput
    location_type: str
    source_file_id: str | None = None
    location_value: str | None = None
    excerpt: str | None = None
    source_sha256: str | None = None
    review_status: str = "unreviewed"
    note: str | None = None


@dataclass(frozen=True, slots=True)
class CreateClaimCommand:
    created_by: str
    subject: EntityReferenceInput
    text: str
    classification: str = "unverified"
    review_status: str = "unreviewed"
    asserted_by_actor_ids: tuple[str, ...] = ()
    basis_document_ids: tuple[str, ...] = ()
    source_reference_ids: tuple[str, ...] = ()
    memberships: tuple[EvidenceMembershipInput, ...] = ()
    uncertainty_note: str | None = None
    process_consequence: str | None = None


@dataclass(frozen=True, slots=True)
class CreateEvidenceRelationCommand:
    created_by: str
    from_entity: EntityReferenceInput
    to_entity: EntityReferenceInput
    relation_type: str
    label: str | None = None
    classification: str = "unverified"
    review_status: str = "unreviewed"
    basis_document_ids: tuple[str, ...] = ()
    source_reference_ids: tuple[str, ...] = ()
    uncertainty_note: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewEvidenceCommand:
    subject: EntityReferenceInput
    decision: str
    new_status: str
    actor_id: str
    expected_version: int
    source_reference_ids: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RecordFindingCommand:
    fingerprint: str
    finding_type: str
    title: str
    description: str
    severity: str
    detector_name: str
    detector_version: str
    subjects: tuple[EntityReferenceInput, ...]
    source_reference_ids: tuple[str, ...] = ()
    confidence: float | None = None
    processing_run_id: str | None = None
    observation_status: str = "detected"
    details: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ReviewFindingCommand:
    finding_id: str
    decision: str
    new_status: str
    actor_id: str
    expected_version: int
    source_reference_ids: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class GetCaseEvidenceQuery:
    case_id: str
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ListEvidenceTimelineQuery:
    case_id: str
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class GetSourceContextQuery:
    source_reference_id: str


@dataclass(frozen=True, slots=True)
class ListReviewHistoryQuery:
    subject_type: str
    subject_id: str
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SetCompatibilityReviewCommand:
    subject_type: str
    external_id: str
    status: str
    actor_id: str
    note: str | None = None
    expected_version: int | None = None


@dataclass(frozen=True, slots=True)
class EntityReferenceDTO:
    entity_type: str
    entity_id: str

    def to_dict(self) -> dict[str, object]:
        return {"type": self.entity_type, "id": self.entity_id}


@dataclass(frozen=True, slots=True)
class EvidenceMembershipDTO:
    membership_id: str
    context_type: str
    context_id: str
    role: str
    is_primary: bool
    source_reference_ids: tuple[str, ...]
    review_status: str
    note: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.membership_id,
            "contextType": self.context_type,
            "contextId": self.context_id,
            "role": self.role,
            "isPrimary": self.is_primary,
            "sourceReferenceIds": list(self.source_reference_ids),
            "reviewStatus": self.review_status,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class EvidenceActorDTO:
    record: EvidenceActorRecord

    def to_dict(self) -> dict[str, object]:
        roles = []
        for membership in self.record.memberships:
            roles.append(
                {
                    "role": membership.role,
                    "caseIds": (
                        [membership.context_id] if membership.context_type == "case" else []
                    ),
                    "proceedingIds": (
                        [membership.context_id] if membership.context_type == "proceeding" else []
                    ),
                    "sourceReferenceIds": (
                        [membership.source_reference_id]
                        if membership.source_reference_id is not None
                        else []
                    ),
                    "reviewStatus": membership.review_status,
                }
            )
        return {
            "id": self.record.actor_id,
            "actorType": self.record.actor_type,
            "displayName": self.record.display_name,
            "normalizedName": self.record.normalized_name,
            "roles": roles,
            "contacts": [],
            "identifiers": [],
            "sourceReferenceIds": list(self.record.source_reference_ids),
            "reviewStatus": self.record.review_status,
            "notes": self.record.notes,
            "version": self.record.version,
        }


@dataclass(frozen=True, slots=True)
class EvidenceDocumentDTO:
    record: EvidenceDocumentRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record.document_id,
            "caseIds": _context_ids(self.record.memberships, "case"),
            "memberships": [_membership_dto(item).to_dict() for item in self.record.memberships],
            "title": self.record.title,
            "label": self.record.label,
            "subtitle": None,
            "date": None,
            "documentType": self.record.document_type,
            "processRole": self.record.process_role,
            "dates": [],
            "summary": self.record.summary,
            "actorIds": list(self.record.actor_ids),
            "fileIds": list(self.record.file_ids),
            "attachmentDocumentIds": list(self.record.attachment_document_ids),
            "claimIds": list(self.record.claim_ids),
            "eventIds": list(self.record.event_ids),
            "relationIds": list(self.record.relation_ids),
            "amounts": [],
            "sourceReferenceIds": list(self.record.source_reference_ids),
            "classification": self.record.classification,
            "reviewStatus": self.record.review_status,
            "isKey": self.record.is_key,
            "version": self.record.version,
        }


@dataclass(frozen=True, slots=True)
class EvidenceEventDTO:
    record: EvidenceEventRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record.event_id,
            "caseIds": _context_ids(self.record.memberships, "case"),
            "memberships": [_membership_dto(item).to_dict() for item in self.record.memberships],
            "title": self.record.title,
            "label": self.record.title,
            "subtitle": None,
            "date": self.record.event_at,
            "eventType": self.record.event_type,
            "dates": [],
            "description": self.record.description,
            "actorIds": list(self.record.actor_ids),
            "documentIds": list(self.record.document_ids),
            "claimIds": list(self.record.claim_ids),
            "relationIds": list(self.record.relation_ids),
            "sourceReferenceIds": list(self.record.source_reference_ids),
            "classification": self.record.classification,
            "status": self.record.workflow_status,
            "reviewStatus": self.record.review_status,
            "processConsequence": self.record.process_consequence,
            "nextAction": self.record.next_action,
            "deadline": self.record.deadline,
            "version": self.record.version,
        }


@dataclass(frozen=True, slots=True)
class SourceReferenceDTO:
    record: SourceReferenceRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record.source_reference_id,
            "sourceEntity": {
                "type": self.record.source_entity_type,
                "id": self.record.source_entity_id,
            },
            "sourceFileId": self.record.source_file_id,
            "locationType": self.record.location_type,
            "location": self.record.location_value,
            "excerpt": self.record.excerpt,
            "sha256": self.record.source_sha256,
            "createdBy": self.record.created_by,
            "createdAt": self.record.created_at.isoformat(),
            "reviewStatus": self.record.review_status,
            "note": self.record.note,
            "version": self.record.version,
        }


@dataclass(frozen=True, slots=True)
class ClaimDTO:
    record: ClaimRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record.claim_id,
            "subject": {"type": self.record.subject_type, "id": self.record.subject_id},
            "text": self.record.claim_text,
            "classification": self.record.classification,
            "assertedByActorIds": list(self.record.asserted_by_actor_ids),
            "basisDocumentIds": list(self.record.basis_document_ids),
            "sourceReferenceIds": list(self.record.source_reference_ids),
            "legalCitationIds": [],
            "reviewStatus": self.record.review_status,
            "reviewDecisionIds": list(self.record.review_decision_ids),
            "uncertaintyNote": self.record.uncertainty_note,
            "processConsequence": self.record.process_consequence,
            "memberships": [_membership_dto(item).to_dict() for item in self.record.memberships],
            "version": self.record.version,
        }


@dataclass(frozen=True, slots=True)
class EvidenceRelationDTO:
    record: EvidenceRelationRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record.relation_id,
            "fromType": self.record.from_type,
            "fromId": self.record.from_id,
            "toType": self.record.to_type,
            "toId": self.record.to_id,
            "relationType": self.record.relation_type,
            "label": self.record.label,
            "basisDocumentIds": list(self.record.basis_document_ids),
            "sourceReferenceIds": list(self.record.source_reference_ids),
            "classification": self.record.classification,
            "reviewStatus": self.record.review_status,
            "reviewDecisionIds": list(self.record.review_decision_ids),
            "uncertaintyNote": self.record.uncertainty_note,
            "validFrom": self.record.valid_from,
            "validTo": self.record.valid_to,
            "version": self.record.version,
        }


@dataclass(frozen=True, slots=True)
class ReviewDecisionDTO:
    record: ReviewDecisionRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record.decision_id,
            "subject": {"type": self.record.subject_type, "id": self.record.subject_id},
            "decision": self.record.decision,
            "previousStatus": self.record.previous_status,
            "newStatus": self.record.new_status,
            "actorId": self.record.actor_id,
            "decidedAt": self.record.decided_at.isoformat(),
            "basisSourceReferenceIds": list(self.record.source_reference_ids),
            "note": self.record.note,
            "subjectVersion": self.record.subject_version,
            "origin": self.record.decision_origin,
        }


@dataclass(frozen=True, slots=True)
class FindingDTO:
    record: FindingRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record.finding_id,
            "fingerprint": self.record.fingerprint,
            "findingType": self.record.finding_type,
            "title": self.record.title,
            "description": self.record.description,
            "severity": self.record.severity,
            "confidence": self.record.confidence,
            "detector": {
                "name": self.record.detector_name,
                "version": self.record.detector_version,
            },
            "processingRunId": self.record.processing_run_id,
            "automaticStatus": self.record.automatic_status,
            "automaticVersion": self.record.automatic_version,
            "reviewStatus": self.record.review_status,
            "reviewVersion": self.record.review_version,
            "subjects": [
                {"type": item.entity_type, "id": item.entity_id} for item in self.record.subjects
            ],
            "sourceReferenceIds": list(self.record.source_reference_ids),
            "reviewDecisionIds": list(self.record.review_decision_ids),
            "firstObservedAt": self.record.first_observed_at.isoformat(),
            "lastObservedAt": self.record.last_observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class TimelineItemDTO:
    record: TimelineRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "entity": {"type": self.record.entity_type, "id": self.record.entity_id},
            "title": self.record.title,
            "occurredAt": self.record.occurred_at,
            "reviewStatus": self.record.review_status,
        }


@dataclass(frozen=True, slots=True)
class SourceContextDTO:
    record: SourceContextRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceReference": SourceReferenceDTO(self.record.source).to_dict(),
            "subjectExists": self.record.subject_exists,
            "linkedClaimIds": list(self.record.linked_claim_ids),
            "linkedRelationIds": list(self.record.linked_relation_ids),
            "linkedFindingIds": list(self.record.linked_finding_ids),
        }


@dataclass(frozen=True, slots=True)
class CompatibilityReviewDTO:
    record: CompatibilityReviewRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "subjectType": self.record.subject_type,
            "externalId": self.record.external_id,
            "status": self.record.current_status,
            "note": self.record.note,
            "version": self.record.version,
            "updatedAt": self.record.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class CaseEvidenceDTO:
    case_id: str
    limit: int
    offset: int
    actors: tuple[EvidenceActorDTO, ...]
    documents: tuple[EvidenceDocumentDTO, ...]
    events: tuple[EvidenceEventDTO, ...]
    claims: tuple[ClaimDTO, ...]
    relations: tuple[EvidenceRelationDTO, ...]
    source_references: tuple[SourceReferenceDTO, ...]
    findings: tuple[FindingDTO, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": "1.1.0",
            "caseId": self.case_id,
            "page": {"limit": self.limit, "offset": self.offset},
            "ordering": "stable-domain-order-v1",
            "actors": [item.to_dict() for item in self.actors],
            "documents": [item.to_dict() for item in self.documents],
            "events": [item.to_dict() for item in self.events],
            "claims": [item.to_dict() for item in self.claims],
            "relations": [item.to_dict() for item in self.relations],
            "sourceReferences": [item.to_dict() for item in self.source_references],
            "findings": [item.to_dict() for item in self.findings],
            "authority": "sqlite",
        }


class EvidenceService:
    def __init__(
        self,
        unit_of_work_factory: EvidenceUnitOfWorkFactory,
        ids: IdProvider,
        clock: Clock,
    ):
        self._unit_of_work_factory = unit_of_work_factory
        self._ids = ids
        self._clock = clock

    def create_actor(self, command: CreateEvidenceActorCommand) -> EvidenceActorDTO:
        created_by = self._required_text(command.created_by, "created_by")
        actor_type = self._choice(command.actor_type, _ACTOR_TYPES, "actor_type")
        display_name = self._required_text(command.display_name, "display_name")
        review_status = self._review_status(command.review_status)
        occurred_at = self._clock.now()
        actor_id = self._ids.new_id()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            memberships = self._memberships(
                unit_of_work.evidence,
                entity_type="actor",
                entity_id=actor_id,
                inputs=command.memberships,
                occurred_at=occurred_at,
            )
            record = EvidenceActorRecord(
                actor_id=actor_id,
                actor_type=actor_type,
                display_name=display_name,
                normalized_name=self._normalize_name(display_name),
                review_status=review_status,
                notes=self._optional_text(command.notes),
                version=1,
                created_at=occurred_at,
                updated_at=occurred_at,
                memberships=memberships,
            )
            unit_of_work.evidence.add_actor(
                record,
                memberships=memberships,
                created_by=created_by,
            )
            saved = self._require_actor(unit_of_work.evidence, actor_id)
            unit_of_work.commit()
        return EvidenceActorDTO(saved)

    def create_document(self, command: CreateEvidenceDocumentCommand) -> EvidenceDocumentDTO:
        created_by = self._required_text(command.created_by, "created_by")
        title = self._required_text(command.title, "title")
        classification = self._classification(command.classification)
        review_status = self._review_status(command.review_status)
        occurred_at = self._clock.now()
        document_id = self._ids.new_id()
        file_ids = self._unique_texts(command.file_ids, "file_ids")
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            for file_id in file_ids:
                if file_id == document_id:
                    raise ValidationError(
                        "File identity не може дорівнювати document identity",
                        {"field": "file_ids"},
                    )
                self._require_entity(repository, "file", file_id)
            memberships = self._memberships(
                repository,
                entity_type="document",
                entity_id=document_id,
                inputs=command.memberships,
                occurred_at=occurred_at,
            )
            record = EvidenceDocumentRecord(
                document_id=document_id,
                title=title,
                label=self._optional_text(command.label) or title,
                document_type=self._optional_text(command.document_type),
                category=self._optional_text(command.category),
                source=self._optional_text(command.source),
                origin_format=self._optional_text(command.origin_format),
                summary=self._optional_text(command.summary),
                process_role=self._optional_text(command.process_role),
                classification=classification,
                review_status=review_status,
                is_key=bool(command.is_key),
                version=1,
                created_at=occurred_at,
                updated_at=occurred_at,
                memberships=memberships,
                file_ids=file_ids,
            )
            repository.add_document(
                record,
                memberships=memberships,
                file_ids=file_ids,
                created_by=created_by,
            )
            saved = self._require_document(repository, document_id)
            unit_of_work.commit()
        return EvidenceDocumentDTO(saved)

    def create_event(self, command: CreateEvidenceEventCommand) -> EvidenceEventDTO:
        created_by = self._required_text(command.created_by, "created_by")
        title = self._required_text(command.title, "title")
        classification = self._classification(command.classification)
        review_status = self._review_status(command.review_status)
        event_at = self._optional_iso(command.event_at, "event_at")
        deadline = self._optional_iso(command.deadline, "deadline")
        actor_ids = self._unique_texts(command.actor_ids, "actor_ids")
        document_ids = self._unique_texts(command.document_ids, "document_ids")
        occurred_at = self._clock.now()
        event_id = self._ids.new_id()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            for actor_id in actor_ids:
                self._require_entity(repository, "actor", actor_id)
            for document_id in document_ids:
                self._require_entity(repository, "document", document_id)
            memberships = self._memberships(
                repository,
                entity_type="event",
                entity_id=event_id,
                inputs=command.memberships,
                occurred_at=occurred_at,
            )
            record = EvidenceEventRecord(
                event_id=event_id,
                title=title,
                event_type=self._optional_text(command.event_type),
                event_at=event_at,
                description=self._optional_text(command.description),
                workflow_status=self._optional_text(command.workflow_status),
                classification=classification,
                review_status=review_status,
                process_consequence=self._optional_text(command.process_consequence),
                next_action=self._optional_text(command.next_action),
                deadline=deadline,
                version=1,
                created_at=occurred_at,
                updated_at=occurred_at,
                memberships=memberships,
                actor_ids=actor_ids,
                document_ids=document_ids,
            )
            repository.add_event(
                record,
                memberships=memberships,
                actor_ids=actor_ids,
                document_ids=document_ids,
                created_by=created_by,
            )
            saved = self._require_event(repository, event_id)
            unit_of_work.commit()
        return EvidenceEventDTO(saved)

    def create_source_reference(self, command: CreateSourceReferenceCommand) -> SourceReferenceDTO:
        created_by = self._required_text(command.created_by, "created_by")
        location_type = self._choice(command.location_type, _LOCATION_TYPES, "location_type")
        source_type = command.source_entity.entity_type
        source_id = self._required_text(command.source_entity.entity_id, "source_entity.id")
        if source_type != "manual_note" and source_type not in _SOURCE_ENTITY_TYPES:
            raise ValidationError(
                "Непідтримуваний source entity type", {"field": "source_entity.type"}
            )
        if source_type == "manual_note" and location_type != "manual_note":
            raise ValidationError(
                "manual_note source потребує location_type=manual_note",
                {"field": "location_type"},
            )
        review_status = self._review_status(command.review_status)
        sha256 = self._optional_sha256(command.source_sha256)
        occurred_at = self._clock.now()
        source_reference_id = self._ids.new_id()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            if source_type != "manual_note":
                self._require_entity(repository, source_type, source_id)
            source_file_id = self._optional_text(command.source_file_id)
            if source_file_id is not None:
                self._require_entity(repository, "file", source_file_id)
                stored_sha = repository.file_sha256(source_file_id)
                if (
                    sha256 is not None
                    and stored_sha is not None
                    and stored_sha.casefold() != sha256
                ):
                    raise ConflictError(
                        "Source SHA-256 не відповідає authoritative file record",
                        {"resource": "source_reference"},
                    )
            elif location_type in {"page", "paragraph", "timecode", "bounding_box", "whole_file"}:
                raise ValidationError(
                    "Цей location_type потребує source_file_id",
                    {"field": "source_file_id"},
                )
            record = SourceReferenceRecord(
                source_reference_id=source_reference_id,
                source_entity_type=source_type,
                source_entity_id=source_id,
                source_file_id=source_file_id,
                location_type=location_type,
                location_value=self._optional_text(command.location_value),
                excerpt=self._optional_text(command.excerpt),
                source_sha256=sha256,
                review_status=review_status,
                created_by=created_by,
                created_at=occurred_at,
                note=self._optional_text(command.note),
                version=1,
            )
            repository.add_source_reference(record)
            saved = self._require_source(repository, source_reference_id)
            unit_of_work.commit()
        return SourceReferenceDTO(saved)

    def create_claim(self, command: CreateClaimCommand) -> ClaimDTO:
        created_by = self._required_text(command.created_by, "created_by")
        text = self._required_text(command.text, "text")
        classification = self._classification(command.classification)
        review_status = self._review_status(command.review_status)
        actor_ids = self._unique_texts(command.asserted_by_actor_ids, "asserted_by_actor_ids")
        document_ids = self._unique_texts(command.basis_document_ids, "basis_document_ids")
        source_ids = self._unique_texts(command.source_reference_ids, "source_reference_ids")
        self._confirmed_basis(classification, review_status, document_ids, source_ids, "claim")
        occurred_at = self._clock.now()
        claim_id = self._ids.new_id()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            subject = self._validated_reference(
                repository,
                command.subject,
                allowed_types=_CLAIM_SUBJECT_TYPES,
            )
            self._require_entities(repository, "actor", actor_ids)
            self._require_entities(repository, "document", document_ids)
            self._require_sources(repository, source_ids)
            memberships = self._memberships(
                repository,
                entity_type="claim",
                entity_id=claim_id,
                inputs=command.memberships,
                occurred_at=occurred_at,
            )
            record = ClaimRecord(
                claim_id=claim_id,
                subject_type=subject.entity_type,
                subject_id=subject.entity_id,
                claim_text=text,
                classification=classification,
                review_status=review_status,
                uncertainty_note=self._optional_text(command.uncertainty_note),
                process_consequence=self._optional_text(command.process_consequence),
                version=1,
                created_at=occurred_at,
                updated_at=occurred_at,
                asserted_by_actor_ids=actor_ids,
                basis_document_ids=document_ids,
                source_reference_ids=source_ids,
                memberships=memberships,
            )
            repository.add_claim(record, memberships=memberships, created_by=created_by)
            saved = self._require_claim(repository, claim_id)
            unit_of_work.commit()
        return ClaimDTO(saved)

    def create_relation(self, command: CreateEvidenceRelationCommand) -> EvidenceRelationDTO:
        created_by = self._required_text(command.created_by, "created_by")
        relation_type = self._machine_code(command.relation_type, "relation_type")
        classification = self._classification(command.classification)
        review_status = self._review_status(command.review_status)
        document_ids = self._unique_texts(command.basis_document_ids, "basis_document_ids")
        source_ids = self._unique_texts(command.source_reference_ids, "source_reference_ids")
        self._confirmed_basis(classification, review_status, document_ids, source_ids, "relation")
        valid_from = self._optional_iso(command.valid_from, "valid_from")
        valid_to = self._optional_iso(command.valid_to, "valid_to")
        if valid_from is not None and valid_to is not None and valid_from > valid_to:
            raise ValidationError("valid_from не може бути пізніше valid_to")
        occurred_at = self._clock.now()
        relation_id = self._ids.new_id()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            from_entity = self._validated_reference(
                repository,
                command.from_entity,
                allowed_types=_RELATION_ENDPOINT_TYPES,
            )
            to_entity = self._validated_reference(
                repository,
                command.to_entity,
                allowed_types=_RELATION_ENDPOINT_TYPES,
            )
            if from_entity == to_entity:
                raise ValidationError("Relation не може посилатися сама на себе")
            self._require_entities(repository, "document", document_ids)
            self._require_sources(repository, source_ids)
            record = EvidenceRelationRecord(
                relation_id=relation_id,
                from_type=from_entity.entity_type,
                from_id=from_entity.entity_id,
                to_type=to_entity.entity_type,
                to_id=to_entity.entity_id,
                relation_type=relation_type,
                label=self._optional_text(command.label),
                classification=classification,
                review_status=review_status,
                uncertainty_note=self._optional_text(command.uncertainty_note),
                valid_from=valid_from,
                valid_to=valid_to,
                version=1,
                created_at=occurred_at,
                updated_at=occurred_at,
                basis_document_ids=document_ids,
                source_reference_ids=source_ids,
            )
            repository.add_relation(record, created_by=created_by)
            saved = self._require_relation(repository, relation_id)
            unit_of_work.commit()
        return EvidenceRelationDTO(saved)

    def review(self, command: ReviewEvidenceCommand) -> ReviewDecisionDTO:
        subject_type = command.subject.entity_type
        subject_id = self._required_text(command.subject.entity_id, "subject.id")
        if subject_type not in _REVIEWABLE_ENTITY_TYPES:
            raise ValidationError("Непідтримуваний review subject type", {"field": "subject.type"})
        decision = self._choice(command.decision, _DECISIONS, "decision")
        new_status = self._review_status(command.new_status)
        self._decision_transition(decision, new_status)
        actor_id = self._required_text(command.actor_id, "actor_id")
        expected_version = self._positive_version(command.expected_version)
        source_ids = self._unique_texts(command.source_reference_ids, "source_reference_ids")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            current_status, current_version = self._review_subject_state(
                repository, subject_type, subject_id
            )
            if current_version != expected_version:
                raise ConflictError(
                    "Evidence entity було змінено іншим рішенням",
                    {"expectedVersion": expected_version, "actualVersion": current_version},
                )
            self._require_sources(repository, source_ids)
            if subject_type == "claim":
                claim = self._require_claim(repository, subject_id)
                self._confirmed_basis(
                    claim.classification,
                    new_status,
                    claim.basis_document_ids,
                    claim.source_reference_ids,
                    "claim",
                )
            if subject_type == "relation":
                relation = self._require_relation(repository, subject_id)
                self._confirmed_basis(
                    relation.classification,
                    new_status,
                    relation.basis_document_ids,
                    relation.source_reference_ids,
                    "relation",
                )
            record = ReviewDecisionRecord(
                decision_id=self._ids.new_id(),
                subject_type=subject_type,
                subject_id=subject_id,
                decision=decision,
                previous_status=current_status,
                new_status=new_status,
                actor_id=actor_id,
                decided_at=occurred_at,
                note=self._optional_text(command.note),
                subject_version=expected_version + 1,
                decision_origin="user",
                source_reference_ids=source_ids,
            )
            saved = repository.add_review_decision(record, expected_version=expected_version)
            unit_of_work.commit()
        return ReviewDecisionDTO(saved)

    def record_finding(self, command: RecordFindingCommand) -> FindingDTO:
        return self._record_finding(command, allow_legacy_subjects=False)

    def record_compatibility_finding(self, command: RecordFindingCommand) -> FindingDTO:
        return self._record_finding(command, allow_legacy_subjects=True)

    def _record_finding(
        self,
        command: RecordFindingCommand,
        *,
        allow_legacy_subjects: bool,
    ) -> FindingDTO:
        fingerprint = self._required_text(command.fingerprint, "fingerprint").upper()
        if _HEX_FINGERPRINT.fullmatch(fingerprint) is None:
            raise ValidationError("Finding fingerprint має бути 16..128 hex символів")
        finding_type = self._machine_code(command.finding_type, "finding_type")
        title = self._required_text(command.title, "title")
        description = self._required_text(command.description, "description")
        severity = self._choice(command.severity, _FINDING_SEVERITIES, "severity")
        detector_name = self._required_text(command.detector_name, "detector_name")
        detector_version = self._required_text(command.detector_version, "detector_version")
        observation_status = self._choice(
            command.observation_status, _FINDING_OBSERVATIONS, "observation_status"
        )
        confidence = self._confidence(command.confidence)
        source_ids = self._unique_texts(command.source_reference_ids, "source_reference_ids")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            subjects: list[EntityReferenceRecord] = []
            for item in command.subjects:
                entity_type = item.entity_type
                entity_id = self._required_text(item.entity_id, "subjects.id")
                if entity_type == "legacy_document" and allow_legacy_subjects:
                    subjects.append(EntityReferenceRecord(entity_type, entity_id))
                    continue
                subjects.append(self._validated_reference(repository, item))
            subject_records = tuple(subjects)
            if not subject_records and not source_ids:
                raise ValidationError("Finding потребує subject або source reference")
            if len({(item.entity_type, item.entity_id) for item in subject_records}) != len(
                subject_records
            ):
                raise ValidationError("Finding subjects мають бути унікальними")
            self._require_sources(repository, source_ids)
            processing_run_id = self._optional_text(command.processing_run_id)
            if processing_run_id is not None and not repository.processing_run_exists(
                processing_run_id
            ):
                raise NotFoundError("Processing run не знайдено", {"resource": "processing_run"})
            current = repository.get_finding_by_fingerprint(fingerprint)
            if current is None and observation_status == "not_detected":
                raise ValidationError("Новий finding не може починатися з not_detected")
            record = FindingRecord(
                finding_id=current.finding_id if current is not None else self._ids.new_id(),
                fingerprint=fingerprint,
                finding_type=finding_type,
                title=title,
                description=description,
                severity=severity,
                confidence=confidence,
                detector_name=detector_name,
                detector_version=detector_version,
                processing_run_id=processing_run_id,
                automatic_status=observation_status,
                automatic_version=(current.automatic_version + 1 if current is not None else 1),
                review_status=(current.review_status if current is not None else "unreviewed"),
                review_version=(current.review_version if current is not None else 0),
                first_observed_at=(
                    current.first_observed_at if current is not None else occurred_at
                ),
                last_observed_at=occurred_at,
                created_at=(current.created_at if current is not None else occurred_at),
                updated_at=occurred_at,
                subjects=subject_records,
                source_reference_ids=source_ids,
                review_decision_ids=(current.review_decision_ids if current is not None else ()),
            )
            saved = repository.record_finding_observation(
                record,
                observation_status=(
                    "compatibility_import" if allow_legacy_subjects else observation_status
                ),
                details=dict(command.details or {}),
            )
            unit_of_work.commit()
        return FindingDTO(saved)

    def review_finding(self, command: ReviewFindingCommand) -> FindingDTO:
        finding_id = self._required_text(command.finding_id, "finding_id")
        decision = self._choice(command.decision, _FINDING_DECISIONS, "decision")
        new_status = self._choice(command.new_status, _FINDING_REVIEW_STATUSES, "new_status")
        actor_id = self._required_text(command.actor_id, "actor_id")
        expected_version = self._nonnegative_version(command.expected_version)
        source_ids = self._unique_texts(command.source_reference_ids, "source_reference_ids")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            finding = repository.get_finding(finding_id)
            if finding is None:
                raise NotFoundError("Finding не знайдено", {"resource": "finding"})
            if finding.review_version != expected_version:
                raise ConflictError(
                    "Finding review було змінено іншим рішенням",
                    {
                        "expectedVersion": expected_version,
                        "actualVersion": finding.review_version,
                    },
                )
            self._require_sources(repository, source_ids)
            record = ReviewDecisionRecord(
                decision_id=self._ids.new_id(),
                subject_type="finding",
                subject_id=finding_id,
                decision=decision,
                previous_status=finding.review_status,
                new_status=new_status,
                actor_id=actor_id,
                decided_at=occurred_at,
                note=self._optional_text(command.note),
                subject_version=expected_version + 1,
                decision_origin="user",
                source_reference_ids=source_ids,
            )
            saved = repository.review_finding(record, expected_version=expected_version)
            unit_of_work.commit()
        return FindingDTO(saved)

    def get_case_evidence(self, query: GetCaseEvidenceQuery) -> CaseEvidenceDTO:
        case_id = self._required_text(query.case_id, "case_id")
        limit, offset = self._page(query.limit, query.offset)
        with self._unit_of_work_factory(write=False) as unit_of_work:
            repository = unit_of_work.evidence
            self._require_entity(repository, "case", case_id)
            result = CaseEvidenceDTO(
                case_id=case_id,
                limit=limit,
                offset=offset,
                actors=tuple(
                    EvidenceActorDTO(item)
                    for item in repository.list_actors_for_case(case_id, limit=limit, offset=offset)
                ),
                documents=tuple(
                    EvidenceDocumentDTO(item)
                    for item in repository.list_documents_for_case(
                        case_id, limit=limit, offset=offset
                    )
                ),
                events=tuple(
                    EvidenceEventDTO(item)
                    for item in repository.list_events_for_case(case_id, limit=limit, offset=offset)
                ),
                claims=tuple(
                    ClaimDTO(item)
                    for item in repository.list_claims_for_case(case_id, limit=limit, offset=offset)
                ),
                relations=tuple(
                    EvidenceRelationDTO(item)
                    for item in repository.list_relations_for_case(
                        case_id, limit=limit, offset=offset
                    )
                ),
                source_references=tuple(
                    SourceReferenceDTO(item)
                    for item in repository.list_sources_for_case(
                        case_id, limit=limit, offset=offset
                    )
                ),
                findings=tuple(
                    FindingDTO(item)
                    for item in repository.list_findings_for_case(
                        case_id, limit=limit, offset=offset
                    )
                ),
            )
            unit_of_work.rollback()
        return result

    def list_timeline(self, query: ListEvidenceTimelineQuery) -> tuple[TimelineItemDTO, ...]:
        case_id = self._required_text(query.case_id, "case_id")
        limit, offset = self._page(query.limit, query.offset)
        with self._unit_of_work_factory(write=False) as unit_of_work:
            repository = unit_of_work.evidence
            self._require_entity(repository, "case", case_id)
            result = tuple(
                TimelineItemDTO(item)
                for item in repository.list_timeline(case_id, limit=limit, offset=offset)
            )
            unit_of_work.rollback()
        return result

    def get_source_context(self, query: GetSourceContextQuery) -> SourceContextDTO:
        source_reference_id = self._required_text(query.source_reference_id, "source_reference_id")
        with self._unit_of_work_factory(write=False) as unit_of_work:
            record = unit_of_work.evidence.get_source_context(source_reference_id)
            if record is None:
                raise NotFoundError(
                    "Source reference не знайдено", {"resource": "source_reference"}
                )
            unit_of_work.rollback()
        return SourceContextDTO(record)

    def list_review_history(self, query: ListReviewHistoryQuery) -> tuple[ReviewDecisionDTO, ...]:
        subject_type = query.subject_type
        subject_id = self._required_text(query.subject_id, "subject_id")
        limit, offset = self._page(query.limit, query.offset)
        with self._unit_of_work_factory(write=False) as unit_of_work:
            repository = unit_of_work.evidence
            if subject_type == "finding":
                if repository.get_finding(subject_id) is None:
                    raise NotFoundError("Finding не знайдено", {"resource": "finding"})
                rows = repository.list_finding_reviews(subject_id, limit=limit, offset=offset)
            else:
                if subject_type not in _REVIEWABLE_ENTITY_TYPES:
                    raise ValidationError("Непідтримуваний review subject type")
                self._require_entity(repository, subject_type, subject_id)
                rows = repository.list_review_decisions(
                    subject_type, subject_id, limit=limit, offset=offset
                )
            unit_of_work.rollback()
        return tuple(ReviewDecisionDTO(item) for item in rows)

    def import_compatibility_reviews(
        self,
        *,
        subject_type: str,
        source_token: str,
        values: Mapping[str, Mapping[str, object]],
    ) -> int:
        self._compatibility_subject_type(subject_type)
        token = self._required_text(source_token, "source_token")
        if _SHA256.fullmatch(token) is None:
            raise ValidationError("Compatibility source_token має бути SHA-256")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            if repository.compatibility_import_seen(token):
                unit_of_work.rollback()
                return 0
            existing = {
                item.external_id for item in repository.list_compatibility_reviews(subject_type)
            }
            imported = 0
            for external_id, raw in sorted(values.items()):
                normalized_id = self._required_text(external_id, "external_id")
                if normalized_id in existing or not isinstance(raw, Mapping):
                    continue
                status = self._compatibility_status(subject_type, raw.get("status"))
                note = self._optional_text(
                    str(raw.get("note")) if raw.get("note") is not None else None
                )
                repository.set_compatibility_review(
                    CompatibilityReviewRecord(
                        subject_type=subject_type,
                        external_id=normalized_id,
                        current_status=status,
                        note=note,
                        version=1,
                        updated_at=occurred_at,
                    ),
                    decision_id=self._ids.new_id(),
                    actor_id="system:compatibility-import",
                    expected_version=None,
                    decision_origin="compatibility_import",
                )
                imported += 1
            repository.record_compatibility_import(
                source_token=token,
                subject_type=subject_type,
                imported_count=imported,
                imported_at=occurred_at,
            )
            unit_of_work.commit()
        return imported

    def set_compatibility_review(
        self, command: SetCompatibilityReviewCommand
    ) -> CompatibilityReviewDTO:
        subject_type = self._compatibility_subject_type(command.subject_type)
        external_id = self._required_text(command.external_id, "external_id")
        status = self._compatibility_status(subject_type, command.status)
        actor_id = self._required_text(command.actor_id, "actor_id")
        if command.expected_version is not None:
            self._positive_version(command.expected_version)
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.evidence
            current = {
                item.external_id: item
                for item in repository.list_compatibility_reviews(subject_type)
            }.get(external_id)
            if command.expected_version is not None:
                actual = current.version if current is not None else 0
                if command.expected_version != actual:
                    raise ConflictError(
                        "Compatibility review було змінено іншим рішенням",
                        {
                            "expectedVersion": command.expected_version,
                            "actualVersion": actual,
                        },
                    )
            review = CompatibilityReviewRecord(
                subject_type=subject_type,
                external_id=external_id,
                current_status=status,
                note=self._optional_text(command.note),
                version=(current.version + 1 if current is not None else 1),
                updated_at=occurred_at,
            )
            saved = repository.set_compatibility_review(
                review,
                decision_id=self._ids.new_id(),
                actor_id=actor_id,
                expected_version=(current.version if current is not None else None),
                decision_origin="user",
            )
            unit_of_work.commit()
        return CompatibilityReviewDTO(saved)

    def list_compatibility_reviews(self, subject_type: str) -> tuple[CompatibilityReviewDTO, ...]:
        subject_type = self._compatibility_subject_type(subject_type)
        with self._unit_of_work_factory(write=False) as unit_of_work:
            rows = unit_of_work.evidence.list_compatibility_reviews(subject_type)
            unit_of_work.rollback()
        return tuple(CompatibilityReviewDTO(item) for item in rows)

    def _memberships(
        self,
        repository: EvidenceRepositoryPort,
        *,
        entity_type: str,
        entity_id: str,
        inputs: tuple[EvidenceMembershipInput, ...],
        occurred_at: datetime,
    ) -> tuple[EvidenceMembershipRecord, ...]:
        rows: list[EvidenceMembershipRecord] = []
        keys: set[tuple[str, str, str]] = set()
        for item in inputs:
            context_type = self._choice(item.context_type, {"case", "proceeding"}, "context_type")
            context_id = self._required_text(item.context_id, "context_id")
            self._require_entity(repository, context_type, context_id)
            role = self._required_text(item.role, "role")
            key = (context_type, context_id, role)
            if key in keys:
                raise ValidationError("Memberships мають бути унікальними")
            keys.add(key)
            source_reference_id = self._optional_text(item.source_reference_id)
            if source_reference_id is not None:
                self._require_entity(repository, "source_reference", source_reference_id)
            rows.append(
                EvidenceMembershipRecord(
                    membership_id=self._ids.new_id(),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    context_type=context_type,
                    context_id=context_id,
                    role=role,
                    is_primary=bool(item.is_primary),
                    source_reference_id=source_reference_id,
                    review_status=self._review_status(item.review_status),
                    note=self._optional_text(item.note),
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
            )
        return tuple(rows)

    def _validated_reference(
        self,
        repository: EvidenceRepositoryPort,
        reference: EntityReferenceInput,
        *,
        allowed_types: set[str] | None = None,
    ) -> EntityReferenceRecord:
        entity_type = reference.entity_type
        if entity_type not in (allowed_types or _ENTITY_TYPES):
            raise ValidationError("Непідтримуваний entity type", {"field": "entity.type"})
        entity_id = self._required_text(reference.entity_id, "entity.id")
        self._require_entity(repository, entity_type, entity_id)
        return EntityReferenceRecord(entity_type, entity_id)

    @staticmethod
    def _require_entity(
        repository: EvidenceRepositoryPort, entity_type: str, entity_id: str
    ) -> None:
        if not repository.entity_exists(entity_type, entity_id):
            raise NotFoundError(
                "Пов’язану evidence entity не знайдено",
                {"resource": entity_type},
            )

    def _require_entities(
        self,
        repository: EvidenceRepositoryPort,
        entity_type: str,
        entity_ids: tuple[str, ...],
    ) -> None:
        for entity_id in entity_ids:
            self._require_entity(repository, entity_type, entity_id)

    def _require_sources(
        self, repository: EvidenceRepositoryPort, source_ids: tuple[str, ...]
    ) -> None:
        self._require_entities(repository, "source_reference", source_ids)

    @staticmethod
    def _confirmed_basis(
        classification: str,
        review_status: str,
        document_ids: tuple[str, ...],
        source_ids: tuple[str, ...],
        resource: str,
    ) -> None:
        if (classification == "confirmed_fact" or review_status == "confirmed") and not (
            document_ids or source_ids
        ):
            raise ValidationError(
                "Confirmed claim/relation потребує evidence basis",
                {"resource": resource},
            )

    @staticmethod
    def _decision_transition(decision: str, new_status: str) -> None:
        allowed: dict[str, set[str]] = {
            "confirm": {"confirmed"},
            "reject": {"rejected"},
            "request_review": {"manual_review_required", "in_review"},
            "resolve": {"resolved"},
            "supersede": {"superseded"},
            "merge": {"resolved", "superseded"},
            "split": {"resolved", "superseded"},
        }
        if new_status not in allowed[decision]:
            raise ValidationError(
                "Decision і new_status утворюють непідтримуваний transition",
                {"decision": decision, "newStatus": new_status},
            )

    def _review_subject_state(
        self,
        repository: EvidenceRepositoryPort,
        subject_type: str,
        subject_id: str,
    ) -> tuple[str, int]:
        record: object | None
        if subject_type == "actor":
            record = repository.get_actor(subject_id)
        elif subject_type == "document":
            record = repository.get_document(subject_id)
        elif subject_type == "event":
            record = repository.get_event(subject_id)
        elif subject_type == "claim":
            record = repository.get_claim(subject_id)
        elif subject_type == "relation":
            record = repository.get_relation(subject_id)
        else:
            record = repository.get_source_reference(subject_id)
        if record is None:
            raise NotFoundError("Review subject не знайдено", {"resource": subject_type})
        return str(getattr(record, "review_status")), int(getattr(record, "version"))

    @staticmethod
    def _require_actor(repository: EvidenceRepositoryPort, actor_id: str) -> EvidenceActorRecord:
        record = repository.get_actor(actor_id)
        if record is None:
            raise NotFoundError("Actor не знайдено", {"resource": "actor"})
        return record

    @staticmethod
    def _require_document(
        repository: EvidenceRepositoryPort, document_id: str
    ) -> EvidenceDocumentRecord:
        record = repository.get_document(document_id)
        if record is None:
            raise NotFoundError("Document не знайдено", {"resource": "document"})
        return record

    @staticmethod
    def _require_event(repository: EvidenceRepositoryPort, event_id: str) -> EvidenceEventRecord:
        record = repository.get_event(event_id)
        if record is None:
            raise NotFoundError("Event не знайдено", {"resource": "event"})
        return record

    @staticmethod
    def _require_source(
        repository: EvidenceRepositoryPort, source_id: str
    ) -> SourceReferenceRecord:
        record = repository.get_source_reference(source_id)
        if record is None:
            raise NotFoundError("Source reference не знайдено", {"resource": "source_reference"})
        return record

    @staticmethod
    def _require_claim(repository: EvidenceRepositoryPort, claim_id: str) -> ClaimRecord:
        record = repository.get_claim(claim_id)
        if record is None:
            raise NotFoundError("Claim не знайдено", {"resource": "claim"})
        return record

    @staticmethod
    def _require_relation(
        repository: EvidenceRepositoryPort, relation_id: str
    ) -> EvidenceRelationRecord:
        record = repository.get_relation(relation_id)
        if record is None:
            raise NotFoundError("Relation не знайдено", {"resource": "relation"})
        return record

    @staticmethod
    def _required_text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Поле має бути непорожнім", {"field": field})
        normalized = value.strip()
        if len(normalized) > 500_000 or any(ord(character) < 32 for character in normalized):
            raise ValidationError("Поле має непідтримуваний формат", {"field": field})
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _choice(cls, value: object, choices: set[str], field: str) -> str:
        normalized = cls._required_text(value, field)
        if normalized not in choices:
            raise ValidationError("Непідтримуване значення", {"field": field})
        return normalized

    @classmethod
    def _machine_code(cls, value: object, field: str) -> str:
        normalized = cls._required_text(value, field)
        if _MACHINE_CODE.fullmatch(normalized) is None:
            raise ValidationError("Поле має бути stable machine code", {"field": field})
        return normalized

    @classmethod
    def _review_status(cls, value: object) -> str:
        return cls._choice(value, _REVIEW_STATUSES, "review_status")

    @classmethod
    def _classification(cls, value: object) -> str:
        return cls._choice(value, _CLASSIFICATIONS, "classification")

    @classmethod
    def _unique_texts(cls, values: tuple[str, ...], field: str) -> tuple[str, ...]:
        normalized = tuple(cls._required_text(value, field) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValidationError("IDs мають бути унікальними", {"field": field})
        return normalized

    @staticmethod
    def _normalize_name(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    @staticmethod
    def _optional_iso(value: str | None, field: str) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        try:
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError("Поле має бути ISO-8601 datetime", {"field": field}) from exc
        return normalized

    @staticmethod
    def _optional_sha256(value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if _SHA256.fullmatch(normalized) is None:
            raise ValidationError("SHA-256 має містити 64 hex символи")
        return normalized

    @staticmethod
    def _confidence(value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError("confidence має бути числом або null")
        normalized = float(value)
        if not 0.0 <= normalized <= 1.0:
            raise ValidationError("confidence має бути у межах 0..1")
        return normalized

    @staticmethod
    def _positive_version(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValidationError("expected_version має бути додатним integer")
        return value

    @staticmethod
    def _nonnegative_version(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValidationError("expected_version має бути non-negative integer")
        return value

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValidationError("limit має бути integer у межах 1..200")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValidationError("offset має бути non-negative integer")
        return limit, offset

    @staticmethod
    def _compatibility_subject_type(value: str) -> str:
        if value not in {"legacy_document", "legacy_finding"}:
            raise ValidationError("Непідтримуваний compatibility subject type")
        return value

    @classmethod
    def _compatibility_status(cls, subject_type: str, value: object) -> str:
        choices = (
            _DOCUMENT_WORK_STATUSES
            if subject_type == "legacy_document"
            else _LEGACY_FINDING_STATUSES
        )
        return cls._choice(value, choices, "status")


def _membership_dto(record: EvidenceMembershipRecord) -> EvidenceMembershipDTO:
    return EvidenceMembershipDTO(
        membership_id=record.membership_id,
        context_type=record.context_type,
        context_id=record.context_id,
        role=record.role,
        is_primary=record.is_primary,
        source_reference_ids=(
            (record.source_reference_id,) if record.source_reference_id is not None else ()
        ),
        review_status=record.review_status,
        note=record.note,
    )


def _context_ids(memberships: tuple[EvidenceMembershipRecord, ...], context_type: str) -> list[str]:
    return sorted({item.context_id for item in memberships if item.context_type == context_type})
