"""Offline local case input translated through the preserved SQL mapping.

No network, credentials, base identity or operating-system secret store is used.
Legacy field IDs are confined to the persistence compatibility boundary.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .airtable import LINK_SPECS, SCALAR_COLUMNS, TABLE_SQL_NAMES, load_airtable_schema
from .application.case_database_import_ports import CaseDatabaseSourceSnapshot


class LocalCaseSourceError(ValueError):
    pass


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def local_field_name(table: str, field: dict[str, Any]) -> str:
    link = LINK_SPECS.get(field["id"])
    if link is not None:
        return link.sql_target
    scalar = SCALAR_COLUMNS.get(field["id"])
    return scalar[1] if scalar and scalar[0] == table else str(field["name"])


def local_input_schema() -> dict[str, object]:
    """Expose SQL names and complete offline field metadata for local authoring."""
    catalog = load_airtable_schema()
    tables: dict[str, object] = {}
    for table in catalog["tables"]:
        name = TABLE_SQL_NAMES[table["id"]]
        fields = {local_field_name(name, field): field for field in table["fields"]}
        if len(fields) != len(table["fields"]):
            raise LocalCaseSourceError("Offline mapping contains ambiguous field names")
        tables[name] = fields
    if set(tables) != set(TABLE_SQL_NAMES.values()):
        raise LocalCaseSourceError("Offline table mapping is incomplete")
    return tables


class LocalCaseSource:
    """Read a local JSON manifest; capture/load detect edits through snapshot hashes."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def capture(self) -> CaseDatabaseSourceSnapshot:
        return self.load()

    def load(self) -> CaseDatabaseSourceSnapshot:
        raw = self.path.read_bytes()
        document = json.loads(raw)
        if self.path.read_bytes() != raw:
            raise LocalCaseSourceError("Local case input changed while reading")
        if (
            not isinstance(document, dict)
            or set(document) != {"formatVersion", "caseId", "tables"}
            or document["formatVersion"] != 1
        ):
            raise LocalCaseSourceError("Expected local case formatVersion, caseId and tables")
        selected = document["caseId"]
        supplied = document["tables"]
        if not isinstance(selected, str) or not selected.strip() or not isinstance(supplied, dict):
            raise LocalCaseSourceError("Local case identity/tables are invalid")
        definitions = local_input_schema()
        if set(supplied) - set(definitions):
            raise LocalCaseSourceError("Unknown local table; reconcile offline mapping first")
        tables: dict[str, dict[str, Any]] = {}
        ids: set[str] = set()
        selected_found = False
        catalog = load_airtable_schema()
        for table in catalog["tables"]:
            name = TABLE_SQL_NAMES[table["id"]]
            fields = {local_field_name(name, field): field for field in table["fields"]}
            records = supplied.get(name, [])
            if not isinstance(records, list):
                raise LocalCaseSourceError("Local table must be an array")
            converted = []
            for record in records:
                if not isinstance(record, dict) or set(record) != {"id", "fields"}:
                    raise LocalCaseSourceError("Local record must contain id and fields")
                identity, values = record["id"], record["fields"]
                if not isinstance(identity, str) or not identity.strip() or identity in ids:
                    raise LocalCaseSourceError("Empty or duplicate local record ID")
                ids.add(identity)
                if not isinstance(values, dict) or set(values) - set(fields):
                    raise LocalCaseSourceError("Unknown local field; reconcile mapping first")
                mapped: dict[str, object] = {}
                for key, value in values.items():
                    field = fields[key]
                    if field["type"] == "multipleAttachments" and (
                        not isinstance(value, list)
                        or any(
                            not isinstance(item, dict)
                            or not isinstance(item.get("id"), str)
                            or not item["id"].strip()
                            for item in value
                        )
                    ):
                        raise LocalCaseSourceError("Local attachments need explicit identities")
                    choices = field.get("config", {}).get("choices")
                    if choices is not None and value is not None:
                        allowed = {choice["name"] for choice in choices}
                        selected_values = value if isinstance(value, list) else [value]
                        if any(
                            not isinstance(item, str) or item not in allowed
                            for item in selected_values
                        ):
                            raise LocalCaseSourceError("Unknown choice; reconcile mapping first")
                    if field["type"] == "multipleRecordLinks" and (
                        not isinstance(value, list)
                        or any(not isinstance(item, str) or not item for item in value)
                    ):
                        raise LocalCaseSourceError("Local links must be arrays of record IDs")
                    mapped[field["id"]] = value
                converted.append({"id": identity, "fields": mapped})
                selected_found |= name == "cases" and identity == selected
            tables[table["id"]] = {"records": sorted(converted, key=lambda item: item["id"])}
        if not selected_found:
            raise LocalCaseSourceError("Selected local case is absent")
        # The applied persistence schema keeps historical mapping IDs; no remote data is read.
        schema = {"tables": catalog["tables"]}
        schema_hash = _hash(schema)
        payload = {
            "formatVersion": 1,
            "sourceKind": "local-case",
            "schema": schema,
            "schemaSha256": schema_hash,
            "catalogMappingSha256": _hash(catalog),
            "tables": tables,
            "paginationComplete": {key: True for key in tables},
            "selectedCaseRecordSha256": hashlib.sha256(selected.encode()).hexdigest(),
        }
        now = datetime.now(timezone.utc).isoformat()
        return CaseDatabaseSourceSnapshot(
            source_identity_sha256=_hash({"localCaseId": selected}),
            schema_sha256=schema_hash,
            snapshot_sha256=_hash(payload),
            captured_start=now,
            captured_end=now,
            table_counts={key: len(value["records"]) for key, value in tables.items()},
            payload=payload,
            selected_case_record_id=selected,
        )


def import_local_case(
    input_path: Path, corpus: Path, workspace: Path, backup: Path
) -> dict[str, object]:
    """Execute the local workflow, including durable restart/backup acceptance."""
    from .application.case_database_import import (
        CaseDatabaseImportService,
        ExecuteCaseDatabaseImportCommand,
        FinalizeCaseDatabaseImportCommand,
        PlanCaseDatabaseImportCommand,
        RecordCaseDatabaseVerificationCommand,
    )
    from .corpus_import import ManagedCorpusImporter
    from .corpus_inventory import FilesystemCorpusInventory
    from .repository.sqlite_case_database_import import SQLiteCaseDatabaseImportRepository
    from .runtime import build_intake_runtime

    corpus, workspace, backup = corpus.resolve(), workspace.resolve(), backup.resolve()
    if not corpus.is_dir():
        raise LocalCaseSourceError("Local corpus directory is absent")
    if workspace.is_relative_to(corpus) or corpus.is_relative_to(workspace):
        raise LocalCaseSourceError("Corpus and workspace must be separate directories")
    if backup.is_relative_to(corpus) or backup.exists():
        raise LocalCaseSourceError("Backup must be a new path outside originals")
    source = LocalCaseSource(input_path)
    source.capture()  # Validate user input before creating a workspace.
    database = build_intake_runtime(workspace).database_path
    repository = SQLiteCaseDatabaseImportRepository(database)

    class Clock:
        def now(self) -> datetime:
            return datetime.now(timezone.utc)

    clock = Clock()
    service = CaseDatabaseImportService(
        source,
        FilesystemCorpusInventory(corpus),
        ManagedCorpusImporter(corpus, workspace, database),
        repository,
        repository,
        clock,
    )
    plan = service.plan(PlanCaseDatabaseImportCommand("local-sql-v1"))
    service.execute(
        ExecuteCaseDatabaseImportCommand(
            plan.import_run_id,
            plan.snapshot_sha256,
            plan.corpus_manifest_sha256,
        )
    )
    verification = repository.verify_restart_and_backup(
        plan.import_run_id,
        backup,
        occurred_at=clock.now(),
    )
    if not verification.verified:
        raise LocalCaseSourceError("Local restart/backup verification failed")
    service.record_verification(
        RecordCaseDatabaseVerificationCommand(
            plan.import_run_id,
            verification.verification_sha256,
        )
    )
    report = service.finalize(FinalizeCaseDatabaseImportCommand(plan.import_run_id))
    return report.to_dict()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Локальний імпорт справи VARTA у SQLite")
    parser.add_argument("--schema", action="store_true", help="Показати offline поля і зв'язки")
    parser.add_argument("--input", type=Path, help="Локальний JSON опис справи")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--backup", type=Path, help="Новий файл для перевірки відновлення")
    args = parser.parse_args()
    if args.schema:
        print(json.dumps(local_input_schema(), ensure_ascii=False, indent=2))
    elif all((args.input, args.corpus, args.workspace, args.backup)):
        print(
            json.dumps(
                import_local_case(args.input, args.corpus, args.workspace, args.backup),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        parser.error("Потрібні --input, --corpus, --workspace, --backup або --schema")


if __name__ == "__main__":
    main()
