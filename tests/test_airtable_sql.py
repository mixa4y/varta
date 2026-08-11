from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from case_docket.airtable import AIRTABLE_SCHEMA_PATH, load_airtable_schema
from case_docket.repository import MigrationError, MigrationRunner, SQLiteRepository


def _snapshot() -> dict[str, list[dict[str, object]]]:
    return {
        "Контакти": [
            {
                "id": "rec-contact",
                "fields": {
                    "fldsUF5FAcJRAYzMG": "Тестова Особа",
                    "fldAbyAGj8TTMlgx6": "Фізична особа",
                    "fldGfWlDfDcXuG420": ["rec-case"],
                    "fldbv0WeRuN86jplD": ["rec-proceeding"],
                    "fldMyuQxJCqhnTY7W": ["rec-event"],
                    "fldBXm28KqnchRzWj": ["rec-participant"],
                },
            }
        ],
        "Справи": [
            {
                "id": "rec-case",
                "fields": {
                    "fldBIYNLnq1NaQk3E": "111/2222/33",
                    "fld7xYu8Bu0BwP8Oq": "Вигадана справа",
                    "fldlv9rvYxpcMiLk0": ["rec-proceeding"],
                    "fld4GdY0KcbY9xBwp": ["rec-event"],
                    "fldbELvq8ZSxKJ9hN": ["rec-document-user", "rec-document-court"],
                    "fldGL45mM96oJf8np": ["rec-participant"],
                },
            }
        ],
        "Провадження": [
            {
                "id": "rec-proceeding",
                "fields": {
                    "fld4gdU5CEgFNVn7I": "Вигадане провадження",
                    "fldKa4sGwfiW8JRA7": "1/111/222/33",
                    "fldnC3G8bYPZjQUdR": ["rec-case"],
                    "fldOj5z7NVQZJQaUH": ["rec-event"],
                    "fldtD1ldsElO0XY6q": ["rec-document-user"],
                    "fld0iUoNDknwSQCvg": ["rec-contact"],
                },
            }
        ],
        "Події": [
            {
                "id": "rec-event",
                "fields": {
                    "fld1y6fnMxVfRsnKw": "Тестова подія",
                    "fldtcR9bMUiIXfy3q": "2026-08-11T10:00:00+03:00",
                    "fldnGMbGPaGVA64Q0": ["rec-case"],
                    "fldU85sGdvXfpyp8y": ["rec-proceeding"],
                    "fldWQZaoDewhxKYY7": ["rec-document-user"],
                    "fldpHAd9Jm5yPFktR": ["rec-contact"],
                },
            }
        ],
        "Документи": [
            {
                "id": "rec-document-user",
                "fields": {
                    "fldXuOovgXZaoZjV3": "Вигаданий документ користувача",
                    "fldearxvbjyJuPOdr": "main",
                    "fldij2txUAF3rHkbA": ["rec-case"],
                    "fldZhefYcXoIeO8Zq": ["rec-proceeding"],
                    "fldp637rPy50IaOcX": ["rec-event"],
                },
            },
            {
                "id": "rec-document-court",
                "fields": {"fldXuOovgXZaoZjV3": "Вигаданий документ суду"},
            },
        ],
        "Учасники справи": [
            {
                "id": "rec-participant",
                "fields": {
                    "fldZY8da3bfjfTiZy": "role-test-1",
                    "fldc7Bw4YJMYzQCwX": ["rec-case"],
                    "flducJ9za4RACiSYP": ["rec-contact"],
                    "fldnQfVMsMWOXwJRV": "Позивач",
                },
            }
        ],
        "document_links": [
            {
                "id": "rec-link",
                "fields": {
                    "fldefA1UCXoAV22gr": "Вигаданий зв'язок",
                    "fldw8cAqivZisjmGX": ["rec-document-user"],
                    "fldGPGtply6TOrrhj": ["rec-document-court"],
                    "fldb9R4mTaWnuho1w": "response_to",
                },
            }
        ],
        "compliance_flags": [
            {
                "id": "rec-flag",
                "fields": {
                    "fldaA64IrdkwF8XVD": "Тестовий сигнал",
                    "fldARhXpTAVPUjlpb": ["rec-document-user"],
                    "fldV6vFnYcCFbVbkO": "missing_attachment",
                    "fldCgu9aYEApr2ioG": "warning",
                },
            }
        ],
        "document_version_match": [
            {
                "id": "rec-match",
                "fields": {
                    "fld0M6V00eNStp0yi": "Тестове зіставлення",
                    "fldqkXhCmRjCSBN7s": ["rec-document-user"],
                    "fldmWFUuKiDUQ0sdD": ["rec-document-court"],
                    "fld0gIaMY0z2yKq30": False,
                    "fldjehVBC2fOQS9GY": 0.75,
                    "fldzT9yfDloirAvKQ": "content_diff",
                    "fldlLs42CoJwlRq2z": True,
                },
            }
        ],
    }


def test_historical_airtable_schema_is_complete() -> None:
    schema = load_airtable_schema()
    assert schema["base"]["id"] == "app2a7GKV6zKK1okN"
    assert len(schema["tables"]) == 9
    assert sum(len(table["fields"]) for table in schema["tables"]) == 127
    assert AIRTABLE_SCHEMA_PATH.stat().st_size == 65_468


def test_sql_catalog_maps_every_airtable_field(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "catalog.sqlite3")
    assert repo.airtable_catalog_counts() == {
        "tables": 9,
        "fields": 127,
        "relations": 38,
        "computed": 12,
    }
    unmapped = repo._conn.execute(
        "SELECT COUNT(*) FROM airtable_field_mappings WHERE sql_target = ''"
    ).fetchone()[0]
    assert unmapped == 0
    assert repo._conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    repo.close()


def test_airtable_snapshot_materializes_sql_relations(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "import.sqlite3")
    first = repo.import_airtable_snapshot(_snapshot())
    second = repo.import_airtable_snapshot(_snapshot())

    assert first.records == 10
    assert first.links > 0
    assert first.unresolved_links == 0
    assert second == first
    assert repo._conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 1
    assert repo._conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
    assert repo._conn.execute("SELECT COUNT(*) FROM proceedings").fetchone()[0] == 1
    assert repo._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2

    contact = repo._conn.execute(
        "SELECT full_name, participant_type FROM contacts"
    ).fetchone()
    assert contact["full_name"] == "Тестова Особа"
    assert contact["participant_type"] == "person"
    assert repo._conn.execute("SELECT role FROM case_participants").fetchone()[0] == "Позивач"

    detail = repo._conn.execute("SELECT * FROM v_contact_proceeding_details").fetchone()
    assert detail["proceeding_name"] == "Вигадане провадження"
    assert detail["case_number"] == "111/2222/33"
    assert repo._conn.execute("SELECT proceeding_count FROM v_cases").fetchone()[0] == 1
    assert repo._conn.execute("SELECT activity_date FROM v_events").fetchone()[0] == (
        "2026-08-11T10:00:00+03:00"
    )

    document_link = repo._conn.execute("SELECT * FROM document_links").fetchone()
    assert document_link["source_document_id"]
    assert document_link["target_document_id"]
    assert repo._conn.execute("SELECT document_id FROM compliance_flags").fetchone()[0]
    version_match = repo._conn.execute("SELECT * FROM document_version_match").fetchone()
    assert version_match["user_document_id"]
    assert version_match["court_document_id"]
    assert version_match["needs_review"] == 1
    repo.close()


def test_unresolved_airtable_link_is_reported(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "unresolved.sqlite3")
    summary = repo.import_airtable_snapshot(
        {
            "Контакти": [
                {
                    "id": "rec-contact",
                    "fields": {
                        "fldsUF5FAcJRAYzMG": "Тестова Особа",
                        "fldAbyAGj8TTMlgx6": "Фізична особа",
                        "fldGfWlDfDcXuG420": ["rec-missing-case"],
                    },
                }
            ]
        }
    )
    assert summary.unresolved_links == 1
    issue = repo._conn.execute("SELECT * FROM v_airtable_unresolved_links").fetchone()
    assert issue["target_airtable_record_id"] == "rec-missing-case"
    repo.close()


def test_foreign_keys_reject_orphan_domain_relation(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "foreign-key.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        repo._conn.execute(
            """
            INSERT INTO contact_cases(contact_id, case_id, origin, created_at)
            VALUES ('missing-contact', 'missing-case', 'local', '2026-08-11T00:00:00Z')
            """
        )
    repo.close()


def test_migration_failure_rolls_back(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_ok.sql").write_text(
        "CREATE TABLE stable(id TEXT PRIMARY KEY);", encoding="utf-8"
    )
    (migrations / "0002_bad.sql").write_text(
        "CREATE TABLE must_rollback(id TEXT); INVALID SQL;", encoding="utf-8"
    )
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    runner = MigrationRunner(connection, migrations)
    with pytest.raises(MigrationError):
        runner.migrate()
    assert connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'must_rollback'"
    ).fetchone()[0] == 0
    connection.close()


def test_applied_migration_checksum_is_immutable(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    migration = migrations / "0001_first.sql"
    migration.write_text("CREATE TABLE first(\n    id TEXT\n);\n", encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    MigrationRunner(connection, migrations).migrate()

    migration.write_bytes(b"CREATE TABLE first(\r\n    id TEXT\r\n);\r\n")
    assert MigrationRunner(connection, migrations).migrate() == []

    migration.write_text("CREATE TABLE changed(id TEXT);", encoding="utf-8")
    with pytest.raises(MigrationError, match="змінена"):
        MigrationRunner(connection, migrations).migrate()
    connection.close()


def test_legacy_generic_rows_are_preserved(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE document_files (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id),
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO documents VALUES (?, ?, ?)",
        ("doc-legacy", "2026-08-10T00:00:00Z", json.dumps({"title": "Старий запис"})),
    )
    connection.execute(
        "INSERT INTO document_files VALUES (?, ?, ?, ?)",
        ("file-legacy", "doc-legacy", "2026-08-10T00:00:00Z", '{"kind":"content"}'),
    )
    connection.commit()
    connection.close()

    repo = SQLiteRepository(db_path)
    document = repo.get("documents", "doc-legacy")
    document_file = repo.get("document_files", "file-legacy")
    assert document is not None and document["title"] == "Старий запис"
    assert document_file is not None and document_file["document_id"] == "doc-legacy"
    assert repo._conn.execute(
        "SELECT COUNT(*) FROM legacy_generic_documents"
    ).fetchone()[0] == 1
    repo.close()
