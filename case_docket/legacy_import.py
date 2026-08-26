"""Read-only legacy XLSX/.caseflow adapter with dry-run and idempotent import."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


@dataclass(frozen=True)
class LegacyImportReport:
    source_kind: str
    source_name: str
    source_sha256: str
    records: int
    proposed: int
    imported: int
    skipped: int
    conflicts: int
    unresolved_links: int
    issues: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "issues": list(self.issues)}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _xlsx(path: Path) -> list[dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=False)
    rows: list[dict[str, Any]] = []
    for sheet in workbook.worksheets:
        values = list(sheet.iter_rows(values_only=True))
        if not values:
            continue
        headers = [str(value).strip() if value is not None else "" for value in values[0]]
        for number, values_row in enumerate(values[1:], 2):
            payload = {header: value for header, value in zip(headers, values_row) if header}
            if any(value not in (None, "") for value in payload.values()):
                rows.append({"record_kind": "xlsx_row", "external_ref": f"{sheet.title}!{number}", "payload": payload})
    return rows


def _caseflow(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("records", payload.get("items", [payload]))
    else:
        raise ValueError(".caseflow має містити JSON object або array")
    result = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            result.append({"record_kind": "caseflow_item", "external_ref": str(index), "payload": {"value": item}})
            continue
        external = str(item.get("id", item.get("external_id", index)))
        result.append({"record_kind": "caseflow_record", "external_ref": external, "payload": item})
    return result


def read_legacy(path: Path) -> tuple[str, list[dict[str, Any]]]:
    suffix = path.suffix.casefold()
    if suffix == ".xlsx":
        return "xlsx", _xlsx(path)
    if suffix == ".caseflow":
        return "caseflow", _caseflow(path)
    raise ValueError("Підтримуються лише .xlsx і .caseflow")


def dry_run(path: Path) -> LegacyImportReport:
    kind, records = read_legacy(path)
    digest = _hash(path)
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        external = record["external_ref"]
        if external in seen:
            issues.append({"external_ref": external, "reason": "duplicate_external_ref", "action": "manual_review_required"})
        seen.add(external)
    return LegacyImportReport(kind, path.name, digest, len(records), len(records) - len(issues), 0, 0, len(issues), 0, tuple(issues))


def import_legacy(
    connection: sqlite3.Connection,
    path: Path,
    *,
    backup_destination: Path,
    actor: str = "system:legacy-import",
) -> LegacyImportReport:
    path = path.resolve()
    backup_destination = backup_destination.resolve()
    if not backup_destination.is_dir() or path.parent == backup_destination or path.is_relative_to(backup_destination):
        raise ValueError("Потрібен verified backup destination directory поза legacy source")
    kind, records = read_legacy(path)
    digest = _hash(path)
    report = dry_run(path)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    imported = skipped = 0
    with connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS legacy_import_runs (
                id TEXT PRIMARY KEY, source_kind TEXT NOT NULL, source_name TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, mode TEXT NOT NULL,
                report_json TEXT NOT NULL CHECK (json_valid(report_json)), created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS legacy_import_records (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES legacy_import_runs(id),
                source_kind TEXT NOT NULL, source_sha256 TEXT NOT NULL, external_ref TEXT NOT NULL,
                record_kind TEXT NOT NULL, payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                status TEXT NOT NULL, UNIQUE(source_kind, source_sha256, external_ref)
            );
            CREATE INDEX IF NOT EXISTS ix_legacy_import_records_run ON legacy_import_records(run_id);
            """
        )
        connection.execute("INSERT INTO legacy_import_runs VALUES (?, ?, ?, ?, ?, ?, ?)", (run_id, kind, path.name, digest, "import", json.dumps(report.to_dict(), ensure_ascii=False), now))
        for record in records:
            existing = connection.execute("SELECT 1 FROM legacy_import_records WHERE source_kind=? AND source_sha256=? AND external_ref=?", (kind, digest, record["external_ref"])).fetchone()
            if existing:
                skipped += 1
                continue
            status = "manual_review_required" if any(i["external_ref"] == record["external_ref"] for i in report.issues) else "imported"
            connection.execute("INSERT INTO legacy_import_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), run_id, kind, digest, record["external_ref"], record["record_kind"], json.dumps(record["payload"], ensure_ascii=False, default=str), status))
            imported += 1
    return LegacyImportReport(kind, path.name, digest, len(records), report.proposed, imported, skipped, report.conflicts, report.unresolved_links, report.issues)
