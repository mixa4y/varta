from dataclasses import dataclass

import pytest

from case_docket.application.evidence_map import EvidenceMapProjectionService
from case_docket.application.evidence_map_source import EvidenceMapSourceQuery
from test_evidence_map_source_r02 import CASE_ID, PROFILE_VERSION, _seed_database
from case_docket.repository import SQLiteEvidenceMapSourcePorts, SQLiteUnitOfWorkFactory
from case_docket.application.evidence_map_source import EvidenceMapSourceQueryService


@dataclass
class _Audit:
    commands: list[object]

    def record_validated(self, command):
        self.commands.append(command)


def _service(database, audit):
    source = EvidenceMapSourceQueryService(SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(database)))
    return EvidenceMapProjectionService(source, audit)


def test_projection_is_schema_valid_and_hash_is_deterministic(tmp_path):
    database = tmp_path / "synthetic.sqlite3"
    _seed_database(database)
    audit = _Audit([])
    service = _service(database, audit)
    request = EvidenceMapSourceQuery(CASE_ID, PROFILE_VERSION, "metadata_only", 1)
    first = service.project(request, export_id="export-c11-golden")
    second = service.project(request, export_id="export-c11-golden")
    assert service.snapshot_sha256(first) == service.snapshot_sha256(second)
    assert first["inventory"]["physicalFileCount"] == 2
    assert first["inventory"]["reviewDecisionCount"] == 1
    assert len(audit.commands) == 2


def test_projection_rejects_cross_case_source_item(tmp_path):
    database = tmp_path / "synthetic.sqlite3"
    _seed_database(database)
    service = _service(database, _Audit([]))
    request = EvidenceMapSourceQuery("missing-case", PROFILE_VERSION, "metadata_only", 1)
    with pytest.raises(Exception):
        service.project(request, export_id="export-c11-broken")
