from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from .errors import ConflictError, NotFoundError, ValidationError
from .ports import Clock, IdProvider
from .workspace_ports import (
    ActiveCasePreferenceRecord,
    CaseBootstrapRecord,
    CaseCandidateRecord,
    DocumentContextMembershipRecord,
    FileContextMembershipRecord,
    WorkspaceCaseRecord,
    WorkspaceProceedingRecord,
    WorkspaceRepositoryPort,
    WorkspaceUnitOfWorkFactory,
)


_DETECTION_SOURCES = frozenset(
    {
        "structured_metadata",
        "document_text",
        "ocr",
        "verified_manifest",
        "filename",
        "folder",
        "manual",
    }
)
_SOLE_EVIDENCE_SOURCES = frozenset(
    {"structured_metadata", "document_text", "ocr", "verified_manifest", "manual"}
)
_CASE_NUMBER_PATTERN = re.compile(
    r"(?<![\w/])(?:№\s*)?(\d{1,6}\s*/\s*\d{1,8}\s*/\s*\d{2,4})(?![\w/])",
    re.UNICODE,
)
_CASE_NUMBER_FULL = re.compile(r"\d{1,6}/\d{1,8}/\d{2,4}", re.UNICODE)


def normalize_case_number(raw_value: str) -> str | None:
    """Normalize a three-segment court case number without inventing missing parts."""

    if not isinstance(raw_value, str):
        return None
    value = unicodedata.normalize("NFKC", raw_value).strip()
    value = re.sub(r"^(?:справа|номер\s+справи)\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:№|N(?:o|r)?\.?)[\s:]*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", "", value)
    if not _CASE_NUMBER_FULL.fullmatch(value):
        return None
    normalized_digits: list[str] = []
    for character in value:
        if character == "/":
            normalized_digits.append(character)
            continue
        try:
            normalized_digits.append(str(unicodedata.decimal(character)))
        except (TypeError, ValueError):
            return None
    return "".join(normalized_digits)


def normalize_external_reference(raw_value: str) -> str:
    value = " ".join(unicodedata.normalize("NFKC", raw_value).split()).casefold()
    if not value:
        raise ValidationError("External reference не може бути порожнім")
    return value


def normalize_external_reference_component(raw_value: str, field: str) -> str:
    value = unicodedata.normalize("NFKC", raw_value).strip().casefold()
    if not value or any(ord(character) < 32 for character in value):
        raise ValidationError("External reference component є некоректним", {"field": field})
    return value


@dataclass(frozen=True, slots=True)
class CandidateSourceInput:
    text: str
    detection_source: str
    source_location: str
    evidence_basis: str
    confidence: float
    tool_name: str | None = None
    tool_version: str | None = None
    external_reference_system: str | None = None
    external_reference_kind: str | None = None
    external_reference_value: str | None = None


@dataclass(frozen=True, slots=True)
class RegisterCandidateSourcesCommand:
    intake_case_id: str
    sources: tuple[CandidateSourceInput, ...]
    actor_id: str = "system:candidate-detector"


@dataclass(frozen=True, slots=True)
class ConfirmCaseBootstrapCommand:
    intake_case_id: str
    actor_id: str
    candidate_id: str | None = None
    manual_case_number: str | None = None
    case_id: str | None = None
    create_case_name: str | None = None
    proceeding_ids: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalReferenceInput:
    system: str
    kind: str
    value: str
    evidence_basis: str
    source_location: str | None = None


@dataclass(frozen=True, slots=True)
class CreateWorkspaceCaseCommand:
    actor_id: str
    case_number: str | None = None
    name: str | None = None
    external_references: tuple[ExternalReferenceInput, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateWorkspaceProceedingCommand:
    actor_id: str
    case_ids: tuple[str, ...]
    proceeding_number: str | None = None
    name: str | None = None
    relationship_kind: str = "membership"


@dataclass(frozen=True, slots=True)
class AddFileMembershipsCommand:
    file_id: str
    actor_id: str
    case_ids: tuple[str, ...] = ()
    proceeding_ids: tuple[str, ...] = ()
    role: str = "evidence"
    note: str | None = None


@dataclass(frozen=True, slots=True)
class AddDocumentMembershipsCommand:
    document_id: str
    actor_id: str
    case_ids: tuple[str, ...] = ()
    proceeding_ids: tuple[str, ...] = ()
    role: str = "evidence"
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SelectActiveCaseCommand:
    preference_id: str
    actor_id: str
    active_case_id: str | None


@dataclass(frozen=True, slots=True)
class ListWorkspaceCasesQuery:
    pass


@dataclass(frozen=True, slots=True)
class ListPendingBootstrapReviewsQuery:
    pass


@dataclass(frozen=True, slots=True)
class GetActiveCaseQuery:
    preference_id: str


@dataclass(frozen=True, slots=True)
class CaseCandidateDTO:
    candidate_id: str
    case_id: str | None
    raw_value: str
    normalized_value: str | None
    detection_source: str
    source_location: str | None
    evidence_basis: str | None
    confidence: float | None
    tool_name: str | None
    tool_version: str | None
    review_status: str
    eligible_as_sole_evidence: bool
    external_reference: dict[str, str] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "candidateId": self.candidate_id,
            "caseId": self.case_id,
            "rawValue": self.raw_value,
            "normalizedValue": self.normalized_value,
            "detectionSource": self.detection_source,
            "sourceLocation": self.source_location,
            "evidenceBasis": self.evidence_basis,
            "confidence": self.confidence,
            "tool": (
                {"name": self.tool_name, "version": self.tool_version}
                if self.tool_name is not None or self.tool_version is not None
                else None
            ),
            "reviewStatus": self.review_status,
            "eligibleAsSoleEvidence": self.eligible_as_sole_evidence,
            "externalReference": self.external_reference,
        }


@dataclass(frozen=True, slots=True)
class BootstrapReviewDTO:
    intake_case_id: str
    intake_entry_id: str
    file_id: str
    status: str
    confirmed_case_id: str | None
    candidates: tuple[CaseCandidateDTO, ...]
    created_at: str
    updated_at: str
    resolved_at: str | None

    @property
    def distinct_candidate_count(self) -> int:
        return len(
            {
                candidate.normalized_value
                for candidate in self.candidates
                if candidate.normalized_value is not None
                and candidate.review_status not in {"rejected", "superseded"}
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "intakeCaseId": self.intake_case_id,
            "intakeEntryId": self.intake_entry_id,
            "fileId": self.file_id,
            "status": self.status,
            "confirmedCaseId": self.confirmed_case_id,
            "manualConfirmationRequired": self.status != "confirmed",
            "distinctCandidateCount": self.distinct_candidate_count,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "resolvedAt": self.resolved_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceCaseDTO:
    case_id: str
    case_number: str | None
    normalized_case_number: str | None
    name: str | None
    status: str | None
    proceeding_ids: tuple[str, ...]
    file_ids: tuple[str, ...]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "caseId": self.case_id,
            "caseNumber": self.case_number,
            "normalizedCaseNumber": self.normalized_case_number,
            "name": self.name,
            "status": self.status,
            "proceedingIds": list(self.proceeding_ids),
            "fileIds": list(self.file_ids),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceProceedingDTO:
    proceeding_id: str
    proceeding_number: str | None
    name: str | None
    status: str | None
    case_ids: tuple[str, ...]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "proceedingId": self.proceeding_id,
            "proceedingNumber": self.proceeding_number,
            "name": self.name,
            "status": self.status,
            "caseIds": list(self.case_ids),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class FileMembershipDTO:
    membership_id: str
    file_id: str
    context_type: str
    context_id: str
    role: str
    origin: str
    actor_id: str
    note: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "membershipId": self.membership_id,
            "fileId": self.file_id,
            "contextType": self.context_type,
            "contextId": self.context_id,
            "role": self.role,
            "origin": self.origin,
            "actorId": self.actor_id,
            "note": self.note,
            "createdAt": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class DocumentMembershipDTO:
    membership_id: str
    document_id: str
    context_type: str
    context_id: str
    role: str
    actor_id: str
    note: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "membershipId": self.membership_id,
            "documentId": self.document_id,
            "contextType": self.context_type,
            "contextId": self.context_id,
            "role": self.role,
            "actorId": self.actor_id,
            "note": self.note,
            "createdAt": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ActiveCaseDTO:
    preference_id: str
    active_case: WorkspaceCaseDTO | None
    updated_by: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "preferenceId": self.preference_id,
            "activeCase": self.active_case.to_dict() if self.active_case else None,
            "updatedBy": self.updated_by,
            "updatedAt": self.updated_at,
            "scope": "presentation_preference",
        }


class CaseNumberDetector:
    """Deterministic C07 extractor for candidate signals supplied by allowed adapters."""

    def detect(self, source: CandidateSourceInput) -> tuple[tuple[str, str], ...]:
        text = unicodedata.normalize("NFKC", source.text)
        found: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for match in _CASE_NUMBER_PATTERN.finditer(text):
            raw_value = match.group(1).strip()
            normalized = normalize_case_number(raw_value)
            if normalized is None or (raw_value, normalized) in seen:
                continue
            seen.add((raw_value, normalized))
            found.append((raw_value, normalized))
        return tuple(found)


class WorkspaceService:
    """C07 multi-case workspace and explicit case-bootstrap application boundary."""

    def __init__(
        self,
        unit_of_work_factory: WorkspaceUnitOfWorkFactory,
        ids: IdProvider,
        clock: Clock,
        detector: CaseNumberDetector | None = None,
    ):
        self._unit_of_work_factory = unit_of_work_factory
        self._ids = ids
        self._clock = clock
        self._detector = detector or CaseNumberDetector()

    def list_cases(
        self,
        query: ListWorkspaceCasesQuery | None = None,
    ) -> tuple[WorkspaceCaseDTO, ...]:
        del query
        with self._unit_of_work_factory() as unit_of_work:
            return tuple(self._case_dto(record) for record in unit_of_work.workspace.list_cases())

    def list_pending_bootstraps(
        self,
        query: ListPendingBootstrapReviewsQuery | None = None,
    ) -> tuple[BootstrapReviewDTO, ...]:
        del query
        with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.workspace
            return tuple(
                self._bootstrap_dto(repository, record)
                for record in repository.list_bootstraps(pending_only=True)
            )

    def register_candidate_sources(
        self,
        command: RegisterCandidateSourcesCommand,
    ) -> BootstrapReviewDTO:
        intake_case_id = self._required_text(command.intake_case_id, "intake_case_id")
        actor_id = self._required_text(command.actor_id, "actor_id")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.workspace
            bootstrap = self._require_bootstrap(repository, intake_case_id)
            if bootstrap.status == "confirmed":
                raise ConflictError(
                    "Case bootstrap уже підтверджено",
                    {"resource": "case_bootstrap"},
                )
            for source in command.sources:
                self._validate_source(source)
                for raw_value, normalized_value in self._detector.detect(source):
                    repository.add_candidate(
                        CaseCandidateRecord(
                            candidate_id=self._ids.new_id(),
                            intake_case_id=intake_case_id,
                            case_id=None,
                            raw_value=raw_value,
                            normalized_value=normalized_value,
                            detection_source=source.detection_source,
                            source_location=source.source_location,
                            confidence=source.confidence,
                            review_status="unreviewed",
                            evidence_basis=source.evidence_basis,
                            tool_name=source.tool_name,
                            tool_version=source.tool_version,
                            external_reference_system=source.external_reference_system,
                            external_reference_kind=source.external_reference_kind,
                            external_reference_value=source.external_reference_value,
                            decided_by=None,
                            decided_at=None,
                            created_at=occurred_at,
                        )
                    )
            candidates = repository.list_candidates(intake_case_id)
            target_status = self._pending_status(candidates)
            if target_status != bootstrap.status:
                repository.set_bootstrap_status(
                    intake_case_id,
                    status=target_status,
                    occurred_at=occurred_at,
                    actor_id=actor_id,
                    note="Candidate detection completed",
                )
            updated = self._require_bootstrap(repository, intake_case_id)
            result = self._bootstrap_dto(repository, updated)
            unit_of_work.commit()
        return result

    def confirm_bootstrap(self, command: ConfirmCaseBootstrapCommand) -> BootstrapReviewDTO:
        intake_case_id = self._required_text(command.intake_case_id, "intake_case_id")
        actor_id = self._required_text(command.actor_id, "actor_id")
        if command.candidate_id is not None and command.manual_case_number is not None:
            raise ValidationError(
                "candidate_id і manual_case_number взаємовиключні",
                {"resource": "case_bootstrap"},
            )
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.workspace
            bootstrap = self._require_bootstrap(repository, intake_case_id)
            if bootstrap.status == "confirmed":
                raise ConflictError(
                    "Case bootstrap уже підтверджено",
                    {"resource": "case_bootstrap"},
                )

            selected_candidate: CaseCandidateRecord | None = None
            normalized_value: str | None = None
            raw_value: str | None = None
            candidate_id = self._optional_text(command.candidate_id)
            if candidate_id is not None:
                selected_candidate = next(
                    (
                        candidate
                        for candidate in repository.list_candidates(intake_case_id)
                        if candidate.candidate_id == candidate_id
                    ),
                    None,
                )
                if selected_candidate is None:
                    raise NotFoundError(
                        "Candidate не знайдено в цьому bootstrap",
                        {"resource": "case_number_candidate"},
                    )
                normalized_value = selected_candidate.normalized_value
                raw_value = selected_candidate.raw_value
                if normalized_value is None:
                    raise ValidationError(
                        "Candidate не має валідного normalized number",
                        {"resource": "case_number_candidate"},
                    )
            elif command.manual_case_number is not None:
                raw_value = self._required_text(command.manual_case_number, "manual_case_number")
                normalized_value = normalize_case_number(raw_value)
                if normalized_value is None:
                    raise ValidationError(
                        "Номер справи має непідтримуваний формат",
                        {"field": "manual_case_number"},
                    )
                selected_candidate = CaseCandidateRecord(
                    candidate_id=self._ids.new_id(),
                    intake_case_id=intake_case_id,
                    case_id=None,
                    raw_value=raw_value,
                    normalized_value=normalized_value,
                    detection_source="manual",
                    source_location="manual_confirmation",
                    confidence=1.0,
                    review_status="unreviewed",
                    evidence_basis="explicit user confirmation",
                    tool_name=None,
                    tool_version=None,
                    external_reference_system=None,
                    external_reference_kind=None,
                    external_reference_value=None,
                    decided_by=None,
                    decided_at=None,
                    created_at=occurred_at,
                )
                repository.add_candidate(selected_candidate)

            requested_case_id = self._optional_text(command.case_id)
            if requested_case_id is None and normalized_value is None:
                raise ValidationError(
                    "Потрібен candidate/manual number або explicit case_id",
                    {"resource": "case_bootstrap"},
                )
            case = self._locate_or_create_case(
                repository,
                requested_case_id=requested_case_id,
                raw_value=raw_value,
                normalized_value=normalized_value,
                create_name=self._optional_text(command.create_case_name),
                actor_id=actor_id,
                occurred_at=occurred_at,
            )
            if selected_candidate is not None:
                self._attach_candidate_external_reference(
                    repository,
                    candidate=selected_candidate,
                    case_id=case.case_id,
                    occurred_at=occurred_at,
                )

            proceeding_ids = self._unique_ids(command.proceeding_ids, "proceeding_ids")
            for proceeding_id in proceeding_ids:
                proceeding = repository.get_proceeding(proceeding_id)
                if proceeding is None:
                    raise NotFoundError(
                        "Провадження не знайдено",
                        {"resource": "proceeding"},
                    )
                if case.case_id not in proceeding.case_ids:
                    raise ValidationError(
                        "Провадження не належить підтвердженій справі",
                        {"resource": "proceeding_membership"},
                    )

            repository.add_file_membership(
                FileContextMembershipRecord(
                    membership_id=self._ids.new_id(),
                    file_id=bootstrap.file_id,
                    context_type="case",
                    context_id=case.case_id,
                    role="evidence",
                    origin="bootstrap_confirmation",
                    actor_id=actor_id,
                    note=self._optional_text(command.note),
                    created_at=occurred_at,
                )
            )
            for proceeding_id in proceeding_ids:
                repository.add_file_membership(
                    FileContextMembershipRecord(
                        membership_id=self._ids.new_id(),
                        file_id=bootstrap.file_id,
                        context_type="proceeding",
                        context_id=proceeding_id,
                        role="evidence",
                        origin="bootstrap_confirmation",
                        actor_id=actor_id,
                        note=self._optional_text(command.note),
                        created_at=occurred_at,
                    )
                )

            repository.decide_candidates(
                intake_case_id,
                selected_normalized_value=normalized_value,
                case_id=case.case_id,
                actor_id=actor_id,
                occurred_at=occurred_at,
            )
            repository.set_bootstrap_status(
                intake_case_id,
                status="confirmed",
                occurred_at=occurred_at,
                candidate_id=(selected_candidate.candidate_id if selected_candidate else None),
                case_id=case.case_id,
                actor_id=actor_id,
                note=self._optional_text(command.note),
            )
            repository.add_review_decision(
                decision_id=self._ids.new_id(),
                file_id=bootstrap.file_id,
                previous_status=bootstrap.status,
                new_status="confirmed",
                actor_id=actor_id,
                occurred_at=occurred_at,
                note=self._optional_text(command.note),
            )
            updated = self._require_bootstrap(repository, intake_case_id)
            result = self._bootstrap_dto(repository, updated)
            unit_of_work.commit()
        return result

    def create_case(self, command: CreateWorkspaceCaseCommand) -> WorkspaceCaseDTO:
        actor_id = self._required_text(command.actor_id, "actor_id")
        raw_value = self._optional_text(command.case_number)
        normalized_value = normalize_case_number(raw_value) if raw_value else None
        if raw_value is not None and normalized_value is None:
            raise ValidationError("Номер справи має непідтримуваний формат")
        if raw_value is None and self._optional_text(command.name) is None:
            raise ValidationError("Справі потрібен номер або name")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.workspace
            if normalized_value is not None and self._matching_cases(
                repository.list_cases(), normalized_value
            ):
                raise ConflictError(
                    "Справу з таким normalized number уже зареєстровано",
                    {"resource": "case"},
                )
            record = self._new_case_record(
                raw_value=raw_value,
                name=self._optional_text(command.name),
                occurred_at=occurred_at,
            )
            repository.add_case(record, actor_id=actor_id)
            if normalized_value is not None and raw_value is not None:
                repository.register_case_number(
                    registry_id=self._ids.new_id(),
                    case_id=record.case_id,
                    raw_value=raw_value,
                    normalized_value=normalized_value,
                    source_kind="case_creation",
                    actor_id=actor_id,
                    occurred_at=occurred_at,
                )
            for reference in command.external_references:
                self._attach_external_reference_input(
                    repository,
                    reference=reference,
                    case_id=record.case_id,
                    occurred_at=occurred_at,
                )
            created = repository.get_case(record.case_id)
            if created is None:
                raise RuntimeError("Створена справа не читається у transaction")
            result = self._case_dto(created)
            unit_of_work.commit()
        return result

    def create_proceeding(
        self,
        command: CreateWorkspaceProceedingCommand,
    ) -> WorkspaceProceedingDTO:
        actor_id = self._required_text(command.actor_id, "actor_id")
        case_ids = self._unique_ids(command.case_ids, "case_ids")
        if not case_ids:
            raise ValidationError("Провадження потребує хоча б одну case membership")
        number = self._optional_text(command.proceeding_number)
        name = self._optional_text(command.name)
        if number is None and name is None:
            raise ValidationError("Провадженню потрібен number або name")
        if command.relationship_kind not in {"membership", "main"}:
            raise ValidationError("Некоректний relationship_kind")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.workspace
            for case_id in case_ids:
                if repository.get_case(case_id) is None:
                    raise NotFoundError("Справу не знайдено", {"resource": "case"})
            record = WorkspaceProceedingRecord(
                proceeding_id=self._ids.new_id(),
                proceeding_number=number,
                name=name,
                status="active",
                created_at=occurred_at,
                updated_at=occurred_at,
                case_ids=(),
            )
            repository.add_proceeding(record, actor_id=actor_id)
            for case_id in case_ids:
                repository.link_case_proceeding(
                    case_id=case_id,
                    proceeding_id=record.proceeding_id,
                    relationship_kind=command.relationship_kind,
                    actor_id=actor_id,
                    occurred_at=occurred_at,
                )
            created = repository.get_proceeding(record.proceeding_id)
            if created is None:
                raise RuntimeError("Створене провадження не читається у transaction")
            result = self._proceeding_dto(created)
            unit_of_work.commit()
        return result

    def add_file_memberships(
        self,
        command: AddFileMembershipsCommand,
    ) -> tuple[FileMembershipDTO, ...]:
        file_id = self._required_text(command.file_id, "file_id")
        actor_id = self._required_text(command.actor_id, "actor_id")
        role = self._required_text(command.role, "role")
        case_ids = self._unique_ids(command.case_ids, "case_ids")
        proceeding_ids = self._unique_ids(command.proceeding_ids, "proceeding_ids")
        if not case_ids and not proceeding_ids:
            raise ValidationError("Membership command потребує case або proceeding")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.workspace
            if not repository.file_exists(file_id):
                raise NotFoundError("File object не знайдено", {"resource": "file"})
            contexts = [("case", case_id) for case_id in case_ids]
            contexts.extend(("proceeding", proceeding_id) for proceeding_id in proceeding_ids)
            for context_type, context_id in contexts:
                if context_type == "case" and repository.get_case(context_id) is None:
                    raise NotFoundError("Справу не знайдено", {"resource": "case"})
                if context_type == "proceeding" and repository.get_proceeding(context_id) is None:
                    raise NotFoundError(
                        "Провадження не знайдено",
                        {"resource": "proceeding"},
                    )
                repository.add_file_membership(
                    FileContextMembershipRecord(
                        membership_id=self._ids.new_id(),
                        file_id=file_id,
                        context_type=context_type,
                        context_id=context_id,
                        role=role,
                        origin="manual_command",
                        actor_id=actor_id,
                        note=self._optional_text(command.note),
                        created_at=occurred_at,
                    )
                )
            result = tuple(
                self._membership_dto(record)
                for record in repository.list_file_memberships(file_id)
            )
            unit_of_work.commit()
        return result

    def add_document_memberships(
        self,
        command: AddDocumentMembershipsCommand,
    ) -> tuple[DocumentMembershipDTO, ...]:
        document_id = self._required_text(command.document_id, "document_id")
        actor_id = self._required_text(command.actor_id, "actor_id")
        role = self._required_text(command.role, "role")
        case_ids = self._unique_ids(command.case_ids, "case_ids")
        proceeding_ids = self._unique_ids(command.proceeding_ids, "proceeding_ids")
        if not case_ids and not proceeding_ids:
            raise ValidationError("Membership command потребує case або proceeding")
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.workspace
            if not repository.document_exists(document_id):
                raise NotFoundError("Document не знайдено", {"resource": "document"})
            contexts = [("case", case_id) for case_id in case_ids]
            contexts.extend(("proceeding", proceeding_id) for proceeding_id in proceeding_ids)
            for context_type, context_id in contexts:
                if context_type == "case" and repository.get_case(context_id) is None:
                    raise NotFoundError("Справу не знайдено", {"resource": "case"})
                if context_type == "proceeding" and repository.get_proceeding(context_id) is None:
                    raise NotFoundError(
                        "Провадження не знайдено",
                        {"resource": "proceeding"},
                    )
                repository.add_document_membership(
                    DocumentContextMembershipRecord(
                        membership_id=self._ids.new_id(),
                        document_id=document_id,
                        context_type=context_type,
                        context_id=context_id,
                        role=role,
                        actor_id=actor_id,
                        note=self._optional_text(command.note),
                        created_at=occurred_at,
                    )
                )
            result = tuple(
                self._document_membership_dto(record)
                for record in repository.list_document_memberships(document_id)
            )
            unit_of_work.commit()
        return result

    def get_active_case(self, query: GetActiveCaseQuery) -> ActiveCaseDTO:
        preference_id = self._required_text(query.preference_id, "preference_id")
        with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.workspace
            preference = repository.get_active_case(preference_id)
            return self._active_case_dto(repository, preference_id, preference)

    def select_active_case(self, command: SelectActiveCaseCommand) -> ActiveCaseDTO:
        preference_id = self._required_text(command.preference_id, "preference_id")
        actor_id = self._required_text(command.actor_id, "actor_id")
        active_case_id = self._optional_text(command.active_case_id)
        occurred_at = self._clock.now()
        with self._unit_of_work_factory(write=True) as unit_of_work:
            repository = unit_of_work.workspace
            if active_case_id is not None and repository.get_case(active_case_id) is None:
                raise NotFoundError("Справу не знайдено", {"resource": "case"})
            preference = ActiveCasePreferenceRecord(
                preference_id=preference_id,
                active_case_id=active_case_id,
                updated_by=actor_id,
                updated_at=occurred_at,
            )
            repository.set_active_case(preference)
            result = self._active_case_dto(repository, preference_id, preference)
            unit_of_work.commit()
        return result

    def _locate_or_create_case(
        self,
        repository: WorkspaceRepositoryPort,
        *,
        requested_case_id: str | None,
        raw_value: str | None,
        normalized_value: str | None,
        create_name: str | None,
        actor_id: str,
        occurred_at: datetime,
    ) -> WorkspaceCaseRecord:
        case: WorkspaceCaseRecord | None
        if requested_case_id is not None:
            case = repository.get_case(requested_case_id)
            if case is None:
                raise NotFoundError("Справу не знайдено", {"resource": "case"})
            existing_normalized = case.normalized_case_number or (
                normalize_case_number(case.case_number) if case.case_number else None
            )
            if (
                normalized_value is not None
                and existing_normalized is not None
                and normalized_value != existing_normalized
            ):
                raise ConflictError(
                    "Candidate number конфліктує з explicit case",
                    {"resource": "case_number"},
                )
        elif normalized_value is not None:
            matches = self._matching_cases(repository.list_cases(), normalized_value)
            if len(matches) > 1:
                raise ConflictError(
                    "Normalized number відповідає кільком справам; потрібне ручне рішення",
                    {"resource": "case_number"},
                )
            case = matches[0] if matches else None
        else:
            case = None

        if case is None:
            if normalized_value is None or raw_value is None:
                raise ValidationError("Новій справі потрібен підтверджений номер")
            case = self._new_case_record(
                raw_value=raw_value,
                name=create_name,
                occurred_at=occurred_at,
            )
            repository.add_case(case, actor_id=actor_id)

        if normalized_value is not None and raw_value is not None:
            registered = case.normalized_case_number
            if registered is None:
                repository.register_case_number(
                    registry_id=self._ids.new_id(),
                    case_id=case.case_id,
                    raw_value=raw_value,
                    normalized_value=normalized_value,
                    source_kind="manual_confirmation",
                    actor_id=actor_id,
                    occurred_at=occurred_at,
                )
                refreshed = repository.get_case(case.case_id)
                if refreshed is not None:
                    case = refreshed
        return case

    def _attach_candidate_external_reference(
        self,
        repository: WorkspaceRepositoryPort,
        *,
        candidate: CaseCandidateRecord,
        case_id: str,
        occurred_at: datetime,
    ) -> None:
        values = (
            candidate.external_reference_system,
            candidate.external_reference_kind,
            candidate.external_reference_value,
        )
        if not any(values):
            return
        if not all(values):
            raise ValidationError("Candidate external reference має неповний contract")
        raw_system, raw_kind, raw_value = (str(value) for value in values)
        system = normalize_external_reference_component(raw_system, "external_reference.system")
        kind = normalize_external_reference_component(raw_kind, "external_reference.kind")
        normalized = normalize_external_reference(raw_value)
        existing_case_id = repository.get_external_reference_case(
            system=system,
            kind=kind,
            normalized_value=normalized,
        )
        if existing_case_id is not None and existing_case_id != case_id:
            raise ConflictError(
                "External reference уже належить іншій справі",
                {"resource": "case_external_reference"},
            )
        if existing_case_id is None:
            repository.add_external_reference(
                reference_id=self._ids.new_id(),
                case_id=case_id,
                system=system,
                kind=kind,
                raw_value=raw_value,
                normalized_value=normalized,
                evidence_basis=candidate.evidence_basis or "candidate evidence",
                source_location=candidate.source_location,
                occurred_at=occurred_at,
            )

    def _attach_external_reference_input(
        self,
        repository: WorkspaceRepositoryPort,
        *,
        reference: ExternalReferenceInput,
        case_id: str,
        occurred_at: datetime,
    ) -> None:
        system = normalize_external_reference_component(
            self._required_text(reference.system, "external_reference.system"),
            "external_reference.system",
        )
        kind = normalize_external_reference_component(
            self._required_text(reference.kind, "external_reference.kind"),
            "external_reference.kind",
        )
        raw_value = self._required_text(reference.value, "external_reference.value")
        evidence_basis = self._required_text(
            reference.evidence_basis,
            "external_reference.evidence_basis",
        )
        normalized = normalize_external_reference(raw_value)
        existing_case_id = repository.get_external_reference_case(
            system=system,
            kind=kind,
            normalized_value=normalized,
        )
        if existing_case_id is not None and existing_case_id != case_id:
            raise ConflictError(
                "External reference уже належить іншій справі",
                {"resource": "case_external_reference"},
            )
        if existing_case_id is None:
            repository.add_external_reference(
                reference_id=self._ids.new_id(),
                case_id=case_id,
                system=system,
                kind=kind,
                raw_value=raw_value,
                normalized_value=normalized,
                evidence_basis=evidence_basis,
                source_location=self._optional_text(reference.source_location),
                occurred_at=occurred_at,
            )

    @staticmethod
    def _pending_status(candidates: tuple[CaseCandidateRecord, ...]) -> str:
        active = tuple(
            candidate
            for candidate in candidates
            if candidate.normalized_value is not None
            and candidate.review_status not in {"rejected", "superseded"}
        )
        normalized_values = {candidate.normalized_value for candidate in active}
        if len(normalized_values) != 1:
            return "manual_review_required"
        if not any(candidate.detection_source in _SOLE_EVIDENCE_SOURCES for candidate in active):
            return "manual_review_required"
        return "candidate_ready"

    @staticmethod
    def _matching_cases(
        cases: tuple[WorkspaceCaseRecord, ...],
        normalized_value: str,
    ) -> tuple[WorkspaceCaseRecord, ...]:
        return tuple(
            case
            for case in cases
            if (
                case.normalized_case_number
                or (normalize_case_number(case.case_number) if case.case_number else None)
            )
            == normalized_value
        )

    def _new_case_record(
        self,
        *,
        raw_value: str | None,
        name: str | None,
        occurred_at: datetime,
    ) -> WorkspaceCaseRecord:
        return WorkspaceCaseRecord(
            case_id=self._ids.new_id(),
            case_number=raw_value,
            name=name,
            status="active",
            created_at=occurred_at,
            updated_at=occurred_at,
        )

    @staticmethod
    def _validate_source(source: CandidateSourceInput) -> None:
        if source.detection_source not in _DETECTION_SOURCES:
            raise ValidationError(
                "Непідтримуване candidate detection_source",
                {"field": "detection_source"},
            )
        if not isinstance(source.text, str) or len(source.text) > 500_000:
            raise ValidationError("Candidate source text має непідтримуваний розмір")
        if not source.source_location.strip():
            raise ValidationError("Candidate source_location є обов’язковим")
        if not source.evidence_basis.strip():
            raise ValidationError("Candidate evidence_basis є обов’язковим")
        if not isinstance(source.confidence, (int, float)) or isinstance(
            source.confidence, bool
        ):
            raise ValidationError("Candidate confidence має бути числом")
        if not 0.0 <= float(source.confidence) <= 1.0:
            raise ValidationError("Candidate confidence має бути в межах 0..1")
        if source.detection_source != "manual" and (
            source.tool_name is None
            or not source.tool_name.strip()
            or source.tool_version is None
            or not source.tool_version.strip()
        ):
            raise ValidationError("Automatic candidate source потребує tool name/version")
        external_values = (
            source.external_reference_system,
            source.external_reference_kind,
            source.external_reference_value,
        )
        present = tuple(value is not None for value in external_values)
        if any(present) and not all(present):
            raise ValidationError("External reference поля мають бути передані разом")
        if all(present) and any(not str(value).strip() for value in external_values):
            raise ValidationError("External reference поля не можуть бути порожніми")

    @staticmethod
    def _require_bootstrap(
        repository: WorkspaceRepositoryPort,
        intake_case_id: str,
    ) -> CaseBootstrapRecord:
        bootstrap = repository.get_bootstrap(intake_case_id)
        if bootstrap is None:
            raise NotFoundError(
                "Pending case bootstrap не знайдено",
                {"resource": "case_bootstrap"},
            )
        return bootstrap

    def _bootstrap_dto(
        self,
        repository: WorkspaceRepositoryPort,
        bootstrap: CaseBootstrapRecord,
    ) -> BootstrapReviewDTO:
        candidates = tuple(
            self._candidate_dto(candidate)
            for candidate in repository.list_candidates(bootstrap.intake_case_id)
        )
        return BootstrapReviewDTO(
            intake_case_id=bootstrap.intake_case_id,
            intake_entry_id=bootstrap.intake_entry_id,
            file_id=bootstrap.file_id,
            status=bootstrap.status,
            confirmed_case_id=bootstrap.confirmed_case_id,
            candidates=candidates,
            created_at=bootstrap.created_at.isoformat(),
            updated_at=bootstrap.updated_at.isoformat(),
            resolved_at=bootstrap.resolved_at.isoformat() if bootstrap.resolved_at else None,
        )

    @staticmethod
    def _candidate_dto(candidate: CaseCandidateRecord) -> CaseCandidateDTO:
        external_reference = None
        if (
            candidate.external_reference_system is not None
            and candidate.external_reference_kind is not None
            and candidate.external_reference_value is not None
        ):
            external_reference = {
                "system": candidate.external_reference_system,
                "kind": candidate.external_reference_kind,
                "value": candidate.external_reference_value,
            }
        return CaseCandidateDTO(
            candidate_id=candidate.candidate_id,
            case_id=candidate.case_id,
            raw_value=candidate.raw_value,
            normalized_value=candidate.normalized_value,
            detection_source=candidate.detection_source,
            source_location=candidate.source_location,
            evidence_basis=candidate.evidence_basis,
            confidence=candidate.confidence,
            tool_name=candidate.tool_name,
            tool_version=candidate.tool_version,
            review_status=candidate.review_status,
            eligible_as_sole_evidence=(
                candidate.detection_source in _SOLE_EVIDENCE_SOURCES
            ),
            external_reference=external_reference,
        )

    @staticmethod
    def _case_dto(record: WorkspaceCaseRecord) -> WorkspaceCaseDTO:
        normalized = record.normalized_case_number or (
            normalize_case_number(record.case_number) if record.case_number else None
        )
        return WorkspaceCaseDTO(
            case_id=record.case_id,
            case_number=record.case_number,
            normalized_case_number=normalized,
            name=record.name,
            status=record.status,
            proceeding_ids=record.proceeding_ids,
            file_ids=record.file_ids,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )

    @staticmethod
    def _proceeding_dto(record: WorkspaceProceedingRecord) -> WorkspaceProceedingDTO:
        return WorkspaceProceedingDTO(
            proceeding_id=record.proceeding_id,
            proceeding_number=record.proceeding_number,
            name=record.name,
            status=record.status,
            case_ids=record.case_ids,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )

    @staticmethod
    def _membership_dto(record: FileContextMembershipRecord) -> FileMembershipDTO:
        return FileMembershipDTO(
            membership_id=record.membership_id,
            file_id=record.file_id,
            context_type=record.context_type,
            context_id=record.context_id,
            role=record.role,
            origin=record.origin,
            actor_id=record.actor_id,
            note=record.note,
            created_at=record.created_at.isoformat(),
        )

    @staticmethod
    def _document_membership_dto(
        record: DocumentContextMembershipRecord,
    ) -> DocumentMembershipDTO:
        return DocumentMembershipDTO(
            membership_id=record.membership_id,
            document_id=record.document_id,
            context_type=record.context_type,
            context_id=record.context_id,
            role=record.role,
            actor_id=record.actor_id,
            note=record.note,
            created_at=record.created_at.isoformat(),
        )

    def _active_case_dto(
        self,
        repository: WorkspaceRepositoryPort,
        preference_id: str,
        preference: ActiveCasePreferenceRecord | None,
    ) -> ActiveCaseDTO:
        if preference is None:
            return ActiveCaseDTO(preference_id, None, None, None)
        case = (
            repository.get_case(preference.active_case_id)
            if preference.active_case_id is not None
            else None
        )
        return ActiveCaseDTO(
            preference_id=preference_id,
            active_case=self._case_dto(case) if case is not None else None,
            updated_by=preference.updated_by,
            updated_at=preference.updated_at.isoformat(),
        )

    @staticmethod
    def _required_text(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Поле має бути непорожнім", {"field": field})
        if any(ord(character) < 32 for character in value):
            raise ValidationError("Поле містить control characters", {"field": field})
        return value.strip()

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _unique_ids(cls, values: tuple[str, ...], field: str) -> tuple[str, ...]:
        normalized = tuple(cls._required_text(value, field) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValidationError("IDs мають бути унікальними", {"field": field})
        return normalized
