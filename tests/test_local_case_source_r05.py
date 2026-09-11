from __future__ import annotations

import json
import hashlib
import socket
import sqlite3
from pathlib import Path

import pytest

from case_docket.airtable import TABLE_SQL_NAMES, load_airtable_schema
from case_docket.local_case_source import (
    LocalCaseSource,
    LocalCaseSourceError,
    import_local_case,
    local_field_name,
    local_input_schema,
)
from test_case_database_import_r05 import _snapshot


def write_local_input(path: Path) -> dict:
    fixture = _snapshot(evidence_extensions=True)
    tables = {}
    for table in load_airtable_schema()["tables"]:
        name = TABLE_SQL_NAMES[table["id"]]
        names = {field["id"]: local_field_name(name, field) for field in table["fields"]}
        tables[name] = [
            {"id": row["id"], "fields": {names[k]: v for k, v in row["fields"].items()}}
            for row in fixture.payload["tables"][table["id"]]["records"]
        ]
    tables["case_participants"][0]["fields"]["role"] = "Позивач"
    document = {"formatVersion": 1, "caseId": "rec-case", "tables": tables}
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return document


def test_local_import_restart_restore_and_query_without_network(
    tmp_path: Path, monkeypatch
) -> None:
    import ctypes

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline import must never call network or DPAPI")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(ctypes, "WinDLL", forbidden, raising=False)
    source = tmp_path / "case.json"
    local = write_local_input(source)
    corpus = tmp_path / "originals"
    corpus.mkdir()
    (corpus / "synthetic.txt").write_text("synthetic only", encoding="utf-8")
    local["tables"]["documents"][0]["fields"]["file_attachments_json"] = [
        {
            "id": "local-file-one",
            "filename": "synthetic.txt",
            "sha256": hashlib.sha256((corpus / "synthetic.txt").read_bytes()).hexdigest(),
        }
    ]
    source.write_text(json.dumps(local), encoding="utf-8")
    workspace = tmp_path / "workspace"
    backup = tmp_path / "restored.sqlite3"
    result = import_local_case(source, corpus, workspace, backup)
    assert result["status"] == "finalized"
    assert result["restartVerified"] and result["backupVerified"]
    assert result["files"]["accepted"] == 1
    assert result["attachments"]["matched"] == 1
    assert (corpus / "synthetic.txt").read_text(encoding="utf-8") == "synthetic only"
    repeated = import_local_case(source, corpus, workspace, tmp_path / "restored-again.sqlite3")
    assert repeated["importRunId"] == result["importRunId"]
    assert repeated["entityCounts"] == result["entityCounts"]
    from case_docket.application.evidence_map_source import (
        EvidenceMapSourceQuery,
        EvidenceMapSourceQueryService,
    )
    from case_docket.repository.sqlite_evidence_map_source import SQLiteEvidenceMapSourcePorts
    from case_docket.repository.sqlite_uow import SQLiteUnitOfWorkFactory

    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        case, version = db.execute("SELECT case_id, profile_version FROM case_profiles").fetchone()
    query = EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(backup))
    )
    dto = query.query(
        EvidenceMapSourceQuery(
            case_id=case, profile_version=version, export_profile="metadata_only"
        )
    )
    assert len(dto.evidence.relations) == 2


def test_offline_mapping_preserves_every_field_and_options() -> None:
    schema = local_input_schema()
    catalog = load_airtable_schema()
    assert len(schema) == len(catalog["tables"])
    assert sum(len(fields) for fields in schema.values()) == sum(
        len(table["fields"]) for table in catalog["tables"]
    )


@pytest.mark.parametrize(
    "failure", ["table", "field", "duplicate", "case", "link", "attachment", "choice"]
)
def test_local_source_rejects_invalid_inputs(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "case.json"
    data = write_local_input(path)
    if failure == "table":
        data["tables"]["unknown"] = []
    elif failure == "field":
        data["tables"]["cases"][0]["fields"]["unknown"] = True
    elif failure == "duplicate":
        data["tables"]["cases"].append(data["tables"]["cases"][0])
    elif failure == "case":
        data["caseId"] = "absent"
    elif failure == "attachment":
        data["tables"]["documents"][0]["fields"]["file_attachments_json"] = [
            {"filename": "missing-id"}
        ]
    elif failure == "choice":
        data["tables"]["contacts"][0]["fields"]["participant_type"] = "unknown-choice"
    else:
        case_fields = data["tables"]["cases"][0]["fields"]
        link = next(k for k, v in case_fields.items() if isinstance(v, list))
        case_fields[link] = "not-an-array"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LocalCaseSourceError):
        LocalCaseSource(path).capture()


def test_local_source_hash_is_stable_and_detects_edits(tmp_path: Path) -> None:
    path = tmp_path / "case.json"
    data = write_local_input(path)
    first = LocalCaseSource(path).capture()
    assert first.snapshot_sha256 == LocalCaseSource(path).load().snapshot_sha256
    data["tables"]["cases"][0]["fields"]["name"] = "Changed synthetic title"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert first.snapshot_sha256 != LocalCaseSource(path).load().snapshot_sha256
