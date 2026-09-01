from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

from case_docket.application.evidence_map_source import (
    CaseScopedSourceItem,
    EvidenceMapExclusionDTO,
    EvidenceMapSourceError,
    EvidenceMapSourcePorts,
)
from case_docket.application.evidence_ports import (
    ClaimRecord,
    EvidenceActorRecord,
    EvidenceDocumentRecord,
    EvidenceEventRecord,
    EvidenceRelationRecord,
    FindingRecord,
    ReviewDecisionRecord,
    SourceReferenceRecord,
)
from case_docket.application.ports import ManagedFileRecord
from case_docket.application.profile import CaseProfileService, GetCaseProfileQuery
from case_docket.application.profile_ports import CaseProfileDTO
from case_docket.application.workspace_ports import (
    WorkspaceCaseRecord,
    WorkspaceProceedingRecord,
)

from .sqlite_uow import SQLiteUnitOfWorkFactory


Record = TypeVar("Record", covariant=True)


class _CasePage(Protocol[Record]):
    def __call__(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Record, ...]: ...


class _ReviewPage(Protocol):
    def __call__(
        self,
        subject_type: str,
        subject_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[ReviewDecisionRecord, ...]: ...


class _FindingReviewPage(Protocol):
    def __call__(
        self,
        finding_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[ReviewDecisionRecord, ...]: ...


class SQLiteEvidenceMapSourcePorts(EvidenceMapSourcePorts):
    """Concrete R02 adapter over the existing authoritative SQLite repositories."""

    def __init__(self, unit_of_work_factory: SQLiteUnitOfWorkFactory):
        self._unit_of_work_factory = unit_of_work_factory

    def get_case(self, case_id: str) -> WorkspaceCaseRecord | None:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            return unit_of_work.workspace.get_case(case_id)

    def get_profile(self, query: GetCaseProfileQuery) -> CaseProfileDTO:
        return CaseProfileService(self._unit_of_work_factory).get(query)

    def list_proceedings(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[WorkspaceProceedingRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            self._require_case(unit_of_work.workspace.get_case(case_id), case_id)
            records = tuple(
                sorted(
                    (
                        record
                        for record in unit_of_work.workspace.list_proceedings()
                        if case_id in record.case_ids
                    ),
                    key=lambda item: item.proceeding_id,
                )
            )
        return self._page(records, case_id, limit=limit, offset=offset)

    def list_files(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[ManagedFileRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            case = self._require_case(unit_of_work.workspace.get_case(case_id), case_id)
            records: list[ManagedFileRecord] = []
            for file_id in sorted(case.file_ids):
                record = unit_of_work.files.get(file_id)
                if record is None:
                    raise EvidenceMapSourceError(f"Case references missing managed file: {file_id}")
                records.append(record)
        return self._page(records, case_id, limit=limit, offset=offset)

    def list_actors(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[EvidenceActorRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            records = unit_of_work.evidence.list_actors_for_case(
                case_id, limit=limit, offset=offset
            )
        return self._scope(records, case_id)

    def list_documents(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[EvidenceDocumentRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            records = unit_of_work.evidence.list_documents_for_case(
                case_id, limit=limit, offset=offset
            )
        return self._scope(records, case_id)

    def list_events(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[EvidenceEventRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            records = unit_of_work.evidence.list_events_for_case(
                case_id, limit=limit, offset=offset
            )
        return self._scope(records, case_id)

    def list_source_references(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[SourceReferenceRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            records = unit_of_work.evidence.list_sources_for_case(
                case_id, limit=limit, offset=offset
            )
        return self._scope(records, case_id)

    def list_claims(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[ClaimRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            records = unit_of_work.evidence.list_claims_for_case(
                case_id, limit=limit, offset=offset
            )
        return self._scope(records, case_id)

    def list_relations(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[EvidenceRelationRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            records = unit_of_work.evidence.list_relations_for_case(
                case_id, limit=limit, offset=offset
            )
        return self._scope(records, case_id)

    def list_reviews(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[ReviewDecisionRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            case = self._require_case(unit_of_work.workspace.get_case(case_id), case_id)
            evidence = unit_of_work.evidence
            subjects: list[tuple[str, str]] = [("case", case_id)]
            subjects.extend(
                ("proceeding", record.proceeding_id)
                for record in unit_of_work.workspace.list_proceedings()
                if case_id in record.case_ids
            )
            subjects.extend(("file", file_id) for file_id in case.file_ids)

            actors = self._all_case_records(evidence.list_actors_for_case, case_id)
            documents = self._all_case_records(evidence.list_documents_for_case, case_id)
            events = self._all_case_records(evidence.list_events_for_case, case_id)
            source_references = self._all_case_records(evidence.list_sources_for_case, case_id)
            claims = self._all_case_records(evidence.list_claims_for_case, case_id)
            relations = self._all_case_records(evidence.list_relations_for_case, case_id)
            findings = self._all_case_records(evidence.list_findings_for_case, case_id)
            subjects.extend(("actor", item.actor_id) for item in actors)
            subjects.extend(("document", item.document_id) for item in documents)
            subjects.extend(("event", item.event_id) for item in events)
            subjects.extend(
                ("source_reference", item.source_reference_id) for item in source_references
            )
            subjects.extend(("claim", item.claim_id) for item in claims)
            subjects.extend(("relation", item.relation_id) for item in relations)

            decisions: dict[str, ReviewDecisionRecord] = {}
            for subject_type, subject_id in sorted(set(subjects)):
                for decision in self._all_reviews(
                    evidence.list_review_decisions,
                    subject_type,
                    subject_id,
                ):
                    decisions[decision.decision_id] = decision
            for finding in findings:
                for decision in self._all_finding_reviews(
                    evidence.list_finding_reviews,
                    finding.finding_id,
                ):
                    decisions[decision.decision_id] = decision

        ordered = tuple(
            sorted(
                decisions.values(),
                key=lambda item: (item.decided_at, item.decision_id),
            )
        )
        return self._page(ordered, case_id, limit=limit, offset=offset)

    def list_findings(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[FindingRecord], ...]:
        with self._unit_of_work_factory(write=False) as unit_of_work:
            records = unit_of_work.evidence.list_findings_for_case(
                case_id, limit=limit, offset=offset
            )
        return self._scope(records, case_id)

    def list_exclusions(
        self,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[EvidenceMapExclusionDTO], ...]:
        del limit, offset
        with self._unit_of_work_factory(write=False) as unit_of_work:
            self._require_case(unit_of_work.workspace.get_case(case_id), case_id)
        # R02 has no exclusion persistence table. An explicit provider call returns
        # the authoritative empty collection; later stages may replace this adapter.
        return ()

    @staticmethod
    def _require_case(
        value: WorkspaceCaseRecord | None,
        case_id: str,
    ) -> WorkspaceCaseRecord:
        if value is None:
            raise EvidenceMapSourceError(f"Unknown case: {case_id}")
        return value

    @staticmethod
    def _scope(
        records: Sequence[Record],
        case_id: str,
    ) -> tuple[CaseScopedSourceItem[Record], ...]:
        return tuple(CaseScopedSourceItem(case_id=case_id, record=item) for item in records)

    @classmethod
    def _page(
        cls,
        records: Sequence[Record],
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CaseScopedSourceItem[Record], ...]:
        cls._validate_page(limit, offset)
        return cls._scope(records[offset : offset + limit], case_id)

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if limit < 1 or offset < 0:
            raise EvidenceMapSourceError("Invalid pagination request")

    @classmethod
    def _all_case_records(
        cls,
        provider: _CasePage[Record],
        case_id: str,
    ) -> tuple[Record, ...]:
        return cls._all_pages(lambda limit, offset: provider(case_id, limit=limit, offset=offset))

    @classmethod
    def _all_reviews(
        cls,
        provider: _ReviewPage,
        subject_type: str,
        subject_id: str,
    ) -> tuple[ReviewDecisionRecord, ...]:
        return cls._all_pages(
            lambda limit, offset: provider(
                subject_type,
                subject_id,
                limit=limit,
                offset=offset,
            )
        )

    @classmethod
    def _all_finding_reviews(
        cls,
        provider: _FindingReviewPage,
        finding_id: str,
    ) -> tuple[ReviewDecisionRecord, ...]:
        return cls._all_pages(
            lambda limit, offset: provider(
                finding_id,
                limit=limit,
                offset=offset,
            )
        )

    @staticmethod
    def _all_pages(
        provider: Callable[[int, int], tuple[Record, ...]],
    ) -> tuple[Record, ...]:
        page_size = 200
        offset = 0
        result: list[Record] = []
        while True:
            page = provider(page_size, offset)
            result.extend(page)
            if len(page) < page_size:
                return tuple(result)
            offset += page_size
