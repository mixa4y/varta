from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self


@dataclass(frozen=True, slots=True)
class WorkspaceCaseRecord:
    case_id: str
    case_number: str | None
    name: str | None
    status: str | None
    created_at: datetime
    updated_at: datetime
    normalized_case_number: str | None = None
    proceeding_ids: tuple[str, ...] = ()
    file_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceProceedingRecord:
    proceeding_id: str
    proceeding_number: str | None
    name: str | None
    status: str | None
    created_at: datetime
    updated_at: datetime
    case_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseBootstrapRecord:
    intake_case_id: str
    intake_entry_id: str
    file_id: str
    status: str
    confirmed_case_id: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class CaseCandidateRecord:
    candidate_id: str
    intake_case_id: str
    case_id: str | None
    raw_value: str
    normalized_value: str | None
    detection_source: str
    source_location: str | None
    confidence: float | None
    review_status: str
    evidence_basis: str | None
    tool_name: str | None
    tool_version: str | None
    external_reference_system: str | None
    external_reference_kind: str | None
    external_reference_value: str | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FileContextMembershipRecord:
    membership_id: str
    file_id: str
    context_type: str
    context_id: str
    role: str
    origin: str
    actor_id: str
    note: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentContextMembershipRecord:
    membership_id: str
    document_id: str
    context_type: str
    context_id: str
    role: str
    actor_id: str
    note: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActiveCasePreferenceRecord:
    preference_id: str
    active_case_id: str | None
    updated_by: str
    updated_at: datetime


class WorkspaceRepositoryPort(Protocol):
    def get_bootstrap(self, intake_case_id: str) -> CaseBootstrapRecord | None: ...

    def list_bootstraps(self, *, pending_only: bool = False) -> tuple[CaseBootstrapRecord, ...]: ...

    def list_candidates(self, intake_case_id: str) -> tuple[CaseCandidateRecord, ...]: ...

    def add_candidate(self, candidate: CaseCandidateRecord) -> bool: ...

    def decide_candidates(
        self,
        intake_case_id: str,
        *,
        selected_normalized_value: str | None,
        case_id: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> None: ...

    def set_bootstrap_status(
        self,
        intake_case_id: str,
        *,
        status: str,
        occurred_at: datetime,
        candidate_id: str | None = None,
        case_id: str | None = None,
        actor_id: str | None = None,
        note: str | None = None,
    ) -> None: ...

    def list_cases(self) -> tuple[WorkspaceCaseRecord, ...]: ...

    def get_case(self, case_id: str) -> WorkspaceCaseRecord | None: ...

    def add_case(self, case: WorkspaceCaseRecord, *, actor_id: str) -> None: ...

    def register_case_number(
        self,
        *,
        registry_id: str,
        case_id: str,
        raw_value: str,
        normalized_value: str,
        source_kind: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> None: ...

    def get_external_reference_case(
        self,
        *,
        system: str,
        kind: str,
        normalized_value: str,
    ) -> str | None: ...

    def add_external_reference(
        self,
        *,
        reference_id: str,
        case_id: str,
        system: str,
        kind: str,
        raw_value: str,
        normalized_value: str,
        evidence_basis: str,
        source_location: str | None,
        occurred_at: datetime,
    ) -> None: ...

    def list_proceedings(self) -> tuple[WorkspaceProceedingRecord, ...]: ...

    def get_proceeding(self, proceeding_id: str) -> WorkspaceProceedingRecord | None: ...

    def add_proceeding(
        self,
        proceeding: WorkspaceProceedingRecord,
        *,
        actor_id: str,
    ) -> None: ...

    def link_case_proceeding(
        self,
        *,
        case_id: str,
        proceeding_id: str,
        relationship_kind: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> None: ...

    def file_exists(self, file_id: str) -> bool: ...

    def add_file_membership(self, membership: FileContextMembershipRecord) -> bool: ...

    def list_file_memberships(self, file_id: str) -> tuple[FileContextMembershipRecord, ...]: ...

    def document_exists(self, document_id: str) -> bool: ...

    def add_document_membership(self, membership: DocumentContextMembershipRecord) -> bool: ...

    def list_document_memberships(
        self,
        document_id: str,
    ) -> tuple[DocumentContextMembershipRecord, ...]: ...

    def get_active_case(self, preference_id: str) -> ActiveCasePreferenceRecord | None: ...

    def set_active_case(self, preference: ActiveCasePreferenceRecord) -> None: ...

    def add_review_decision(
        self,
        *,
        decision_id: str,
        file_id: str,
        previous_status: str,
        new_status: str,
        actor_id: str,
        occurred_at: datetime,
        note: str | None,
    ) -> None: ...


class WorkspaceUnitOfWork(Protocol):
    @property
    def workspace(self) -> WorkspaceRepositoryPort: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class WorkspaceUnitOfWorkFactory(Protocol):
    def __call__(self, *, write: bool = False) -> WorkspaceUnitOfWork: ...
