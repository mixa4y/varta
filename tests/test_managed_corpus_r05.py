from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from case_docket.application.case_database_import import (
    CaseDatabaseImportService,
    ExecuteCaseDatabaseImportCommand,
    PlanCaseDatabaseImportCommand,
)
from case_docket.corpus_import import ManagedCorpusImporter
from case_docket.corpus_inventory import FilesystemCorpusInventory
from case_docket.repository.sqlite_case_database_import import (
    SQLiteCaseDatabaseImportRepository,
)
from case_docket.runtime import build_intake_runtime
from test_case_database_import_r05 import FixedClock, FixedSource, _snapshot


def test_local_settings_round_trip_without_dpapi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from case_docket.r05_private import R05PrivateSettings, R05PrivateSettingsStore
    import ctypes

    def forbidden(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("Local settings must not use DPAPI")

    monkeypatch.setattr(ctypes, "WinDLL", forbidden, raising=False)
    path = tmp_path / "local" / "settings.json"
    settings = R05PrivateSettings(tmp_path / "synthetic-corpus", tmp_path / "workspace")
    R05PrivateSettingsStore(path).save(settings)
    assert R05PrivateSettingsStore(path).load() == settings
    replacement = R05PrivateSettings(settings.corpus_root, tmp_path / "new-workspace")
    R05PrivateSettingsStore(path).save(replacement)
    assert R05PrivateSettingsStore(path).load() == replacement
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("value", ["{}", "[]", '{"corpusRoot": [], "workspaceRoot": "local"}'])
def test_local_settings_reject_malformed_paths(tmp_path: Path, value: str) -> None:
    from case_docket.r05_private import R05PrivateSettingsStore

    path = tmp_path / "settings.json"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(ValueError):
        R05PrivateSettingsStore(path).load()


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_managed_corpus_is_copied_once_and_source_originals_remain_unchanged(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "synthetic-corpus"
    corpus.mkdir()
    (corpus / "без-розширення").write_bytes(b"alpha")
    (corpus / "synthetic.zip").write_bytes(b"immutable-archive-original")
    nested = corpus / "nested"
    nested.mkdir()
    (nested / "document.txt").write_bytes(b"beta")
    before = _hashes(corpus)

    workspace = tmp_path / "workspace"
    database = build_intake_runtime(workspace).database_path
    repository = SQLiteCaseDatabaseImportRepository(database)
    service = CaseDatabaseImportService(
        FixedSource(_snapshot()),
        FilesystemCorpusInventory(corpus),
        ManagedCorpusImporter(corpus, workspace, database),
        repository,
        repository,
        FixedClock(),
    )
    plan = service.plan(PlanCaseDatabaseImportCommand("mapping-v1"))
    first = service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id, plan.snapshot_sha256, plan.corpus_manifest_sha256
        )
    )
    second = service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id, plan.snapshot_sha256, plan.corpus_manifest_sha256
        )
    )

    assert first.files == {"accepted": 3, "duplicate": 0, "failed": 0, "skipped": 0}
    assert second.files == first.files
    assert _hashes(corpus) == before
    connection = repository._open()
    try:
        assert connection._conn.execute("SELECT COUNT(*) FROM file_objects").fetchone()[0] == 3
        assert (
            connection._conn.execute(
                "SELECT COUNT(*) FROM managed_storage_records WHERE state = 'verified'"
            ).fetchone()[0]
            == 3
        )
    finally:
        connection.close()
