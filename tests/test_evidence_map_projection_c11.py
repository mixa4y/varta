"""Synthetic C11 acceptance, independently runnable gate groups."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from case_docket.application.evidence_map import (
    EvidenceMapProjectionError,
    EvidenceMapProjectionService,
)
from case_docket.application.evidence_map_export import EvidenceMapExportAuditError
from case_docket.application.evidence_map_source import (
    CaseScopedSourceItem,
    EvidenceMapExclusionDTO,
    EvidenceMapSourceError,
    EvidenceMapSourceQuery,
    EvidenceMapSourceQueryService,
)
from case_docket.repository import SQLiteEvidenceMapSourcePorts, SQLiteUnitOfWorkFactory
from test_evidence_map_source_r02 import CASE_ID, PROFILE_VERSION, _seed_database
from test_r04_consumer_readiness import _rows


def service(database: Path) -> EvidenceMapProjectionService:
    factory = SQLiteUnitOfWorkFactory(database)
    factory.prepare()  # Startup/migrations precede read-only projection or audit transaction.
    return EvidenceMapProjectionService(
        EvidenceMapSourceQueryService(SQLiteEvidenceMapSourcePorts(factory))
    )


def query(profile: str = "full_local", page_size: int = 1) -> EvidenceMapSourceQuery:
    return EvidenceMapSourceQuery(CASE_ID, PROFILE_VERSION, profile, page_size)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-c11.sqlite3"
    _seed_database(path)
    return path


def test_golden_populated_and_restart(database: Path) -> None:
    before = _rows(database)
    snapshot = service(database).project(query(), export_id="synthetic-export")
    assert snapshot == service(database).project(query(page_size=100), export_id="synthetic-export")
    assert _rows(database) == before
    assert snapshot["schemaVersion"] == "1.2.0"
    assert snapshot["export"]["caseProfileId"] == "profile-r02-v1"
    assert snapshot["export"]["sealed"] is False
    assert all(p["number"] is None for p in snapshot["proceedings"])
    assert len(snapshot["findings"]) == 1
    assert len(snapshot["reviewDecisions"]) == 2
    assert any(r["subject"]["type"] == "finding" for r in snapshot["reviewDecisions"])
    assert snapshot["findings"][0]["detector"]["version"]
    assert snapshot["inventory"]["findingCount"] == 1
    golden = Path(__file__).parent / "fixtures/c11/populated.json"
    assert snapshot == json.loads(golden.read_text(encoding="utf-8"))


def test_determinism_order_and_hash(database: Path, tmp_path: Path) -> None:
    other = tmp_path / "reversed.sqlite3"
    _seed_database(other, reverse=True)
    a = service(database).project(query(), export_id="a")
    b = service(other).project(query(), export_id="b")
    assert a["export"]["sourceSnapshotSha256"] == b["export"]["sourceSnapshotSha256"]
    assert a["export"]["sourceRevision"] == b["export"]["sourceRevision"]
    shuffled = copy.deepcopy(a)
    for key, value in shuffled.items():
        if isinstance(value, list):
            value.reverse()
    assert service(database).snapshot_sha256(shuffled) == a["export"]["sourceSnapshotSha256"]
    shuffled["export"]["generatedAt"] = "2026-01-05T03:00:00+03:00"
    assert service(database).snapshot_sha256(shuffled) == a["export"]["sourceSnapshotSha256"]
    shuffled["case"]["title"] = "Synthetic changed title"
    with pytest.raises(EvidenceMapProjectionError, match="hash mismatch"):
        service(database).validate(shuffled)


def test_audit_ui_export_parity_idempotency_restart(database: Path) -> None:
    before = _rows(database)
    generator = service(database)
    ui = generator.project(query(), export_id="shared")
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        exported = generator.export(
            query(),
            export_id="shared",
            generated_by="synthetic-reviewer",
            audit=uow.evidence_map_exports,
        )
        uow.commit()
    assert ui == exported
    with factory(write=True) as uow:
        generator.export(
            query(),
            export_id="shared",
            generated_by="synthetic-reviewer",
            audit=uow.evidence_map_exports,
        )
        uow.commit()
    after = _rows(database)
    assert {k for k in before if before[k] != after[k]} == {"evidence_map_exports"}
    assert len(after["evidence_map_exports"]) == 1
    with SQLiteUnitOfWorkFactory(database)() as uow:
        audit = uow.evidence_map_exports.get("shared")
        assert audit.case_profile_id == "profile-r02-v1"
        assert audit.source_snapshot_sha256 == ui["export"]["sourceSnapshotSha256"]
        assert audit.schema_version == "1.2.0"
        assert not audit.sealed


def test_audit_rollback_and_conflict(database: Path) -> None:
    factory = SQLiteUnitOfWorkFactory(database)
    generator = service(database)
    before = _rows(database)
    with factory(write=True) as uow:
        generator.export(
            query(),
            export_id="rolled-back",
            generated_by="synthetic-reviewer",
            audit=uow.evidence_map_exports,
        )
        uow.rollback()
    assert _rows(database) == before
    with factory(write=True) as uow:
        generator.export(
            query(),
            export_id="conflict",
            generated_by="synthetic-reviewer",
            audit=uow.evidence_map_exports,
        )
        uow.commit()
    with factory(write=True) as uow:
        with pytest.raises(EvidenceMapExportAuditError, match="different audit metadata"):
            generator.export(
                query(),
                export_id="conflict",
                generated_by="another-reviewer",
                audit=uow.evidence_map_exports,
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "reference",
        "basis",
        "classification",
        "duplicate",
        "timestamp",
        "nonfinite",
        "missing-findings",
    ],
)
def test_negative_validation(database: Path, mutation: str) -> None:
    generator = service(database)
    snap = generator.project(query(), export_id="negative")
    if mutation == "reference":
        snap["claims"][0]["subject"]["id"] = "missing"
    elif mutation == "basis":
        snap["claims"][0].update(
            classification="confirmed_fact", basisDocumentIds=[], sourceReferenceIds=[]
        )
    elif mutation == "classification":
        snap["documents"][0]["classification"] = "unsupported"
    elif mutation == "duplicate":
        snap["actors"].append(copy.deepcopy(snap["actors"][0]))
    elif mutation == "timestamp":
        snap["reviewDecisions"][0]["decidedAt"] = "2026-01-01T00:00:00"
    elif mutation == "nonfinite":
        snap["findings"][0]["confidence"] = float("nan")
    else:
        del snap["findings"]
    with pytest.raises(EvidenceMapProjectionError):
        generator.validate(snap, verify_hash=False)


def test_privacy_profiles_fail_closed(database: Path) -> None:
    before = _rows(database)
    generator = service(database)
    snap = generator.project(query("metadata_only"), export_id="metadata")
    assert all(r["excerpt"] is None for r in snap["sourceReferences"])
    assert all(f["storageReference"] is None for f in snap["files"])
    assert all(c["text"] == "[content omitted]" for c in snap["claims"])
    with pytest.raises(EvidenceMapProjectionError, match="redaction policy"):
        generator.project(query("redacted"), export_id="redacted")
    assert _rows(database) == before


def test_exclusions_preserved(database: Path) -> None:
    class ExcludedPorts(SQLiteEvidenceMapSourcePorts):
        def list_exclusions(self, case_id: str, *, limit: int, offset: int):
            values = (
                CaseScopedSourceItem(
                    case_id,
                    EvidenceMapExclusionDTO(
                        "document",
                        "document-b",
                        "not_key",
                        "Synthetic non-key document",
                        (),
                        "unreviewed",
                    ),
                ),
            )
            return values[offset : offset + limit]

    generator = EvidenceMapProjectionService(
        EvidenceMapSourceQueryService(ExcludedPorts(SQLiteUnitOfWorkFactory(database)))
    )
    snap = generator.project(query(), export_id="exclusions")
    assert snap["exclusions"][0]["entity"]["id"] == "document-b"
    assert len(snap["documents"]) == 2  # disposition is visible, not destructive filtering


def test_source_errors_propagate_without_audit(database: Path) -> None:
    class BrokenPorts(SQLiteEvidenceMapSourcePorts):
        def list_claims(self, case_id: str, *, limit: int, offset: int):
            return tuple(
                replace(item, record=replace(item.record, subject_id="missing"))
                for item in super().list_claims(case_id, limit=limit, offset=offset)
            )

    factory = SQLiteUnitOfWorkFactory(database)
    factory.prepare()
    generator = EvidenceMapProjectionService(EvidenceMapSourceQueryService(BrokenPorts(factory)))
    before = _rows(database)
    with SQLiteUnitOfWorkFactory(database)(write=True) as uow:
        with pytest.raises(EvidenceMapSourceError, match="Broken reference"):
            generator.export(
                query(),
                export_id="broken",
                generated_by="synthetic-reviewer",
                audit=uow.evidence_map_exports,
            )
        uow.commit()
    assert _rows(database) == before


def test_integrity_source_hash_mismatch(database: Path) -> None:
    class HashMismatchPorts(SQLiteEvidenceMapSourcePorts):
        def list_source_references(self, case_id: str, *, limit: int, offset: int):
            return tuple(
                replace(item, record=replace(item.record, source_sha256="0" * 64))
                for item in super().list_source_references(case_id, limit=limit, offset=offset)
            )

    generator = EvidenceMapProjectionService(
        EvidenceMapSourceQueryService(HashMismatchPorts(SQLiteUnitOfWorkFactory(database)))
    )
    with pytest.raises(EvidenceMapProjectionError, match="hash differs"):
        generator.project(query(), export_id="mismatch")


def test_pure_projection_does_not_write_database_bytes(database: Path) -> None:
    generator = service(database)  # Startup happens before observation.
    before = database.read_bytes()
    generator.project(query(), export_id="pure")
    assert database.read_bytes() == before


def test_unreviewed_finding_and_manual_source(database: Path) -> None:
    class UnreviewedPorts(SQLiteEvidenceMapSourcePorts):
        def list_findings(self, case_id: str, *, limit: int, offset: int):
            return tuple(
                replace(item, record=replace(item.record, review_version=0, review_status="open"))
                for item in super().list_findings(case_id, limit=limit, offset=offset)
            )

        def list_source_references(self, case_id: str, *, limit: int, offset: int):
            return tuple(
                replace(
                    item,
                    record=replace(
                        item.record,
                        source_entity_type="manual_note",
                        source_entity_id="synthetic-note",
                    ),
                )
                for item in super().list_source_references(case_id, limit=limit, offset=offset)
            )

    generator = EvidenceMapProjectionService(
        EvidenceMapSourceQueryService(UnreviewedPorts(SQLiteUnitOfWorkFactory(database)))
    )
    snap = generator.project(query(), export_id="unreviewed")
    assert snap["findings"][0]["reviewVersion"] == 0
    assert snap["inventory"]["manualReviewRequiredCount"] == 1
