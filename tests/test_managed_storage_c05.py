from __future__ import annotations

import errno
import hashlib
import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application import (
    AcceptOriginalCommand,
    OriginalStorageService,
)
from case_docket.repository import SQLiteUnitOfWorkFactory
from case_docket.storage import ManagedFilesystem, StorageIOError, UnsafePathError
from case_docket.storage.paths import native_path


FILE_1 = "11111111-1111-4111-8111-111111111111"
FILE_2 = "22222222-2222-4222-8222-222222222222"
FILE_3 = "33333333-3333-4333-8333-333333333333"
FILE_4 = "abcdefab-cdef-4abc-8def-abcdefabcdef"


class SequenceIds:
    def __init__(self, *values: str):
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 18, 12, 34, 56, tzinfo=timezone.utc)


def _service(
    workspace: Path,
    filesystem: ManagedFilesystem,
    *ids: str,
) -> tuple[OriginalStorageService, SQLiteUnitOfWorkFactory]:
    database = filesystem.layout.zone("database") / "varta.sqlite3"
    factory = SQLiteUnitOfWorkFactory(database)
    return OriginalStorageService(factory, filesystem, SequenceIds(*ids), FixedClock()), factory


def _stored_path(workspace: Path, reference: str) -> Path:
    return workspace / ".varta" / Path(*reference.split("/"))


def test_streaming_accept_preserves_literal_provenance_and_separates_managed_name(
    c05_workspace: Path,
) -> None:
    source_root = c05_workspace.parent / "synthetic-source"
    source = source_root / "Вхідні" / "Оригінал № 1.txt"
    source.parent.mkdir(parents=True)
    payload = "синтетичні байти\n".encode()
    source.write_bytes(payload)
    source_stat = source.stat()
    chunks: list[str] = []

    def record_chunks(event: str, path: Path) -> None:
        del path
        if event == "after_stage_write":
            chunks.append(event)

    filesystem = ManagedFilesystem(c05_workspace, chunk_size=3, fault_hook=record_chunks)
    service, factory = _service(c05_workspace, filesystem, FILE_1)

    accepted = service.accept(
        AcceptOriginalCommand(
            source_root=source_root,
            source_relative_path="Вхідні/Оригінал № 1.txt",
            managed_name="20260818_oryhinal_001.txt",
            kind="content",
        )
    )

    stored = _stored_path(c05_workspace, accepted.storage_reference)
    assert len(chunks) > 1
    assert accepted.file_id == FILE_1
    assert accepted.original_name == "Оригінал № 1.txt"
    assert accepted.managed_name == "20260818_oryhinal_001.txt"
    assert accepted.source_relative_path == "Вхідні/Оригінал № 1.txt"
    assert accepted.sha256 == hashlib.sha256(payload).hexdigest()
    assert accepted.bytes == len(payload)
    assert accepted.cleanup_pending is False
    assert stored.read_bytes() == payload
    assert FILE_1 in stored.as_posix()
    assert "Оригінал" not in stored.as_posix()
    assert "oryhinal" not in stored.as_posix()
    assert not bool(stored.stat().st_mode & stat.S_IWUSR)
    assert source.read_bytes() == payload
    assert source.stat().st_size == source_stat.st_size
    assert source.stat().st_mtime_ns == source_stat.st_mtime_ns

    reopened = SQLiteUnitOfWorkFactory(factory.database_path)
    with reopened() as unit_of_work:
        record = unit_of_work.files.get(FILE_1)
    assert record is not None
    assert record.original_name == "Оригінал № 1.txt"
    assert record.managed_name == "20260818_oryhinal_001.txt"
    assert record.storage_reference == accepted.storage_reference
    assert record.state == "verified"
    assert record.integrity_status == "verified"


def test_duplicate_and_name_collisions_never_overwrite_or_merge_records(
    c05_workspace: Path,
) -> None:
    source_root = c05_workspace.parent / "collision-source"
    source_root.mkdir()
    (source_root / "same-name.txt").write_bytes(b"first")
    (source_root / "different-name.txt").write_bytes(b"first")
    nested = source_root / "nested"
    nested.mkdir()
    (nested / "same-name.txt").write_bytes(b"second")
    filesystem = ManagedFilesystem(c05_workspace)
    service, factory = _service(c05_workspace, filesystem, FILE_1, FILE_2, FILE_3)

    first = service.accept(
        AcceptOriginalCommand(source_root, "same-name.txt", "Managed.TXT", "content")
    )
    different_bytes = service.accept(
        AcceptOriginalCommand(source_root, "nested/same-name.txt", "managed.txt", "attachment")
    )
    duplicate = service.accept(
        AcceptOriginalCommand(source_root, "different-name.txt", "Managed.TXT", "signature")
    )

    assert first.storage_reference != different_bytes.storage_reference
    assert first.storage_reference != duplicate.storage_reference
    assert _stored_path(c05_workspace, first.storage_reference).read_bytes() == b"first"
    assert _stored_path(c05_workspace, different_bytes.storage_reference).read_bytes() == b"second"
    assert _stored_path(c05_workspace, duplicate.storage_reference).read_bytes() == b"first"
    assert first.duplicate_of_file_ids == ()
    assert different_bytes.duplicate_of_file_ids == ()
    assert duplicate.duplicate_of_file_ids == (FILE_1,)

    with factory() as unit_of_work:
        records = unit_of_work.files.list()
    assert [record.file_id for record in records] == [FILE_1, FILE_2, FILE_3]
    assert [record.kind for record in records] == ["content", "attachment", "signature"]
    assert [record.managed_name for record in records] == [
        "Managed.TXT",
        "managed.txt",
        "Managed.TXT",
    ]


def test_streaming_accept_reads_an_actual_source_path_longer_than_windows_max_path(
    c05_workspace: Path,
) -> None:
    source_root = c05_workspace.parent / "long-source"
    components = [f"довгий-{index}-" + "я" * 55 for index in range(4)]
    filename = "Оригінал-" + "Ї" * 80 + ".bin"
    relative = "/".join((*components, filename))
    source_parent = source_root.joinpath(*components)
    source = source_parent / filename
    os.makedirs(native_path(source_parent))
    try:
        with open(native_path(source), "wb") as stream:
            stream.write(b"long-path synthetic bytes")
        assert len(os.path.abspath(source)) > 260
        source_metadata = os.stat(native_path(source))
        before = (source_metadata.st_size, source_metadata.st_mtime_ns)
        filesystem = ManagedFilesystem(c05_workspace)
        service, _ = _service(c05_workspace, filesystem, FILE_1)

        accepted = service.accept(AcceptOriginalCommand(source_root, relative))

        assert accepted.source_relative_path == relative
        assert accepted.original_name == filename
        assert _stored_path(c05_workspace, accepted.storage_reference).read_bytes() == (
            b"long-path synthetic bytes"
        )
        assert (os.stat(native_path(source)).st_size, os.stat(native_path(source)).st_mtime_ns) == before
    finally:
        try:
            os.unlink(native_path(source))
        except OSError:
            pass
        for directory in (source_parent, *source_parent.parents):
            if directory == source_root.parent:
                break
            try:
                os.rmdir(native_path(directory))
            except OSError:
                break


def test_verified_original_metadata_and_record_cannot_be_updated_or_deleted(
    c05_workspace: Path,
) -> None:
    source_root = c05_workspace.parent / "immutable-source"
    source_root.mkdir()
    (source_root / "synthetic.bin").write_bytes(b"immutable")
    filesystem = ManagedFilesystem(c05_workspace)
    service, factory = _service(c05_workspace, filesystem, FILE_1)
    accepted = service.accept(AcceptOriginalCommand(source_root, "synthetic.bin"))
    stored = _stored_path(c05_workspace, accepted.storage_reference)

    connection = sqlite3.connect(factory.database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="metadata is immutable"):
            connection.execute(
                "UPDATE file_objects SET original_name = 'changed.bin' WHERE id = ?",
                (FILE_1,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="verified original is immutable"):
            connection.execute("DELETE FROM file_objects WHERE id = ?", (FILE_1,))
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="storage record is immutable"):
            connection.execute("DELETE FROM managed_storage_records WHERE file_id = ?", (FILE_1,))
    finally:
        connection.close()

    assert stored.read_bytes() == b"immutable"


def test_readonly_source_is_accepted_without_source_mutation(c05_workspace: Path) -> None:
    source_root = c05_workspace.parent / "readonly-source"
    source_root.mkdir()
    source = source_root / "readonly.txt"
    source.write_bytes(b"readonly synthetic")
    before = source.stat()
    os.chmod(source, stat.S_IREAD)
    try:
        filesystem = ManagedFilesystem(c05_workspace)
        service, _ = _service(c05_workspace, filesystem, FILE_1)
        accepted = service.accept(AcceptOriginalCommand(source_root, "readonly.txt"))
        assert _stored_path(c05_workspace, accepted.storage_reference).read_bytes() == source.read_bytes()
        assert source.stat().st_size == before.st_size
        assert source.stat().st_mtime_ns == before.st_mtime_ns
    finally:
        os.chmod(source, stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("failure", ["locked", "disk_full"])
def test_locked_or_disk_full_failure_is_explicit_and_does_not_accept_partial_original(
    c05_workspace: Path,
    failure: str,
) -> None:
    source_root = c05_workspace.parent / f"{failure}-source"
    source_root.mkdir()
    source = source_root / "synthetic.bin"
    source.write_bytes(b"abcdefghijk")
    before = (source.read_bytes(), source.stat().st_mtime_ns)

    def fail(event: str, path: Path) -> None:
        del path
        if failure == "locked" and event == "before_source_open":
            raise PermissionError(errno.EACCES, "synthetic lock")
        if failure == "disk_full" and event == "after_stage_write":
            raise OSError(errno.ENOSPC, "synthetic disk full")

    filesystem = ManagedFilesystem(c05_workspace, chunk_size=4, fault_hook=fail)
    service, _ = _service(c05_workspace, filesystem, FILE_1)

    with pytest.raises(StorageIOError, match="Streaming copy не завершено"):
        service.accept(AcceptOriginalCommand(source_root, "synthetic.bin"))

    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert filesystem.scan().finalized_file_ids == ()
    assert not list((c05_workspace / ".varta" / "staging" / "v1").glob("*.part"))


def test_noncanonical_case_variant_file_id_is_rejected_before_storage_write(
    c05_workspace: Path,
) -> None:
    source_root = c05_workspace.parent / "id-source"
    source_root.mkdir()
    (source_root / "synthetic.txt").write_text("synthetic", encoding="utf-8")
    filesystem = ManagedFilesystem(c05_workspace)
    service, _ = _service(c05_workspace, filesystem, FILE_4.upper())

    with pytest.raises(UnsafePathError, match="lowercase UUIDv4"):
        service.accept(AcceptOriginalCommand(source_root, "synthetic.txt"))
