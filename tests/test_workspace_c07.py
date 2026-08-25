from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from pathlib import Path

import pytest

from case_docket.application import (
    AddDocumentMembershipsCommand,
    AddFileMembershipsCommand,
    CandidateSourceInput,
    ConfirmCaseBootstrapCommand,
    ConflictError,
    CreateWorkspaceCaseCommand,
    CreateWorkspaceProceedingCommand,
    ExternalReferenceInput,
    GetActiveCaseQuery,
    IntakeCommand,
    RegisterCandidateSourcesCommand,
    SelectActiveCaseCommand,
)
from case_docket.repository import MigrationRunner, SQLiteRepository
from case_docket.runtime import build_intake_runtime


MIGRATIONS = Path(__file__).resolve().parents[1] / "case_docket" / "repository" / "migrations"


def _accept_synthetic_file(tmp_path: Path, name: str, payload: str):
    workspace = tmp_path / f"workspace-{name}"
    workspace.mkdir()
    source = tmp_path / f"source-{name}.txt"
    source.write_text(payload, encoding="utf-8")
    runtime = build_intake_runtime(workspace)
    batch = runtime.intake_service.intake(
        IntakeCommand(
            source=source,
            idempotency_key=f"c07-{name}",
        )
    )
    assert batch.status == "succeeded"
    entry = batch.entries[0]
    assert entry.file_id is not None
    assert entry.intake_case_id is not None
    assert entry.bootstrap_status == "manual_review_required"
    return workspace, runtime, entry


def _automatic_source(
    text: str,
    *,
    detection_source: str = "document_text",
    location: str = "page:1/paragraph:synthetic",
    external_reference: tuple[str, str, str] | None = None,
) -> CandidateSourceInput:
    external = external_reference or (None, None, None)
    return CandidateSourceInput(
        text=text,
        detection_source=detection_source,
        source_location=location,
        evidence_basis="synthetic extracted span",
        confidence=0.91,
        tool_name="varta-synthetic-detector",
        tool_version="1.0-test",
        external_reference_system=external[0],
        external_reference_kind=external[1],
        external_reference_value=external[2],
    )


def _restore_original_permissions(workspace: Path) -> None:
    for original in (workspace / ".varta" / "originals").rglob("original.bin"):
        try:
            os.chmod(original, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass


def test_c06_database_upgrade_backfills_pending_bootstrap_for_every_accepted_file(
    tmp_path: Path,
) -> None:
    migration_subset = tmp_path / "migrations-through-c06"
    migration_subset.mkdir()
    for version in range(1, 9):
        source = next(MIGRATIONS.glob(f"{version:04d}_*.sql"))
        shutil.copyfile(source, migration_subset / source.name)
    database = tmp_path / "c06-upgrade.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    MigrationRunner(
        connection,
        migration_subset,
        schema_floor=2,
        schema_ceiling=8,
        enforce_scopes=True,
    ).migrate()
    occurred = "2026-01-01T00:00:00+00:00"
    connection.execute(
        """
        INSERT INTO intake_contexts(
            id, status, created_at, updated_at, completed_at
        )
        VALUES ('11111111-1111-4111-8111-111111111111', 'succeeded', ?, ?, ?)
        """,
        (occurred, occurred, occurred),
    )
    connection.execute(
        """
        INSERT INTO import_batches(
            id, intake_context_id, idempotency_key, request_fingerprint,
            source_uri, requested_kind, detected_kind, status,
            created_at, updated_at, completed_at
        )
        VALUES (
            '22222222-2222-4222-8222-222222222222',
            '11111111-1111-4111-8111-111111111111',
            'synthetic-upgrade-key', ?, 'upload://synthetic/upgrade',
            'auto', 'file', 'succeeded', ?, ?, ?
        )
        """,
        ("a" * 64, occurred, occurred, occurred),
    )
    connection.execute(
        """
        INSERT INTO file_objects(
            id, import_batch_id, kind, original_name, size_bytes, sha256,
            integrity_status, review_status, created_at, updated_at
        )
        VALUES (
            '33333333-3333-4333-8333-333333333333',
            '22222222-2222-4222-8222-222222222222',
            'content', 'synthetic-upgrade.txt', 1, ?,
            'verified', 'unreviewed', ?, ?
        )
        """,
        ("b" * 64, occurred, occurred),
    )
    connection.execute(
        """
        INSERT INTO intake_entries(
            id, import_batch_id, ordinal, source_uri, source_relative_path,
            literal_name, entry_kind, status, size_bytes, file_id,
            created_at, updated_at
        )
        VALUES (
            '44444444-4444-4444-8444-444444444444',
            '22222222-2222-4222-8222-222222222222', 0,
            'upload://synthetic/upgrade', 'synthetic-upgrade.txt',
            'synthetic-upgrade.txt', 'file', 'accepted', 1,
            '33333333-3333-4333-8333-333333333333', ?, ?
        )
        """,
        (occurred, occurred),
    )

    applied = MigrationRunner(
        connection,
        MIGRATIONS,
        schema_floor=2,
        schema_ceiling=9,
        enforce_scopes=True,
    ).migrate()
    assert applied == [9]
    bootstrap = connection.execute(
        "SELECT * FROM case_bootstraps WHERE intake_entry_id = ?",
        ("44444444-4444-4444-8444-444444444444",),
    ).fetchone()
    assert bootstrap is not None
    assert bootstrap["intake_case_id"] == "44444444-4444-4444-8444-444444444444"
    assert bootstrap["file_id"] == "33333333-3333-4333-8333-333333333333"
    assert bootstrap["status"] == "manual_review_required"
    connection.close()


def test_zero_candidate_file_remains_explicit_pending_after_restart(tmp_path: Path) -> None:
    workspace, runtime, entry = _accept_synthetic_file(
        tmp_path,
        "zero",
        "Синтетичний документ без реквізитів справи.",
    )
    try:
        pending = runtime.workspace_service.list_pending_bootstraps()
        assert len(pending) == 1
        assert pending[0].intake_case_id == entry.intake_case_id
        assert pending[0].distinct_candidate_count == 0

        reviewed = runtime.workspace_service.register_candidate_sources(
            RegisterCandidateSourcesCommand(
                intake_case_id=str(entry.intake_case_id),
                sources=(_automatic_source("У фрагменті немає номера справи."),),
            )
        )
        assert reviewed.status == "manual_review_required"
        assert reviewed.distinct_candidate_count == 0
    finally:
        _restore_original_permissions(workspace)

    restarted = build_intake_runtime(workspace)
    pending = restarted.workspace_service.list_pending_bootstraps()
    assert len(pending) == 1
    assert pending[0].file_id == entry.file_id
    assert pending[0].status == "manual_review_required"


def test_filename_only_never_suffices_and_duplicate_normalized_evidence_is_one_candidate(
    tmp_path: Path,
) -> None:
    workspace, runtime, entry = _accept_synthetic_file(
        tmp_path,
        "one",
        "Синтетичний текст для candidate test.",
    )
    try:
        filename_only = runtime.workspace_service.register_candidate_sources(
            RegisterCandidateSourcesCommand(
                intake_case_id=str(entry.intake_case_id),
                sources=(
                    _automatic_source(
                        "999/9001/99-synthetic.txt",
                        detection_source="filename",
                        location="filename",
                    ),
                ),
            )
        )
        assert filename_only.status == "manual_review_required"
        assert filename_only.distinct_candidate_count == 1
        assert filename_only.candidates[0].eligible_as_sole_evidence is False

        proposed = runtime.workspace_service.register_candidate_sources(
            RegisterCandidateSourcesCommand(
                intake_case_id=str(entry.intake_case_id),
                sources=(
                    _automatic_source(
                        "Синтетичний документ: справа № 999 / 9001 / 99.",
                    ),
                ),
            )
        )
        assert proposed.status == "candidate_ready"
        assert proposed.distinct_candidate_count == 1
        assert len(proposed.candidates) == 2

        trusted_candidate = next(
            candidate
            for candidate in proposed.candidates
            if candidate.detection_source == "document_text"
        )
        confirmed = runtime.workspace_service.confirm_bootstrap(
            ConfirmCaseBootstrapCommand(
                intake_case_id=str(entry.intake_case_id),
                candidate_id=trusted_candidate.candidate_id,
                actor_id="user:synthetic-reviewer",
                note="Synthetic manual confirmation",
            )
        )
        assert confirmed.status == "confirmed"
        assert confirmed.confirmed_case_id is not None
        cases = runtime.workspace_service.list_cases()
        assert len(cases) == 1
        assert cases[0].normalized_case_number == "999/9001/99"
        assert cases[0].file_ids == (entry.file_id,)

        repository = SQLiteRepository(runtime.database_path)
        try:
            assert repository._conn.execute(
                "SELECT COUNT(*) FROM case_bootstrap_status_history WHERE intake_case_id = ?",
                (entry.intake_case_id,),
            ).fetchone()[0] >= 3
            assert repository._conn.execute(
                "SELECT COUNT(*) FROM review_decisions WHERE subject_id = ?",
                (entry.file_id,),
            ).fetchone()[0] == 1
        finally:
            repository.close()
    finally:
        _restore_original_permissions(workspace)


def test_multiple_candidates_require_manual_selection(tmp_path: Path) -> None:
    workspace, runtime, entry = _accept_synthetic_file(
        tmp_path,
        "multiple",
        "Синтетичний текст для ambiguous candidate test.",
    )
    try:
        review = runtime.workspace_service.register_candidate_sources(
            RegisterCandidateSourcesCommand(
                intake_case_id=str(entry.intake_case_id),
                sources=(
                    _automatic_source(
                        "Посилання на справи № 999/9002/99 та № 999/9003/99.",
                    ),
                ),
            )
        )
        assert review.status == "manual_review_required"
        assert review.distinct_candidate_count == 2

        selected = next(
            candidate
            for candidate in review.candidates
            if candidate.normalized_value == "999/9003/99"
        )
        confirmed = runtime.workspace_service.confirm_bootstrap(
            ConfirmCaseBootstrapCommand(
                intake_case_id=str(entry.intake_case_id),
                candidate_id=selected.candidate_id,
                actor_id="user:synthetic-reviewer",
            )
        )
        assert confirmed.status == "confirmed"
        statuses = {
            candidate.normalized_value: candidate.review_status
            for candidate in confirmed.candidates
        }
        assert statuses == {
            "999/9002/99": "rejected",
            "999/9003/99": "confirmed",
        }
    finally:
        _restore_original_permissions(workspace)


def test_conflicting_external_reference_does_not_merge_cases(tmp_path: Path) -> None:
    workspace, runtime, entry = _accept_synthetic_file(
        tmp_path,
        "external-conflict",
        "Синтетичний текст для external reference test.",
    )
    try:
        first_case = runtime.workspace_service.create_case(
            CreateWorkspaceCaseCommand(
                actor_id="user:synthetic-reviewer",
                case_number="999/9010/99",
                name="Синтетична справа A",
                external_references=(
                    ExternalReferenceInput(
                        system="synthetic-registry",
                        kind="record",
                        value="SYN-REF-001",
                        evidence_basis="synthetic fixture",
                    ),
                ),
            )
        )
        review = runtime.workspace_service.register_candidate_sources(
            RegisterCandidateSourcesCommand(
                intake_case_id=str(entry.intake_case_id),
                sources=(
                    _automatic_source(
                        "Справу № 999/9011/99 зазначено у синтетичному джерелі.",
                        external_reference=(
                            "synthetic-registry",
                            "record",
                            "SYN-REF-001",
                        ),
                    ),
                ),
            )
        )
        with pytest.raises(ConflictError, match="External reference"):
            runtime.workspace_service.confirm_bootstrap(
                ConfirmCaseBootstrapCommand(
                    intake_case_id=str(entry.intake_case_id),
                    candidate_id=review.candidates[0].candidate_id,
                    actor_id="user:synthetic-reviewer",
                )
            )
        cases = runtime.workspace_service.list_cases()
        assert [case.case_id for case in cases] == [first_case.case_id]
        pending = runtime.workspace_service.list_pending_bootstraps()
        assert pending[0].status == "candidate_ready"
    finally:
        _restore_original_permissions(workspace)


def test_many_to_many_memberships_and_active_case_preference_are_independent(
    tmp_path: Path,
) -> None:
    workspace, runtime, entry = _accept_synthetic_file(
        tmp_path,
        "many-to-many",
        "Синтетичний файл для membership test.",
    )
    try:
        case_a = runtime.workspace_service.create_case(
            CreateWorkspaceCaseCommand(
                actor_id="user:synthetic-reviewer",
                name="Синтетична справа A",
            )
        )
        case_b = runtime.workspace_service.create_case(
            CreateWorkspaceCaseCommand(
                actor_id="user:synthetic-reviewer",
                name="Синтетична справа B",
            )
        )
        proceeding_a = runtime.workspace_service.create_proceeding(
            CreateWorkspaceProceedingCommand(
                actor_id="user:synthetic-reviewer",
                case_ids=(case_a.case_id, case_b.case_id),
                proceeding_number="SYNTHETIC-PROCEEDING-A",
            )
        )
        proceeding_b = runtime.workspace_service.create_proceeding(
            CreateWorkspaceProceedingCommand(
                actor_id="user:synthetic-reviewer",
                case_ids=(case_b.case_id,),
                proceeding_number="SYNTHETIC-PROCEEDING-B",
            )
        )
        memberships = runtime.workspace_service.add_file_memberships(
            AddFileMembershipsCommand(
                file_id=str(entry.file_id),
                actor_id="user:synthetic-reviewer",
                case_ids=(case_a.case_id, case_b.case_id),
                proceeding_ids=(proceeding_a.proceeding_id, proceeding_b.proceeding_id),
            )
        )
        assert {(item.context_type, item.context_id) for item in memberships} == {
            ("case", case_a.case_id),
            ("case", case_b.case_id),
            ("proceeding", proceeding_a.proceeding_id),
            ("proceeding", proceeding_b.proceeding_id),
        }

        document_id = "document-synthetic-membership"
        repository = SQLiteRepository(runtime.database_path)
        try:
            repository.insert(
                "documents",
                {
                    "id": document_id,
                    "title": "Синтетичний логічний документ",
                    "requires_manual_review": False,
                },
            )
        finally:
            repository.close()
        document_memberships = runtime.workspace_service.add_document_memberships(
            AddDocumentMembershipsCommand(
                document_id=document_id,
                actor_id="user:synthetic-reviewer",
                case_ids=(case_a.case_id, case_b.case_id),
                proceeding_ids=(proceeding_a.proceeding_id, proceeding_b.proceeding_id),
            )
        )
        assert {
            (item.context_type, item.context_id) for item in document_memberships
        } == {
            ("case", case_a.case_id),
            ("case", case_b.case_id),
            ("proceeding", proceeding_a.proceeding_id),
            ("proceeding", proceeding_b.proceeding_id),
        }

        first_active = runtime.workspace_service.select_active_case(
            SelectActiveCaseCommand(
                preference_id="browser-session-synthetic",
                actor_id="user:synthetic-reviewer",
                active_case_id=case_a.case_id,
            )
        )
        assert first_active.active_case is not None
        assert first_active.active_case.case_id == case_a.case_id
        second_active = runtime.workspace_service.select_active_case(
            SelectActiveCaseCommand(
                preference_id="browser-session-synthetic",
                actor_id="user:synthetic-reviewer",
                active_case_id=case_b.case_id,
            )
        )
        assert second_active.active_case is not None
        assert second_active.active_case.case_id == case_b.case_id

        cases = {case.case_id: case for case in runtime.workspace_service.list_cases()}
        assert cases[case_a.case_id].file_ids == (entry.file_id,)
        assert cases[case_b.case_id].file_ids == (entry.file_id,)
    finally:
        _restore_original_permissions(workspace)

    restarted = build_intake_runtime(workspace)
    active = restarted.workspace_service.get_active_case(
        GetActiveCaseQuery("browser-session-synthetic")
    )
    assert active.active_case is not None
    assert active.active_case.case_id == case_b.case_id
    cases = {case.case_id: case for case in restarted.workspace_service.list_cases()}
    assert cases[case_a.case_id].file_ids == (entry.file_id,)
    assert cases[case_b.case_id].file_ids == (entry.file_id,)
