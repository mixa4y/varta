from __future__ import annotations

import hashlib
import io
import sqlite3
import stat
import zipfile
from pathlib import Path

import pytest

from case_docket.application import ConflictError, IntakeCommand
from case_docket.repository import SQLiteRepository
from case_docket.runtime import WorkspaceDatabaseConflictError, build_intake_runtime


def _source_tree_snapshot(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.stat()
        digest.update(relative.encode("utf-8"))
        digest.update(f":{metadata.st_mode}:{metadata.st_size}:{metadata.st_mtime_ns}\n".encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _stored_path(workspace: Path, reference: str) -> Path:
    return workspace / ".varta" / Path(*reference.split("/"))


def test_folder_intake_is_idempotent_duplicate_explicit_and_restart_inventory_is_sqlite_only(
    c05_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = c05_workspace.parent / "synthetic-folder-input"
    source.mkdir()
    (source / "a-original.txt").write_bytes("синтетичні байти".encode())
    (source / "b-copy.txt").write_bytes("синтетичні байти".encode())
    (source / "empty.bin").write_bytes(b"")
    nested = source / "nested"
    nested.mkdir()
    (nested / "different.txt").write_bytes(b"different synthetic bytes")
    before = _source_tree_snapshot(source)

    runtime = build_intake_runtime(c05_workspace)
    batch = runtime.intake_service.intake(
        IntakeCommand(source=source, idempotency_key="folder-synthetic-001")
    )

    assert batch.status == "succeeded"
    assert batch.detected_kind == "folder"
    assert dict(batch.counts) == {
        "discovered": 0,
        "accepted": 3,
        "duplicate": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert _source_tree_snapshot(source) == before
    by_name = {entry.literal_name: entry for entry in batch.entries}
    assert by_name["a-original.txt"].status == "accepted"
    assert by_name["b-copy.txt"].status == "duplicate"
    assert by_name["b-copy.txt"].duplicate_of_file_ids == (
        by_name["a-original.txt"].file_id,
    )
    assert by_name["empty.bin"].size_bytes == 0
    assert by_name["empty.bin"].sha256 == hashlib.sha256(b"").hexdigest()
    accepted = [entry for entry in batch.entries if entry.file_id is not None]
    assert len({entry.file_id for entry in accepted}) == 4
    assert len({entry.storage_reference for entry in accepted}) == 4
    for entry in accepted:
        assert entry.storage_reference is not None
        assert _stored_path(c05_workspace, entry.storage_reference).is_file()

    replay = runtime.intake_service.intake(
        IntakeCommand(source=source, idempotency_key="folder-synthetic-001")
    )
    assert replay.replayed is True
    assert replay.batch_id == batch.batch_id
    assert replay.entries == batch.entries

    other = c05_workspace.parent / "different-source.txt"
    other.write_text("other synthetic", encoding="utf-8")
    with pytest.raises(ConflictError, match="Idempotency key"):
        runtime.intake_service.intake(
            IntakeCommand(source=other, idempotency_key="folder-synthetic-001")
        )

    restarted = build_intake_runtime(c05_workspace)

    def fail_if_source_is_read(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("inventory must not enumerate source or filesystem")

    monkeypatch.setattr(restarted.intake_service._source, "discover", fail_if_source_is_read)
    inventory = restarted.intake_service.inventory()
    assert inventory.to_dict()["authority"] == "sqlite"
    assert inventory.batches == (batch,)

    connection = sqlite3.connect(runtime.database_path)
    try:
        batch_history = connection.execute(
            """
            SELECT from_status, to_status
            FROM import_batch_status_history
            WHERE import_batch_id = ?
            ORDER BY sequence
            """,
            (batch.batch_id,),
        ).fetchall()
        entry_history = connection.execute(
            """
            SELECT from_status, to_status
            FROM intake_entry_status_history
            WHERE intake_entry_id = ?
            ORDER BY sequence
            """,
            (by_name["a-original.txt"].entry_id,),
        ).fetchall()
        linked_batch = connection.execute(
            "SELECT import_batch_id FROM file_objects WHERE id = ?",
            (by_name["a-original.txt"].file_id,),
        ).fetchone()
        assert batch_history == [
            (None, "enumerating"),
            ("enumerating", "processing"),
            ("processing", "succeeded"),
        ]
        assert entry_history == [(None, "discovered"), ("discovered", "accepted")]
        assert linked_batch == (batch.batch_id,)
        with pytest.raises(sqlite3.IntegrityError, match="invalid intake entry status transition"):
            connection.execute(
                "UPDATE intake_entries SET status = 'failed', error_code = 'late' WHERE id = ?",
                (by_name["a-original.txt"].entry_id,),
            )
    finally:
        connection.close()


def test_mixed_zip_keeps_successes_visible_rejects_traversal_and_does_not_expand_nested(
    c05_workspace: Path,
) -> None:
    source = c05_workspace.parent / "mixed-synthetic.zip"
    nested_buffer = io.BytesIO()
    with zipfile.ZipFile(nested_buffer, "w") as nested_archive:
        nested_archive.writestr("inner.txt", b"nested synthetic")
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("docs/", b"")
        archive.writestr("docs/good.txt", "добрі синтетичні байти".encode())
        archive.writestr("empty.bin", b"")
        archive.writestr("../escape.txt", b"must never extract")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("docs/good.txt", b"duplicate member path")
        archive.writestr("nested.zip", nested_buffer.getvalue())
    before = (source.read_bytes(), source.stat().st_mtime_ns)

    runtime = build_intake_runtime(c05_workspace)
    batch = runtime.intake_service.intake(
        IntakeCommand(source=source, idempotency_key="zip-synthetic-001")
    )

    assert batch.status == "partial"
    assert batch.detected_kind == "zip"
    assert dict(batch.counts) == {
        "discovered": 0,
        "accepted": 3,
        "duplicate": 0,
        "failed": 1,
        "skipped": 2,
    }
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    traversal = next(entry for entry in batch.entries if entry.source_relative_path == "../escape.txt")
    assert traversal.status == "failed"
    assert traversal.error_code == "unsafe_archive_path"
    good_members = [
        entry for entry in batch.entries if entry.source_relative_path == "docs/good.txt"
    ]
    assert [entry.status for entry in good_members] == ["accepted", "skipped"]
    assert good_members[1].error_code == "duplicate_archive_member"
    empty = next(entry for entry in batch.entries if entry.source_relative_path == "empty.bin")
    assert empty.status == "accepted"
    assert empty.size_bytes == 0
    nested = next(entry for entry in batch.entries if entry.source_relative_path == "nested.zip")
    assert nested.status == "accepted"
    assert nested.type_hint == "nested_zip_not_expanded"
    assert nested.storage_reference is not None
    assert _stored_path(c05_workspace, nested.storage_reference).read_bytes() == nested_buffer.getvalue()
    assert not any(entry.source_relative_path == "inner.txt" for entry in batch.entries)
    assert not (c05_workspace.parent / "escape.txt").exists()


@pytest.mark.parametrize(
    ("filename", "payload", "entry_status", "error_code", "detected_kind"),
    [
        ("corrupt.zip", b"not a zip", "failed", "corrupt_zip", "zip"),
        ("unsupported.rar", b"synthetic archive bytes", "skipped", "unsupported_archive_format", "file"),
    ],
)
def test_corrupt_and_unavailable_archive_capabilities_are_explicit(
    c05_workspace: Path,
    filename: str,
    payload: bytes,
    entry_status: str,
    error_code: str,
    detected_kind: str,
) -> None:
    source = c05_workspace.parent / filename
    source.write_bytes(payload)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    runtime = build_intake_runtime(c05_workspace)

    batch = runtime.intake_service.intake(
        IntakeCommand(source=source, idempotency_key=f"archive-{filename}")
    )

    assert batch.status == "failed"
    assert batch.detected_kind == detected_kind
    assert len(batch.entries) == 1
    assert batch.entries[0].status == entry_status
    assert batch.entries[0].error_code == error_code
    assert batch.entries[0].file_id is None
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_encrypted_zip_member_is_explicit_and_source_archive_remains_unchanged(
    c05_workspace: Path,
) -> None:
    source = c05_workspace.parent / "encrypted-flag-synthetic.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("secret.txt", b"synthetic encrypted marker")
    payload = bytearray(source.read_bytes())
    local_header = payload.index(b"PK\x03\x04")
    central_header = payload.index(b"PK\x01\x02")
    local_flags = int.from_bytes(payload[local_header + 6 : local_header + 8], "little") | 0x1
    central_flags = int.from_bytes(
        payload[central_header + 8 : central_header + 10], "little"
    ) | 0x1
    payload[local_header + 6 : local_header + 8] = local_flags.to_bytes(2, "little")
    payload[central_header + 8 : central_header + 10] = central_flags.to_bytes(2, "little")
    source.write_bytes(payload)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    runtime = build_intake_runtime(c05_workspace)

    batch = runtime.intake_service.intake(
        IntakeCommand(source=source, idempotency_key="zip-encrypted-synthetic-001")
    )

    assert batch.status == "failed"
    assert batch.detected_kind == "zip"
    assert len(batch.entries) == 1
    assert batch.entries[0].status == "failed"
    assert batch.entries[0].error_code == "encrypted_archive_member"
    assert batch.entries[0].file_id is None
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_same_bytes_under_another_path_get_new_original_and_duplicate_provenance(
    c05_workspace: Path,
) -> None:
    first_source = c05_workspace.parent / "first-synthetic.bin"
    second_source = c05_workspace.parent / "second-synthetic.bin"
    first_source.write_bytes(b"same synthetic payload")
    second_source.write_bytes(b"same synthetic payload")
    runtime = build_intake_runtime(c05_workspace)

    first = runtime.intake_service.intake(IntakeCommand(first_source, "same-bytes-1"))
    second = runtime.intake_service.intake(IntakeCommand(second_source, "same-bytes-2"))

    first_entry = first.entries[0]
    second_entry = second.entries[0]
    assert first_entry.status == "accepted"
    assert second_entry.status == "duplicate"
    assert second_entry.duplicate_of_file_ids == (first_entry.file_id,)
    assert first_entry.file_id != second_entry.file_id
    assert first_entry.storage_reference != second_entry.storage_reference
    assert first_entry.storage_reference is not None
    assert second_entry.storage_reference is not None
    assert _stored_path(c05_workspace, first_entry.storage_reference).read_bytes() == (
        b"same synthetic payload"
    )
    assert _stored_path(c05_workspace, second_entry.storage_reference).read_bytes() == (
        b"same synthetic payload"
    )
    assert not bool(
        _stored_path(c05_workspace, second_entry.storage_reference).stat().st_mode & stat.S_IWUSR
    )


def test_same_literal_name_different_bytes_and_folder_zip_never_overwrite_or_expand(
    c05_workspace: Path,
) -> None:
    source = c05_workspace.parent / "same-name-folder"
    first = source / "alpha" / "same-name.txt"
    second = source / "beta" / "same-name.txt"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"first synthetic content")
    second.write_bytes(b"second synthetic content")
    inner_zip = source / "ordinary-container.zip"
    with zipfile.ZipFile(inner_zip, "w") as archive:
        archive.writestr("must-not-expand.txt", b"contained synthetic bytes")
    before = _source_tree_snapshot(source)
    runtime = build_intake_runtime(c05_workspace)

    batch = runtime.intake_service.intake(
        IntakeCommand(source=source, idempotency_key="same-name-different-bytes-001")
    )

    assert batch.status == "succeeded"
    same_name = [entry for entry in batch.entries if entry.literal_name == "same-name.txt"]
    assert len(same_name) == 2
    assert {entry.status for entry in same_name} == {"accepted"}
    assert len({entry.sha256 for entry in same_name}) == 2
    assert len({entry.storage_reference for entry in same_name}) == 2
    container = next(
        entry for entry in batch.entries if entry.literal_name == "ordinary-container.zip"
    )
    assert container.status == "accepted"
    assert container.type_hint == "zip_file_not_expanded"
    assert not any(entry.literal_name == "must-not-expand.txt" for entry in batch.entries)
    assert _source_tree_snapshot(source) == before


def test_runtime_preserves_single_legacy_database_and_rejects_dual_authority(
    c05_workspace: Path,
) -> None:
    legacy = c05_workspace / ".caseflow" / "varta.sqlite3"
    legacy.parent.mkdir(parents=True)
    repository = SQLiteRepository(legacy)
    repository.close()

    runtime = build_intake_runtime(c05_workspace)
    assert runtime.database_path == legacy
    target = c05_workspace / ".varta" / "database" / "varta.sqlite3"
    assert not target.exists()

    target_repository = SQLiteRepository(target)
    target_repository.close()
    with pytest.raises(WorkspaceDatabaseConflictError, match="одночасно існують"):
        build_intake_runtime(c05_workspace)
