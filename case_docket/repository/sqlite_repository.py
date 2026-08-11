from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .base import Repository
from .migrations import MigrationRunner


_KNOWN_TABLES = {
    "cases",
    "proceedings",
    "contacts",
    "documents",
    "document_files",
    "actors",
    "events",
    "case_participants",
    "document_links",
    "compliance_flags",
    "document_version_match",
}

_LEGACY_CONFLICT_TABLES = (
    "document_files",
    "documents",
    "actors",
    "events",
    "document_links",
    "compliance_flags",
    "document_version_match",
)

_SYSTEM_COLUMNS = {
    "id",
    "airtable_record_id",
    "created_at",
    "updated_at",
    "legacy_payload",
}


class SQLiteRepository(Repository):
    def __init__(
        self,
        db_path: str | Path = "case_docket.sqlite3",
        *,
        migrations_path: Path | None = None,
    ):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._prepare_legacy_tables()
        MigrationRunner(self._conn, migrations_path).migrate()
        self._restore_legacy_records()

    def close(self) -> None:
        self._conn.close()

    def _check_table(self, table: str) -> None:
        if table not in _KNOWN_TABLES:
            raise ValueError(f"Невідома таблиця '{table}'. Дозволені: {sorted(_KNOWN_TABLES)}")

    def _table_columns(self, table: str) -> set[str]:
        return {
            str(row["name"])
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _table_exists(self, table: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            is not None
        )

    def _prepare_legacy_tables(self) -> None:
        if self._table_exists("schema_migrations"):
            return
        for table in _LEGACY_CONFLICT_TABLES:
            if not self._table_exists(table):
                continue
            columns = self._table_columns(table)
            if "payload" not in columns or "legacy_payload" in columns:
                continue
            legacy_table = f"legacy_generic_{table}"
            if self._table_exists(legacy_table):
                raise RuntimeError(
                    f"Одночасно існують {table} і {legacy_table}; автоматичну migration зупинено"
                )
            self._conn.execute(f"ALTER TABLE {table} RENAME TO {legacy_table}")
        self._conn.commit()

    def _restore_legacy_records(self) -> None:
        restored: dict[str, int] = {}
        table_columns = {
            "documents": ("title", "category"),
            "events": ("title",),
            "document_links": ("title", "link_type"),
            "compliance_flags": ("title", "flag_type", "severity", "detected_by"),
            "document_version_match": (
                "title",
                "hashes_equal",
                "text_similarity_score",
                "mismatch_type",
                "needs_review",
            ),
            "actors": (),
        }
        with self._conn:
            for table, copied_columns in table_columns.items():
                legacy_table = f"legacy_generic_{table}"
                if not self._table_exists(legacy_table):
                    continue
                count = 0
                rows = self._conn.execute(
                    f"SELECT id, created_at, payload FROM {legacy_table}"
                ).fetchall()
                for row in rows:
                    payload = self._decode_payload(row["payload"])
                    values: dict[str, Any] = {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "updated_at": row["created_at"],
                        "legacy_payload": json.dumps(payload, ensure_ascii=False),
                    }
                    for column in copied_columns:
                        if column in payload:
                            values[column] = self._sqlite_value(payload[column])
                    cursor = self._insert_or_ignore(table, values)
                    count += max(cursor.rowcount, 0)
                restored[table] = count

            legacy_files = "legacy_generic_document_files"
            if self._table_exists(legacy_files):
                count = 0
                rows = self._conn.execute(
                    f"SELECT id, document_id, created_at, payload FROM {legacy_files}"
                ).fetchall()
                for row in rows:
                    payload = self._decode_payload(row["payload"])
                    cursor = self._insert_or_ignore(
                        "document_files",
                        {
                            "id": row["id"],
                            "document_id": row["document_id"],
                            "created_at": row["created_at"],
                            "updated_at": row["created_at"],
                            "legacy_payload": json.dumps(payload, ensure_ascii=False),
                        },
                    )
                    count += max(cursor.rowcount, 0)
                restored["document_files"] = count

            for table, count in restored.items():
                if count:
                    self._record_audit_event(
                        "migrate_legacy",
                        table,
                        None,
                        {"records": count, "source": f"legacy_generic_{table}"},
                    )

    def _insert_or_ignore(
        self,
        table: str,
        values: dict[str, Any],
    ) -> sqlite3.Cursor:
        return self._conn.execute(
            f"INSERT OR IGNORE INTO {table} ({', '.join(values)}) "
            f"VALUES ({', '.join('?' for _ in values)})",
            list(values.values()),
        )

    # --- generic compatibility CRUD -----------------------------------------
    def insert(self, table: str, record: dict[str, Any]) -> str:
        self._check_table(table)
        record_id = str(record.get("id") or uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        payload = {key: value for key, value in record.items() if key not in {"id", "created_at"}}
        columns = self._table_columns(table)
        values: dict[str, Any] = {
            "id": record_id,
            "created_at": now,
            "updated_at": now,
            "legacy_payload": json.dumps(payload, ensure_ascii=False),
        }
        for key, value in payload.items():
            if key in columns and key not in _SYSTEM_COLUMNS:
                values[key] = self._sqlite_value(value)
        if table == "document_files" and not record.get("document_id"):
            raise ValueError("document_files: обов'язкове поле 'document_id'")
        with self._conn:
            self._conn.execute(
                f"INSERT INTO {table} ({', '.join(values)}) "
                f"VALUES ({', '.join('?' for _ in values)})",
                list(values.values()),
            )
            self._record_audit_event("insert", table, record_id, {"fields": sorted(payload)})
        return record_id

    def get(self, table: str, record_id: str) -> Optional[dict[str, Any]]:
        self._check_table(table)
        row = self._conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return None
        item = self._decode_payload(row["legacy_payload"])
        for key in row.keys():
            if key in _SYSTEM_COLUMNS or key == "legacy_payload":
                continue
            if row[key] is not None:
                item[key] = row[key]
        item["id"] = row["id"]
        item["created_at"] = row["created_at"]
        return item

    def update(self, table: str, record_id: str, fields: dict[str, Any]) -> None:
        self._check_table(table)
        current = self.get(table, record_id)
        if current is None:
            raise KeyError(f"{table}:{record_id} не знайдено")
        current.update(fields)
        payload = {
            key: value for key, value in current.items() if key not in {"id", "created_at"}
        }
        columns = self._table_columns(table)
        updates: dict[str, Any] = {
            "legacy_payload": json.dumps(payload, ensure_ascii=False),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for key, value in fields.items():
            if key in columns and key not in _SYSTEM_COLUMNS:
                updates[key] = self._sqlite_value(value)
        assignments = ", ".join(f"{column} = ?" for column in updates)
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                [*updates.values(), record_id],
            )
            if cursor.rowcount == 0:
                raise KeyError(f"{table}:{record_id} не знайдено")
            self._record_audit_event("update", table, record_id, {"fields": sorted(fields)})

    def query(
        self,
        table: str,
        where: Optional[dict[str, Any]] = None,
    ) -> Iterable[dict[str, Any]]:
        self._check_table(table)
        for row in self._conn.execute(f"SELECT id FROM {table} ORDER BY created_at").fetchall():
            item = self.get(table, str(row["id"]))
            assert item is not None
            if where and any(item.get(key) != value for key, value in where.items()):
                continue
            yield item

    # --- audit log ------------------------------------------------------------
    def record_audit_event(
        self,
        action: str,
        entity_table: str,
        entity_id: Optional[str],
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._conn:
            self._record_audit_event(action, entity_table, entity_id, details)

    def _record_audit_event(
        self,
        action: str,
        entity_table: str,
        entity_id: Optional[str],
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_log(id, ts, action, entity_table, entity_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                datetime.now(timezone.utc).isoformat(),
                action,
                entity_table,
                entity_id,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )

    def get_audit_log(
        self,
        entity_table: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> Iterable[dict[str, Any]]:
        query = "SELECT * FROM audit_log"
        conditions: list[str] = []
        params: list[str] = []
        if entity_table:
            conditions.append("entity_table = ?")
            params.append(entity_table)
        if entity_id:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY ts ASC"
        for row in self._conn.execute(query, params).fetchall():
            item = dict(row)
            item["details"] = self._decode_payload(item.get("details"))
            yield item

    @staticmethod
    def _decode_payload(value: Any) -> dict[str, Any]:
        if not value:
            return {}
        if isinstance(value, dict):
            return dict(value)
        decoded = json.loads(str(value))
        return decoded if isinstance(decoded, dict) else {"value": decoded}

    @staticmethod
    def _sqlite_value(value: Any) -> Any:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value
