"""R04 populated SQLite -> application-query readiness gate."""
from __future__ import annotations

import sqlite3
from dataclasses import InitVar, dataclass, field
from pathlib import Path

from case_docket.application.evidence_map_export import RecordEvidenceMapExportCommand
from case_docket.application.evidence_map_source import (
    EvidenceMapSourceQuery,
    EvidenceMapSourceQueryService,
)
from case_docket.repository import SQLiteEvidenceMapSourcePorts, SQLiteUnitOfWorkFactory

from test_evidence_map_source_r02 import CASE_ID, PROFILE_VERSION, _seed_database


@dataclass(frozen=True, slots=True)
class _SafeSyntheticHandle:
    """Isolated, test-only handle that cannot select an existing case database."""

    root: InitVar[Path]
    label: str = field(
        init=False,
        default="synthetic://r04/consumer-readiness/v1",
    )
    database: Path = field(init=False)

    def __post_init__(self, root: Path) -> None:
        synthetic_root = root / "r04-safe-synthetic-handle"
        synthetic_root.mkdir()
        database = synthetic_root / "varta.sqlite3"
        _seed_database(database)
        object.__setattr__(self, "database", database)

    def query(self, *, page_size: int):
        return EvidenceMapSourceQueryService(
            SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(self.database))
        ).query(
            EvidenceMapSourceQuery(
                CASE_ID,
                PROFILE_VERSION,
                "metadata_only",
                page_size,
            )
        )


def _rows(database: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(database) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        return {
            name: tuple(connection.execute(f'SELECT * FROM "{name}"').fetchall())
            for name in names
        }


def _query(database: Path, page_size: int = 1):
    return EvidenceMapSourceQueryService(
        SQLiteEvidenceMapSourcePorts(SQLiteUnitOfWorkFactory(database))
    ).query(EvidenceMapSourceQuery(CASE_ID, PROFILE_VERSION, "metadata_only", page_size))


def test_populated_golden_contract_and_allowed_audit_db_diff(tmp_path: Path) -> None:
    database = tmp_path / "r04-golden.sqlite3"
    _seed_database(database)
    before = _rows(database)

    source = _query(database)
    assert len(source.proceedings) == 2
    assert len(source.files) == 2
    assert len(source.evidence.actors) == 2
    assert len(source.evidence.documents) == 2
    assert len(source.evidence.events) == 1
    assert len(source.evidence.claims) == 1
    assert len(source.evidence.relations) == 1
    assert len(source.reviews) == 2
    assert len(source.findings) == 1
    assert source.data_cutoff == "2026-01-05T00:00:00+00:00"

    factory = SQLiteUnitOfWorkFactory(database)
    command = RecordEvidenceMapExportCommand(
        export_id="export-r04-golden",
        case_id=CASE_ID,
        case_profile_id="profile-r02-v1",
        schema_version="1.1.0",
        product_version="0.1.0",
        export_profile="metadata_only",
        source_revision=source.source_revision,
        source_snapshot_sha256="a" * 64,
        generated_by="synthetic-r04",
        generated_at="2026-01-06T00:00:00+00:00",
    )
    with factory(write=True) as unit_of_work:
        unit_of_work.evidence_map_exports.record_validated(command)
        unit_of_work.commit()

    after = _rows(database)
    changed = {
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    }
    assert changed == {"evidence_map_exports"}


def test_golden_revision_is_independent_of_order_and_restart(tmp_path: Path) -> None:
    forward = tmp_path / "forward.sqlite3"
    reverse = tmp_path / "reverse.sqlite3"
    _seed_database(forward)
    _seed_database(reverse, reverse=True)
    first = _query(forward, page_size=1)
    restarted = _query(forward, page_size=100)
    reversed_source = _query(reverse, page_size=1)
    assert first == restarted
    assert first.source_revision == reversed_source.source_revision


def test_local_smoke_uses_separate_safe_synthetic_handle(tmp_path: Path) -> None:
    handle = _SafeSyntheticHandle(tmp_path)

    first = handle.query(page_size=1)
    restarted = handle.query(page_size=100)

    assert handle.label == "synthetic://r04/consumer-readiness/v1"
    assert first == restarted
    assert first.case_id == CASE_ID
    assert first.case.case_number is None
    assert all(item.record.proceeding_number is None for item in first.proceedings)
    assert {path.name for path in handle.database.parent.iterdir()} == {"varta.sqlite3"}
