from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime

from case_docket.application.evidence_map_export import (
    EvidenceMapExportAudit,
    EvidenceMapExportAuditError,
    RecordEvidenceMapExportCommand,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROFILES = {"full_local", "redacted", "metadata_only"}


class SQLiteEvidenceMapExportRepository:
    def __init__(self, repository):
        self._repository = repository

    def record_validated(self, command: RecordEvidenceMapExportCommand) -> EvidenceMapExportAudit:
        self._validate(command)
        self._validate_profile_scope(command)
        expected = self._from_command(command)
        row = self._repository._conn.execute(
            "SELECT * FROM evidence_map_exports WHERE id = ?", (command.export_id,)
        ).fetchone()
        if row is not None:
            existing = self._to_audit(row)
            if existing.source_snapshot_sha256 != command.source_snapshot_sha256:
                raise EvidenceMapExportAuditError("export ID already exists with another hash")
            if existing != expected:
                raise EvidenceMapExportAuditError(
                    "export ID already exists with different audit metadata"
                )
            return existing
        limitations_json = json.dumps(
            list(command.limitations), ensure_ascii=False, separators=(",", ":")
        )
        try:
            self._repository._conn.execute(
                """INSERT INTO evidence_map_exports
                (id, case_id, case_profile_id, schema_version, product_version,
                 export_profile, source_revision, source_snapshot_sha256, status,
                 sealed, generated_by, generated_at, data_cutoff, limitations_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'valid', ?, ?, ?, ?, ?)""",
                (
                    command.export_id,
                    command.case_id,
                    command.case_profile_id,
                    command.schema_version,
                    command.product_version,
                    command.export_profile,
                    command.source_revision,
                    command.source_snapshot_sha256,
                    int(command.sealed),
                    command.generated_by,
                    command.generated_at,
                    command.data_cutoff,
                    limitations_json,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise EvidenceMapExportAuditError(
                "evidence map export audit integrity conflict"
            ) from exc
        stored = self.get(command.export_id)
        if stored is None:
            raise EvidenceMapExportAuditError("evidence map export audit was not stored")
        return stored

    def get(self, export_id: str) -> EvidenceMapExportAudit | None:
        row = self._repository._conn.execute(
            "SELECT * FROM evidence_map_exports WHERE id = ?", (export_id,)
        ).fetchone()
        return self._to_audit(row) if row is not None else None

    @staticmethod
    def _validate(c: RecordEvidenceMapExportCommand) -> None:
        if c.status != "valid":
            raise EvidenceMapExportAuditError("only valid export audits may be recorded")
        if c.export_profile not in _PROFILES:
            raise EvidenceMapExportAuditError("invalid export profile")
        if not _SHA256.fullmatch(c.source_snapshot_sha256):
            raise EvidenceMapExportAuditError("source snapshot hash must be lowercase SHA-256")
        if c.source_revision is None or not _SHA256.fullmatch(c.source_revision):
            raise EvidenceMapExportAuditError("source revision must be lowercase SHA-256")
        required = (
            c.export_id,
            c.case_id,
            c.case_profile_id,
            c.schema_version,
            c.product_version,
            c.generated_by,
            c.generated_at,
        )
        if not all(isinstance(value, str) and value.strip() for value in required):
            raise EvidenceMapExportAuditError("required export audit field is empty")
        if not all(isinstance(value, str) for value in c.limitations):
            raise EvidenceMapExportAuditError("export limitations must be strings")
        SQLiteEvidenceMapExportRepository._validate_timestamp(c.generated_at, "generated_at")
        if c.data_cutoff is not None:
            SQLiteEvidenceMapExportRepository._validate_timestamp(c.data_cutoff, "data_cutoff")

    def _validate_profile_scope(self, command: RecordEvidenceMapExportCommand) -> None:
        row = self._repository._conn.execute(
            "SELECT case_id, schema_version FROM case_profiles WHERE id = ?",
            (command.case_profile_id,),
        ).fetchone()
        if row is None:
            raise EvidenceMapExportAuditError("case profile does not exist")
        if row["case_id"] != command.case_id:
            raise EvidenceMapExportAuditError("case profile belongs to another case")
        if row["schema_version"] != command.schema_version:
            raise EvidenceMapExportAuditError("case profile schema version does not match export")

    @staticmethod
    def _validate_timestamp(value: str, field: str) -> None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceMapExportAuditError(f"{field} must be an ISO 8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise EvidenceMapExportAuditError(f"{field} must include a timezone")

    @staticmethod
    def _from_command(command: RecordEvidenceMapExportCommand) -> EvidenceMapExportAudit:
        return EvidenceMapExportAudit(
            export_id=command.export_id,
            case_id=command.case_id,
            case_profile_id=command.case_profile_id,
            schema_version=command.schema_version,
            product_version=command.product_version,
            export_profile=command.export_profile,
            source_revision=command.source_revision,
            source_snapshot_sha256=command.source_snapshot_sha256,
            status="valid",
            sealed=command.sealed,
            generated_by=command.generated_by,
            generated_at=command.generated_at,
            data_cutoff=command.data_cutoff,
            limitations=command.limitations,
        )

    @staticmethod
    def _to_audit(row) -> EvidenceMapExportAudit:
        return EvidenceMapExportAudit(
            export_id=row["id"],
            case_id=row["case_id"],
            case_profile_id=row["case_profile_id"],
            schema_version=row["schema_version"],
            product_version=row["product_version"],
            export_profile=row["export_profile"],
            source_revision=row["source_revision"],
            source_snapshot_sha256=row["source_snapshot_sha256"],
            status=row["status"],
            sealed=bool(row["sealed"]),
            generated_by=row["generated_by"],
            generated_at=row["generated_at"],
            data_cutoff=row["data_cutoff"],
            limitations=tuple(json.loads(row["limitations_json"])),
        )


class SQLiteEvidenceMapExportRecorder:
    """Operation-scoped adapter that commits one validated audit record."""

    def __init__(self, unit_of_work_factory):
        self._unit_of_work_factory = unit_of_work_factory

    def record_validated(
        self,
        command: RecordEvidenceMapExportCommand,
    ) -> EvidenceMapExportAudit:
        with self._unit_of_work_factory(write=True) as unit_of_work:
            result = unit_of_work.evidence_map_exports.record_validated(command)
            unit_of_work.commit()
        return result
