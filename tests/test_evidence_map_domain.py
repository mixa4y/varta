from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from case_docket.repository.migrations import MigrationRunner


MIGRATIONS = Path(__file__).resolve().parents[1] / "case_docket" / "repository" / "migrations"


def migrated_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    MigrationRunner(connection, MIGRATIONS).migrate()
    return connection


def test_evidence_map_domain_migration_creates_formal_tables() -> None:
    connection = migrated_connection()
    expected = {
        "case_profiles",
        "case_number_candidates",
        "file_objects",
        "processing_runs",
        "signatures",
        "source_references",
        "entity_memberships",
        "entity_dates",
        "claims",
        "evidence_relations",
        "review_decisions",
        "amounts",
        "evidence_map_exports",
        "evidence_map_export_artifacts",
    }
    actual = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert expected.issubset(actual)
    assert [row["version"] for row in connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )] == [1, 2, 3, 4, 5, 6, 7, 8]
    connection.close()


def test_claim_classification_is_formalized() -> None:
    connection = migrated_connection()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO claims(
                id, subject_type, subject_id, claim_text, classification,
                review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "claim_example",
                "document",
                "document_example",
                "Вигадане тестове твердження",
                "informal_value",
                "unreviewed",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
    connection.close()


def test_case_number_candidate_requires_reviewable_detection_source() -> None:
    connection = migrated_connection()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO case_number_candidates(
                id, intake_case_id, raw_value, detection_source,
                review_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "candidate_example",
                "intake_example",
                "000/0000/00",
                "guess",
                "unreviewed",
                "2026-01-01T00:00:00+00:00",
            ),
        )
    connection.close()


def test_review_decisions_are_append_only() -> None:
    connection = migrated_connection()
    connection.execute(
        """
        INSERT INTO review_decisions(
            id, subject_type, subject_id, decision, previous_status,
            new_status, actor_id, decided_at, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "decision_example",
            "claim",
            "claim_example",
            "confirm",
            "in_review",
            "confirmed",
            "actor_example",
            "2026-01-01T00:00:00+00:00",
            None,
        ),
    )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE review_decisions SET new_status = 'rejected' WHERE id = 'decision_example'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM review_decisions WHERE id = 'decision_example'")
    connection.close()
