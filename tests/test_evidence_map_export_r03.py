from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
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
        source_revision="c" * 64,
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


def test_same_id_and_hash_with_different_metadata_conflicts(tmp_path: Path) -> None:
    database = tmp_path / "r03.sqlite3"
    _seed_database(database)
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        original = uow.evidence_map_exports.record_validated(_command())
        uow.commit()

    with factory(write=True) as uow:
        with pytest.raises(EvidenceMapExportAuditError, match="different audit metadata"):
            uow.evidence_map_exports.record_validated(
                replace(_command(), generated_by="synthetic-r03-other")
            )

    with factory() as uow:
        assert uow.evidence_map_exports.get(original.export_id) == original


def test_profile_must_belong_to_export_case_and_match_schema(tmp_path: Path) -> None:
    database = tmp_path / "r03.sqlite3"
    _seed_database(database)
    factory = SQLiteUnitOfWorkFactory(database)
    profile_json = json.dumps({}, separators=(",", ":"))
    with factory(write=True) as uow:
        connection = uow._repository._conn
        connection.execute(
            "INSERT INTO cases(id, created_at, updated_at) VALUES (?, ?, ?)",
            ("case-synthetic-r03-other", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """INSERT INTO case_profiles(
                id, case_id, schema_version, profile_version, profile_json,
                profile_sha256, status, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "profile-synthetic-r03-other",
                "case-synthetic-r03-other",
                "1.1.0",
                "v1",
                profile_json,
                hashlib.sha256(profile_json.encode("utf-8")).hexdigest(),
                "active",
                "synthetic-r03",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        uow.commit()

    with factory(write=True) as uow:
        with pytest.raises(EvidenceMapExportAuditError, match="another case"):
            uow.evidence_map_exports.record_validated(
                replace(_command(), case_profile_id="profile-synthetic-r03-other")
            )
    with factory(write=True) as uow:
        with pytest.raises(EvidenceMapExportAuditError, match="schema version"):
            uow.evidence_map_exports.record_validated(replace(_command(), schema_version="1.0.0"))

    with factory() as uow:
        assert uow.evidence_map_exports.get("export-synthetic-r03") is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "invalid"}, "only valid"),
        ({"export_profile": "unsupported"}, "export profile"),
        ({"source_revision": "revision-synthetic"}, "source revision"),
        ({"generated_at": "2026-01-06"}, "generated_at"),
        ({"data_cutoff": "not-a-timestamp"}, "data_cutoff"),
    ],
)
def test_source_revision_and_timestamps_are_validated_before_write(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    database = tmp_path / "r03.sqlite3"
    _seed_database(database)
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        with pytest.raises(EvidenceMapExportAuditError, match=message):
            uow.evidence_map_exports.record_validated(replace(_command(), **changes))
    with factory() as uow:
        assert uow.evidence_map_exports.get("export-synthetic-r03") is None


def test_database_diff_contains_only_export_audit(tmp_path: Path) -> None:
    database = tmp_path / "r03.sqlite3"
    _seed_database(database)
    before = _database_snapshot(database)
    factory = SQLiteUnitOfWorkFactory(database)
    with factory(write=True) as uow:
        uow.evidence_map_exports.record_validated(_command())
        uow.commit()
    after = _database_snapshot(database)

    assert before["evidence_map_exports"] == ()
    assert len(after["evidence_map_exports"]) == 1
    assert {table: rows for table, rows in before.items() if table != "evidence_map_exports"} == {
        table: rows for table, rows in after.items() if table != "evidence_map_exports"
    }


def _database_snapshot(database: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(database) as connection:
        tables = connection.execute(
            """SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name"""
        ).fetchall()
        return {
            table: tuple(
                tuple(row)
                for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            )
            for (table,) in tables
        }
