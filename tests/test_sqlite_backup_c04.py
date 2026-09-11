from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application import ContactService, CreateContactCommand
from case_docket.models.contact import Contact
from case_docket.repository import (
    APPLICATION_SCHEMA_CEILING,
    SQLiteBackupError,
    SQLiteRepository,
    SQLiteUnitOfWorkFactory,
    create_online_backup,
    restore_sqlite_snapshot,
    verify_sqlite_database,
)


class SequenceIds:
    def __init__(self, *values: str):
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)


def test_online_backup_restore_integrity_and_committed_readback(tmp_path: Path) -> None:
    database = tmp_path / "source.sqlite3"
    snapshot = tmp_path / "backup" / "snapshot.sqlite3"
    restored = tmp_path / "restore" / "restored.sqlite3"
    factory = SQLiteUnitOfWorkFactory(database)
    ContactService(factory, SequenceIds("contact-committed"), FixedClock()).create(
        CreateContactCommand(
            full_name="Синтетичний збережений контакт",
            participant_type="person",
            email="backup@example.invalid",
        )
    )

    with factory(write=True) as uncommitted:
        uncommitted.contacts.add(
            Contact(
                id="contact-uncommitted",
                full_name="Синтетичний незавершений контакт",
                participant_type="person",
            )
        )
        backup_result = create_online_backup(database, snapshot, pages=1)

    restore_result = restore_sqlite_snapshot(snapshot, restored)
    verification = verify_sqlite_database(restored)
    repository = SQLiteRepository(restored, initialize=False)
    try:
        committed = repository.get_contact("contact-committed")
        not_committed = repository.get_contact("contact-uncommitted")
    finally:
        repository.close()

    assert backup_result.path == snapshot.resolve()
    assert backup_result.schema_version == APPLICATION_SCHEMA_CEILING
    assert backup_result.integrity_check == ("ok",)
    assert backup_result.sha256 == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert restore_result.path == restored.resolve()
    assert restore_result.schema_version == APPLICATION_SCHEMA_CEILING
    assert verification.integrity_check == ("ok",)
    assert verification.foreign_key_violations == ()
    assert committed is not None
    assert committed["email"] == "backup@example.invalid"
    assert not_committed is None


def test_backup_and_restore_refuse_existing_or_same_target(tmp_path: Path) -> None:
    database = tmp_path / "source.sqlite3"
    factory = SQLiteUnitOfWorkFactory(database)
    factory.prepare()
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"do-not-overwrite")

    with pytest.raises(SQLiteBackupError, match="вже існує"):
        create_online_backup(database, existing)
    with pytest.raises(SQLiteBackupError, match="мають бути різними"):
        create_online_backup(database, database)

    assert existing.read_bytes() == b"do-not-overwrite"
