from __future__ import annotations

from pathlib import Path

import pytest

from case_docket.application.case_database_import import (
    ExecuteCaseDatabaseImportCommand,
    PlanCaseDatabaseImportCommand,
)
from case_docket.application.case_read_models import (
    CaseReadModelService,
    GetContactCardQuery,
    GetDocumentCardQuery,
    GetEntityNeighborhoodQuery,
    ListCaseChronologyQuery,
)
from case_docket.application.errors import NotFoundError
from case_docket.application.profile import CaseProfileService
from case_docket.repository.sqlite_case_read_models import (
    CaseReadModelIntegrityError,
    SQLiteCaseReadModelRepository,
)
from case_docket.repository.sqlite_uow import SQLiteUnitOfWorkFactory
from test_case_database_import_r05 import _service, _snapshot


def _import(database: Path):
    import_service, import_repository = _service(database, _snapshot())
    plan = import_service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    import_service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id, plan.snapshot_sha256, plan.corpus_manifest_sha256
        )
    )
    connection = import_repository._open()
    try:
        profile = connection._conn.execute(
            "SELECT case_id, profile_version FROM case_profiles"
        ).fetchone()
        contact_id = str(connection._conn.execute("SELECT id FROM contacts").fetchone()[0])
        document_id = str(connection._conn.execute("SELECT id FROM documents").fetchone()[0])
        event_id = str(connection._conn.execute("SELECT id FROM events").fetchone()[0])
        return (
            str(profile["case_id"]),
            str(profile["profile_version"]),
            contact_id,
            document_id,
            event_id,
        )
    finally:
        connection.close()


def _read_service(database: Path) -> CaseReadModelService:
    return CaseReadModelService(
        CaseProfileService(SQLiteUnitOfWorkFactory(database)),
        SQLiteCaseReadModelRepository(database),
    )


def test_contact_and_document_cards_are_complete_and_case_scoped(tmp_path: Path) -> None:
    database = tmp_path / "r05.sqlite3"
    case_id, version, contact_id, document_id, event_id = _import(database)
    service = _read_service(database)

    contact = service.get_contact_card(GetContactCardQuery(case_id, version, contact_id))
    assert len(contact.identifiers) == 2
    assert len(contact.roles) == 1
    assert contact.event_ids == (event_id,)
    assert len(contact.actor_ids) == 1

    document = service.get_document_card(GetDocumentCardQuery(case_id, version, document_id))
    assert document.event_ids == (event_id,)
    assert document.actor_ids == contact.actor_ids
    assert document.source_reference_ids
    assert all(not hasattr(item, "storage_reference") for item in document.files)

    repository = SQLiteCaseReadModelRepository(database)
    assert repository.get_contact_card("case-outside", version, contact_id) is None
    assert repository.get_document_card("case-outside", version, document_id) is None


def test_chronology_preserves_exact_datetime_and_keeps_undated_items(tmp_path: Path) -> None:
    database = tmp_path / "r05.sqlite3"
    case_id, version, _contact_id, document_id, event_id = _import(database)
    chronology = _read_service(database).list_chronology(ListCaseChronologyQuery(case_id, version))

    assert [(item.entity_type, item.entity_id) for item in chronology.dated] == [
        ("event", event_id)
    ]
    dated = chronology.dated[0]
    assert dated.precision == "exact_datetime"
    assert dated.timezone == "explicit"
    assert dated.document_ids == (document_id,)
    assert {item.entity_type for item in chronology.undated} == {
        "case",
        "document",
        "proceeding",
    }


def test_entity_neighborhood_contains_structural_case_graph(tmp_path: Path) -> None:
    database = tmp_path / "r05.sqlite3"
    case_id, version, _contact_id, document_id, event_id = _import(database)
    neighborhood = _read_service(database).get_neighborhood(
        GetEntityNeighborhoodQuery(case_id, version, "event", event_id, depth=2)
    )

    node_keys = {(item.entity_type, item.entity_id) for item in neighborhood.nodes}
    assert ("case", case_id) in node_keys
    assert ("document", document_id) in node_keys
    assert any(edge.relation_type == "documented_by" for edge in neighborhood.edges)
    assert any(edge.relation_type == "member_of" for edge in neighborhood.edges)


def test_confirmed_semantic_relation_without_basis_blocks_graph(tmp_path: Path) -> None:
    database = tmp_path / "r05.sqlite3"
    case_id, version, _contact_id, document_id, event_id = _import(database)
    repository = SQLiteUnitOfWorkFactory(database)
    with repository(write=True) as uow:
        uow._repository._conn.execute(
            """
            INSERT INTO evidence_relations(
                id, from_type, from_id, to_type, to_id, relation_type,
                classification, review_status, created_at, updated_at, version
            ) VALUES (
                'relation-no-basis', 'event', ?, 'document', ?, 'supports',
                'confirmed_fact', 'confirmed',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1
            )
            """,
            (event_id, document_id),
        )
        uow.commit()

    with pytest.raises(CaseReadModelIntegrityError, match="no source basis"):
        _read_service(database).get_neighborhood(
            GetEntityNeighborhoodQuery(case_id, version, "event", event_id)
        )


def test_relation_endpoint_type_and_cross_case_leakage_are_explicit(tmp_path: Path) -> None:
    database = tmp_path / "r05.sqlite3"
    case_id, version, _contact_id, document_id, event_id = _import(database)
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        connection = uow._repository._conn
        connection.execute(
            """
            INSERT INTO evidence_relations(
                id, from_type, from_id, to_type, to_id, relation_type,
                classification, review_status, created_at, updated_at, version
            ) VALUES (
                'relation-bad-types', 'event', ?, 'document', ?, 'response_to',
                'unverified', 'unreviewed',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1
            )
            """,
            (event_id, document_id),
        )
        uow.commit()
    with pytest.raises(CaseReadModelIntegrityError, match="endpoint type"):
        _read_service(database).get_neighborhood(
            GetEntityNeighborhoodQuery(case_id, version, "event", event_id)
        )

    with factory(write=True) as uow:
        connection = uow._repository._conn
        connection.execute("DELETE FROM evidence_relations WHERE id = 'relation-bad-types'")
        connection.execute(
            """
            INSERT INTO cases(id, name, created_at, updated_at, legacy_payload)
            VALUES ('case-b', 'Synthetic case B', ?, ?, '{}')
            """,
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id, title, classification, review_status, version,
                created_at, updated_at, legacy_payload
            ) VALUES (
                'document-b', 'Synthetic document B', 'unverified', 'unreviewed', 1, ?, ?, '{}'
            )
            """,
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO case_documents(case_id, document_id, origin, created_at)
            VALUES ('case-b', 'document-b', 'synthetic', ?)
            """,
            ("2026-01-01T00:00:00+00:00",),
        )
        connection.execute(
            """
            INSERT INTO evidence_relations(
                id, from_type, from_id, to_type, to_id, relation_type,
                classification, review_status, created_at, updated_at, version
            ) VALUES (
                'relation-cross-case', 'event', ?, 'document', 'document-b', 'supports',
                'unverified', 'unreviewed',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1
            )
            """,
            (event_id,),
        )
        uow.commit()
    with pytest.raises(CaseReadModelIntegrityError, match="Cross-case"):
        _read_service(database).get_neighborhood(
            GetEntityNeighborhoodQuery(case_id, version, "event", event_id)
        )


def test_read_service_requires_exact_profile_version(tmp_path: Path) -> None:
    database = tmp_path / "r05.sqlite3"
    case_id, _version, contact_id, _document_id, _event_id = _import(database)
    with pytest.raises(NotFoundError):
        _read_service(database).get_contact_card(
            GetContactCardQuery(case_id, "missing-version", contact_id)
        )
