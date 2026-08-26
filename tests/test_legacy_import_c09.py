from pathlib import Path

from openpyxl import Workbook

import pytest

from case_docket.legacy_import import dry_run, import_legacy
from case_docket.repository import SQLiteRepository


def _xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Синтетичний реєстр"
    sheet.append(["external_id", "title", "status"])
    sheet.append(["legacy-1", "Вигаданий документ", "review"])
    sheet.append(["legacy-2", "Інший вигаданий документ", "done"])
    workbook.save(path)


def test_xlsx_dry_run_is_zero_write_and_import_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.xlsx"
    _xlsx(source)
    before = source.read_bytes()
    report = dry_run(source)
    assert report.records == 2 and report.proposed == 2 and report.imported == 0
    database = tmp_path / "target.sqlite3"
    backup = tmp_path / "verified-backup"
    backup.mkdir()
    repository = SQLiteRepository(database)
    first = import_legacy(repository._conn, source, backup_destination=backup)
    second = import_legacy(repository._conn, source, backup_destination=backup)
    assert first.imported == 2 and first.skipped == 0
    assert second.imported == 0 and second.skipped == 2
    assert repository._conn.execute("SELECT COUNT(*) FROM legacy_import_records").fetchone()[0] == 2
    assert source.read_bytes() == before
    repository.close()


def test_caseflow_duplicate_external_reference_is_explained(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.caseflow"
    source.write_text('{"records":[{"id":"same","title":"A"},{"id":"same","title":"B"}]}', encoding="utf-8")
    report = dry_run(source)
    assert report.conflicts == 1
    assert report.issues[0]["action"] == "manual_review_required"
    repository = SQLiteRepository(tmp_path / "target.sqlite3")
    backup = tmp_path / "verified-backup"
    backup.mkdir()
    imported = import_legacy(repository._conn, source, backup_destination=backup)
    assert imported.imported == 1
    assert repository._conn.execute("SELECT COUNT(*) FROM legacy_import_records WHERE status='manual_review_required'").fetchone()[0] == 1
    repository.close()


def test_import_requires_verified_backup_destination(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.caseflow"
    source.write_text('{"records": [{"id": "one"}]}', encoding="utf-8")
    repository = SQLiteRepository(tmp_path / "target.sqlite3")
    with pytest.raises(ValueError, match="backup destination"):
        import_legacy(repository._conn, source, backup_destination=tmp_path / "missing")
    repository.close()
