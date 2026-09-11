from __future__ import annotations

import sqlite3
from datetime import datetime

from case_docket.application.ports import ManagedFileRecord, ManagedFileRepositoryPort

from .sqlite_repository import SQLiteRepository


_STATES = frozenset(
    {"prepared", "finalized", "verified", "mismatch", "reference_unavailable", "error"}
)
_INTEGRITY_STATUSES = frozenset(
    {"verified", "mismatch", "reference_unavailable", "not_checked", "error"}
)


class SQLiteManagedFileRepository(ManagedFileRepositoryPort):
    """Typed C05 metadata adapter inside an existing SQLite Unit of Work."""

    def __init__(self, repository: SQLiteRepository):
        self._repository = repository

    def add(self, record: ManagedFileRecord) -> None:
        self._validate_record(record)
        created_at = record.created_at.isoformat()
        updated_at = record.updated_at.isoformat()
        self._repository._conn.execute(
            """
            INSERT INTO file_objects(
                id, kind, original_name, managed_name, source_relative_path,
                storage_reference, size_bytes, sha256, integrity_status,
                review_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_reviewed', ?, ?)
            """,
            (
                record.file_id,
                record.kind,
                record.original_name,
                record.managed_name,
                record.source_relative_path,
                record.storage_reference,
                record.bytes,
                record.sha256,
                record.integrity_status,
                created_at,
                updated_at,
            ),
        )
        self._repository._conn.execute(
            """
            INSERT INTO managed_storage_records(
                file_id, layout_version, storage_key, storage_reference,
                staging_reference, state, source_created_ns, source_modified_ns,
                last_error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.file_id,
                record.layout_version,
                record.storage_key,
                record.storage_reference,
                record.staging_reference,
                record.state,
                record.source_created_ns,
                record.source_modified_ns,
                record.last_error,
                created_at,
                updated_at,
            ),
        )
        self._repository._record_audit_event(
            "prepare_original",
            "file_objects",
            record.file_id,
            {
                "layout_version": record.layout_version,
                "bytes": record.bytes,
                "sha256": record.sha256,
                "state": record.state,
            },
        )

    def get(self, file_id: str) -> ManagedFileRecord | None:
        row = self._repository._conn.execute(self._select_sql() + " WHERE f.id = ?", (file_id,)).fetchone()
        return self._record(row) if row is not None else None

    def list(self) -> tuple[ManagedFileRecord, ...]:
        rows = self._repository._conn.execute(
            self._select_sql() + " ORDER BY m.created_at, f.id"
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    def find_by_sha256(self, sha256: str) -> tuple[str, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT f.id
            FROM file_objects AS f
            JOIN managed_storage_records AS m ON m.file_id = f.id
            WHERE f.sha256 = ?
            ORDER BY m.created_at, f.id
            """,
            (sha256,),
        ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def update_state(
        self,
        file_id: str,
        *,
        state: str,
        integrity_status: str,
        occurred_at: datetime,
        last_error: str | None = None,
    ) -> None:
        if state not in _STATES or integrity_status not in _INTEGRITY_STATUSES:
            raise ValueError("Некоректний managed storage/integrity state")
        occurred = occurred_at.isoformat()
        finalized_at = occurred if state in {"finalized", "verified"} else None
        verified_at = occurred if state == "verified" else None
        cursor = self._repository._conn.execute(
            """
            UPDATE managed_storage_records
            SET state = ?,
                finalized_at = COALESCE(finalized_at, ?),
                verified_at = COALESCE(verified_at, ?),
                last_error = ?,
                updated_at = ?
            WHERE file_id = ?
            """,
            (state, finalized_at, verified_at, last_error, occurred, file_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"managed file {file_id} не знайдено")
        self._repository._conn.execute(
            """
            UPDATE file_objects
            SET integrity_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (integrity_status, occurred, file_id),
        )
        self._repository._record_audit_event(
            "reconcile_original",
            "file_objects",
            file_id,
            {"state": state, "integrity_status": integrity_status, "error": last_error},
        )

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT
                f.id AS file_id,
                f.kind,
                f.original_name,
                f.managed_name,
                f.source_relative_path,
                f.size_bytes,
                f.sha256,
                f.integrity_status,
                m.layout_version,
                m.storage_key,
                m.storage_reference,
                m.staging_reference,
                m.source_created_ns,
                m.source_modified_ns,
                m.state,
                m.last_error,
                m.created_at,
                m.updated_at
            FROM file_objects AS f
            JOIN managed_storage_records AS m ON m.file_id = f.id
        """

    @staticmethod
    def _record(row: sqlite3.Row) -> ManagedFileRecord:
        return ManagedFileRecord(
            file_id=str(row["file_id"]),
            layout_version=int(row["layout_version"]),
            storage_key=str(row["storage_key"]),
            storage_reference=str(row["storage_reference"]),
            staging_reference=str(row["staging_reference"]),
            original_name=str(row["original_name"]),
            managed_name=str(row["managed_name"]) if row["managed_name"] is not None else None,
            source_relative_path=str(row["source_relative_path"]),
            kind=str(row["kind"]),
            bytes=int(row["size_bytes"]),
            sha256=str(row["sha256"]),
            source_created_ns=(
                int(row["source_created_ns"]) if row["source_created_ns"] is not None else None
            ),
            source_modified_ns=int(row["source_modified_ns"]),
            state=str(row["state"]),
            integrity_status=str(row["integrity_status"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        )

    @staticmethod
    def _validate_record(record: ManagedFileRecord) -> None:
        if record.state not in _STATES or record.integrity_status not in _INTEGRITY_STATUSES:
            raise ValueError("Некоректний managed storage record state")
        if record.bytes < 0 or len(record.sha256) != 64:
            raise ValueError("Managed file потребує non-negative bytes і SHA-256")
