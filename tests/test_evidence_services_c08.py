from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application import (
    ConflictError,
    CreateClaimCommand,
    CreateEvidenceActorCommand,
    CreateEvidenceDocumentCommand,
    CreateEvidenceEventCommand,
    CreateEvidenceRelationCommand,
    CreateSourceReferenceCommand,
    CreateWorkspaceCaseCommand,
    CreateWorkspaceProceedingCommand,
    EntityReferenceInput,
    EvidenceMembershipInput,
    EvidenceService,
    GetCaseEvidenceQuery,
    GetSourceContextQuery,
    ListEvidenceTimelineQuery,
    ListReviewHistoryQuery,
    NotFoundError,
    RecordFindingCommand,
    ReviewEvidenceCommand,
    ReviewFindingCommand,
    SetCompatibilityReviewCommand,
    SystemClock,
    UuidProvider,
    ValidationError,
    WorkspaceService,
)
from case_docket.repository import SQLiteRepository, SQLiteUnitOfWorkFactory


SYNTHETIC_ACTOR = "user:synthetic-c08-reviewer"


def services(database: Path) -> tuple[WorkspaceService, EvidenceService]:
    factory = SQLiteUnitOfWorkFactory(database)
    ids = UuidProvider()
    clock = SystemClock()
    return WorkspaceService(factory, ids, clock), EvidenceService(factory, ids, clock)


def create_context(
    workspace: WorkspaceService,
) -> tuple[str, str, tuple[EvidenceMembershipInput, ...]]:
    case = workspace.create_case(
        CreateWorkspaceCaseCommand(
            actor_id=SYNTHETIC_ACTOR,
            case_number="111/2222/33",
            name="Синтетична справа C08",
        )
    )
    proceeding = workspace.create_proceeding(
        CreateWorkspaceProceedingCommand(
            actor_id=SYNTHETIC_ACTOR,
            case_ids=(case.case_id,),
            proceeding_number="synthetic-c08-proceeding",
            name="Синтетичне провадження C08",
        )
    )
    memberships = (
        EvidenceMembershipInput("case", case.case_id, "evidence", True),
        EvidenceMembershipInput("proceeding", proceeding.proceeding_id, "evidence"),
    )
    return case.case_id, proceeding.proceeding_id, memberships


def build_synthetic_domain(
    evidence: EvidenceService,
    memberships: tuple[EvidenceMembershipInput, ...],
) -> dict[str, str]:
    actor = evidence.create_actor(
        CreateEvidenceActorCommand(
            created_by=SYNTHETIC_ACTOR,
            actor_type="organization",
            display_name="Синтетична організація C08",
            memberships=memberships,
        )
    )
    document = evidence.create_document(
        CreateEvidenceDocumentCommand(
            created_by=SYNTHETIC_ACTOR,
            title="Синтетичний документ C08",
            document_type="synthetic_notice",
            classification="unverified",
            memberships=memberships,
        )
    )
    event = evidence.create_event(
        CreateEvidenceEventCommand(
            created_by=SYNTHETIC_ACTOR,
            title="Синтетична подія C08",
            event_type="synthetic_event",
            event_at="2026-01-02T10:00:00+00:00",
            memberships=memberships,
            actor_ids=(actor.record.actor_id,),
            document_ids=(document.record.document_id,),
        )
    )
    source = evidence.create_source_reference(
        CreateSourceReferenceCommand(
            created_by=SYNTHETIC_ACTOR,
            source_entity=EntityReferenceInput("document", document.record.document_id),
            location_type="document",
            review_status="unreviewed",
        )
    )
    claim = evidence.create_claim(
        CreateClaimCommand(
            created_by=SYNTHETIC_ACTOR,
            subject=EntityReferenceInput("event", event.record.event_id),
            text="Синтетичне твердження для перевірки C08",
            classification="confirmed_fact",
            asserted_by_actor_ids=(actor.record.actor_id,),
            basis_document_ids=(document.record.document_id,),
            source_reference_ids=(source.record.source_reference_id,),
            memberships=memberships,
        )
    )
    relation = evidence.create_relation(
        CreateEvidenceRelationCommand(
            created_by=SYNTHETIC_ACTOR,
            from_entity=EntityReferenceInput("event", event.record.event_id),
            to_entity=EntityReferenceInput("claim", claim.record.claim_id),
            relation_type="supports",
            classification="confirmed_fact",
            basis_document_ids=(document.record.document_id,),
            source_reference_ids=(source.record.source_reference_id,),
        )
    )
    return {
        "actor": actor.record.actor_id,
        "document": document.record.document_id,
        "event": event.record.event_id,
        "source": source.record.source_reference_id,
        "claim": claim.record.claim_id,
        "relation": relation.record.relation_id,
    }


def test_synthetic_case_round_trip_review_and_finding_histories(tmp_path: Path) -> None:
    database = tmp_path / "c08.sqlite3"
    workspace, evidence = services(database)
    case_id, proceeding_id, memberships = create_context(workspace)
    ids = build_synthetic_domain(evidence, memberships)

    finding = evidence.record_finding(
        RecordFindingCommand(
            fingerprint="A" * 64,
            finding_type="synthetic_consistency_check",
            title="Синтетична перевірка C08",
            description="Синтетичний automatic finding без правового висновку",
            severity="info",
            detector_name="synthetic-c08-detector",
            detector_version="1.0",
            subjects=(EntityReferenceInput("claim", ids["claim"]),),
            source_reference_ids=(ids["source"],),
            details={"rule": "synthetic_only"},
        )
    )
    reviewed = evidence.review_finding(
        ReviewFindingCommand(
            finding_id=finding.record.finding_id,
            decision="resolve",
            new_status="resolved",
            actor_id=SYNTHETIC_ACTOR,
            expected_version=0,
            source_reference_ids=(ids["source"],),
            note="Синтетичне ручне рішення",
        )
    )
    recomputed = evidence.record_finding(
        RecordFindingCommand(
            fingerprint="A" * 64,
            finding_type="synthetic_consistency_check",
            title="Синтетична перевірка C08",
            description="Повторний synthetic automatic observation",
            severity="low",
            detector_name="synthetic-c08-detector",
            detector_version="1.1",
            subjects=(EntityReferenceInput("claim", ids["claim"]),),
            source_reference_ids=(ids["source"],),
        )
    )

    assert reviewed.record.review_version == 1
    assert recomputed.record.automatic_version == 2
    assert recomputed.record.review_version == 1
    assert recomputed.record.review_status == "resolved"

    decision = evidence.review(
        ReviewEvidenceCommand(
            subject=EntityReferenceInput("claim", ids["claim"]),
            decision="confirm",
            new_status="confirmed",
            actor_id=SYNTHETIC_ACTOR,
            expected_version=1,
            source_reference_ids=(ids["source"],),
        )
    )
    assert decision.record.subject_version == 2
    with pytest.raises(ConflictError):
        evidence.review(
            ReviewEvidenceCommand(
                subject=EntityReferenceInput("claim", ids["claim"]),
                decision="confirm",
                new_status="confirmed",
                actor_id=SYNTHETIC_ACTOR,
                expected_version=1,
            )
        )

    view = evidence.get_case_evidence(GetCaseEvidenceQuery(case_id))
    assert [item.record.actor_id for item in view.actors] == [ids["actor"]]
    assert [item.record.document_id for item in view.documents] == [ids["document"]]
    assert [item.record.event_id for item in view.events] == [ids["event"]]
    assert [item.record.claim_id for item in view.claims] == [ids["claim"]]
    assert [item.record.relation_id for item in view.relations] == [ids["relation"]]
    assert [item.record.finding_id for item in view.findings] == [finding.record.finding_id]
    assert {item.context_id for item in view.documents[0].record.memberships} == {
        case_id,
        proceeding_id,
    }

    timeline = evidence.list_timeline(ListEvidenceTimelineQuery(case_id))
    assert {item.record.entity_type for item in timeline} == {"document", "event"}
    assert [
        (item.record.occurred_at, item.record.entity_type, item.record.entity_id)
        for item in timeline
    ] == sorted(
        (
            item.record.occurred_at,
            item.record.entity_type,
            item.record.entity_id,
        )
        for item in timeline
    )
    source_context = evidence.get_source_context(GetSourceContextQuery(ids["source"]))
    assert source_context.record.subject_exists is True
    assert source_context.record.linked_claim_ids == (ids["claim"],)
    assert source_context.record.linked_relation_ids == (ids["relation"],)
    assert source_context.record.linked_finding_ids == (finding.record.finding_id,)

    claim_history = evidence.list_review_history(ListReviewHistoryQuery("claim", ids["claim"]))
    finding_history = evidence.list_review_history(
        ListReviewHistoryQuery("finding", finding.record.finding_id)
    )
    assert [item.record.decision for item in claim_history] == ["confirm"]
    assert [item.record.decision for item in finding_history] == ["resolve"]

    _, restarted = services(database)
    restarted_view = restarted.get_case_evidence(GetCaseEvidenceQuery(case_id))
    assert restarted_view.to_dict() == view.to_dict()

    repository = SQLiteRepository(database)
    try:
        assert (
            repository._conn.execute("SELECT COUNT(*) FROM finding_observations").fetchone()[0] == 2
        )
        assert (
            repository._conn.execute("SELECT COUNT(*) FROM finding_review_decisions").fetchone()[0]
            == 1
        )
        assert (
            repository._conn.execute(
                "SELECT COUNT(*) FROM review_decisions WHERE subject_type = 'claim'"
            ).fetchone()[0]
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            repository._conn.execute("UPDATE finding_observations SET observation_status = 'error'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            repository._conn.execute("UPDATE finding_review_decisions SET new_status = 'rejected'")
    finally:
        repository.close()


def test_negative_orphan_type_basis_and_file_document_invariants(tmp_path: Path) -> None:
    database = tmp_path / "negative.sqlite3"
    workspace, evidence = services(database)
    _, _, memberships = create_context(workspace)
    ids = build_synthetic_domain(evidence, memberships)

    with pytest.raises(ValidationError, match="evidence basis"):
        evidence.create_relation(
            CreateEvidenceRelationCommand(
                created_by=SYNTHETIC_ACTOR,
                from_entity=EntityReferenceInput("event", ids["event"]),
                to_entity=EntityReferenceInput("claim", ids["claim"]),
                relation_type="supports",
                classification="confirmed_fact",
            )
        )
    with pytest.raises(ValidationError, match="entity type"):
        evidence.create_relation(
            CreateEvidenceRelationCommand(
                created_by=SYNTHETIC_ACTOR,
                from_entity=EntityReferenceInput("source_reference", ids["source"]),
                to_entity=EntityReferenceInput("claim", ids["claim"]),
                relation_type="supports",
            )
        )
    with pytest.raises(NotFoundError) as orphan_error:
        evidence.create_claim(
            CreateClaimCommand(
                created_by=SYNTHETIC_ACTOR,
                subject=EntityReferenceInput("document", "missing-synthetic-document"),
                text="Синтетичний orphan claim",
            )
        )
    assert orphan_error.value.details == {"resource": "document"}

    repository = SQLiteRepository(database)
    try:
        now = datetime.now(timezone.utc).isoformat()
        repository._conn.execute(
            """
            INSERT INTO file_objects(
                id, kind, original_name, sha256, integrity_status, review_status,
                created_at, updated_at
            ) VALUES ('shared-synthetic-id', 'content', 'synthetic.txt',
                      ?, 'not_checked', 'unreviewed', ?, ?)
            """,
            ("A" * 64, now, now),
        )
        repository._conn.commit()
    finally:
        repository.close()

    with pytest.raises(ConflictError, match="SHA-256"):
        evidence.create_source_reference(
            CreateSourceReferenceCommand(
                created_by=SYNTHETIC_ACTOR,
                source_entity=EntityReferenceInput("document", ids["document"]),
                source_file_id="shared-synthetic-id",
                location_type="whole_file",
                source_sha256="B" * 64,
            )
        )

    class SharedIdProvider:
        def new_id(self) -> str:
            return "shared-synthetic-id"

    same_id_service = EvidenceService(
        SQLiteUnitOfWorkFactory(database), SharedIdProvider(), SystemClock()
    )
    with pytest.raises(ValidationError, match="File identity"):
        same_id_service.create_document(
            CreateEvidenceDocumentCommand(
                created_by=SYNTHETIC_ACTOR,
                title="Синтетичний document/file collision",
                file_ids=("shared-synthetic-id",),
            )
        )


def test_claim_and_audit_rollback_together_on_late_failure(tmp_path: Path) -> None:
    database = tmp_path / "rollback.sqlite3"
    workspace, evidence = services(database)
    _, _, memberships = create_context(workspace)
    ids = build_synthetic_domain(evidence, memberships)

    repository = SQLiteRepository(database)
    try:
        repository._conn.execute(
            """
            CREATE TRIGGER synthetic_c08_audit_failure
            BEFORE INSERT ON audit_log
            WHEN NEW.action = 'create_claim'
            BEGIN
                SELECT RAISE(ABORT, 'synthetic audit failure');
            END;
            """
        )
        repository._conn.commit()
    finally:
        repository.close()

    with pytest.raises(ConflictError):
        evidence.create_claim(
            CreateClaimCommand(
                created_by=SYNTHETIC_ACTOR,
                subject=EntityReferenceInput("document", ids["document"]),
                text="Синтетичне твердження для rollback",
                source_reference_ids=(ids["source"],),
                memberships=memberships,
            )
        )

    repository = SQLiteRepository(database)
    try:
        assert (
            repository._conn.execute(
                "SELECT COUNT(*) FROM claims WHERE claim_text = ?",
                ("Синтетичне твердження для rollback",),
            ).fetchone()[0]
            == 0
        )
        assert (
            repository._conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'create_claim'"
            ).fetchone()[0]
            == 1
        )
    finally:
        repository.close()


def test_compatibility_review_import_is_sqlite_authoritative_and_versioned(
    tmp_path: Path,
) -> None:
    database = tmp_path / "compatibility.sqlite3"
    _, evidence = services(database)
    token = "B" * 64
    values = {
        "DOC_SYNTHETIC": {
            "status": "needs_review",
            "note": "Синтетичний compatibility import",
        }
    }
    assert (
        evidence.import_compatibility_reviews(
            subject_type="legacy_document",
            source_token=token,
            values=values,
        )
        == 1
    )
    assert (
        evidence.import_compatibility_reviews(
            subject_type="legacy_document",
            source_token=token,
            values=values,
        )
        == 0
    )

    updated = evidence.set_compatibility_review(
        SetCompatibilityReviewCommand(
            subject_type="legacy_document",
            external_id="DOC_SYNTHETIC",
            status="completed",
            actor_id=SYNTHETIC_ACTOR,
            expected_version=1,
            note="Синтетичне user decision",
        )
    )
    assert updated.record.version == 2
    with pytest.raises(ConflictError):
        evidence.set_compatibility_review(
            SetCompatibilityReviewCommand(
                subject_type="legacy_document",
                external_id="DOC_SYNTHETIC",
                status="waiting",
                actor_id=SYNTHETIC_ACTOR,
                expected_version=1,
            )
        )

    _, restarted = services(database)
    rows = restarted.list_compatibility_reviews("legacy_document")
    assert [(row.record.current_status, row.record.version) for row in rows] == [("completed", 2)]

    repository = SQLiteRepository(database)
    try:
        origins = [
            row[0]
            for row in repository._conn.execute(
                """
                SELECT decision_origin FROM compatibility_review_decisions
                ORDER BY sequence
                """
            )
        ]
        assert origins == ["compatibility_import", "user"]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            repository._conn.execute(
                "UPDATE compatibility_review_decisions SET new_status = 'waiting'"
            )
    finally:
        repository.close()
