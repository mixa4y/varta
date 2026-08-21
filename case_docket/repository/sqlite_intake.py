from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from case_docket.application.ports import (
    ImportBatchRecord,
    IntakeContextRecord,
    IntakeEntryRecord,
    IntakeRepositoryPort,
)

from .sqlite_repository import SQLiteRepository


_BATCH_STATUSES = frozenset({"enumerating", "processing", "succeeded", "partial", "failed"})
_TERMINAL_BATCH_STATUSES = frozenset({"succeeded", "partial", "failed"})
_DETECTED_KINDS = frozenset({"file", "folder", "zip"})
_ENTRY_STATUSES = frozenset({"discovered", "accepted", "duplicate", "failed", "skipped"})


class SQLiteIntakeRepository(IntakeRepositoryPort):
    """SQLite-backed C06 batch, entry, provenance and status-history adapter."""

    def __init__(self, repository: SQLiteRepository):
        self._repository = repository

    def create_batch(
        self,
        context: IntakeContextRecord,
        batch: ImportBatchRecord,
    ) -> None:
        if context.context_id != batch.context_id:
            raise ValueError("Intake context і import batch мають узгоджені IDs")
        if context.status != "enumerating" or batch.status != "enumerating":
            raise ValueError("Новий intake batch має починатися зі status enumerating")
        if context.completed_at is not None or batch.completed_at is not None:
            raise ValueError("Новий intake batch не може бути completed")
        created_at = batch.created_at.isoformat()
        self._repository._conn.execute(
            """
            INSERT INTO intake_contexts(
                id, status, last_error_code, last_error_message,
                created_at, updated_at, completed_at
            )
            VALUES (?, 'enumerating', NULL, NULL, ?, ?, NULL)
            """,
            (context.context_id, context.created_at.isoformat(), context.updated_at.isoformat()),
        )
        self._repository._conn.execute(
            """
            INSERT INTO import_batches(
                id, intake_context_id, idempotency_key, request_fingerprint,
                source_uri, requested_kind, detected_kind, status,
                last_error_code, last_error_message, created_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, 'enumerating', NULL, NULL, ?, ?, NULL)
            """,
            (
                batch.batch_id,
                batch.context_id,
                batch.idempotency_key,
                batch.request_fingerprint,
                batch.source_uri,
                batch.requested_kind,
                created_at,
                batch.updated_at.isoformat(),
            ),
        )
        self._repository._conn.execute(
            """
            INSERT INTO import_batch_status_history(
                import_batch_id, from_status, to_status, error_code, error_message, occurred_at
            )
            VALUES (?, NULL, 'enumerating', NULL, NULL, ?)
            """,
            (batch.batch_id, created_at),
        )
        self._repository._record_audit_event(
            "create_import_batch",
            "import_batches",
            batch.batch_id,
            {"status": "enumerating", "requested_kind": batch.requested_kind},
        )

    def get_batch(self, batch_id: str) -> ImportBatchRecord | None:
        row = self._repository._conn.execute(
            self._batch_select() + " WHERE id = ?",
            (batch_id,),
        ).fetchone()
        return self._batch(row) if row is not None else None

    def get_batch_by_idempotency_key(self, key: str) -> ImportBatchRecord | None:
        row = self._repository._conn.execute(
            self._batch_select() + " WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        return self._batch(row) if row is not None else None

    def list_batches(self) -> tuple[ImportBatchRecord, ...]:
        rows = self._repository._conn.execute(
            self._batch_select() + " ORDER BY created_at, id"
        ).fetchall()
        return tuple(self._batch(row) for row in rows)

    def set_detected_kind(
        self,
        batch_id: str,
        *,
        detected_kind: str,
        occurred_at: datetime,
    ) -> None:
        if detected_kind not in _DETECTED_KINDS:
            raise ValueError("Некоректний detected intake kind")
        cursor = self._repository._conn.execute(
            """
            UPDATE import_batches
            SET detected_kind = ?, updated_at = ?
            WHERE id = ? AND status = 'enumerating' AND detected_kind IS NULL
            """,
            (detected_kind, occurred_at.isoformat(), batch_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"import batch {batch_id} не знайдено або вже класифіковано")

    def set_batch_status(
        self,
        batch_id: str,
        *,
        status: str,
        occurred_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in _BATCH_STATUSES or status == "enumerating":
            raise ValueError("Некоректний next import batch status")
        row = self._repository._conn.execute(
            "SELECT intake_context_id, status FROM import_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"import batch {batch_id} не знайдено")
        previous = str(row["status"])
        allowed = {
            "enumerating": {"processing", "failed"},
            "processing": _TERMINAL_BATCH_STATUSES,
        }.get(previous, frozenset())
        if status not in allowed:
            raise ValueError(f"Некоректний import batch transition {previous} -> {status}")
        occurred = occurred_at.isoformat()
        completed_at = occurred if status in _TERMINAL_BATCH_STATUSES else None
        self._repository._conn.execute(
            """
            UPDATE import_batches
            SET status = ?, last_error_code = ?, last_error_message = ?,
                updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (status, error_code, error_message, occurred, completed_at, batch_id),
        )
        self._repository._conn.execute(
            """
            UPDATE intake_contexts
            SET status = ?, last_error_code = ?, last_error_message = ?,
                updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                status,
                error_code,
                error_message,
                occurred,
                completed_at,
                str(row["intake_context_id"]),
            ),
        )
        self._repository._conn.execute(
            """
            INSERT INTO import_batch_status_history(
                import_batch_id, from_status, to_status, error_code, error_message, occurred_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (batch_id, previous, status, error_code, error_message, occurred),
        )
        self._repository._record_audit_event(
            "transition_import_batch",
            "import_batches",
            batch_id,
            {"from": previous, "to": status, "error_code": error_code},
        )

    def add_entry(self, entry: IntakeEntryRecord) -> None:
        if entry.status != "discovered" or entry.file_id is not None:
            raise ValueError("Новий intake entry має починатися як discovered без file_id")
        if entry.duplicate_of_file_ids or entry.error_code is not None:
            raise ValueError("Discovered intake entry не може мати final result")
        created = entry.created_at.isoformat()
        self._repository._conn.execute(
            """
            INSERT INTO intake_entries(
                id, import_batch_id, ordinal, source_uri, source_relative_path,
                literal_name, entry_kind, status, size_bytes, source_created_at,
                source_modified_at, extension, media_type, type_hint, file_id,
                duplicate_of_file_ids_json, warning_code, warning_message,
                error_code, error_message, created_at, updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, 'discovered', ?, ?, ?, ?, ?, ?, NULL,
                '[]', NULL, NULL, NULL, NULL, ?, ?
            )
            """,
            (
                entry.entry_id,
                entry.batch_id,
                entry.ordinal,
                entry.source_uri,
                entry.source_relative_path,
                entry.literal_name,
                entry.entry_kind,
                entry.size_bytes,
                entry.source_created_at,
                entry.source_modified_at,
                entry.extension,
                entry.media_type,
                entry.type_hint,
                created,
                entry.updated_at.isoformat(),
            ),
        )
        self._repository._conn.execute(
            """
            INSERT INTO intake_entry_status_history(
                intake_entry_id, from_status, to_status, error_code, error_message, occurred_at
            )
            VALUES (?, NULL, 'discovered', NULL, NULL, ?)
            """,
            (entry.entry_id, created),
        )
        self._repository._record_audit_event(
            "discover_intake_entry",
            "intake_entries",
            entry.entry_id,
            {"batch_id": entry.batch_id, "ordinal": entry.ordinal},
        )

    def transition_entry(
        self,
        entry_id: str,
        *,
        status: str,
        occurred_at: datetime,
        file_id: str | None = None,
        duplicate_of_file_ids: tuple[str, ...] = (),
        warning_code: str | None = None,
        warning_message: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in _ENTRY_STATUSES or status == "discovered":
            raise ValueError("Некоректний final intake entry status")
        if status in {"accepted", "duplicate"} and file_id is None:
            raise ValueError("Accepted/duplicate intake entry потребує file_id")
        if status not in {"accepted", "duplicate"} and file_id is not None:
            raise ValueError("Failed/skipped intake entry не може посилатися на file_id")
        if status == "duplicate" and not duplicate_of_file_ids:
            raise ValueError("Duplicate intake entry потребує duplicate references")
        if status != "duplicate" and duplicate_of_file_ids:
            raise ValueError("Duplicate references дозволені лише для duplicate status")
        if status in {"failed", "skipped"} and error_code is None:
            raise ValueError("Failed/skipped intake entry потребує error_code")
        if status not in {"failed", "skipped"} and error_code is not None:
            raise ValueError("Accepted/duplicate intake entry не може мати error_code")

        row = self._repository._conn.execute(
            "SELECT import_batch_id, status FROM intake_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"intake entry {entry_id} не знайдено")
        previous = str(row["status"])
        if previous != "discovered":
            raise ValueError(f"Intake entry already terminal: {previous}")

        batch_id = str(row["import_batch_id"])
        if file_id is not None:
            cursor = self._repository._conn.execute(
                """
                UPDATE file_objects
                SET import_batch_id = ?
                WHERE id = ? AND (import_batch_id IS NULL OR import_batch_id = ?)
                """,
                (batch_id, file_id, batch_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"managed file {file_id} не знайдено або належить іншому batch")

        occurred = occurred_at.isoformat()
        self._repository._conn.execute(
            """
            UPDATE intake_entries
            SET status = ?, file_id = ?, duplicate_of_file_ids_json = ?,
                warning_code = ?, warning_message = ?, error_code = ?,
                error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                file_id,
                json.dumps(duplicate_of_file_ids, ensure_ascii=False, separators=(",", ":")),
                warning_code,
                warning_message,
                error_code,
                error_message,
                occurred,
                entry_id,
            ),
        )
        self._repository._conn.execute(
            """
            INSERT INTO intake_entry_status_history(
                intake_entry_id, from_status, to_status, error_code, error_message, occurred_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_id, previous, status, error_code, error_message, occurred),
        )
        self._repository._record_audit_event(
            "transition_intake_entry",
            "intake_entries",
            entry_id,
            {"from": previous, "to": status, "error_code": error_code},
        )

    def list_entries(self, batch_id: str) -> tuple[IntakeEntryRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT
                e.id AS entry_id,
                e.import_batch_id,
                e.ordinal,
                e.source_uri,
                e.source_relative_path,
                e.literal_name,
                e.entry_kind,
                e.status,
                e.size_bytes,
                e.source_created_at,
                e.source_modified_at,
                e.extension,
                e.media_type,
                e.type_hint,
                e.file_id,
                e.duplicate_of_file_ids_json,
                e.warning_code,
                e.warning_message,
                e.error_code,
                e.error_message,
                f.sha256,
                m.storage_reference,
                e.created_at,
                e.updated_at
            FROM intake_entries AS e
            LEFT JOIN file_objects AS f ON f.id = e.file_id
            LEFT JOIN managed_storage_records AS m ON m.file_id = e.file_id
            WHERE e.import_batch_id = ?
            ORDER BY e.ordinal, e.id
            """,
            (batch_id,),
        ).fetchall()
        return tuple(self._entry(row) for row in rows)

    @staticmethod
    def _batch_select() -> str:
        return """
            SELECT
                id, intake_context_id, idempotency_key, request_fingerprint,
                source_uri, requested_kind, detected_kind, status,
                last_error_code, last_error_message, created_at, updated_at, completed_at
            FROM import_batches
        """

    @staticmethod
    def _batch(row: sqlite3.Row) -> ImportBatchRecord:
        return ImportBatchRecord(
            batch_id=str(row["id"]),
            context_id=str(row["intake_context_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request_fingerprint=str(row["request_fingerprint"]),
            source_uri=str(row["source_uri"]),
            requested_kind=str(row["requested_kind"]),
            detected_kind=(str(row["detected_kind"]) if row["detected_kind"] is not None else None),
            status=str(row["status"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            completed_at=(
                datetime.fromisoformat(str(row["completed_at"]))
                if row["completed_at"] is not None
                else None
            ),
            last_error_code=(
                str(row["last_error_code"]) if row["last_error_code"] is not None else None
            ),
            last_error_message=(
                str(row["last_error_message"])
                if row["last_error_message"] is not None
                else None
            ),
        )

    @staticmethod
    def _entry(row: sqlite3.Row) -> IntakeEntryRecord:
        raw_duplicates = json.loads(str(row["duplicate_of_file_ids_json"]))
        if not isinstance(raw_duplicates, list) or not all(
            isinstance(item, str) for item in raw_duplicates
        ):
            raise ValueError("SQLite intake duplicate references мають бути string array")
        return IntakeEntryRecord(
            entry_id=str(row["entry_id"]),
            batch_id=str(row["import_batch_id"]),
            ordinal=int(row["ordinal"]),
            source_uri=str(row["source_uri"]),
            source_relative_path=str(row["source_relative_path"]),
            literal_name=str(row["literal_name"]),
            entry_kind=str(row["entry_kind"]),
            status=str(row["status"]),
            size_bytes=int(row["size_bytes"]) if row["size_bytes"] is not None else None,
            source_created_at=(
                str(row["source_created_at"]) if row["source_created_at"] is not None else None
            ),
            source_modified_at=(
                str(row["source_modified_at"])
                if row["source_modified_at"] is not None
                else None
            ),
            extension=str(row["extension"]) if row["extension"] is not None else None,
            media_type=str(row["media_type"]) if row["media_type"] is not None else None,
            type_hint=str(row["type_hint"]) if row["type_hint"] is not None else None,
            file_id=str(row["file_id"]) if row["file_id"] is not None else None,
            duplicate_of_file_ids=tuple(raw_duplicates),
            warning_code=(str(row["warning_code"]) if row["warning_code"] is not None else None),
            warning_message=(
                str(row["warning_message"]) if row["warning_message"] is not None else None
            ),
            error_code=str(row["error_code"]) if row["error_code"] is not None else None,
            error_message=(
                str(row["error_message"]) if row["error_message"] is not None else None
            ),
            sha256=str(row["sha256"]) if row["sha256"] is not None else None,
            storage_reference=(
                str(row["storage_reference"]) if row["storage_reference"] is not None else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
