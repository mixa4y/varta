from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pytest

from case_docket.airtable import TABLE_SQL_NAMES, load_airtable_schema
from case_docket.application.case_database_import import (
    CaseDatabaseImportService,
    ExecuteCaseDatabaseImportCommand,
    FinalizeCaseDatabaseImportCommand,
    GetCaseDatabaseImportReportQuery,
    PlanCaseDatabaseImportCommand,
    RecordCaseDatabaseVerificationCommand,
    ResumeCaseDatabaseImportCommand,
)
from case_docket.application.case_database_import_ports import (
    CaseDatabaseSourceSnapshot,
    CorpusImportResult,
    CorpusInventorySummary,
)
from case_docket.application.errors import ConflictError
from case_docket.application.evidence_map_source import (
    EvidenceMapSourceError,
    EvidenceMapSourceQuery,
    EvidenceMapSourceQueryService,
)
from case_docket.application.profile import CaseProfileService, GetCaseProfileQuery
from case_docket.repository.sqlite_case_database_import import (
    SQLiteCaseDatabaseImportRepository,
)
from case_docket.repository.sqlite_evidence_map_source import SQLiteEvidenceMapSourcePorts
from case_docket.repository.sqlite_uow import SQLiteUnitOfWorkFactory


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class FixedSource:
    def __init__(self, snapshot: CaseDatabaseSourceSnapshot):
        self.snapshot = snapshot
        self.capture_calls = 0
        self.load_calls = 0

    def capture(self) -> CaseDatabaseSourceSnapshot:
        self.capture_calls += 1
        return self.snapshot

    def load(self) -> CaseDatabaseSourceSnapshot:
        self.load_calls += 1
        return self.snapshot


class FixedCorpus:
    def __init__(self, manifest: str = "d" * 64):
        self.summary = CorpusInventorySummary(manifest, 3, 2, 1, 0)

    def inventory(self) -> CorpusInventorySummary:
        return self.summary


class FixedCorpusImport:
    def import_corpus(self, idempotency_key: str) -> CorpusImportResult:
        assert idempotency_key.startswith("r05-corpus:")
        return CorpusImportResult(0, 0, 0, 0)


class FailOnceCorpusImport:
    def __init__(self) -> None:
        self.calls = 0

    def import_corpus(self, idempotency_key: str) -> CorpusImportResult:
        assert idempotency_key.startswith("r05-corpus:")
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("synthetic interrupted corpus import")
        return CorpusImportResult(2, 0, 0, 0)


class MutatingCorpusImport:
    def __init__(self, corpus: FixedCorpus) -> None:
        self.corpus = corpus

    def import_corpus(self, idempotency_key: str) -> CorpusImportResult:
        assert idempotency_key.startswith("r05-corpus:")
        self.corpus.summary = CorpusInventorySummary("e" * 64, 3, 2, 1, 0)
        return CorpusImportResult(2, 0, 0, 0)


def _snapshot(
    *,
    unresolved: bool = False,
    attachment: bool = False,
    evidence_extensions: bool = False,
) -> CaseDatabaseSourceSnapshot:
    tables: dict[str, object] = {table_id: {"records": []} for table_id in TABLE_SQL_NAMES}
    missing_case = "rec-missing-case" if unresolved else "rec-case"
    tables["tbl2OUBStFDdfxNNS"] = {
        "records": [
            {
                "id": "rec-contact",
                "fields": {
                    "fldsUF5FAcJRAYzMG": "Synthetic Person",
                    "fldAbyAGj8TTMlgx6": "Фізична особа",
                    "fldGn1lbv0naouTTw": "person@example.invalid",
                    "fldAv2Ga4NF7IRAuH": "+380000000000",
                    "fldGfWlDfDcXuG420": [missing_case],
                    "fldbv0WeRuN86jplD": ["rec-proceeding"],
                    "fldMyuQxJCqhnTY7W": ["rec-event"],
                    "fldBXm28KqnchRzWj": ["rec-participant"],
                },
            }
        ]
    }
    tables["tblw2m5qeasGSW3h8"] = {
        "records": [
            {
                "id": "rec-case",
                "fields": {
                    "fldBIYNLnq1NaQk3E": "SYNTHETIC-CASE",
                    "fld7xYu8Bu0BwP8Oq": "Synthetic case",
                    "fldlv9rvYxpcMiLk0": ["rec-proceeding"],
                    "fld4GdY0KcbY9xBwp": ["rec-event"],
                    "fldbELvq8ZSxKJ9hN": ["rec-document"],
                    "fldGL45mM96oJf8np": ["rec-participant"],
                },
            }
        ]
    }
    tables["tbl0fQuxzzyGijsXK"] = {
        "records": [
            {
                "id": "rec-proceeding",
                "fields": {
                    "fld4gdU5CEgFNVn7I": "Synthetic proceeding",
                    "fldKa4sGwfiW8JRA7": "SYNTHETIC-PROCEEDING",
                    "fldnC3G8bYPZjQUdR": ["rec-case"],
                    "fldOj5z7NVQZJQaUH": ["rec-event"],
                    "fldtD1ldsElO0XY6q": ["rec-document"],
                    "fld0iUoNDknwSQCvg": ["rec-contact"],
                },
            }
        ]
    }
    tables["tbl2GzptAOVCEHQM7"] = {
        "records": [
            {
                "id": "rec-event",
                "fields": {
                    "fld1y6fnMxVfRsnKw": "Synthetic event",
                    "fldtcR9bMUiIXfy3q": "2026-01-01T10:00:00+02:00",
                    "fldnGMbGPaGVA64Q0": ["rec-case"],
                    "fldU85sGdvXfpyp8y": ["rec-proceeding"],
                    "fldWQZaoDewhxKYY7": ["rec-document"],
                    "fldpHAd9Jm5yPFktR": ["rec-contact"],
                },
            }
        ]
    }
    document_fields: dict[str, object] = {
        "fldXuOovgXZaoZjV3": "Synthetic document",
        "fldij2txUAF3rHkbA": ["rec-case"],
        "fldZhefYcXoIeO8Zq": ["rec-proceeding"],
        "fldp637rPy50IaOcX": ["rec-event"],
    }
    if attachment:
        document_fields["fldYaR97pw7qkWEH6"] = [
            {
                "id": "att-synthetic",
                "filename": "synthetic.txt",
                "size": 10,
                "type": "text/plain",
            }
        ]
    tables["tblhxvEsiaMwgl0BF"] = {"records": [{"id": "rec-document", "fields": document_fields}]}
    if evidence_extensions:
        second_document_fields = {
            "fldXuOovgXZaoZjV3": "Synthetic response document",
            "fldij2txUAF3rHkbA": ["rec-case"],
            "fldZhefYcXoIeO8Zq": ["rec-proceeding"],
        }
        tables["tblhxvEsiaMwgl0BF"]["records"].append(
            {"id": "rec-document-response", "fields": second_document_fields}
        )
        tables["tblw2m5qeasGSW3h8"]["records"][0]["fields"]["fldbELvq8ZSxKJ9hN"].append(
            "rec-document-response"
        )
        tables["tbl0fQuxzzyGijsXK"]["records"][0]["fields"]["fldtD1ldsElO0XY6q"].append(
            "rec-document-response"
        )
        tables["tblgiLYvazAF2YWOW"] = {
            "records": [
                {
                    "id": "rec-document-link",
                    "fields": {
                        "fldefA1UCXoAV22gr": "Synthetic response link",
                        "fldb9R4mTaWnuho1w": "response_to",
                        "fldw8cAqivZisjmGX": ["rec-document-response"],
                        "fldGPGtply6TOrrhj": ["rec-document"],
                    },
                }
            ]
        }
        tables["tblPvqu8ch6e29bq7"] = {
            "records": [
                {
                    "id": "rec-compliance",
                    "fields": {
                        "fldaA64IrdkwF8XVD": "Synthetic review signal",
                        "fldV6vFnYcCFbVbkO": "count_mismatch",
                        "fldCgu9aYEApr2ioG": "warning",
                        "fldX5iiacnhJzFa0z": "manual",
                        "fld7YCh4JPsm3nYTT": "Synthetic-only review note",
                        "fldARhXpTAVPUjlpb": ["rec-document"],
                    },
                }
            ]
        }
        tables["tblACqocW5KmtYJp5"] = {
            "records": [
                {
                    "id": "rec-version-match",
                    "fields": {
                        "fld0M6V00eNStp0yi": "Synthetic version comparison",
                        "fld0gIaMY0z2yKq30": False,
                        "fldjehVBC2fOQS9GY": 0.5,
                        "fldzT9yfDloirAvKQ": "content_diff",
                        "fldlLs42CoJwlRq2z": True,
                        "fldqkXhCmRjCSBN7s": ["rec-document"],
                        "fldmWFUuKiDUQ0sdD": ["rec-document-response"],
                    },
                }
            ]
        }
    tables["tbll4F8mAUkQqUnQJ"] = {
        "records": [
            {
                "id": "rec-participant",
                "fields": {
                    "fldZY8da3bfjfTiZy": "synthetic-role",
                    "fldc7Bw4YJMYzQCwX": ["rec-case"],
                    "flducJ9za4RACiSYP": ["rec-contact"],
                    "fldnQfVMsMWOXwJRV": "participant",
                },
            }
        ]
    }
    control = load_airtable_schema()
    live_tables = json.loads(json.dumps(control["tables"]))
    for live_table in live_tables:
        live_table["primaryFieldId"] = live_table.pop("primary_field_id")
        for field in live_table["fields"]:
            if "config" in field:
                field["options"] = field.pop("config")
    schema: Mapping[str, object] = {"tables": live_tables}
    schema_encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    catalog_encoded = json.dumps(control, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    schema_sha256 = hashlib.sha256(schema_encoded.encode()).hexdigest()
    payload: Mapping[str, object] = {
        "formatVersion": 1,
        "schemaSha256": schema_sha256,
        "catalogMappingSha256": hashlib.sha256(catalog_encoded.encode()).hexdigest(),
        "schema": schema,
        "tables": tables,
        "paginationComplete": {table_id: True for table_id in tables},
        "selectedCaseRecordSha256": hashlib.sha256(b"rec-case").hexdigest(),
    }
    counts = {
        table_id: len(value["records"])
        for table_id, value in tables.items()
        if isinstance(value, dict)
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return CaseDatabaseSourceSnapshot(
        source_identity_sha256="a" * 64,
        schema_sha256=schema_sha256,
        snapshot_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
        captured_start="2026-01-01T00:00:00+00:00",
        captured_end="2026-01-01T00:01:00+00:00",
        table_counts=counts,
        payload=payload,
        selected_case_record_id="rec-case",
    )


def _service(
    database: Path, snapshot: CaseDatabaseSourceSnapshot
) -> tuple[CaseDatabaseImportService, SQLiteCaseDatabaseImportRepository]:
    repository = SQLiteCaseDatabaseImportRepository(database)
    service = CaseDatabaseImportService(
        FixedSource(snapshot),
        FixedCorpus(),
        FixedCorpusImport(),
        repository,
        repository,
        FixedClock(),
    )
    return service, repository


def _with_payload(
    snapshot: CaseDatabaseSourceSnapshot, payload: dict[str, object]
) -> CaseDatabaseSourceSnapshot:
    tables = payload["tables"]
    assert isinstance(tables, dict)
    counts = {
        str(table_id): len(table_payload["records"])
        for table_id, table_payload in tables.items()
        if isinstance(table_payload, dict)
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return replace(
        snapshot,
        payload=payload,
        table_counts=counts,
        snapshot_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
    )


def _insert_corpus_batch(connection: sqlite3.Connection, import_run_id: str) -> None:
    sqlite = connection
    now = FixedClock().now().isoformat()
    sqlite.execute(
        """
        INSERT INTO intake_contexts(
            id, status, created_at, updated_at, completed_at
        ) VALUES ('context-synthetic', 'succeeded', ?, ?, ?)
        """,
        (now, now, now),
    )
    sqlite.execute(
        """
        INSERT INTO import_batches(
            id, intake_context_id, idempotency_key, request_fingerprint,
            source_uri, requested_kind, detected_kind, status,
            created_at, updated_at, completed_at
        ) VALUES (
            'batch-synthetic', 'context-synthetic', ?, ?,
            'private://r05/corpus', 'auto', 'folder', 'succeeded', ?, ?, ?
        )
        """,
        (f"r05-corpus:{import_run_id}", "e" * 64, now, now, now),
    )


def test_schema_13_has_append_only_import_history_and_relation_catalog(tmp_path: Path) -> None:
    repository = SQLiteCaseDatabaseImportRepository(tmp_path / "r05.sqlite3")
    connection = repository._open()._conn
    try:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "airtable_import_runs",
            "airtable_import_batches",
            "airtable_record_versions",
            "airtable_record_scopes",
            "airtable_schema_snapshots",
            "airtable_corpus_manifest_entries",
            "airtable_attachment_references",
            "airtable_reconciliation_issues",
            "airtable_import_verifications",
            "contact_identifiers",
            "contact_actor_links",
            "relation_type_catalog",
        } <= names
        assert connection.execute("SELECT COUNT(*) FROM relation_type_catalog").fetchone()[0] == 23
    finally:
        connection.close()


def test_plan_is_idempotent_and_changed_snapshot_creates_new_run(tmp_path: Path) -> None:
    service, _ = _service(tmp_path / "r05.sqlite3", _snapshot())
    first = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    second = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    assert first.import_run_id == second.import_run_id
    assert not first.replayed
    assert second.replayed

    source = service._snapshot_source
    assert isinstance(source, FixedSource)
    changed_payload = deepcopy(source.snapshot.payload)
    assert isinstance(changed_payload, dict)
    changed_payload["syntheticChangeMarker"] = 1
    changed_encoded = json.dumps(
        changed_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    source.snapshot = replace(
        source.snapshot,
        payload=changed_payload,
        snapshot_sha256=hashlib.sha256(changed_encoded.encode()).hexdigest(),
    )
    changed = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    assert changed.import_run_id != first.import_run_id


def test_one_time_import_materializes_profile_contacts_dates_and_survives_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "r05.sqlite3"
    snapshot = _snapshot()
    service, repository = _service(database, snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    report = service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id,
            plan.snapshot_sha256,
            plan.corpus_manifest_sha256,
        )
    )
    assert report.status == "ready"
    assert report.entity_counts["cases"] == 1
    assert report.entity_counts["contacts"] == 1
    assert report.links["unresolved"] == 0
    assert report.issues["critical"] == 0
    assert report.profiles["active"] == 1

    reopened = repository._open()
    try:
        assert (
            reopened._conn.execute("SELECT COUNT(*) FROM airtable_record_versions").fetchone()[0]
            == 6
        )
        assert reopened._conn.execute("SELECT COUNT(*) FROM contact_identifiers").fetchone()[0] == 2
        assert reopened._conn.execute("SELECT COUNT(*) FROM contact_actor_links").fetchone()[0] == 1
        assert reopened._conn.execute("SELECT COUNT(*) FROM entity_dates").fetchone()[0] == 1
        row = reopened._conn.execute(
            "SELECT case_id, profile_version FROM case_profiles"
        ).fetchone()
        profile_case_id = str(row["case_id"])
        profile_version = str(row["profile_version"])
    finally:
        reopened.close()
    profile = CaseProfileService(SQLiteUnitOfWorkFactory(database)).get(
        GetCaseProfileQuery(profile_case_id, profile_version)
    )
    assert profile.case_id == profile_case_id

    verification = repository.verify_restart_and_backup(
        plan.import_run_id,
        tmp_path / "відновлена.sqlite3",
        occurred_at=FixedClock().now(),
    )
    assert verification.verified
    verified = service.record_verification(
        RecordCaseDatabaseVerificationCommand(plan.import_run_id, verification.verification_sha256)
    )
    assert verified.restart_verified and verified.backup_verified
    finalized = service.finalize(FinalizeCaseDatabaseImportCommand(plan.import_run_id))
    assert finalized.status == "finalized"


def test_unresolved_link_is_explicit_and_resume_does_not_duplicate_records(tmp_path: Path) -> None:
    snapshot = _snapshot(unresolved=True)
    service, repository = _service(tmp_path / "r05.sqlite3", snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    first = service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id, plan.snapshot_sha256, plan.corpus_manifest_sha256
        )
    )
    assert first.links["unresolved"] == 1
    assert first.issues["critical"] == 1
    assert first.profiles["draft"] == 1

    resumed = service.resume(ResumeCaseDatabaseImportCommand(plan.import_run_id))
    assert resumed.entity_counts == first.entity_counts
    connection = repository._open()
    try:
        assert (
            connection._conn.execute("SELECT COUNT(*) FROM airtable_record_versions").fetchone()[0]
            == 6
        )
    finally:
        connection.close()
    with pytest.raises(ConflictError, match="critical issues"):
        service.finalize(FinalizeCaseDatabaseImportCommand(plan.import_run_id))


def test_resume_after_interrupted_corpus_import_replays_only_idempotent_phases(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    repository = SQLiteCaseDatabaseImportRepository(tmp_path / "r05.sqlite3")
    corpus_import = FailOnceCorpusImport()
    service = CaseDatabaseImportService(
        FixedSource(snapshot),
        FixedCorpus(),
        corpus_import,
        repository,
        repository,
        FixedClock(),
    )
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))

    with pytest.raises(RuntimeError, match="interrupted corpus"):
        service.execute(
            ExecuteCaseDatabaseImportCommand(
                plan.import_run_id,
                plan.snapshot_sha256,
                plan.corpus_manifest_sha256,
            )
        )

    resumed = service.resume(ResumeCaseDatabaseImportCommand(plan.import_run_id))
    assert resumed.files == {"accepted": 2, "duplicate": 0, "failed": 0, "skipped": 0}
    assert corpus_import.calls == 2
    connection = repository._open()
    try:
        assert (
            connection._conn.execute(
                "SELECT COUNT(*) FROM airtable_record_versions WHERE import_run_id = ?",
                (plan.import_run_id,),
            ).fetchone()[0]
            == 6
        )
        assert connection._conn.execute("SELECT COUNT(*) FROM case_profiles").fetchone()[0] == 1
    finally:
        connection.close()


def test_corpus_manifest_drift_blocks_before_and_during_import(tmp_path: Path) -> None:
    snapshot = _snapshot()
    corpus = FixedCorpus()
    repository = SQLiteCaseDatabaseImportRepository(tmp_path / "before.sqlite3")
    service = CaseDatabaseImportService(
        FixedSource(snapshot), corpus, FixedCorpusImport(), repository, repository, FixedClock()
    )
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    corpus.summary = CorpusInventorySummary("e" * 64, 3, 2, 1, 0)
    with pytest.raises(ConflictError, match="змінився після dry-run"):
        service.execute(
            ExecuteCaseDatabaseImportCommand(
                plan.import_run_id,
                plan.snapshot_sha256,
                plan.corpus_manifest_sha256,
            )
        )

    during_corpus = FixedCorpus()
    during_repository = SQLiteCaseDatabaseImportRepository(tmp_path / "during.sqlite3")
    during_service = CaseDatabaseImportService(
        FixedSource(snapshot),
        during_corpus,
        MutatingCorpusImport(during_corpus),
        during_repository,
        during_repository,
        FixedClock(),
    )
    during_plan = during_service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    with pytest.raises(ConflictError, match="originals змінилися"):
        during_service.execute(
            ExecuteCaseDatabaseImportCommand(
                during_plan.import_run_id,
                during_plan.snapshot_sha256,
                during_plan.corpus_manifest_sha256,
            )
        )


def test_selected_shared_and_cross_case_records_are_scoped_to_one_profile(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    payload = deepcopy(snapshot.payload)
    assert isinstance(payload, dict)
    tables = payload["tables"]
    assert isinstance(tables, dict)
    cases = tables["tblw2m5qeasGSW3h8"]
    contacts = tables["tbl2OUBStFDdfxNNS"]
    assert isinstance(cases, dict) and isinstance(contacts, dict)
    cases["records"].append(
        {
            "id": "rec-other-case",
            "fields": {
                "fldBIYNLnq1NaQk3E": "SYNTHETIC-OTHER-CASE",
                "fld7xYu8Bu0BwP8Oq": "Synthetic other case",
            },
        }
    )
    contacts["records"][0]["fields"]["fldGfWlDfDcXuG420"].append("rec-other-case")
    snapshot = _with_payload(snapshot, payload)
    service, repository = _service(tmp_path / "r05.sqlite3", snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id, plan.snapshot_sha256, plan.corpus_manifest_sha256
        )
    )

    connection = repository._open()
    try:
        classifications = {
            str(row[0]): int(row[1])
            for row in connection._conn.execute(
                "SELECT classification, COUNT(*) FROM airtable_record_scopes "
                "WHERE import_run_id = ? GROUP BY classification",
                (plan.import_run_id,),
            ).fetchall()
        }
        assert classifications["selected_case"] >= 1
        assert classifications["shared"] >= 1
        assert classifications["cross_case"] >= 1
        assert connection._conn.execute("SELECT COUNT(*) FROM case_profiles").fetchone()[0] == 1
        other = connection._conn.execute(
            "SELECT local_id FROM airtable_record_versions "
            "WHERE import_run_id = ? AND airtable_record_id = 'rec-other-case'",
            (plan.import_run_id,),
        ).fetchone()
        assert (
            connection._conn.execute(
                "SELECT COUNT(*) FROM source_references "
                "WHERE source_entity_type = 'case' AND source_entity_id = ?",
                (str(other[0]),),
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_import_materializes_evidence_extensions_and_r02_query_survives_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "r05.sqlite3"
    snapshot = _snapshot(evidence_extensions=True)
    service, repository = _service(database, snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    first = service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id,
            plan.snapshot_sha256,
            plan.corpus_manifest_sha256,
        )
    )
    second = service.resume(ResumeCaseDatabaseImportCommand(plan.import_run_id))
    assert second.entity_counts == first.entity_counts

    connection = repository._open()
    try:
        profile = connection._conn.execute(
            "SELECT case_id, profile_version FROM case_profiles"
        ).fetchone()
        assert profile is not None
        case_id = str(profile["case_id"])
        profile_version = str(profile["profile_version"])
        relations = connection._conn.execute(
            """
            SELECT relations.relation_type, COUNT(sources.source_reference_id)
            FROM evidence_relations AS relations
            LEFT JOIN relation_source_references AS sources
              ON sources.relation_id = relations.id
            GROUP BY relations.id, relations.relation_type
            ORDER BY relations.relation_type
            """
        ).fetchall()
        assert {str(row[0]) for row in relations} == {"response_to", "version_of"}
        assert all(int(row[1]) == 1 for row in relations)
        assert connection._conn.execute("SELECT COUNT(*) FROM evidence_findings").fetchone()[0] == 1
        assert (
            connection._conn.execute("SELECT COUNT(*) FROM finding_source_references").fetchone()[0]
            == 1
        )
    finally:
        connection.close()

    query = EvidenceMapSourceQuery(
        case_id=case_id,
        profile_version=profile_version,
        export_profile="metadata_only",
        page_size=1,
    )
    before_restart = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(database))
    ).query(query)
    after_restart = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(database))
    ).query(query)
    assert after_restart.source_revision == before_restart.source_revision
    assert len(after_restart.evidence.relations) == 2
    assert len(after_restart.findings) == 1
    with pytest.raises(EvidenceMapSourceError):
        EvidenceMapSourceQueryService(
            SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(database))
        ).query(
            EvidenceMapSourceQuery(
                case_id="synthetic-other-case",
                profile_version=profile_version,
                export_profile="metadata_only",
            )
        )


def test_attachment_metadata_is_private_provenance_and_blocks_unreconciled_cutover(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(attachment=True)
    service, repository = _service(tmp_path / "r05.sqlite3", snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    report = service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id, plan.snapshot_sha256, plan.corpus_manifest_sha256
        )
    )
    assert report.attachments == {"matched": 0, "unmatched": 1}
    assert report.issues["critical"] == 1
    with pytest.raises(Exception, match="Verification evidence"):
        service.record_verification(
            RecordCaseDatabaseVerificationCommand(plan.import_run_id, "0" * 64)
        )
    with pytest.raises(ConflictError, match="critical issues"):
        service.finalize(FinalizeCaseDatabaseImportCommand(plan.import_run_id))


def test_report_is_aggregate_only_and_rejects_hash_mismatch(tmp_path: Path) -> None:
    snapshot = _snapshot()
    service, _ = _service(tmp_path / "r05.sqlite3", snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    with pytest.raises(ConflictError, match="Snapshot hash"):
        service.execute(
            ExecuteCaseDatabaseImportCommand(
                plan.import_run_id, "0" * 64, plan.corpus_manifest_sha256
            )
        )
    report = service.get_report(GetCaseDatabaseImportReportQuery(plan.import_run_id)).to_dict()
    encoded = json.dumps(report, ensure_ascii=False)
    assert "Synthetic Person" not in encoded
    assert "person@example.invalid" not in encoded
    assert str(tmp_path) not in encoded


def test_attachment_reconciliation_uses_exact_hash_and_links_document_file(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(attachment=True)
    tables = snapshot.payload["tables"]
    assert isinstance(tables, dict)
    document_table = tables["tblhxvEsiaMwgl0BF"]
    assert isinstance(document_table, dict)
    attachment = document_table["records"][0]["fields"]["fldYaR97pw7qkWEH6"][0]
    attachment["sha256"] = "f" * 64
    encoded = json.dumps(
        snapshot.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    snapshot = replace(snapshot, snapshot_sha256=hashlib.sha256(encoded.encode()).hexdigest())
    service, repository = _service(tmp_path / "r05.sqlite3", snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    repository.execute(plan.import_run_id, snapshot, occurred_at=FixedClock().now())
    connection = repository._open(auto_commit=False)
    try:
        connection.begin(write=True)
        _insert_corpus_batch(connection._conn, plan.import_run_id)
        connection._conn.execute(
            """
            INSERT INTO file_objects(
                id, import_batch_id, kind, original_name, size_bytes, sha256, integrity_status,
                review_status, created_at, updated_at
            ) VALUES (
                'file-synthetic', 'batch-synthetic', 'attachment', 'different-name.bin', 999, ?,
                'verified', 'unreviewed', ?, ?
            )
            """,
            ("f" * 64, FixedClock().now().isoformat(), FixedClock().now().isoformat()),
        )
        connection.commit()
    finally:
        connection.close()

    report = repository.reconcile_attachments(plan.import_run_id, occurred_at=FixedClock().now())
    assert report.attachments_matched == 1
    assert report.attachments_unmatched == 0
    check = repository._open()
    try:
        row = check._conn.execute(
            "SELECT file_id, match_method FROM airtable_attachment_references"
        ).fetchone()
        assert tuple(row) == ("file-synthetic", "sha256")
        linked = check._conn.execute(
            "SELECT document_id, document_file_id FROM file_objects WHERE id = 'file-synthetic'"
        ).fetchone()
        assert linked[0] is not None and linked[1] is not None
    finally:
        check.close()


def test_same_name_multiple_files_is_ambiguous_not_fuzzy_matched(tmp_path: Path) -> None:
    snapshot = _snapshot(attachment=True)
    service, repository = _service(tmp_path / "r05.sqlite3", snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    repository.execute(plan.import_run_id, snapshot, occurred_at=FixedClock().now())
    connection = repository._open(auto_commit=False)
    try:
        connection.begin(write=True)
        _insert_corpus_batch(connection._conn, plan.import_run_id)
        for ordinal, digest in enumerate(("1" * 64, "2" * 64), start=1):
            connection._conn.execute(
                """
                INSERT INTO file_objects(
                    id, import_batch_id, kind, original_name, size_bytes, sha256, integrity_status,
                    review_status, created_at, updated_at
                ) VALUES (?, 'batch-synthetic', 'attachment', 'synthetic.txt', 10, ?, 'verified', 'unreviewed', ?, ?)
                """,
                (
                    f"file-{ordinal}",
                    digest,
                    FixedClock().now().isoformat(),
                    FixedClock().now().isoformat(),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    report = repository.reconcile_attachments(plan.import_run_id, occurred_at=FixedClock().now())
    assert report.attachments_matched == 0
    assert report.attachments_unmatched == 1
    assert report.critical_issues == 1


def test_name_and_size_single_candidate_is_review_suggestion_not_identity(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(attachment=True)
    service, repository = _service(tmp_path / "r05.sqlite3", snapshot)
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    repository.execute(plan.import_run_id, snapshot, occurred_at=FixedClock().now())
    connection = repository._open(auto_commit=False)
    try:
        connection.begin(write=True)
        _insert_corpus_batch(connection._conn, plan.import_run_id)
        connection._conn.execute(
            """
            INSERT INTO file_objects(
                id, import_batch_id, kind, original_name, size_bytes, sha256,
                integrity_status, review_status, created_at, updated_at
            ) VALUES (
                'file-suggestion', 'batch-synthetic', 'attachment',
                'synthetic.txt', 10, ?, 'verified', 'unreviewed', ?, ?
            )
            """,
            ("3" * 64, FixedClock().now().isoformat(), FixedClock().now().isoformat()),
        )
        connection.commit()
    finally:
        connection.close()

    report = repository.reconcile_attachments(plan.import_run_id, occurred_at=FixedClock().now())
    assert report.attachments_matched == 0
    check = repository._open()
    try:
        row = check._conn.execute(
            "SELECT match_status, file_id, match_method FROM airtable_attachment_references"
        ).fetchone()
        assert tuple(row) == ("ambiguous", None, None)
    finally:
        check.close()
