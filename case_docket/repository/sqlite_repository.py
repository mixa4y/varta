from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from case_docket.airtable import (
    AirtableImportSummary,
    import_airtable_snapshot,
    install_airtable_catalog,
)
from case_docket.models.contact import Contact

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
        airtable_schema_path: Path | None = None,
        migrations_path: Path | None = None,
        auto_commit: bool = True,
    ):
        self.db_path = Path(db_path)
        self._auto_commit = auto_commit
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._prepare_legacy_tables()
        MigrationRunner(self._conn, migrations_path).migrate()
        install_airtable_catalog(self._conn, airtable_schema_path)
        self._restore_legacy_records()

    def close(self) -> None:
        self._conn.close()

    def begin(self) -> None:
        if self._conn.in_transaction:
            raise RuntimeError("SQLite transaction already active")
        self._conn.execute("BEGIN")

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def _write_scope(self):
        return self._conn if self._auto_commit else nullcontext()

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
        if table == "contacts":
            if not str(record.get("full_name") or "").strip():
                raise ValueError("contacts.full_name є обов'язковим")
            participant_type = record.get("participant_type")
            if participant_type not in {"person", "organization"}:
                raise ValueError("contacts.participant_type має бути person або organization")
        with self._write_scope():
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
        with self._write_scope():
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

    # --- contacts ------------------------------------------------------------
    def create_contact(self, record: dict[str, Any]) -> str:
        validated = self._validate_contact(record)
        return self.insert("contacts", validated)

    def get_contact(self, contact_id: str) -> Optional[dict[str, Any]]:
        item = self.get("contacts", contact_id)
        if item is not None:
            item["roles"] = self.list_contact_roles(contact_id)
        return item

    def list_contacts(self, search: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id FROM contacts"
        params: list[Any] = []
        if search:
            sql += (
                " WHERE full_name LIKE ? OR short_name LIKE ? OR email LIKE ? "
                "OR phone LIKE ? OR additional_phone LIKE ?"
            )
            needle = f"%{search}%"
            params = [needle] * 5
        sql += " ORDER BY full_name COLLATE NOCASE"
        contacts: list[dict[str, Any]] = []
        for row in self._conn.execute(sql, params).fetchall():
            item = self.get_contact(str(row["id"]))
            assert item is not None
            contacts.append(item)
        return contacts

    def update_contact(self, contact_id: str, fields: dict[str, Any]) -> None:
        allowed = self._table_columns("contacts") - _SYSTEM_COLUMNS
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Невідомі contact fields: {sorted(unknown)}")
        current = self.get("contacts", contact_id)
        if current is None:
            raise KeyError(f"contacts:{contact_id} не знайдено")
        merged = {key: current.get(key) for key in allowed}
        merged.update(fields)
        validated = self._validate_contact({"id": contact_id, **merged})
        self.update("contacts", contact_id, validated)

    def contacts_context(self) -> dict[str, Any]:
        cases = [
            dict(row)
            for row in self._conn.execute(
                "SELECT id, case_number, name FROM cases ORDER BY case_number, name"
            ).fetchall()
        ]
        proceedings = [
            dict(row)
            for row in self._conn.execute(
                """
                SELECT
                    p.id,
                    p.proceeding_number,
                    p.name,
                    GROUP_CONCAT(cp.case_id) AS case_ids
                FROM proceedings AS p
                LEFT JOIN case_proceedings AS cp ON cp.proceeding_id = p.id
                GROUP BY p.id
                ORDER BY p.proceeding_number, p.name
                """
            ).fetchall()
        ]
        for proceeding in proceedings:
            raw_case_ids = proceeding.pop("case_ids", None)
            proceeding["caseIds"] = raw_case_ids.split(",") if raw_case_ids else []
        roles = [
            str(row["choice_name"])
            for row in self._conn.execute(
                """
                SELECT choice_name
                FROM airtable_select_choices
                WHERE airtable_field_id = 'fldnQfVMsMWOXwJRV'
                ORDER BY position
                """
            ).fetchall()
        ]
        return {"cases": cases, "proceedings": proceedings, "roles": roles}

    def assign_contact_role(self, record: dict[str, Any]) -> str:
        required = ("contact_id", "case_id", "role")
        if any(not record.get(field) for field in required):
            raise ValueError("case_participants потребує contact_id, case_id і role")
        participant_id = str(record.get("id") or uuid.uuid4())
        now = str(record.get("created_at") or datetime.now(timezone.utc).isoformat())
        values = {
            "id": participant_id,
            "contact_id": record["contact_id"],
            "case_id": record["case_id"],
            "proceeding_id": record.get("proceeding_id"),
            "role": record["role"],
            "active": int(record.get("active", True)),
            "notes": record.get("notes"),
            "created_at": now,
            "updated_at": now,
            "legacy_payload": "{}",
        }
        with self._write_scope():
            self._conn.execute(
                f"INSERT INTO case_participants ({', '.join(values)}) "
                f"VALUES ({', '.join('?' for _ in values)})",
                list(values.values()),
            )
            self._record_audit_event(
                "assign_role",
                "contacts",
                str(record["contact_id"]),
                {
                    "case_id": record["case_id"],
                    "proceeding_id": record.get("proceeding_id"),
                    "role": record["role"],
                },
            )
        return participant_id

    def list_contact_roles(self, contact_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, case_id, proceeding_id, role, active, notes, created_at
            FROM case_participants
            WHERE contact_id = ?
            ORDER BY created_at
            """,
            (contact_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    # --- Airtable migration adapter ------------------------------------------
    def import_airtable_snapshot(self, snapshot: dict[str, Any]) -> AirtableImportSummary:
        return import_airtable_snapshot(self._conn, snapshot, self._record_audit_event)

    def airtable_catalog_counts(self) -> dict[str, int]:
        return {
            "tables": int(
                self._conn.execute("SELECT COUNT(*) FROM airtable_table_mappings").fetchone()[0]
            ),
            "fields": int(
                self._conn.execute("SELECT COUNT(*) FROM airtable_field_mappings").fetchone()[0]
            ),
            "relations": int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM airtable_relationship_mappings"
                ).fetchone()[0]
            ),
            "computed": int(
                self._conn.execute(
                    """
                    SELECT COUNT(*) FROM airtable_field_mappings
                    WHERE sql_kind IN ('lookup', 'formula')
                    """
                ).fetchone()[0]
            ),
        }

    @staticmethod
    def _validate_contact(record: dict[str, Any]) -> dict[str, object]:
        raw_date = record.get("birth_or_registration_date")
        parsed_date = date.fromisoformat(str(raw_date)) if raw_date else None
        model = Contact(
            id=str(record.get("id") or uuid.uuid4()),
            full_name=str(record.get("full_name") or ""),
            participant_type=str(record.get("participant_type") or ""),
            short_name=record.get("short_name"),
            active=bool(record.get("active", True)),
            email=record.get("email"),
            phone=record.get("phone"),
            additional_phone=record.get("additional_phone"),
            address=record.get("address"),
            tax_id=record.get("tax_id"),
            edrpou=record.get("edrpou"),
            birth_or_registration_date=parsed_date,
            representative_or_contact_person=record.get("representative_or_contact_person"),
            notes=record.get("notes"),
        )
        return model.to_record()

    # --- audit log ------------------------------------------------------------
    def record_audit_event(
        self,
        action: str,
        entity_table: str,
        entity_id: Optional[str],
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._write_scope():
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
