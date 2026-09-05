from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application.evidence_map_source import (
    CaseScopedSourceItem,
    EvidenceMapExclusionDTO,
    EvidenceMapSourceError,
    EvidenceMapSourceQuery,
    EvidenceMapSourceQueryService,
)
from case_docket.application.evidence_ports import (
    ClaimRecord,
    EntityReferenceRecord,
    EvidenceActorRecord,
    EvidenceDocumentRecord,
    EvidenceEventRecord,
    EvidenceMembershipRecord,
    EvidenceRelationRecord,
    FindingRecord,
    ReviewDecisionRecord,
    SourceReferenceRecord,
)
from case_docket.application.ports import ManagedFileRecord
from case_docket.application.workspace_ports import (
    FileContextMembershipRecord,
    WorkspaceCaseRecord,
    WorkspaceProceedingRecord,
)
from case_docket.repository import SQLiteEvidenceMapSourcePorts, SQLiteUnitOfWorkFactory


CASE_ID = "case-synthetic-r02"
PROFILE_VERSION = "v1"
REVIEWER = "user:synthetic-r02-reviewer"
DAY_1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
DAY_2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
DAY_3 = datetime(2026, 1, 3, tzinfo=timezone.utc)
DAY_4 = datetime(2026, 1, 4, tzinfo=timezone.utc)
DAY_5 = datetime(2026, 1, 5, tzinfo=timezone.utc)


def _profile() -> dict[str, object]:
    return {
        "schemaVersion": "1.1.0",
        "profileVersion": PROFILE_VERSION,
        "case": {
            "id": CASE_ID,
            "number": None,
            "numberStatus": "unknown",
            "folderKey": "synthetic-r02",
            "title": "Synthetic R02 case",
            "aliases": [],
        },
        "bootstrap": {
            "firstDocumentId": None,
            "temporaryIntakeCaseId": None,
            "numberDetectionSources": [],
            "requireManualReviewForMultipleCandidates": True,
            "allowFilenameAsSoleEvidence": False,
        },
        "proceedings": [],
        "evidenceMap": {
            "rootDocumentId": None,
            "rootSelector": None,
            "keyDocumentRules": [],
            "relationHypotheses": [],
        },
        "exportDefaults": {
            "profile": "metadata_only",
            "includeFullText": False,
            "includeOriginalFiles": False,
            "sealed": False,
        },
        "validationRules": {
            "requireSourceForConfirmedFacts": True,
            "requireAllRequiredProceedings": False,
            "requireReferentialIntegrity": True,
            "requireUniqueIds": True,
            "blockExternalNetworkInSealedExport": True,
        },
    }


def _membership(entity_type: str, entity_id: str, ordinal: int) -> EvidenceMembershipRecord:
    return EvidenceMembershipRecord(
        membership_id=f"membership-{ordinal}",
        entity_type=entity_type,
        entity_id=entity_id,
        context_type="case",
        context_id=CASE_ID,
        role="evidence",
        is_primary=True,
        source_reference_id=None,
        review_status="unreviewed",
        note=None,
        created_at=DAY_1,
        updated_at=DAY_1,
    )


def _managed_file(file_id: str, marker: str) -> ManagedFileRecord:
    return ManagedFileRecord(
        file_id=file_id,
        layout_version=1,
        storage_key=f"synthetic-r02/{file_id}",
        storage_reference=f"objects/synthetic-r02/{file_id}",
        staging_reference=f"staging/synthetic-r02/{file_id}",
        original_name=f"{file_id}.txt",
        managed_name=None,
        source_relative_path=f"synthetic/{file_id}.txt",
        kind="content",
        bytes=10,
        sha256=marker * 64,
        source_created_ns=None,
        source_modified_ns=1,
        state="verified",
        integrity_status="verified",
        created_at=DAY_1,
        updated_at=DAY_2,
    )


def _seed_database(database: Path, *, reverse: bool = False) -> None:
    factory = SQLiteUnitOfWorkFactory(database)
    case = WorkspaceCaseRecord(
        case_id=CASE_ID,
        case_number=None,
        name="Synthetic R02 case",
        status="active",
        created_at=DAY_1,
        updated_at=DAY_2,
    )
    proceedings = (
        WorkspaceProceedingRecord(
            proceeding_id="proceeding-a",
            proceeding_number=None,
            name="Synthetic proceeding A",
            status="active",
            created_at=DAY_1,
            updated_at=DAY_2,
            case_ids=(CASE_ID,),
        ),
        WorkspaceProceedingRecord(
            proceeding_id="proceeding-b",
            proceeding_number=None,
            name="Synthetic proceeding B",
            status="active",
            created_at=DAY_1,
            updated_at=DAY_2,
            case_ids=(CASE_ID,),
        ),
    )
    files = (
        _managed_file("file-a", "a"),
        _managed_file("file-b", "b"),
    )
    actor_memberships = (
        _membership("actor", "actor-a", 1),
        _membership("actor", "actor-b", 2),
    )
    actors = (
        EvidenceActorRecord(
            actor_id="actor-a",
            actor_type="organization",
            display_name="Synthetic actor A",
            normalized_name="synthetic actor a",
            review_status="unreviewed",
            notes=None,
            version=1,
            created_at=DAY_1,
            updated_at=DAY_2,
            memberships=(actor_memberships[0],),
        ),
        EvidenceActorRecord(
            actor_id="actor-b",
            actor_type="person",
            display_name="Synthetic actor B",
            normalized_name="synthetic actor b",
            review_status="unreviewed",
            notes=None,
            version=1,
            created_at=DAY_1,
            updated_at=DAY_2,
            memberships=(actor_memberships[1],),
        ),
    )
    document_memberships = (
        _membership("document", "document-a", 3),
        _membership("document", "document-b", 4),
    )
    documents = (
        EvidenceDocumentRecord(
            document_id="document-a",
            title="Synthetic document A",
            label="Document A",
            document_type="synthetic",
            category=None,
            source="synthetic",
            origin_format="text/plain",
            summary=None,
            process_role=None,
            classification="unverified",
            review_status="unreviewed",
            is_key=True,
            version=1,
            created_at=DAY_1,
            updated_at=DAY_2,
            memberships=(document_memberships[0],),
            file_ids=("file-a",),
        ),
        EvidenceDocumentRecord(
            document_id="document-b",
            title="Synthetic document B",
            label="Document B",
            document_type="synthetic",
            category=None,
            source="synthetic",
            origin_format="text/plain",
            summary=None,
            process_role=None,
            classification="unverified",
            review_status="unreviewed",
            is_key=False,
            version=1,
            created_at=DAY_1,
            updated_at=DAY_2,
            memberships=(document_memberships[1],),
            file_ids=("file-b",),
        ),
    )
    event_membership = _membership("event", "event-a", 5)
    event = EvidenceEventRecord(
        event_id="event-a",
        title="Synthetic event",
        event_type="synthetic",
        event_at=DAY_2.isoformat(),
        description=None,
        workflow_status="open",
        classification="unverified",
        review_status="unreviewed",
        process_consequence=None,
        next_action=None,
        deadline=None,
        version=1,
        created_at=DAY_1,
        updated_at=DAY_2,
        memberships=(event_membership,),
        actor_ids=("actor-a",),
        document_ids=("document-a",),
    )
    source = SourceReferenceRecord(
        source_reference_id="source-a",
        source_entity_type="document",
        source_entity_id="document-a",
        source_file_id="file-a",
        location_type="document",
        location_value=None,
        excerpt=None,
        source_sha256="a" * 64,
        review_status="unreviewed",
        created_by=REVIEWER,
        created_at=DAY_2,
        note=None,
        version=1,
    )
    claim_membership = _membership("claim", "claim-a", 6)
    claim = ClaimRecord(
        claim_id="claim-a",
        subject_type="event",
        subject_id="event-a",
        claim_text="Synthetic R02 claim",
        classification="confirmed_fact",
        review_status="unreviewed",
        uncertainty_note=None,
        process_consequence=None,
        version=1,
        created_at=DAY_2,
        updated_at=DAY_2,
        asserted_by_actor_ids=("actor-a",),
        basis_document_ids=("document-a",),
        source_reference_ids=("source-a",),
        memberships=(claim_membership,),
    )
    relation = EvidenceRelationRecord(
        relation_id="relation-a",
        from_type="event",
        from_id="event-a",
        to_type="claim",
        to_id="claim-a",
        relation_type="supports",
        label=None,
        classification="confirmed_fact",
        review_status="unreviewed",
        uncertainty_note=None,
        valid_from=None,
        valid_to=None,
        version=1,
        created_at=DAY_2,
        updated_at=DAY_2,
        basis_document_ids=("document-a",),
        source_reference_ids=("source-a",),
    )
    finding = FindingRecord(
        finding_id="finding-a",
        fingerprint="f" * 64,
        finding_type="synthetic_check",
        title="Synthetic finding",
        description="Synthetic R02 finding",
        severity="info",
        confidence=1.0,
        detector_name="synthetic-r02-detector",
        detector_version="1.0",
        processing_run_id=None,
        automatic_status="detected",
        automatic_version=1,
        review_status="unreviewed",
        review_version=0,
        first_observed_at=DAY_3,
        last_observed_at=DAY_3,
        created_at=DAY_3,
        updated_at=DAY_3,
        subjects=(EntityReferenceRecord("claim", "claim-a"),),
        source_reference_ids=("source-a",),
    )

    with factory(write=True) as unit_of_work:
        workspace = unit_of_work.workspace
        evidence = unit_of_work.evidence
        workspace.add_case(case, actor_id=REVIEWER)
        profile_json = json.dumps(_profile(), ensure_ascii=False, sort_keys=True)
        unit_of_work._repository._conn.execute(
            """
            INSERT INTO case_profiles(
                id, case_id, schema_version, profile_version, profile_json,
                profile_sha256, status, created_by, created_at, activated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "profile-r02-v1",
                CASE_ID,
                "1.1.0",
                PROFILE_VERSION,
                profile_json,
                hashlib.sha256(profile_json.encode("utf-8")).hexdigest(),
                "active",
                REVIEWER,
                DAY_1.isoformat(),
                DAY_1.isoformat(),
            ),
        )
        ordered_proceedings = proceedings[::-1] if reverse else proceedings
        for proceeding in ordered_proceedings:
            workspace.add_proceeding(proceeding, actor_id=REVIEWER)
            workspace.link_case_proceeding(
                case_id=CASE_ID,
                proceeding_id=proceeding.proceeding_id,
                relationship_kind="main",
                actor_id=REVIEWER,
                occurred_at=DAY_1,
            )
        ordered_files = files[::-1] if reverse else files
        for ordinal, file_record in enumerate(ordered_files, start=1):
            unit_of_work.files.add(file_record)
            workspace.add_file_membership(
                FileContextMembershipRecord(
                    membership_id=f"file-membership-{ordinal}-{file_record.file_id}",
                    file_id=file_record.file_id,
                    context_type="case",
                    context_id=CASE_ID,
                    role="evidence",
                    origin="manual_command",
                    actor_id=REVIEWER,
                    note=None,
                    created_at=DAY_1,
                )
            )
        actor_pairs = tuple(zip(actors, actor_memberships, strict=True))
        if reverse:
            actor_pairs = actor_pairs[::-1]
        for actor, membership in actor_pairs:
            evidence.add_actor(actor, memberships=(membership,), created_by=REVIEWER)
        document_pairs = tuple(zip(documents, document_memberships, strict=True))
        if reverse:
            document_pairs = document_pairs[::-1]
        for document, membership in document_pairs:
            evidence.add_document(
                document,
                memberships=(membership,),
                file_ids=document.file_ids,
                created_by=REVIEWER,
            )
        evidence.add_event(
            event,
            memberships=(event_membership,),
            actor_ids=event.actor_ids,
            document_ids=event.document_ids,
            created_by=REVIEWER,
        )
        evidence.add_source_reference(source)
        evidence.add_claim(
            claim,
            memberships=(claim_membership,),
            created_by=REVIEWER,
        )
        evidence.add_relation(relation, created_by=REVIEWER)
        evidence.record_finding_observation(
            finding,
            observation_status="detected",
            details={"source": "synthetic-r02"},
        )
        evidence.add_review_decision(
            ReviewDecisionRecord(
                decision_id="review-claim-a",
                subject_type="claim",
                subject_id="claim-a",
                decision="confirm",
                previous_status="unreviewed",
                new_status="confirmed",
                actor_id=REVIEWER,
                decided_at=DAY_4,
                note="Synthetic claim review",
                subject_version=2,
                decision_origin="user",
                source_reference_ids=("source-a",),
            ),
            expected_version=1,
        )
        evidence.review_finding(
            ReviewDecisionRecord(
                decision_id="review-finding-a",
                subject_type="finding",
                subject_id="finding-a",
                decision="resolve",
                previous_status="unreviewed",
                new_status="resolved",
                actor_id=REVIEWER,
                decided_at=DAY_5,
                note="Synthetic finding review",
                subject_version=1,
                decision_origin="user",
                source_reference_ids=("source-a",),
            ),
            expected_version=0,
        )
        unit_of_work.commit()


def _query() -> EvidenceMapSourceQuery:
    return EvidenceMapSourceQuery(
        case_id=CASE_ID,
        profile_version=PROFILE_VERSION,
        export_profile="metadata_only",
        page_size=1,
    )


def test_sqlite_source_is_complete_and_stable_after_real_restart(tmp_path: Path) -> None:
    database = tmp_path / "r02.sqlite3"
    _seed_database(database)

    first = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(database))
    ).query(_query())
    restarted = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(database))
    ).query(_query())

    assert first == restarted
    assert len(first.proceedings) == 2
    assert len(first.files) == 2
    assert len(first.evidence.actors) == 2
    assert len(first.evidence.documents) == 2
    assert len(first.evidence.events) == 1
    assert len(first.evidence.source_references) == 1
    assert len(first.evidence.claims) == 1
    assert len(first.evidence.relations) == 1
    assert {item.record.decision_id for item in first.reviews} == {
        "review-claim-a",
        "review-finding-a",
    }
    assert [item.record.finding_id for item in first.findings] == ["finding-a"]
    assert first.exclusions == ()
    assert first.data_cutoff == DAY_5.isoformat()
    assert not (tmp_path / "map-data.json").exists()


def test_revision_ignores_insertion_order_and_page_boundaries(tmp_path: Path) -> None:
    forward_database = tmp_path / "forward.sqlite3"
    reverse_database = tmp_path / "reverse.sqlite3"
    _seed_database(forward_database)
    _seed_database(reverse_database, reverse=True)

    forward = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(forward_database))
    ).query(_query())
    reverse = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(reverse_database))
    ).query(_query())
    unpaged = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(forward_database))
    ).query(
        EvidenceMapSourceQuery(
            case_id=CASE_ID,
            profile_version=PROFILE_VERSION,
            export_profile="metadata_only",
            page_size=100,
        )
    )

    assert forward.source_revision == reverse.source_revision == unpaged.source_revision


def test_source_rejects_cross_case_rows_and_missing_provider(tmp_path: Path) -> None:
    database = tmp_path / "r02.sqlite3"
    _seed_database(database)
    factory = SQLiteUnitOfWorkFactory(database)

    class CrossCasePorts(SQLiteEvidenceMapSourcePorts):
        def list_files(
            self,
            case_id: str,
            *,
            limit: int,
            offset: int,
        ) -> tuple[CaseScopedSourceItem[ManagedFileRecord], ...]:
            page = super().list_files(case_id, limit=limit, offset=offset)
            return tuple(
                CaseScopedSourceItem(case_id="other-case", record=item.record) for item in page
            )

    with pytest.raises(EvidenceMapSourceError, match="files provider returned another case"):
        EvidenceMapSourceQueryService(CrossCasePorts(factory)).query(_query())

    missing = SQLiteEvidenceMapSourcePorts(factory)
    missing.list_findings = None  # type: ignore[assignment,method-assign]
    with pytest.raises(EvidenceMapSourceError, match="list_findings"):
        EvidenceMapSourceQueryService(missing).query(_query())


def test_repeating_full_page_fails_instead_of_hanging(tmp_path: Path) -> None:
    database = tmp_path / "r02.sqlite3"
    _seed_database(database)

    class RepeatingExclusionsPorts(SQLiteEvidenceMapSourcePorts):
        def list_exclusions(
            self,
            case_id: str,
            *,
            limit: int,
            offset: int,
        ) -> tuple[CaseScopedSourceItem[EvidenceMapExclusionDTO], ...]:
            del limit, offset
            return (
                CaseScopedSourceItem(
                    case_id=case_id,
                    record=EvidenceMapExclusionDTO(
                        entity_type="document",
                        entity_id="document-a",
                        reason_code="other",
                        reason="Synthetic pagination guard",
                        source_reference_ids=("source-a",),
                        review_status="unreviewed",
                    ),
                ),
            )

    with pytest.raises(EvidenceMapSourceError, match="pagination did not advance"):
        EvidenceMapSourceQueryService(
            RepeatingExclusionsPorts(SQLiteUnitOfWorkFactory(database))
        ).query(_query())
