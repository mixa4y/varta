from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from case_docket.airtable import TABLE_SQL_NAMES, load_airtable_schema
from case_docket.application.case_database_import_ports import (
    CaseDatabaseImportReportRecord,
    CaseDatabaseSourceSnapshot,
    CorpusImportResult,
    CorpusInventorySummary,
    ImportRunPlanRecord,
)

from .sqlite_connection import SQLiteConnectionFactory, SQLiteConnectionPolicy
from .sqlite_repository import SQLiteRepository


_R05_NAMESPACE = uuid.UUID("5b77113e-99db-4b3f-9fc9-b171d10b2265")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENTITY_TABLES = (
    "cases",
    "proceedings",
    "contacts",
    "events",
    "documents",
    "case_participants",
    "document_links",
    "compliance_flags",
    "document_version_match",
)
_DATE_COLUMNS = {
    "events": {
        "event_at": "other",
        "sent_at": "submitted_date",
        "delivered_at": "received_date",
        "deadline": "due_date",
    },
    "documents": {
        "sent_on": "submitted_date",
        "delivered_on": "received_date",
        "registered_on": "registered_date",
        "imported_on": "other",
    },
    "cases": {"opened_on": "opened_date", "closed_on": "closed_date"},
    "proceedings": {"started_on": "opened_date", "ended_on": "closed_date"},
}


class CaseDatabaseImportRepositoryError(RuntimeError):
    """Raised when durable one-time import state violates its contract."""


@dataclass(frozen=True, slots=True)
class BackupVerification:
    source_integrity: str
    restored_integrity: str
    source_revision: str
    restored_revision: str
    source_counts_sha256: str
    restored_counts_sha256: str
    managed_files_verified: int
    verification_sha256: str
    source_foreign_keys_ok: bool
    restored_foreign_keys_ok: bool

    @property
    def verified(self) -> bool:
        return (
            self.source_integrity == "ok"
            and self.restored_integrity == "ok"
            and self.source_revision == self.restored_revision
            and self.source_counts_sha256 == self.restored_counts_sha256
            and self.source_foreign_keys_ok
            and self.restored_foreign_keys_ok
        )


class SQLiteCaseDatabaseImportRepository:
    """SQLite adapter for one-time Airtable import, reconciliation, and cutover."""

    def __init__(
        self,
        database_path: Path,
        *,
        connection_policy: SQLiteConnectionPolicy | None = None,
    ):
        self.database_path = Path(database_path)
        self.connection_policy = connection_policy or SQLiteConnectionPolicy()
        repository = self._open()
        repository.close()

    def plan(
        self,
        snapshot: CaseDatabaseSourceSnapshot,
        corpus: CorpusInventorySummary,
        *,
        mapping_version: str,
        occurred_at: datetime,
    ) -> ImportRunPlanRecord:
        self._validate_snapshot(snapshot)
        idempotency_key = _sha256_text(
            "\x00".join(
                (
                    snapshot.source_identity_sha256,
                    snapshot.schema_sha256,
                    snapshot.snapshot_sha256,
                    corpus.manifest_sha256,
                    mapping_version,
                )
            )
        )
        run_id = str(uuid.uuid5(_R05_NAMESPACE, f"import:{idempotency_key}"))
        repository = self._open(auto_commit=False)
        try:
            repository.begin(write=True)
            existing = repository._conn.execute(
                "SELECT id FROM airtable_import_runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is None:
                now = occurred_at.isoformat()
                repository._conn.execute(
                    """
                    INSERT INTO airtable_import_runs(
                        id, source_identity_sha256, schema_sha256, snapshot_sha256,
                        selected_case_record_id, corpus_manifest_sha256,
                        mapping_version, idempotency_key,
                        status, counts_json, started_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)
                    """,
                    (
                        run_id,
                        snapshot.source_identity_sha256,
                        snapshot.schema_sha256,
                        snapshot.snapshot_sha256,
                        snapshot.selected_case_record_id,
                        corpus.manifest_sha256,
                        mapping_version,
                        idempotency_key,
                        _json(
                            {
                                "sourceRecords": snapshot.record_count,
                                "sourceTables": len(snapshot.table_counts),
                                "corpusDiscovered": corpus.discovered,
                                "corpusFiles": corpus.files,
                                "corpusDirectories": corpus.directories,
                                "corpusUnreadable": corpus.unreadable,
                            }
                        ),
                        now,
                        now,
                    ),
                )
                schema_payload = snapshot.payload.get("schema")
                catalog_mapping_sha256 = str(snapshot.payload.get("catalogMappingSha256") or "")
                repository._conn.execute(
                    """
                    INSERT INTO airtable_import_schema_snapshots(
                        import_run_id, schema_json, schema_sha256,
                        catalog_mapping_sha256, captured_start, captured_end
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        _json(schema_payload),
                        snapshot.schema_sha256,
                        catalog_mapping_sha256,
                        snapshot.captured_start,
                        snapshot.captured_end,
                    ),
                )
                for entry in corpus.entries:
                    repository._conn.execute(
                        """
                        INSERT INTO airtable_corpus_manifest_entries(
                            import_run_id, relative_path, relative_path_sha256,
                            size_bytes, file_sha256
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            entry.relative_path,
                            _sha256_text(entry.relative_path),
                            entry.size_bytes,
                            entry.sha256,
                        ),
                    )
                replayed = False
            else:
                run_id = str(existing["id"])
                replayed = True
            repository.commit()
            return ImportRunPlanRecord(run_id, idempotency_key, replayed)
        except Exception:
            if repository._conn.in_transaction:
                repository.rollback()
            raise
        finally:
            repository.close()

    def execute(
        self,
        import_run_id: str,
        snapshot: CaseDatabaseSourceSnapshot,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord:
        self._validate_snapshot(snapshot)
        repository = self._open(auto_commit=False)
        try:
            repository.begin(write=True)
            run = self._require_run(repository._conn, import_run_id)
            self._assert_snapshot_identity(run, snapshot)
            if str(run["status"]) == "finalized":
                repository.rollback()
                report = self.get_report(import_run_id)
                assert report is not None
                return report

            now = occurred_at.isoformat()
            repository._conn.execute(
                "UPDATE airtable_import_runs SET status = 'running', updated_at = ? WHERE id = ?",
                (now, import_run_id),
            )
            batch_id = str(uuid.uuid5(_R05_NAMESPACE, f"{import_run_id}:core-records"))
            repository._conn.execute(
                """
                INSERT INTO airtable_import_batches(
                    id, import_run_id, phase, batch_key, ordinal, status,
                    item_count, input_sha256, started_at, updated_at
                ) VALUES (?, ?, 'core_import', 'all-records', 0, 'running', ?, ?, ?, ?)
                ON CONFLICT(import_run_id, phase, batch_key) DO UPDATE SET
                    status = 'running', started_at = COALESCE(started_at, excluded.started_at),
                    last_error_code = NULL, updated_at = excluded.updated_at
                """,
                (
                    batch_id,
                    import_run_id,
                    snapshot.record_count,
                    snapshot.snapshot_sha256,
                    now,
                    now,
                ),
            )
            summary = repository.import_airtable_snapshot(dict(snapshot.payload))
            self._persist_record_versions(repository._conn, import_run_id, snapshot, now)
            selected_case_id = self._classify_record_scopes(
                repository._conn,
                import_run_id,
                snapshot.selected_case_record_id,
                now,
            )
            repository._conn.execute(
                "UPDATE airtable_import_runs SET selected_case_id = ? WHERE id = ?",
                (selected_case_id, import_run_id),
            )
            self._persist_source_references(repository._conn, import_run_id, now)
            self._persist_attachments(repository._conn, import_run_id, snapshot, now)
            self._materialize_dates(repository._conn, now)
            self._materialize_contact_identities(repository._conn, now)
            self._materialize_case_memberships(repository._conn, now)
            self._materialize_event_actor_links(repository._conn)
            self._materialize_evidence_extensions(
                repository._conn,
                import_run_id,
                selected_case_id,
                now,
            )
            self._replace_unresolved_link_issues(repository._conn, import_run_id, now)
            self._replace_orphan_issues(repository._conn, import_run_id, now)
            critical = self._issue_count(repository._conn, import_run_id, "critical")
            self._materialize_profiles(
                repository._conn,
                import_run_id,
                snapshot.snapshot_sha256,
                str(run["mapping_version"]),
                now,
                selected_case_id=selected_case_id,
                active=critical == 0,
            )
            output_sha = self._source_revision(repository._conn)
            counts = json.loads(str(run["counts_json"]))
            counts.update(
                {
                    "importedRecords": summary.records,
                    "linksObserved": summary.links,
                    "linksUnresolved": summary.unresolved_links,
                }
            )
            repository._conn.execute(
                """
                UPDATE airtable_import_batches
                SET status = 'completed', output_sha256 = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (output_sha, now, now, batch_id),
            )
            repository._conn.execute(
                """
                UPDATE airtable_import_runs
                SET status = 'ready', counts_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json(counts), now, import_run_id),
            )
            repository.commit()
        except Exception as exc:
            if repository._conn.in_transaction:
                repository.rollback()
            self._mark_interrupted(import_run_id, occurred_at, type(exc).__name__)
            raise
        finally:
            repository.close()
        report = self.get_report(import_run_id)
        assert report is not None
        return report

    def resume(
        self,
        import_run_id: str,
        snapshot: CaseDatabaseSourceSnapshot,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord:
        report = self.get_report(import_run_id)
        if report is None:
            raise CaseDatabaseImportRepositoryError("Import run не знайдено")
        if report.status == "finalized":
            return report
        return self.execute(import_run_id, snapshot, occurred_at=occurred_at)

    def finalize(
        self,
        import_run_id: str,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord:
        repository = self._open(auto_commit=False)
        try:
            repository.begin(write=True)
            run = self._require_run(repository._conn, import_run_id)
            if str(run["status"]) not in {"ready", "finalized"}:
                raise CaseDatabaseImportRepositoryError("Import run не готовий до cutover")
            if not bool(run["restart_verified"]) or not bool(run["backup_verified"]):
                raise CaseDatabaseImportRepositoryError(
                    "Cutover потребує restart і restored-backup verification"
                )
            if self._issue_count(repository._conn, import_run_id, "critical"):
                raise CaseDatabaseImportRepositoryError("Cutover має відкриті critical issues")
            pending_attachments = int(
                repository._conn.execute(
                    """
                    SELECT COUNT(*) FROM airtable_attachment_references
                    WHERE import_run_id = ? AND match_status = 'pending'
                    """,
                    (import_run_id,),
                ).fetchone()[0]
            )
            if pending_attachments:
                raise CaseDatabaseImportRepositoryError(
                    "Cutover потребує explicit attachment reconciliation"
                )
            now = occurred_at.isoformat()
            repository._conn.execute(
                """
                UPDATE airtable_import_runs
                SET status = 'finalized', cutover_marker = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    _sha256_text(f"{import_run_id}:{run['snapshot_sha256']}"),
                    now,
                    now,
                    import_run_id,
                ),
            )
            repository.commit()
        except Exception:
            if repository._conn.in_transaction:
                repository.rollback()
            raise
        finally:
            repository.close()
        report = self.get_report(import_run_id)
        assert report is not None
        return report

    def record_verification(
        self,
        import_run_id: str,
        *,
        verification_evidence_sha256: str,
        occurred_at: datetime,
    ) -> None:
        repository = self._open(auto_commit=False)
        try:
            repository.begin(write=True)
            self._require_run(repository._conn, import_run_id)
            evidence = repository._conn.execute(
                """
                SELECT * FROM airtable_import_verifications
                WHERE import_run_id = ? AND verification_sha256 = ?
                """,
                (import_run_id, verification_evidence_sha256),
            ).fetchone()
            if evidence is None:
                raise CaseDatabaseImportRepositoryError(
                    "Verification evidence не належить import run"
                )
            verified = (
                str(evidence["source_integrity"]) == "ok"
                and str(evidence["restored_integrity"]) == "ok"
                and bool(evidence["source_foreign_keys_ok"])
                and bool(evidence["restored_foreign_keys_ok"])
                and str(evidence["source_revision"]) == str(evidence["restored_revision"])
                and str(evidence["source_counts_sha256"]) == str(evidence["restored_counts_sha256"])
            )
            if not verified:
                raise CaseDatabaseImportRepositoryError("Verification evidence не пройшла gates")
            repository._conn.execute(
                """
                UPDATE airtable_import_runs
                SET restart_verified = ?, backup_verified = ?, updated_at = ?
                WHERE id = ?
                """,
                (1, 1, occurred_at.isoformat(), import_run_id),
            )
            repository.commit()
        finally:
            repository.close()

    def record_corpus_result(
        self,
        import_run_id: str,
        result: CorpusImportResult,
        *,
        occurred_at: datetime,
    ) -> None:
        repository = self._open(auto_commit=False)
        try:
            repository.begin(write=True)
            run = self._require_run(repository._conn, import_run_id)
            counts = json.loads(str(run["counts_json"]))
            counts.update(
                {
                    "filesAccepted": result.accepted,
                    "filesDuplicate": result.duplicate,
                    "filesFailed": result.failed,
                    "filesSkipped": result.skipped,
                }
            )
            repository._conn.execute(
                "UPDATE airtable_import_runs SET counts_json = ?, updated_at = ? WHERE id = ?",
                (_json(counts), occurred_at.isoformat(), import_run_id),
            )
            repository.commit()
        finally:
            repository.close()

    def reconcile_attachments(
        self,
        import_run_id: str,
        *,
        occurred_at: datetime,
    ) -> CaseDatabaseImportReportRecord:
        repository = self._open(auto_commit=False)
        try:
            repository.begin(write=True)
            self._require_run(repository._conn, import_run_id)
            now = occurred_at.isoformat()
            attachments = repository._conn.execute(
                """
                SELECT * FROM airtable_attachment_references
                WHERE import_run_id = ? AND match_status = 'pending'
                ORDER BY id
                """,
                (import_run_id,),
            ).fetchall()
            for attachment in attachments:
                self._reconcile_attachment(repository._conn, import_run_id, attachment, now)
            repository.commit()
        except Exception:
            if repository._conn.in_transaction:
                repository.rollback()
            raise
        finally:
            repository.close()
        report = self.get_report(import_run_id)
        assert report is not None
        return report

    def get_report(self, import_run_id: str) -> CaseDatabaseImportReportRecord | None:
        repository = self._open()
        try:
            run = repository._conn.execute(
                "SELECT * FROM airtable_import_runs WHERE id = ?", (import_run_id,)
            ).fetchone()
            if run is None:
                return None
            entity_counts = {
                table_name: int(
                    repository._conn.execute(
                        """
                        SELECT COUNT(*) FROM airtable_record_versions
                        WHERE import_run_id = ? AND airtable_table_id = ?
                        """,
                        (import_run_id, table_id),
                    ).fetchone()[0]
                )
                for table_id, table_name in TABLE_SQL_NAMES.items()
            }
            scope_counts = self._status_counts(
                repository._conn,
                "airtable_record_scopes",
                "classification",
                where="import_run_id = ?",
                parameters=(import_run_id,),
            )
            entity_counts.update(
                {f"scope:{classification}": count for classification, count in scope_counts.items()}
            )
            persisted_counts = json.loads(str(run["counts_json"]))
            attachment_counts = self._status_counts(
                repository._conn,
                "airtable_attachment_references",
                "match_status",
                where="import_run_id = ?",
                parameters=(import_run_id,),
            )
            profile_counts = self._status_counts(
                repository._conn,
                "case_profiles",
                "status",
                where="created_by = ?",
                parameters=(f"r05-import:{import_run_id}",),
            )
            issue_counts = self.open_issue_counts(import_run_id, connection=repository._conn)
            links_total = int(persisted_counts.get("linksObserved", 0))
            links_unresolved = int(persisted_counts.get("linksUnresolved", 0))
            return CaseDatabaseImportReportRecord(
                import_run_id=str(run["id"]),
                status=str(run["status"]),
                schema_sha256=str(run["schema_sha256"]),
                snapshot_sha256=str(run["snapshot_sha256"]),
                corpus_manifest_sha256=(
                    str(run["corpus_manifest_sha256"])
                    if run["corpus_manifest_sha256"] is not None
                    else None
                ),
                entity_counts=entity_counts,
                files_accepted=int(persisted_counts.get("filesAccepted", 0)),
                files_duplicate=int(persisted_counts.get("filesDuplicate", 0)),
                files_failed=int(persisted_counts.get("filesFailed", 0)),
                files_skipped=int(persisted_counts.get("filesSkipped", 0)),
                links_resolved=links_total - links_unresolved,
                links_unresolved=links_unresolved,
                attachments_matched=attachment_counts.get("matched", 0),
                attachments_unmatched=sum(
                    count for status, count in attachment_counts.items() if status != "matched"
                ),
                profiles_draft=profile_counts.get("draft", 0),
                profiles_active=profile_counts.get("active", 0),
                profiles_rejected=profile_counts.get("rejected", 0),
                critical_issues=issue_counts.get("critical", 0),
                warning_issues=issue_counts.get("warning", 0),
                info_issues=issue_counts.get("info", 0),
                restart_verified=bool(run["restart_verified"]),
                backup_verified=bool(run["backup_verified"]),
            )
        finally:
            repository.close()

    def open_issue_counts(
        self,
        import_run_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Mapping[str, int]:
        owned = connection is None
        repository = self._open() if owned else None
        actual = connection or cast(SQLiteRepository, repository)._conn
        try:
            result = {"critical": 0, "warning": 0, "info": 0}
            rows = actual.execute(
                """
                SELECT severity, COUNT(*) AS count
                FROM airtable_reconciliation_issues
                WHERE import_run_id = ? AND status = 'open'
                GROUP BY severity
                """,
                (import_run_id,),
            ).fetchall()
            result.update({str(row["severity"]): int(row["count"]) for row in rows})
            return result
        finally:
            if repository is not None:
                repository.close()

    def verify_restart_and_backup(
        self, import_run_id: str, restore_path: Path, *, occurred_at: datetime
    ) -> BackupVerification:
        source = SQLiteConnectionFactory(self.database_path, self.connection_policy).connect()
        restore = Path(restore_path)
        restore.parent.mkdir(parents=True, exist_ok=True)
        if restore.exists():
            raise CaseDatabaseImportRepositoryError("Backup restore target вже існує")
        target = SQLiteConnectionFactory(restore, self.connection_policy).connect()
        try:
            source_integrity = str(source.execute("PRAGMA integrity_check").fetchone()[0])
            source_foreign_keys_ok = not source.execute("PRAGMA foreign_key_check").fetchall()
            if not source_foreign_keys_ok:
                raise CaseDatabaseImportRepositoryError("SQLite foreign_key_check failed")
            run = self._require_run(source, import_run_id)
            source.backup(target)
            restored_integrity = str(target.execute("PRAGMA integrity_check").fetchone()[0])
            restored_foreign_keys_ok = not target.execute("PRAGMA foreign_key_check").fetchall()
            source_revision = self._source_revision(source)
            restored_revision = self._source_revision(target)
            source_counts_sha256 = self._verification_counts_sha256(source, import_run_id)
            restored_counts_sha256 = self._verification_counts_sha256(target, import_run_id)
            managed_files_verified = self._verify_managed_files(source)
            evidence_payload = {
                "importRunIdSha256": _sha256_text(import_run_id),
                "snapshotSha256": str(run["snapshot_sha256"]),
                "sourceIntegrity": source_integrity,
                "restoredIntegrity": restored_integrity,
                "sourceForeignKeysOk": source_foreign_keys_ok,
                "restoredForeignKeysOk": restored_foreign_keys_ok,
                "sourceRevision": source_revision,
                "restoredRevision": restored_revision,
                "sourceCountsSha256": source_counts_sha256,
                "restoredCountsSha256": restored_counts_sha256,
                "managedFilesVerified": managed_files_verified,
            }
            verification_sha256 = _sha256_text(_json(evidence_payload))
            source.execute(
                """
                INSERT OR IGNORE INTO airtable_import_verifications(
                    id, import_run_id, verification_sha256,
                    source_integrity, restored_integrity,
                    source_foreign_keys_ok, restored_foreign_keys_ok,
                    source_revision, restored_revision,
                    source_counts_sha256, restored_counts_sha256,
                    managed_files_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid5(_R05_NAMESPACE, f"verification:{verification_sha256}")),
                    import_run_id,
                    verification_sha256,
                    source_integrity,
                    restored_integrity,
                    int(source_foreign_keys_ok),
                    int(restored_foreign_keys_ok),
                    source_revision,
                    restored_revision,
                    source_counts_sha256,
                    restored_counts_sha256,
                    managed_files_verified,
                    occurred_at.isoformat(),
                ),
            )
            source.commit()
            return BackupVerification(
                source_integrity=source_integrity,
                restored_integrity=restored_integrity,
                source_revision=source_revision,
                restored_revision=restored_revision,
                source_counts_sha256=source_counts_sha256,
                restored_counts_sha256=restored_counts_sha256,
                managed_files_verified=managed_files_verified,
                verification_sha256=verification_sha256,
                source_foreign_keys_ok=source_foreign_keys_ok,
                restored_foreign_keys_ok=restored_foreign_keys_ok,
            )
        finally:
            target.close()
            source.close()

    @staticmethod
    def _verification_counts_sha256(connection: sqlite3.Connection, import_run_id: str) -> str:
        tables = (
            "airtable_record_versions",
            "airtable_record_scopes",
            "airtable_attachment_references",
            "airtable_reconciliation_issues",
            "case_profiles",
            "file_objects",
            "managed_storage_records",
            "source_references",
            "evidence_relations",
            "evidence_findings",
            "review_decisions",
            "finding_review_decisions",
        )
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
        counts["runRecordVersions"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM airtable_record_versions WHERE import_run_id = ?",
                (import_run_id,),
            ).fetchone()[0]
        )
        return _sha256_text(_json(counts))

    def _verify_managed_files(self, connection: sqlite3.Connection) -> int:
        managed_root = self.database_path.resolve().parent.parent
        rows = connection.execute(
            """
            SELECT records.storage_reference, files.sha256, files.size_bytes
            FROM managed_storage_records AS records
            JOIN file_objects AS files ON files.id = records.file_id
            WHERE records.state = 'verified'
            ORDER BY records.file_id
            """
        ).fetchall()
        verified = 0
        for row in rows:
            reference = str(row["storage_reference"])
            candidate = managed_root.joinpath(*reference.split("/"))
            digest = hashlib.sha256()
            size = 0
            try:
                with candidate.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
            except OSError as exc:
                raise CaseDatabaseImportRepositoryError(
                    "Managed original недоступний для backup verification"
                ) from exc
            if digest.hexdigest() != str(row["sha256"]) or size != int(row["size_bytes"]):
                raise CaseDatabaseImportRepositoryError(
                    "Managed original не пройшов hash verification"
                )
            verified += 1
        return verified

    def _open(self, *, auto_commit: bool = True) -> SQLiteRepository:
        return SQLiteRepository(
            self.database_path,
            auto_commit=auto_commit,
            connection_policy=self.connection_policy,
        )

    @staticmethod
    def _require_run(connection: sqlite3.Connection, import_run_id: str) -> sqlite3.Row:
        run = connection.execute(
            "SELECT * FROM airtable_import_runs WHERE id = ?", (import_run_id,)
        ).fetchone()
        if run is None:
            raise CaseDatabaseImportRepositoryError("Import run не знайдено")
        return cast(sqlite3.Row, run)

    @staticmethod
    def _assert_snapshot_identity(run: sqlite3.Row, snapshot: CaseDatabaseSourceSnapshot) -> None:
        expected = (
            str(run["source_identity_sha256"]),
            str(run["schema_sha256"]),
            str(run["snapshot_sha256"]),
        )
        actual = (
            snapshot.source_identity_sha256,
            snapshot.schema_sha256,
            snapshot.snapshot_sha256,
        )
        if expected != actual:
            raise CaseDatabaseImportRepositoryError("Import snapshot не відповідає plan identity")

    @staticmethod
    def _validate_snapshot(snapshot: CaseDatabaseSourceSnapshot) -> None:
        hashes = (
            snapshot.source_identity_sha256,
            snapshot.schema_sha256,
            snapshot.snapshot_sha256,
        )
        if not all(_HASH_PATTERN.fullmatch(value) for value in hashes):
            raise CaseDatabaseImportRepositoryError("Snapshot identity hash некоректний")
        tables = snapshot.payload.get("tables")
        if not isinstance(tables, Mapping) or len(tables) != 9:
            raise CaseDatabaseImportRepositoryError("Snapshot має містити всі 9 Airtable tables")
        if set(map(str, tables)) != set(snapshot.table_counts):
            raise CaseDatabaseImportRepositoryError("Snapshot table counts не відповідають payload")
        pagination = snapshot.payload.get("paginationComplete")
        if not isinstance(pagination, Mapping) or {
            str(key): value for key, value in pagination.items()
        } != {str(table_id): True for table_id in tables}:
            raise CaseDatabaseImportRepositoryError("Snapshot pagination не підтверджена")
        schema = snapshot.payload.get("schema")
        if not isinstance(schema, Mapping) or _sha256_text(_json(schema)) != snapshot.schema_sha256:
            raise CaseDatabaseImportRepositoryError("Snapshot full schema hash некоректний")
        catalog_hash = str(snapshot.payload.get("catalogMappingSha256") or "")
        if not _HASH_PATTERN.fullmatch(catalog_hash):
            raise CaseDatabaseImportRepositoryError("Snapshot catalog mapping hash некоректний")
        actual_record_ids: set[str] = set()
        case_table_id = next(
            table_id for table_id, table_name in TABLE_SQL_NAMES.items() if table_name == "cases"
        )
        selected_found = False
        for table_id, table in tables.items():
            if not isinstance(table, Mapping) or not isinstance(table.get("records"), list):
                raise CaseDatabaseImportRepositoryError("Snapshot table payload некоректний")
            records = cast(list[object], table["records"])
            if int(snapshot.table_counts[str(table_id)]) != len(records):
                raise CaseDatabaseImportRepositoryError("Snapshot exact table count некоректний")
            for record in records:
                record_id = _record_identifier(record)
                if record_id in actual_record_ids:
                    raise CaseDatabaseImportRepositoryError("Snapshot duplicate record ID")
                actual_record_ids.add(record_id)
                if str(table_id) == case_table_id and record_id == snapshot.selected_case_record_id:
                    selected_found = True
        if not snapshot.selected_case_record_id or not selected_found:
            raise CaseDatabaseImportRepositoryError("Snapshot selected case record відсутній")
        if _sha256_text(_json(snapshot.payload)) != snapshot.snapshot_sha256:
            raise CaseDatabaseImportRepositoryError("Snapshot SHA-256 не відповідає payload")

    @staticmethod
    def _persist_record_versions(
        connection: sqlite3.Connection,
        import_run_id: str,
        snapshot: CaseDatabaseSourceSnapshot,
        captured_at: str,
    ) -> None:
        for table_id, record in _snapshot_records(snapshot):
            record_id = str(record["id"])
            fields = record.get("fields", {})
            raw = _json(fields)
            mapped = connection.execute(
                """
                SELECT local_id FROM airtable_record_map
                WHERE airtable_table_id = ? AND airtable_record_id = ?
                """,
                (table_id, record_id),
            ).fetchone()
            if mapped is None:
                raise CaseDatabaseImportRepositoryError("Imported record mapping is missing")
            identity = f"{import_run_id}:{table_id}:{record_id}"
            connection.execute(
                """
                INSERT OR IGNORE INTO airtable_record_versions(
                    id, import_run_id, airtable_table_id, airtable_record_id,
                    local_id, record_sha256, raw_fields_json, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid5(_R05_NAMESPACE, identity)),
                    import_run_id,
                    table_id,
                    record_id,
                    str(mapped["local_id"]),
                    _sha256_text(raw),
                    raw,
                    captured_at,
                ),
            )

    @staticmethod
    def _classify_record_scopes(
        connection: sqlite3.Connection,
        import_run_id: str,
        selected_case_record_id: str,
        created_at: str,
    ) -> str:
        rows = connection.execute(
            """
            SELECT versions.airtable_table_id, versions.airtable_record_id,
                   versions.local_id, mappings.id AS map_id
            FROM airtable_record_versions AS versions
            JOIN airtable_record_map AS mappings
              ON mappings.airtable_table_id = versions.airtable_table_id
             AND mappings.airtable_record_id = versions.airtable_record_id
            WHERE versions.import_run_id = ?
            ORDER BY versions.airtable_table_id, versions.airtable_record_id
            """,
            (import_run_id,),
        ).fetchall()
        by_map_id = {int(row["map_id"]): row for row in rows}
        by_source = {
            (str(row["airtable_table_id"]), str(row["airtable_record_id"])): row for row in rows
        }
        case_table_id = next(
            table_id for table_id, table_name in TABLE_SQL_NAMES.items() if table_name == "cases"
        )
        selected = by_source.get((case_table_id, selected_case_record_id))
        if selected is None:
            raise CaseDatabaseImportRepositoryError("Selected case mapping відсутній")

        adjacency: dict[int, set[int]] = {map_id: set() for map_id in by_map_id}
        links = connection.execute(
            """
            SELECT links.source_map_id, links.target_map_id
            FROM airtable_record_links AS links
            JOIN airtable_record_versions AS versions
              ON versions.local_id = (
                  SELECT local_id FROM airtable_record_map
                  WHERE id = links.source_map_id
              )
             AND versions.import_run_id = ?
            WHERE links.target_map_id IS NOT NULL
            """,
            (import_run_id,),
        ).fetchall()
        for link in links:
            source_id = int(link["source_map_id"])
            target_id = int(link["target_map_id"])
            if source_id in adjacency and target_id in adjacency:
                adjacency[source_id].add(target_id)
                adjacency[target_id].add(source_id)

        case_maps = {
            map_id: str(row["airtable_record_id"])
            for map_id, row in by_map_id.items()
            if str(row["airtable_table_id"]) == case_table_id
        }
        for map_id, row in by_map_id.items():
            owners: set[str] = set()
            if map_id in case_maps:
                owners.add(case_maps[map_id])
            else:
                pending = list(adjacency[map_id])
                visited = {map_id}
                while pending:
                    candidate = pending.pop()
                    if candidate in visited:
                        continue
                    visited.add(candidate)
                    if candidate in case_maps:
                        owners.add(case_maps[candidate])
                        continue
                    pending.extend(adjacency[candidate] - visited)
            if str(row["airtable_table_id"]) == case_table_id:
                classification = (
                    "selected_case"
                    if str(row["airtable_record_id"]) == selected_case_record_id
                    else "cross_case"
                )
                reason = (
                    "selected_case_record" if classification == "selected_case" else "other_case"
                )
            elif selected_case_record_id in owners and len(owners) > 1:
                classification, reason = "shared", "linked_to_multiple_cases"
            elif selected_case_record_id in owners:
                classification, reason = "selected_case", "linked_to_selected_case"
            elif owners:
                classification, reason = "cross_case", "linked_only_to_other_case"
            else:
                classification, reason = "unresolved", "no_case_path"
            connection.execute(
                """
                INSERT OR IGNORE INTO airtable_record_scopes(
                    import_run_id, airtable_table_id, airtable_record_id,
                    local_id, classification, owning_case_ids_json,
                    reason_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_run_id,
                    str(row["airtable_table_id"]),
                    str(row["airtable_record_id"]),
                    str(row["local_id"]),
                    classification,
                    _json(sorted(owners)),
                    reason,
                    created_at,
                ),
            )
        return str(selected["local_id"])

    @staticmethod
    def _persist_source_references(
        connection: sqlite3.Connection, import_run_id: str, created_at: str
    ) -> None:
        rows = connection.execute(
            """
            SELECT versions.airtable_table_id, versions.airtable_record_id,
                   versions.local_id
            FROM airtable_record_versions AS versions
            JOIN airtable_record_scopes AS scopes
              ON scopes.import_run_id = versions.import_run_id
             AND scopes.airtable_table_id = versions.airtable_table_id
             AND scopes.airtable_record_id = versions.airtable_record_id
            WHERE versions.import_run_id = ?
              AND scopes.classification IN ('selected_case', 'shared')
            ORDER BY versions.airtable_table_id, versions.airtable_record_id
            """,
            (import_run_id,),
        ).fetchall()
        for row in rows:
            table_id = str(row["airtable_table_id"])
            entity_type = TABLE_SQL_NAMES[table_id].removesuffix("s")
            if entity_type not in {"case", "proceeding", "document", "event"}:
                continue
            local_id = str(row["local_id"])
            reference_id = str(
                uuid.uuid5(_R05_NAMESPACE, f"source:{import_run_id}:{table_id}:{local_id}")
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO source_references(
                    id, source_entity_type, source_entity_id, location_type,
                    location_value, review_status, created_by, created_at, version
                ) VALUES (?, ?, ?, 'metadata', ?, 'unreviewed', 'r05-import', ?, 1)
                """,
                (reference_id, entity_type, local_id, str(row["airtable_record_id"]), created_at),
            )

    @staticmethod
    def _persist_attachments(
        connection: sqlite3.Connection,
        import_run_id: str,
        snapshot: CaseDatabaseSourceSnapshot,
        created_at: str,
    ) -> None:
        schema = load_airtable_schema()
        attachment_fields = {
            (str(table["id"]), str(field["id"]))
            for table in schema["tables"]
            for field in table["fields"]
            if str(field["type"]) == "multipleAttachments"
        }
        for table_id, record in _snapshot_records(snapshot):
            fields = record.get("fields", {})
            if not isinstance(fields, Mapping):
                continue
            for field_id, value in fields.items():
                if (table_id, str(field_id)) not in attachment_fields:
                    continue
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if not isinstance(item, Mapping) or not item.get("id"):
                        continue
                    metadata = _json(item)
                    identity = f"attachment:{import_run_id}:{table_id}:{record['id']}:{field_id}:{item['id']}"
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO airtable_attachment_references(
                            id, import_run_id, source_table_id, source_record_id,
                            source_field_id, attachment_id, metadata_json, metadata_sha256,
                            match_status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                        """,
                        (
                            str(uuid.uuid5(_R05_NAMESPACE, identity)),
                            import_run_id,
                            table_id,
                            str(record["id"]),
                            str(field_id),
                            str(item["id"]),
                            metadata,
                            _sha256_text(metadata),
                            created_at,
                            created_at,
                        ),
                    )

    @staticmethod
    def _materialize_dates(connection: sqlite3.Connection, created_at: str) -> None:
        for table, column_roles in _DATE_COLUMNS.items():
            entity_type = table.removesuffix("s")
            rows = connection.execute(
                f"SELECT id, {', '.join(column_roles)} FROM {table} ORDER BY id"
            ).fetchall()
            for row in rows:
                for column, date_role in column_roles.items():
                    value = row[column]
                    if value is None or not str(value).strip():
                        continue
                    text = str(value)
                    precision = "exact_datetime" if "T" in text else "exact_date"
                    timezone_value = (
                        "explicit"
                        if precision == "exact_datetime"
                        and re.search(r"(?:Z|[+-]\d\d:\d\d)$", text)
                        else None
                    )
                    identity = f"date:{entity_type}:{row['id']}:{column}:{text}"
                    source_id = connection.execute(
                        """
                        SELECT id FROM source_references
                        WHERE source_entity_type = ? AND source_entity_id = ?
                        ORDER BY id LIMIT 1
                        """,
                        (entity_type, str(row["id"])),
                    ).fetchone()
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO entity_dates(
                            id, entity_type, entity_id, date_role, date_value,
                            precision, timezone, source_reference_id, review_status,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unreviewed', ?, ?)
                        """,
                        (
                            str(uuid.uuid5(_R05_NAMESPACE, identity)),
                            entity_type,
                            str(row["id"]),
                            date_role,
                            text,
                            precision,
                            timezone_value,
                            str(source_id["id"]) if source_id is not None else None,
                            created_at,
                            created_at,
                        ),
                    )

    @staticmethod
    def _materialize_contact_identities(connection: sqlite3.Connection, created_at: str) -> None:
        contacts = connection.execute("SELECT * FROM contacts ORDER BY id").fetchall()
        for contact in contacts:
            source = connection.execute(
                """
                SELECT id FROM source_references
                WHERE source_entity_type = 'contact' AND source_entity_id = ?
                ORDER BY id LIMIT 1
                """,
                (str(contact["id"]),),
            ).fetchone()
            source_id = str(source["id"]) if source is not None else None
            candidates = (
                ("email", contact["email"]),
                ("phone", contact["phone"]),
                ("phone", contact["additional_phone"]),
                ("address", contact["address"]),
                ("tax_id", contact["tax_id"]),
                ("registration_id", contact["edrpou"]),
            )
            for ordinal, (kind, value) in enumerate(candidates):
                if value is None or not str(value).strip():
                    continue
                display = str(value)
                normalized = _normalize_identifier(kind, display)
                identity = f"contact-id:{contact['id']}:{kind}:{ordinal}:{normalized}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO contact_identifiers(
                        id, contact_id, identifier_type, normalized_value, display_value,
                        source_reference_id, review_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'unreviewed', ?, ?)
                    """,
                    (
                        str(uuid.uuid5(_R05_NAMESPACE, identity)),
                        str(contact["id"]),
                        kind,
                        normalized,
                        display,
                        source_id,
                        created_at,
                        created_at,
                    ),
                )

        links = connection.execute(
            """
            SELECT contact_id, case_id FROM contact_cases
            UNION
            SELECT contact_id, case_id FROM case_participants
            WHERE contact_id IS NOT NULL AND case_id IS NOT NULL
            ORDER BY case_id, contact_id
            """
        ).fetchall()
        for link in links:
            contact_id = str(link["contact_id"])
            case_id = str(link["case_id"])
            contact = connection.execute(
                "SELECT full_name, participant_type FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            if contact is None:
                continue
            actor_id = str(uuid.uuid5(_R05_NAMESPACE, f"actor:{contact_id}"))
            connection.execute(
                """
                INSERT OR IGNORE INTO actors(
                    id, actor_type, display_name, normalized_name, review_status,
                    created_at, updated_at, legacy_payload, version
                ) VALUES (?, ?, ?, ?, 'unreviewed', ?, ?, '{}', 1)
                """,
                (
                    actor_id,
                    str(contact["participant_type"] or "unknown"),
                    str(contact["full_name"]),
                    str(contact["full_name"]).casefold(),
                    created_at,
                    created_at,
                ),
            )
            identity = f"contact-actor:{case_id}:{contact_id}:{actor_id}"
            connection.execute(
                """
                INSERT OR IGNORE INTO contact_actor_links(
                    id, case_id, contact_id, actor_id, match_method,
                    review_status, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'import_identity', 'unreviewed', 1, ?, ?)
                """,
                (
                    str(uuid.uuid5(_R05_NAMESPACE, identity)),
                    case_id,
                    contact_id,
                    actor_id,
                    created_at,
                    created_at,
                ),
            )

    @staticmethod
    def _materialize_case_memberships(connection: sqlite3.Connection, created_at: str) -> None:
        sources = (
            ("document", "case_documents", "document_id"),
            ("event", "case_events", "event_id"),
        )
        for entity_type, table, entity_column in sources:
            rows = connection.execute(
                f"SELECT case_id, {entity_column} AS entity_id FROM {table} ORDER BY case_id, entity_id"
            ).fetchall()
            for row in rows:
                SQLiteCaseDatabaseImportRepository._insert_membership(
                    connection,
                    entity_type,
                    str(row["entity_id"]),
                    str(row["case_id"]),
                    created_at,
                )
        actors = connection.execute(
            "SELECT case_id, actor_id FROM contact_actor_links ORDER BY case_id, actor_id"
        ).fetchall()
        for row in actors:
            SQLiteCaseDatabaseImportRepository._insert_membership(
                connection,
                "actor",
                str(row["actor_id"]),
                str(row["case_id"]),
                created_at,
            )

    @staticmethod
    def _insert_membership(
        connection: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        case_id: str,
        created_at: str,
    ) -> None:
        identity = f"membership:{entity_type}:{entity_id}:case:{case_id}:member"
        source = connection.execute(
            """
            SELECT id FROM source_references
            WHERE source_entity_type = ? AND source_entity_id = ?
            ORDER BY id LIMIT 1
            """,
            (entity_type, entity_id),
        ).fetchone()
        connection.execute(
            """
            INSERT OR IGNORE INTO entity_memberships(
                id, entity_type, entity_id, context_type, context_id, role,
                is_primary, source_reference_id, review_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'case', ?, 'member', 0, ?, 'unreviewed', ?, ?)
            """,
            (
                str(uuid.uuid5(_R05_NAMESPACE, identity)),
                entity_type,
                entity_id,
                case_id,
                str(source["id"]) if source is not None else None,
                created_at,
                created_at,
            ),
        )

    @staticmethod
    def _materialize_event_actor_links(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT DISTINCT ec.event_id, cal.actor_id, ec.role
            FROM event_contacts ec
            JOIN case_events ce ON ce.event_id = ec.event_id
            JOIN contact_actor_links cal
              ON cal.contact_id = ec.contact_id AND cal.case_id = ce.case_id
            ORDER BY ec.event_id, cal.actor_id, ec.role
            """
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO event_actor_links(event_id, actor_id, role)
                VALUES (?, ?, ?)
                """,
                (str(row["event_id"]), str(row["actor_id"]), str(row["role"])),
            )

    @classmethod
    def _materialize_evidence_extensions(
        cls,
        connection: sqlite3.Connection,
        import_run_id: str,
        selected_case_id: str,
        created_at: str,
    ) -> None:
        selected_documents = {
            str(row["document_id"])
            for row in connection.execute(
                "SELECT document_id FROM case_documents WHERE case_id = ?",
                (selected_case_id,),
            ).fetchall()
        }
        link_rows = connection.execute(
            """
            SELECT links.*, scopes.airtable_record_id
            FROM document_links AS links
            JOIN airtable_record_scopes AS scopes ON scopes.local_id = links.id
            WHERE scopes.import_run_id = ?
              AND scopes.classification IN ('selected_case', 'shared')
            ORDER BY links.id
            """,
            (import_run_id,),
        ).fetchall()
        for row in link_rows:
            source_id = str(row["source_document_id"] or "")
            target_id = str(row["target_document_id"] or "")
            if not source_id or not target_id:
                continue
            if source_id not in selected_documents or target_id not in selected_documents:
                cls._upsert_issue(
                    connection,
                    import_run_id,
                    issue_code="cross_case_relation",
                    severity="critical",
                    subject_type="document_link",
                    subject_key=str(row["id"]),
                    detail_code="endpoint_outside_selected_case",
                    created_at=created_at,
                )
                continue
            relation_type = str(row["link_type"] or "refers_to")
            known_type = connection.execute(
                """
                SELECT 1 FROM relation_type_catalog
                WHERE relation_type = ? AND active = 1
                ORDER BY catalog_version DESC LIMIT 1
                """,
                (relation_type,),
            ).fetchone()
            if known_type is None:
                relation_type = "refers_to"
            cls._insert_import_relation(
                connection,
                import_run_id=import_run_id,
                source_record_id=str(row["airtable_record_id"]),
                source_kind="document-link",
                from_id=source_id,
                to_id=target_id,
                relation_type=relation_type,
                label=str(row["title"]) if row["title"] is not None else None,
                created_at=created_at,
            )

        version_rows = connection.execute(
            """
            SELECT matches.*, scopes.airtable_record_id
            FROM document_version_match AS matches
            JOIN airtable_record_scopes AS scopes ON scopes.local_id = matches.id
            WHERE scopes.import_run_id = ?
              AND scopes.classification IN ('selected_case', 'shared')
            ORDER BY matches.id
            """,
            (import_run_id,),
        ).fetchall()
        for row in version_rows:
            source_id = str(row["user_document_id"] or "")
            target_id = str(row["court_document_id"] or "")
            if not source_id or not target_id:
                continue
            if source_id not in selected_documents or target_id not in selected_documents:
                cls._upsert_issue(
                    connection,
                    import_run_id,
                    issue_code="cross_case_relation",
                    severity="critical",
                    subject_type="document_version_match",
                    subject_key=str(row["id"]),
                    detail_code="endpoint_outside_selected_case",
                    created_at=created_at,
                )
                continue
            cls._insert_import_relation(
                connection,
                import_run_id=import_run_id,
                source_record_id=str(row["airtable_record_id"]),
                source_kind="document-version-match",
                from_id=source_id,
                to_id=target_id,
                relation_type="version_of",
                label=str(row["mismatch_type"]) if row["mismatch_type"] is not None else None,
                created_at=created_at,
            )

        flag_rows = connection.execute(
            """
            SELECT flags.*, scopes.airtable_record_id
            FROM compliance_flags AS flags
            JOIN airtable_record_scopes AS scopes ON scopes.local_id = flags.id
            WHERE scopes.import_run_id = ?
              AND scopes.classification IN ('selected_case', 'shared')
            ORDER BY flags.id
            """,
            (import_run_id,),
        ).fetchall()
        for row in flag_rows:
            document_id = str(row["document_id"] or "")
            if not document_id or document_id not in selected_documents:
                if document_id:
                    cls._upsert_issue(
                        connection,
                        import_run_id,
                        issue_code="cross_case_relation",
                        severity="critical",
                        subject_type="compliance_flag",
                        subject_key=str(row["id"]),
                        detail_code="subject_outside_selected_case",
                        created_at=created_at,
                    )
                continue
            source = connection.execute(
                """
                SELECT id FROM source_references
                WHERE source_entity_type = 'document' AND source_entity_id = ?
                  AND created_by = 'r05-import'
                ORDER BY id LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            if source is None:
                raise CaseDatabaseImportRepositoryError("Compliance finding source basis відсутня")
            source_reference_id = str(source["id"])
            fingerprint = _sha256_text(f"{import_run_id}:compliance:{row['airtable_record_id']}")
            finding_id = str(uuid.uuid5(_R05_NAMESPACE, f"finding:{fingerprint}"))
            severity = {
                "info": "info",
                "warning": "medium",
                "critical": "high",
                "falsification_risk": "critical",
            }.get(str(row["severity"] or ""), "unknown")
            title = str(row["title"] or row["flag_type"] or "Imported compliance signal")
            description = str(row["note"] or title)
            connection.execute(
                """
                INSERT OR IGNORE INTO evidence_findings(
                    id, fingerprint, finding_type, title, description, severity,
                    detector_name, detector_version, automatic_status,
                    review_status, first_observed_at, last_observed_at,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'airtable-import', 'r05-v1', 'unknown',
                    'manual_review_required', ?, ?, ?, ?
                )
                """,
                (
                    finding_id,
                    fingerprint,
                    str(row["flag_type"] or "imported_compliance_signal"),
                    title,
                    description,
                    severity,
                    created_at,
                    created_at,
                    created_at,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO finding_subjects(
                    finding_id, subject_type, subject_id
                ) VALUES (?, 'document', ?)
                """,
                (finding_id, document_id),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO finding_source_references(
                    finding_id, source_reference_id
                ) VALUES (?, ?)
                """,
                (finding_id, source_reference_id),
            )
            connection.execute(
                """
                INSERT INTO finding_observations(
                    finding_id, observation_status, detector_name,
                    detector_version, severity, details_json, observed_at
                )
                SELECT ?, 'compatibility_import', 'airtable-import', 'r05-v1',
                       ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM finding_observations
                    WHERE finding_id = ? AND detector_name = 'airtable-import'
                      AND detector_version = 'r05-v1'
                )
                """,
                (
                    finding_id,
                    severity,
                    _json(
                        {
                            "sourceRecordSha256": _sha256_text(str(row["airtable_record_id"])),
                            "detectedBy": str(row["detected_by"] or ""),
                        }
                    ),
                    created_at,
                    finding_id,
                ),
            )

    @staticmethod
    def _insert_import_relation(
        connection: sqlite3.Connection,
        *,
        import_run_id: str,
        source_record_id: str,
        source_kind: str,
        from_id: str,
        to_id: str,
        relation_type: str,
        label: str | None,
        created_at: str,
    ) -> None:
        relation_id = str(
            uuid.uuid5(
                _R05_NAMESPACE,
                f"relation:{import_run_id}:{source_kind}:{source_record_id}",
            )
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO evidence_relations(
                id, from_type, from_id, to_type, to_id, relation_type,
                label, classification, review_status,
                created_at, updated_at, version
            ) VALUES (
                ?, 'document', ?, 'document', ?, ?, ?,
                'unverified', 'manual_review_required', ?, ?, 1
            )
            """,
            (
                relation_id,
                from_id,
                to_id,
                relation_type,
                label,
                created_at,
                created_at,
            ),
        )
        source_reference_id = str(
            uuid.uuid5(
                _R05_NAMESPACE,
                f"relation-source:{import_run_id}:{source_kind}:{source_record_id}",
            )
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO source_references(
                id, source_entity_type, source_entity_id, location_type,
                location_value, review_status, created_by, created_at, version
            ) VALUES (
                ?, 'relation', ?, 'metadata', ?,
                'manual_review_required', 'r05-import', ?, 1
            )
            """,
            (
                source_reference_id,
                relation_id,
                _sha256_text(source_record_id),
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO relation_source_references(
                relation_id, source_reference_id
            ) VALUES (?, ?)
            """,
            (relation_id, source_reference_id),
        )

    @classmethod
    def _replace_unresolved_link_issues(
        cls, connection: sqlite3.Connection, import_run_id: str, created_at: str
    ) -> None:
        unresolved = connection.execute(
            """
            SELECT source_map_id, airtable_field_id, target_table_id,
                   target_airtable_record_id, position
            FROM airtable_record_links
            WHERE target_map_id IS NULL
              AND source_map_id IN (
                  SELECT mappings.id
                  FROM airtable_record_map AS mappings
                  JOIN airtable_record_versions AS versions
                    ON versions.airtable_table_id = mappings.airtable_table_id
                   AND versions.airtable_record_id = mappings.airtable_record_id
                  WHERE versions.import_run_id = ?
              )
            ORDER BY source_map_id, airtable_field_id, position
            """,
            (import_run_id,),
        ).fetchall()
        for row in unresolved:
            subject = ":".join(str(row[key]) for key in row.keys())
            cls._upsert_issue(
                connection,
                import_run_id,
                issue_code="unresolved_link",
                severity="critical",
                subject_type="airtable_link",
                subject_key=subject,
                detail_code="target_not_imported",
                created_at=created_at,
            )

    @classmethod
    def _replace_orphan_issues(
        cls, connection: sqlite3.Connection, import_run_id: str, created_at: str
    ) -> None:
        queries = {
            "contact": """
                SELECT id FROM contacts c WHERE NOT EXISTS (
                    SELECT 1 FROM contact_cases cc WHERE cc.contact_id = c.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM case_participants cp WHERE cp.contact_id = c.id AND cp.case_id IS NOT NULL
                )
                AND c.id IN (
                    SELECT local_id FROM airtable_record_scopes
                    WHERE import_run_id = ? AND classification IN ('selected_case', 'shared')
                )
            """,
            "document": """
                SELECT id FROM documents d WHERE NOT EXISTS (
                    SELECT 1 FROM case_documents cd WHERE cd.document_id = d.id
                )
                AND d.id IN (
                    SELECT local_id FROM airtable_record_scopes
                    WHERE import_run_id = ? AND classification IN ('selected_case', 'shared')
                )
            """,
            "event": """
                SELECT id FROM events e WHERE NOT EXISTS (
                    SELECT 1 FROM case_events ce WHERE ce.event_id = e.id
                )
                AND e.id IN (
                    SELECT local_id FROM airtable_record_scopes
                    WHERE import_run_id = ? AND classification IN ('selected_case', 'shared')
                )
            """,
            "proceeding": """
                SELECT id FROM proceedings p WHERE NOT EXISTS (
                    SELECT 1 FROM case_proceedings cp WHERE cp.proceeding_id = p.id
                )
                AND p.id IN (
                    SELECT local_id FROM airtable_record_scopes
                    WHERE import_run_id = ? AND classification IN ('selected_case', 'shared')
                )
            """,
        }
        for entity_type, query in queries.items():
            for row in connection.execute(query, (import_run_id,)).fetchall():
                cls._upsert_issue(
                    connection,
                    import_run_id,
                    issue_code="orphan_record",
                    severity="warning",
                    subject_type=entity_type,
                    subject_key=str(row["id"]),
                    detail_code="no_case_membership",
                    created_at=created_at,
                )

    @staticmethod
    def _upsert_issue(
        connection: sqlite3.Connection,
        import_run_id: str,
        *,
        issue_code: str,
        severity: str,
        subject_type: str,
        subject_key: str,
        detail_code: str,
        created_at: str,
    ) -> None:
        subject_hash = _sha256_text(subject_key)
        identity = f"issue:{import_run_id}:{issue_code}:{subject_type}:{subject_hash}:{detail_code}"
        connection.execute(
            """
            INSERT OR IGNORE INTO airtable_reconciliation_issues(
                id, import_run_id, issue_code, severity, subject_type,
                subject_key_sha256, detail_code, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                str(uuid.uuid5(_R05_NAMESPACE, identity)),
                import_run_id,
                issue_code,
                severity,
                subject_type,
                subject_hash,
                detail_code,
                created_at,
                created_at,
            ),
        )

    @staticmethod
    def _materialize_profiles(
        connection: sqlite3.Connection,
        import_run_id: str,
        snapshot_sha256: str,
        mapping_version: str,
        created_at: str,
        *,
        selected_case_id: str,
        active: bool,
    ) -> None:
        profile_version = "r05-" + _sha256_text(f"{mapping_version}:{snapshot_sha256}")[:16]
        cases = connection.execute(
            "SELECT * FROM cases WHERE id = ? ORDER BY id", (selected_case_id,)
        ).fetchall()
        if len(cases) != 1:
            raise CaseDatabaseImportRepositoryError("Selected case domain row відсутній")
        for case in cases:
            proceedings = connection.execute(
                """
                SELECT p.* FROM proceedings p
                JOIN case_proceedings cp ON cp.proceeding_id = p.id
                WHERE cp.case_id = ?
                ORDER BY p.id
                """,
                (str(case["id"]),),
            ).fetchall()
            proceeding_profiles: list[dict[str, object]] = [
                {
                    "id": str(item["id"]),
                    "number": str(item["proceeding_number"]),
                    "folderKey": "proceeding-" + _sha256_text(str(item["id"]))[:12],
                    "aliases": [],
                    "required": False,
                    "reviewStatus": "unreviewed",
                    "expectedKind": str(item["proceeding_type"])
                    if item["proceeding_type"]
                    else None,
                    "expectedTitle": str(item["name"]) if item["name"] else None,
                }
                for item in proceedings
                if item["proceeding_number"] and str(item["proceeding_number"]).strip()
            ]
            number = str(case["case_number"]) if case["case_number"] else None
            title = str(case["name"] or case["case_number"] or "Imported case")
            profile = {
                "schemaVersion": "1.1.0",
                "profileVersion": profile_version,
                "case": {
                    "id": str(case["id"]),
                    "number": number,
                    "numberStatus": "confirmed" if number else "unknown",
                    "folderKey": "case-" + _sha256_text(str(case["id"]))[:12],
                    "title": title,
                    "aliases": [],
                    "caseType": str(case["category"]) if case["category"] else None,
                    "jurisdiction": None,
                    "primaryCourtName": str(case["court"]) if case["court"] else None,
                    "description": str(case["short_description"])
                    if case["short_description"]
                    else None,
                    "tags": [],
                },
                "bootstrap": {
                    "firstDocumentId": None,
                    "temporaryIntakeCaseId": None,
                    "numberDetectionSources": ["structured_metadata"] if number else [],
                    "requireManualReviewForMultipleCandidates": True,
                    "allowFilenameAsSoleEvidence": False,
                },
                "proceedings": proceeding_profiles,
                "evidenceMap": {
                    "rootDocumentId": None,
                    "rootSelector": None,
                    "keyDocumentRules": [],
                    "relationHypotheses": [],
                },
                "exportDefaults": {
                    "profile": "metadata_only",
                    "includeFullText": False,
                    "includeOriginalFiles": False,
                    "sealed": False,
                    "language": "uk",
                },
                "validationRules": {
                    "requireSourceForConfirmedFacts": True,
                    "requireAllRequiredProceedings": False,
                    "requireReferentialIntegrity": True,
                    "requireUniqueIds": True,
                    "blockExternalNetworkInSealedExport": True,
                },
            }
            raw = _json(profile)
            profile_id = str(uuid.uuid5(_R05_NAMESPACE, f"profile:{case['id']}:{profile_version}"))
            connection.execute(
                """
                INSERT OR IGNORE INTO case_profiles(
                    id, case_id, schema_version, profile_version, profile_json,
                    profile_sha256, status, created_by, created_at, activated_at
                ) VALUES (?, ?, '1.1.0', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    str(case["id"]),
                    profile_version,
                    raw,
                    _sha256_text(raw),
                    "active" if active else "draft",
                    f"r05-import:{import_run_id}",
                    created_at,
                    created_at if active else None,
                ),
            )

    @staticmethod
    def _status_counts(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        *,
        where: str | None = None,
        parameters: tuple[object, ...] = (),
    ) -> dict[str, int]:
        clause = f" WHERE {where}" if where else ""
        rows = connection.execute(
            f"SELECT {column} AS status, COUNT(*) AS count FROM {table}{clause} GROUP BY {column}",
            parameters,
        ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    @classmethod
    def _reconcile_attachment(
        cls,
        connection: sqlite3.Connection,
        import_run_id: str,
        attachment: sqlite3.Row,
        occurred_at: str,
    ) -> None:
        metadata = json.loads(str(attachment["metadata_json"]))
        if not isinstance(metadata, dict):
            raise CaseDatabaseImportRepositoryError("Attachment metadata має бути object")
        expected_hash = str(metadata.get("sha256") or metadata.get("file_hash") or "")
        name = str(metadata.get("filename") or "")
        size = metadata.get("size")
        source_path = str(metadata.get("sourceRelativePath") or "")
        candidates: list[sqlite3.Row] = []
        method: str | None = None
        corpus_batch_key = f"r05-corpus:{import_run_id}"
        if _HASH_PATTERN.fullmatch(expected_hash):
            candidates = connection.execute(
                """
                SELECT files.* FROM file_objects AS files
                JOIN import_batches AS batches ON batches.id = files.import_batch_id
                WHERE files.sha256 = ? AND batches.idempotency_key = ?
                ORDER BY files.id
                """,
                (expected_hash, corpus_batch_key),
            ).fetchall()
            method = "sha256"
        if not candidates and source_path:
            candidates = connection.execute(
                """
                SELECT files.* FROM file_objects AS files
                JOIN import_batches AS batches ON batches.id = files.import_batch_id
                WHERE files.source_relative_path = ? AND batches.idempotency_key = ?
                ORDER BY files.id
                """,
                (source_path, corpus_batch_key),
            ).fetchall()
            method = "source_provenance" if candidates else None
        if not candidates and name and isinstance(size, int):
            suggestions = connection.execute(
                """
                SELECT files.* FROM file_objects AS files
                JOIN import_batches AS batches ON batches.id = files.import_batch_id
                WHERE files.original_name = ? AND files.size_bytes = ?
                  AND batches.idempotency_key = ?
                ORDER BY files.id
                """,
                (name, size, corpus_batch_key),
            ).fetchall()
            if suggestions:
                connection.execute(
                    """
                    UPDATE airtable_attachment_references
                    SET match_status = 'ambiguous', match_method = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (occurred_at, str(attachment["id"])),
                )
                cls._upsert_issue(
                    connection,
                    import_run_id,
                    issue_code="ambiguous_file_match",
                    severity="critical",
                    subject_type="airtable_attachment",
                    subject_key=str(attachment["id"]),
                    detail_code="name_size_is_suggestion_only",
                    created_at=occurred_at,
                )
                return
        if len(candidates) == 1:
            file_row = candidates[0]
            if expected_hash and file_row["sha256"] != expected_hash:
                cls._upsert_issue(
                    connection,
                    import_run_id,
                    issue_code="hash_mismatch",
                    severity="critical",
                    subject_type="airtable_attachment",
                    subject_key=str(attachment["id"]),
                    detail_code="matched_file_hash_differs",
                    created_at=occurred_at,
                )
                status, method = "missing", None
            else:
                status = "matched"
                cls._link_attachment_file(connection, attachment, file_row, occurred_at)
            connection.execute(
                """
                UPDATE airtable_attachment_references
                SET file_id = ?, match_status = ?, match_method = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(file_row["id"]) if status == "matched" else None,
                    status,
                    method,
                    occurred_at,
                    str(attachment["id"]),
                ),
            )
            return
        issue_code = "ambiguous_file_match" if len(candidates) > 1 else "missing_local_file"
        status = "ambiguous" if candidates else "missing"
        connection.execute(
            """
            UPDATE airtable_attachment_references
            SET match_status = ?, match_method = NULL, updated_at = ? WHERE id = ?
            """,
            (status, occurred_at, str(attachment["id"])),
        )
        cls._upsert_issue(
            connection,
            import_run_id,
            issue_code=issue_code,
            severity="critical",
            subject_type="airtable_attachment",
            subject_key=str(attachment["id"]),
            detail_code="requires_explicit_review",
            created_at=occurred_at,
        )

    @classmethod
    def _link_attachment_file(
        cls,
        connection: sqlite3.Connection,
        attachment: sqlite3.Row,
        file_row: sqlite3.Row,
        occurred_at: str,
    ) -> None:
        mapped = connection.execute(
            """
            SELECT local_id FROM airtable_record_map
            WHERE airtable_table_id = ? AND airtable_record_id = ?
            """,
            (str(attachment["source_table_id"]), str(attachment["source_record_id"])),
        ).fetchone()
        if mapped is None or TABLE_SQL_NAMES.get(str(attachment["source_table_id"])) != "documents":
            return
        document_id = str(mapped["local_id"])
        document_file_id = str(
            uuid.uuid5(
                _R05_NAMESPACE,
                f"document-file:{document_id}:{attachment['attachment_id']}",
            )
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO document_files(
                id, document_id, role, sequence_number, created_at, updated_at, legacy_payload
            ) VALUES (?, ?, 'attachment', NULL, ?, ?, '{}')
            """,
            (document_file_id, document_id, occurred_at, occurred_at),
        )
        connection.execute(
            """
            UPDATE file_objects SET document_id = ?, document_file_id = ?, updated_at = ?
            WHERE id = ? AND (document_id IS NULL OR document_id = ?)
            """,
            (document_id, document_file_id, occurred_at, str(file_row["id"]), document_id),
        )
        memberships = connection.execute(
            """
            SELECT context_id FROM entity_memberships
            WHERE entity_type = 'document' AND entity_id = ? AND context_type = 'case'
            """,
            (document_id,),
        ).fetchall()
        for membership in memberships:
            cls._insert_membership(
                connection, "file", str(file_row["id"]), str(membership["context_id"]), occurred_at
            )
            membership_id = str(
                uuid.uuid5(
                    _R05_NAMESPACE, f"local-file-case:{file_row['id']}:{membership['context_id']}"
                )
            )
            connection.execute(
                """
                INSERT INTO file_context_memberships(
                    id, file_id, context_type, context_id, role, origin, actor_id, note, created_at
                ) VALUES (?, ?, 'case', ?, 'attachment', 'manual_command',
                          'r05-local-import', 'Explicit local document attachment mapping', ?)
                ON CONFLICT(file_id, context_type, context_id, role) DO NOTHING
                """,
                (membership_id, str(file_row["id"]), str(membership["context_id"]), occurred_at),
            )

    @staticmethod
    def _issue_count(connection: sqlite3.Connection, import_run_id: str, severity: str) -> int:
        return int(
            connection.execute(
                """
                SELECT COUNT(*) FROM airtable_reconciliation_issues
                WHERE import_run_id = ? AND severity = ? AND status = 'open'
                """,
                (import_run_id, severity),
            ).fetchone()[0]
        )

    @staticmethod
    def _source_revision(connection: sqlite3.Connection) -> str:
        payload: dict[str, object] = {}
        tables = (
            "schema_migrations",
            "airtable_import_runs",
            "airtable_import_batches",
            "airtable_record_versions",
            "airtable_attachment_references",
            "airtable_reconciliation_issues",
            "airtable_record_map",
            "airtable_record_links",
            *_ENTITY_TABLES,
            "case_profiles",
            "contact_identifiers",
            "contact_actor_links",
            "entity_dates",
        )
        for table in tables:
            columns = [
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            payload[table] = [
                {column: row[column] for column in columns if column not in {"updated_at"}}
                for row in rows
            ]
        return _sha256_text(_json(payload))

    def _mark_interrupted(self, import_run_id: str, occurred_at: datetime, error_code: str) -> None:
        repository = self._open(auto_commit=False)
        try:
            repository.begin(write=True)
            repository._conn.execute(
                """
                UPDATE airtable_import_runs
                SET status = 'interrupted', updated_at = ?
                WHERE id = ? AND status != 'finalized'
                """,
                (occurred_at.isoformat(), import_run_id),
            )
            repository._conn.execute(
                """
                UPDATE airtable_import_batches
                SET status = 'interrupted', last_error_code = ?, updated_at = ?
                WHERE import_run_id = ? AND status = 'running'
                """,
                (error_code, occurred_at.isoformat(), import_run_id),
            )
            repository.commit()
        finally:
            repository.close()


def _snapshot_records(
    snapshot: CaseDatabaseSourceSnapshot,
) -> Iterable[tuple[str, Mapping[str, object]]]:
    tables = cast(Mapping[str, object], snapshot.payload["tables"])
    for table_id in sorted(tables):
        table = tables[table_id]
        if not isinstance(table, Mapping) or not isinstance(table.get("records"), list):
            raise CaseDatabaseImportRepositoryError("Snapshot table payload некоректний")
        for record in cast(list[object], table["records"]):
            if not isinstance(record, Mapping) or not record.get("id"):
                raise CaseDatabaseImportRepositoryError("Snapshot record некоректний")
            yield str(table_id), cast(Mapping[str, object], record)


def _record_identifier(record: object) -> str:
    if not isinstance(record, Mapping) or not record.get("id"):
        raise CaseDatabaseImportRepositoryError("Snapshot record некоректний")
    return str(record["id"])


def _normalize_identifier(kind: str, value: str) -> str:
    normalized = value.strip().casefold()
    if kind == "phone":
        return "".join(
            character for character in normalized if character.isdigit() or character == "+"
        )
    if kind in {"tax_id", "registration_id"}:
        return "".join(character for character in normalized if character.isalnum())
    return " ".join(normalized.split())


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
