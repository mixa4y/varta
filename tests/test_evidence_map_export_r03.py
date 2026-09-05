from __future__ import annotations

from pathlib import Path

import pytest

from case_docket.application.evidence_map_export import (
    EvidenceMapExportAuditError,
    RecordEvidenceMapExportCommand,
)
from case_docket.repository import SQLiteUnitOfWorkFactory

from test_evidence_map_source_r02 import _seed_database


def _command(hash_value: str = "a" * 64) -> RecordEvidenceMapExportCommand:
    return RecordEvidenceMapExportCommand(
        export_id="export-synthetic-r03",
        case_id="case-synthetic-r02",
        case_profile_id="profile-r02-v1",
        schema_version="1.1.0",
        product_version="0.1.0",
        export_profile="metadata_only",
        source_revision="revision-synthetic",
        source_snapshot_sha256=hash_value,
        generated_by="synthetic-r03",
        generated_at="2026-01-06T00:00:00+00:00",
    )


def test_valid_audit_is_idempotent_and_survives_restart(tmp_path: Path) -> None:
    database = tmp_path / "r03.sqlite3"
    _seed_database(database)
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        first = uow.evidence_map_exports.record_validated(_command())
        again = uow.evidence_map_exports.record_validated(_command())
        uow.commit()
    assert first == again
    with factory() as uow:
        assert uow.evidence_map_exports.get(first.export_id) == first


def test_different_hash_conflicts_and_invalid_never_persists(tmp_path: Path) -> None:
    database = tmp_path / "r03.sqlite3"
    _seed_database(database)
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        uow.evidence_map_exports.record_validated(_command())
        with pytest.raises(EvidenceMapExportAuditError, match="another hash"):
            uow.evidence_map_exports.record_validated(_command("b" * 64))
    with factory() as uow:
        assert uow.evidence_map_exports.get("export-synthetic-r03") is None


@pytest.mark.parametrize("bad_hash", ["", "A" * 64, "not-a-hash"])
def test_hash_validation_rejects_before_write(tmp_path: Path, bad_hash: str) -> None:
    database = tmp_path / "r03.sqlite3"
    _seed_database(database)
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        with pytest.raises(EvidenceMapExportAuditError, match="SHA-256"):
            uow.evidence_map_exports.record_validated(_command(bad_hash))
    with factory() as uow:
        assert uow.evidence_map_exports.get("export-synthetic-r03") is None
