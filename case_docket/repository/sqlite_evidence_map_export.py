from __future__ import annotations

import json
import re
import sqlite3

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
        row = self._repository._conn.execute(
            "SELECT * FROM evidence_map_exports WHERE id = ?", (command.export_id,)
        ).fetchone()
        if row is not None:
            existing = self._to_audit(row)
            if existing.source_snapshot_sha256 != command.source_snapshot_sha256:
                raise EvidenceMapExportAuditError("export ID already exists with another hash")
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
        return self.get(command.export_id)  # type: ignore[return-value]

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
        if not all(
            (
                c.export_id,
                c.case_id,
                c.case_profile_id,
                c.schema_version,
                c.product_version,
                c.generated_by,
                c.generated_at,
            )
        ):
            raise EvidenceMapExportAuditError("required export audit field is empty")

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
