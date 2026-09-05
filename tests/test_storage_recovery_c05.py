from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application import (
    AcceptOriginalCommand,
    OriginalStorageService,
    StorageInspection,
)
from case_docket.repository import SQLiteUnitOfWorkFactory
from case_docket.storage import ManagedFilesystem, StorageCollisionError


FILE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ORPHAN_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class SyntheticCrash(BaseException):
    pass


class SequenceIds:
    def __init__(self, *values: str):
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)


def _service(
    filesystem: ManagedFilesystem,
    database: Path,
    *ids: str,
) -> OriginalStorageService:
    return OriginalStorageService(
        SQLiteUnitOfWorkFactory(database),
        filesystem,
        SequenceIds(*ids),
        FixedClock(),
    )


@pytest.mark.parametrize(
    ("crash_event", "expected_action"),
    [
        ("after_prepare", "recovered"),
        ("before_atomic_move", "reconciled"),
        ("after_atomic_move", "reconciled"),
    ],
)
def test_reconciliation_recovers_crash_before_or_after_finalize(
    c05_workspace: Path,
    crash_event: str,
    expected_action: str,
) -> None:
    source_root = c05_workspace.parent / f"source-{crash_event}"
    source_root.mkdir()
    source = source_root / "синтетичний оригінал.txt"
    source.write_bytes(b"crash-safe synthetic bytes")
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)
    triggered = False

    def crash(event: str, path: Path) -> None:
        nonlocal triggered
        del path
        if event == crash_event and not triggered:
            triggered = True
            raise SyntheticCrash(event)

    interrupted = ManagedFilesystem(c05_workspace, fault_hook=crash)
    database = interrupted.layout.zone("database") / "varta.sqlite3"
    command = AcceptOriginalCommand(
        source_root,
        "синтетичний оригінал.txt",
        "syntetychnyi_oryhinal.txt",
        "content",
    )
    with pytest.raises(SyntheticCrash):
        _service(interrupted, database, FILE_ID).accept(command)

    recovered_filesystem = ManagedFilesystem(c05_workspace)
    report = _service(recovered_filesystem, database).reconcile()
    item = next(item for item in report.items if item.file_id == FILE_ID)

    assert item.status == "verified"
    assert item.action == expected_action
    assert report.failures == 0
    with SQLiteUnitOfWorkFactory(database)() as unit_of_work:
        record = unit_of_work.files.get(FILE_ID)
    assert record is not None
    assert record.state == "verified"
    assert record.original_name == "синтетичний оригінал.txt"
    assert record.managed_name == "syntetychnyi_oryhinal.txt"
    stored = c05_workspace / ".varta" / Path(*record.storage_reference.split("/"))
    assert stored.read_bytes() == b"crash-safe synthetic bytes"
    assert not bool(stored.stat().st_mode & stat.S_IWUSR)
    assert recovered_filesystem.scan().pending == ()
    assert recovered_filesystem.scan().issues == ()
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before


def test_reconciliation_reports_orphan_staging_without_adopting_it(
    c05_workspace: Path,
) -> None:
    filesystem = ManagedFilesystem(c05_workspace)
    staging = filesystem.layout.zone("staging") / "v1" / f"{ORPHAN_ID}.part"
    staging.write_bytes(b"no provenance manifest")
    database = filesystem.layout.zone("database") / "varta.sqlite3"

    report = _service(filesystem, database).reconcile()

    issue = next(item for item in report.items if item.action == "orphan_staging_file")
    assert issue.status == "error"
    assert report.failures == 1
    with SQLiteUnitOfWorkFactory(database)() as unit_of_work:
        assert unit_of_work.files.list() == ()
    assert staging.read_bytes() == b"no provenance manifest"


def test_reconciliation_reports_malformed_manifest_without_adopting_it(
    c05_workspace: Path,
) -> None:
    filesystem = ManagedFilesystem(c05_workspace)
    manifest = filesystem.layout.zone("staging") / "v1" / f"{FILE_ID}.json"
    manifest.write_text('{"contract":"varta.managed-original","version":1', encoding="utf-8")
    database = filesystem.layout.zone("database") / "varta.sqlite3"

    report = _service(filesystem, database).reconcile()

    issue = next(item for item in report.items if item.action == "invalid_manifest")
    assert issue.status == "error"
    assert report.failures == 1
    with SQLiteUnitOfWorkFactory(database)() as unit_of_work:
        assert unit_of_work.files.list() == ()


def test_reconciliation_detects_external_byte_mismatch_without_repairing_original(
    c05_workspace: Path,
) -> None:
    source_root = c05_workspace.parent / "mismatch-source"
    source_root.mkdir()
    source = source_root / "synthetic.bin"
    source.write_bytes(b"expected bytes")
    filesystem = ManagedFilesystem(c05_workspace)
    database = filesystem.layout.zone("database") / "varta.sqlite3"
    accepted = _service(filesystem, database, FILE_ID).accept(
        AcceptOriginalCommand(source_root, "synthetic.bin")
    )
    stored = c05_workspace / ".varta" / Path(*accepted.storage_reference.split("/"))
    os.chmod(stored, stat.S_IREAD | stat.S_IWRITE)
    stored.write_bytes(b"externally changed")

    report = _service(filesystem, database).reconcile()
    item = next(item for item in report.items if item.file_id == FILE_ID)

    assert item.status == "mismatch"
    assert item.action == "integrity_failure"
    assert stored.read_bytes() == b"externally changed"
    assert source.read_bytes() == b"expected bytes"
    with SQLiteUnitOfWorkFactory(database)() as unit_of_work:
        record = unit_of_work.files.get(FILE_ID)
    assert record is not None
    assert record.state == "mismatch"
    assert record.integrity_status == "mismatch"


def test_reconciliation_marks_simulated_missing_reference_without_touching_bytes(
    c05_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = c05_workspace.parent / "missing-source"
    source_root.mkdir()
    source = source_root / "synthetic.bin"
    source.write_bytes(b"registered bytes remain intact")
    filesystem = ManagedFilesystem(c05_workspace)
    database = filesystem.layout.zone("database") / "varta.sqlite3"
    accepted = _service(filesystem, database, FILE_ID).accept(
        AcceptOriginalCommand(source_root, "synthetic.bin")
    )
    stored = c05_workspace / ".varta" / Path(*accepted.storage_reference.split("/"))

    monkeypatch.setattr(
        filesystem,
        "inspect",
        lambda *args, **kwargs: StorageInspection(
            "reference_unavailable", None, None, None
        ),
    )
    report = _service(filesystem, database).reconcile()
    item = next(item for item in report.items if item.file_id == FILE_ID)

    assert item.status == "reference_unavailable"
    assert item.action == "integrity_failure"
    assert stored.read_bytes() == b"registered bytes remain intact"
    assert source.read_bytes() == b"registered bytes remain intact"
    with SQLiteUnitOfWorkFactory(database)() as unit_of_work:
        record = unit_of_work.files.get(FILE_ID)
    assert record is not None
    assert record.state == "reference_unavailable"
    assert record.integrity_status == "reference_unavailable"


def test_finalize_collision_never_overwrites_existing_target(c05_workspace: Path) -> None:
    source_root = c05_workspace.parent / "collision-source"
    source_root.mkdir()
    (source_root / "synthetic.bin").write_bytes(b"new bytes")
    collision_bytes = b"pre-existing foreign bytes"

    def create_collision(event: str, path: Path) -> None:
        del path
        if event != "before_atomic_move":
            return
        target = (
            c05_workspace
            / ".varta"
            / "originals"
            / "v1"
            / FILE_ID[:2]
            / FILE_ID
            / "original.bin"
        )
        target.write_bytes(collision_bytes)

    filesystem = ManagedFilesystem(c05_workspace, fault_hook=create_collision)
    database = filesystem.layout.zone("database") / "varta.sqlite3"

    with pytest.raises(StorageCollisionError, match="не перезаписує"):
        _service(filesystem, database, FILE_ID).accept(
            AcceptOriginalCommand(source_root, "synthetic.bin")
        )

    target = (
        c05_workspace
        / ".varta"
        / "originals"
        / "v1"
        / FILE_ID[:2]
        / FILE_ID
        / "original.bin"
    )
    assert target.read_bytes() == collision_bytes
