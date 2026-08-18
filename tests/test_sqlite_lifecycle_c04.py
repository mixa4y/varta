from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from case_docket.application import (
    ConflictError,
    ContactService,
    CreateContactCommand,
    ListContactsQuery,
)
from case_docket.models.contact import Contact
from case_docket.repository import (
    SQLiteBusyError,
    SQLiteConnectionFactory,
    SQLiteConnectionPolicy,
    SQLiteUnitOfWorkFactory,
    checkpoint_wal,
    inspect_connection_settings,
)


class SequenceIds:
    def __init__(self, *values: str):
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)


def _service(factory: SQLiteUnitOfWorkFactory, *ids: str) -> ContactService:
    return ContactService(factory, SequenceIds(*ids), FixedClock())


def test_each_connection_enforces_policy_and_thread_ownership(tmp_path: Path) -> None:
    database = tmp_path / "policy.sqlite3"
    policy = SQLiteConnectionPolicy(busy_timeout_ms=275, wal_autocheckpoint_pages=37)
    factory = SQLiteConnectionFactory(database, policy)
    connection = factory.connect()
    connection.execute("CREATE TABLE synthetic_policy(id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO synthetic_policy(id) VALUES ('synthetic')")

    settings = inspect_connection_settings(connection)
    checkpoint = checkpoint_wal(connection)
    assert settings.foreign_keys is True
    assert settings.busy_timeout_ms == 275
    assert settings.journal_mode == "wal"
    assert settings.synchronous == 1
    assert settings.wal_autocheckpoint_pages == 37
    assert checkpoint.busy is False

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: connection.execute("SELECT 1").fetchone())
        with pytest.raises(sqlite3.ProgrammingError, match="same thread"):
            future.result()
    connection.close()

    reopened = factory.connect()
    assert inspect_connection_settings(reopened) == settings
    reopened.close()


def test_foreign_keys_are_enabled_on_a_new_operation_connection(tmp_path: Path) -> None:
    database = tmp_path / "foreign-keys.sqlite3"
    uow_factory = SQLiteUnitOfWorkFactory(database)
    uow_factory.prepare()
    connection = SQLiteConnectionFactory(database).connect()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                """
                INSERT INTO contact_cases(contact_id, case_id, origin, created_at)
                VALUES ('missing-contact', 'missing-case', 'local', ?)
                """,
                ("2026-01-01T00:00:00+00:00",),
            )
    finally:
        connection.close()


def test_application_write_rolls_back_when_audit_fails(tmp_path: Path) -> None:
    database = tmp_path / "audit-failure.sqlite3"
    factory = SQLiteUnitOfWorkFactory(database)
    factory.prepare()
    connection = SQLiteConnectionFactory(database).connect()
    connection.executescript(
        """
        CREATE TRIGGER fail_c04_audit_insert
        BEFORE INSERT ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'synthetic audit failure');
        END;
        """
    )
    connection.close()

    service = _service(factory, "contact-audit-failure")
    with pytest.raises(ConflictError, match="Конфлікт збереження контакту"):
        service.create(
            CreateContactCommand(
                full_name="Синтетична Особа",
                participant_type="person",
            )
        )

    assert _service(factory).list(ListContactsQuery()) == ()


def test_unit_of_work_rolls_back_after_downstream_failure_and_is_single_use(
    tmp_path: Path,
) -> None:
    database = tmp_path / "downstream-failure.sqlite3"
    factory = SQLiteUnitOfWorkFactory(database)

    class SyntheticDownstreamFailure(RuntimeError):
        pass

    unit_of_work = factory(write=True)
    with pytest.raises(SyntheticDownstreamFailure):
        with unit_of_work:
            unit_of_work.contacts.add(
                Contact(
                    id="contact-downstream-failure",
                    full_name="Синтетична Особа",
                    participant_type="person",
                )
            )
            raise SyntheticDownstreamFailure("synthetic downstream failure")

    assert _service(factory).list(ListContactsQuery()) == ()
    with pytest.raises(RuntimeError, match="cannot be entered twice"):
        with unit_of_work:
            pass


def test_wal_reader_succeeds_while_second_writer_fails_with_bounded_busy(
    tmp_path: Path,
) -> None:
    database = tmp_path / "concurrency.sqlite3"
    policy = SQLiteConnectionPolicy(busy_timeout_ms=150, wal_autocheckpoint_pages=32)
    factory = SQLiteUnitOfWorkFactory(database, connection_policy=policy)
    _service(factory, "contact-committed").create(
        CreateContactCommand(
            full_name="Синтетичний читач",
            participant_type="person",
        )
    )

    elapsed = 0.0
    busy_error: SQLiteBusyError | None = None
    with factory(write=True) as owner:
        owner.contacts.add(
            Contact(
                id="contact-uncommitted",
                full_name="Синтетичний незавершений запис",
                participant_type="person",
            )
        )

        reader_service = _service(factory)
        writer_service = _service(factory, "contact-contended")
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as executor:
            reader_future = executor.submit(reader_service.list, ListContactsQuery())
            writer_future = executor.submit(
                writer_service.create,
                CreateContactCommand(
                    full_name="Синтетичний конкурентний запис",
                    participant_type="person",
                ),
            )
            reader_result = reader_future.result(timeout=2)
            try:
                writer_future.result(timeout=2)
            except SQLiteBusyError as exc:
                busy_error = exc
        elapsed = time.monotonic() - started

        assert [contact.id for contact in reader_result] == ["contact-committed"]
        assert busy_error is not None
        assert busy_error.timeout_ms == 150
        assert elapsed < 1.0

    created = _service(factory, "contact-after-lock").create(
        CreateContactCommand(
            full_name="Синтетичний запис після lock",
            participant_type="person",
        )
    )
    assert created.id == "contact-after-lock"
