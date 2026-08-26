from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol, Self


@dataclass(frozen=True, slots=True)
class EntityReferenceRecord:
    entity_type: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class EvidenceMembershipRecord:
    membership_id: str
    entity_type: str
    entity_id: str
    context_type: str
    context_id: str
    role: str
    is_primary: bool
    source_reference_id: str | None
    review_status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceActorRecord:
    actor_id: str
    actor_type: str
    display_name: str
    normalized_name: str | None
    review_status: str
    notes: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    memberships: tuple[EvidenceMembershipRecord, ...] = ()
    source_reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceDocumentRecord:
    document_id: str
    title: str
    label: str
    document_type: str | None
    category: str | None
    source: str | None
    origin_format: str | None
    summary: str | None
    process_role: str | None
    classification: str
    review_status: str
    is_key: bool
    version: int
    created_at: datetime
    updated_at: datetime
    memberships: tuple[EvidenceMembershipRecord, ...] = ()
    file_ids: tuple[str, ...] = ()
    actor_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    attachment_document_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    source_reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceEventRecord:
    event_id: str
    title: str
    event_type: str | None
    event_at: str | None
    description: str | None
    workflow_status: str | None
    classification: str
    review_status: str
    process_consequence: str | None
    next_action: str | None
    deadline: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    memberships: tuple[EvidenceMembershipRecord, ...] = ()
    actor_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    source_reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceReferenceRecord:
    source_reference_id: str
    source_entity_type: str
    source_entity_id: str
    source_file_id: str | None
    location_type: str
    location_value: str | None
    excerpt: str | None
    source_sha256: str | None
    review_status: str
    created_by: str
    created_at: datetime
    note: str | None
    version: int


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    claim_id: str
    subject_type: str
    subject_id: str
    claim_text: str
    classification: str
    review_status: str
    uncertainty_note: str | None
    process_consequence: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    asserted_by_actor_ids: tuple[str, ...] = ()
    basis_document_ids: tuple[str, ...] = ()
    source_reference_ids: tuple[str, ...] = ()
    review_decision_ids: tuple[str, ...] = ()
    memberships: tuple[EvidenceMembershipRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceRelationRecord:
    relation_id: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relation_type: str
    label: str | None
    classification: str
    review_status: str
    uncertainty_note: str | None
    valid_from: str | None
    valid_to: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    basis_document_ids: tuple[str, ...] = ()
    source_reference_ids: tuple[str, ...] = ()
    review_decision_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewDecisionRecord:
    decision_id: str
    subject_type: str
    subject_id: str
    decision: str
    previous_status: str | None
    new_status: str
    actor_id: str
    decided_at: datetime
    note: str | None
    subject_version: int
    decision_origin: str
    source_reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FindingRecord:
    finding_id: str
    fingerprint: str
    finding_type: str
    title: str
    description: str
    severity: str
    confidence: float | None
    detector_name: str
    detector_version: str
    processing_run_id: str | None
    automatic_status: str
    automatic_version: int
    review_status: str
    review_version: int
    first_observed_at: datetime
    last_observed_at: datetime
    created_at: datetime
    updated_at: datetime
    subjects: tuple[EntityReferenceRecord, ...] = ()
    source_reference_ids: tuple[str, ...] = ()
    review_decision_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TimelineRecord:
    entity_type: str
    entity_id: str
    title: str
    occurred_at: str
    review_status: str


@dataclass(frozen=True, slots=True)
class SourceContextRecord:
    source: SourceReferenceRecord
    subject_exists: bool
    linked_claim_ids: tuple[str, ...]
    linked_relation_ids: tuple[str, ...]
    linked_finding_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompatibilityReviewRecord:
    subject_type: str
    external_id: str
    current_status: str
    note: str | None
    version: int
    updated_at: datetime


class EvidenceRepositoryPort(Protocol):
    def entity_exists(self, entity_type: str, entity_id: str) -> bool: ...

    def processing_run_exists(self, processing_run_id: str) -> bool: ...

    def file_sha256(self, file_id: str) -> str | None: ...

    def add_actor(
        self,
        actor: EvidenceActorRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        created_by: str,
    ) -> None: ...

    def add_document(
        self,
        document: EvidenceDocumentRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        file_ids: tuple[str, ...],
        created_by: str,
    ) -> None: ...

    def add_event(
        self,
        event: EvidenceEventRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        actor_ids: tuple[str, ...],
        document_ids: tuple[str, ...],
        created_by: str,
    ) -> None: ...

    def add_source_reference(self, source: SourceReferenceRecord) -> None: ...

    def add_claim(
        self,
        claim: ClaimRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        created_by: str,
    ) -> None: ...

    def add_relation(
        self,
        relation: EvidenceRelationRecord,
        *,
        created_by: str,
    ) -> None: ...

    def get_actor(self, actor_id: str) -> EvidenceActorRecord | None: ...

    def get_document(self, document_id: str) -> EvidenceDocumentRecord | None: ...

    def get_event(self, event_id: str) -> EvidenceEventRecord | None: ...

    def get_source_reference(self, source_reference_id: str) -> SourceReferenceRecord | None: ...

    def get_claim(self, claim_id: str) -> ClaimRecord | None: ...

    def get_relation(self, relation_id: str) -> EvidenceRelationRecord | None: ...

    def list_actors_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceActorRecord, ...]: ...

    def list_documents_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceDocumentRecord, ...]: ...

    def list_events_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceEventRecord, ...]: ...

    def list_sources_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[SourceReferenceRecord, ...]: ...

    def list_claims_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[ClaimRecord, ...]: ...

    def list_relations_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceRelationRecord, ...]: ...

    def list_findings_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[FindingRecord, ...]: ...

    def list_timeline(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[TimelineRecord, ...]: ...

    def get_source_context(self, source_reference_id: str) -> SourceContextRecord | None: ...

    def add_review_decision(
        self,
        decision: ReviewDecisionRecord,
        *,
        expected_version: int,
    ) -> ReviewDecisionRecord: ...

    def list_review_decisions(
        self,
        subject_type: str,
        subject_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[ReviewDecisionRecord, ...]: ...

    def record_finding_observation(
        self,
        finding: FindingRecord,
        *,
        observation_status: str,
        details: Mapping[str, object],
    ) -> FindingRecord: ...

    def get_finding(self, finding_id: str) -> FindingRecord | None: ...

    def get_finding_by_fingerprint(self, fingerprint: str) -> FindingRecord | None: ...

    def review_finding(
        self,
        decision: ReviewDecisionRecord,
        *,
        expected_version: int,
    ) -> FindingRecord: ...

    def list_finding_reviews(
        self,
        finding_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[ReviewDecisionRecord, ...]: ...

    def compatibility_import_seen(self, source_token: str) -> bool: ...

    def record_compatibility_import(
        self,
        *,
        source_token: str,
        subject_type: str,
        imported_count: int,
        imported_at: datetime,
    ) -> None: ...

    def set_compatibility_review(
        self,
        review: CompatibilityReviewRecord,
        *,
        decision_id: str,
        actor_id: str,
        expected_version: int | None,
        decision_origin: str,
    ) -> CompatibilityReviewRecord: ...

    def list_compatibility_reviews(
        self,
        subject_type: str,
    ) -> tuple[CompatibilityReviewRecord, ...]: ...


class EvidenceUnitOfWork(Protocol):
    @property
    def evidence(self) -> EvidenceRepositoryPort: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class EvidenceUnitOfWorkFactory(Protocol):
    def __call__(self, *, write: bool = False) -> EvidenceUnitOfWork: ...
