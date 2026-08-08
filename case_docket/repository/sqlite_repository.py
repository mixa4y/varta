"""
case_docket.repository.sqlite_repository
===========================================
Основна реалізація Repository. SQLite — п.7 і п.9 оригінальних вимог
CSMD ("SQLite — основна локальна БД"; "Airtable не є частиною основної
архітектури"), підтверджено як Рек.8 в ADR-001.

СТАТУС: каркас Патча 0. Схема таблиць — чорнова (generic id/created_at/
payload-json), буде уточнена предметними полями по мірі реалізації
Патчів 2/4/5/7/8. Мета цього патча — довести, що Repository Layer
реально працює наскрізно (insert → get → update → audit log), а не
залишається абстракцією на папері.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .base import Repository

# Чорнова схема. Кожна таблиця: id (PK) + created_at + payload (JSON-блоб
# з рештою полів). Це свідомо мінімально на цьому етапі — фіксувати
# конкретні колонки зараз означало б передбачати рішення Патчів 2-8,
# які ще не ухвалені в деталях. payload дозволяє еволюціонувати поля
# без міграції схеми на кожному кроці; перехід на "тверді" колонки —
# окрема задача, коли модель кожної сутності стабілізується.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_files (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actors (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_links (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS compliance_flags (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_version_match (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
-- Audit Log: append-only, ніколи UPDATE/DELETE (п.11 CSMD; Рек.7 ADR-001).
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_table TEXT NOT NULL,
    entity_id TEXT,
    details TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
"""

_KNOWN_TABLES = {
    "documents", "document_files", "actors", "events",
    "document_links", "compliance_flags", "document_version_match",
}


class SQLiteRepository(Repository):
    def __init__(self, db_path: str | Path = "case_docket.sqlite3"):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _check_table(self, table: str) -> None:
        if table not in _KNOWN_TABLES:
            raise ValueError(f"Невідома таблиця '{table}'. Дозволені: {sorted(_KNOWN_TABLES)}")

    # --- generic record access ------------------------------------------------
    def insert(self, table: str, record: dict[str, Any]) -> str:
        self._check_table(table)
        record_id = record.get("id") or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        payload = {k: v for k, v in record.items() if k not in ("id", "created_at")}

        with self._conn:
            if table == "document_files":
                if "document_id" not in record:
                    raise ValueError("document_files: обов'язкове поле 'document_id' (Рек.1 ADR-001)")
                self._conn.execute(
                    "INSERT INTO document_files "
                    "(id, document_id, created_at, payload) VALUES (?, ?, ?, ?)",
                    (record_id, record["document_id"], now, json.dumps(payload, ensure_ascii=False)),
                )
            else:
                self._conn.execute(
                    f"INSERT INTO {table} (id, created_at, payload) VALUES (?, ?, ?)",
                    (record_id, now, json.dumps(payload, ensure_ascii=False)),
                )
            self._record_audit_event("insert", table, record_id, {"fields": sorted(payload)})
        return record_id

    def get(self, table: str, record_id: str) -> Optional[dict[str, Any]]:
        self._check_table(table)
        row = self._conn.execute(
            f"SELECT id, created_at, payload FROM {table} WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row["payload"])
        data["id"] = row["id"]
        data["created_at"] = row["created_at"]
        return data

    def update(self, table: str, record_id: str, fields: dict[str, Any]) -> None:
        self._check_table(table)
        current = self.get(table, record_id)
        if current is None:
            raise KeyError(f"{table}:{record_id} не знайдено")
        current.update(fields)
        current.pop("id", None)
        current.pop("created_at", None)
        payload_json = json.dumps(current, ensure_ascii=False)
        with self._conn:
            if table == "document_files" and "document_id" in fields:
                self._conn.execute(
                    "UPDATE document_files SET document_id = ?, payload = ? WHERE id = ?",
                    (fields["document_id"], payload_json, record_id),
                )
            else:
                self._conn.execute(
                    f"UPDATE {table} SET payload = ? WHERE id = ?",
                    (payload_json, record_id),
                )
            self._record_audit_event("update", table, record_id, {"fields": sorted(fields)})

    def query(self, table: str, where: Optional[dict[str, Any]] = None) -> Iterable[dict[str, Any]]:
        self._check_table(table)
        rows = self._conn.execute(f"SELECT id, created_at, payload FROM {table}").fetchall()
        for row in rows:
            data = json.loads(row["payload"])
            data["id"] = row["id"]
            data["created_at"] = row["created_at"]
            if where and any(data.get(k) != v for k, v in where.items()):
                continue
            yield data

    # --- audit log --------------------------------------------------------
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
        # Умисно НЕ через self.insert() — інакше запис у audit_log сам
        # породжував би новий запис у audit_log до нескінченності.
        self._conn.execute(
            "INSERT INTO audit_log (id, ts, action, entity_table, entity_id, details) "
            "VALUES (?, ?, ?, ?, ?, ?)",
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
        conditions, params = [], []
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
            item["details"] = json.loads(item["details"])
            yield item
