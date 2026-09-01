from __future__ import annotations

import sqlite3
from datetime import datetime

from case_docket.application.errors import ConflictError, NotFoundError, ValidationError
from case_docket.application.workspace_ports import (
    ActiveCasePreferenceRecord,
    CaseBootstrapRecord,
    CaseCandidateRecord,
    DocumentContextMembershipRecord,
    FileContextMembershipRecord,
    WorkspaceCaseRecord,
    WorkspaceProceedingRecord,
    WorkspaceRepositoryPort,
)

from .sqlite_repository import SQLiteRepository


class SQLiteWorkspaceRepository(WorkspaceRepositoryPort):
    """SQLite adapter for C07 cases, bootstrap review and presentation preferences."""

    def __init__(self, repository: SQLiteRepository):
        self._repository = repository

    def get_bootstrap(self, intake_case_id: str) -> CaseBootstrapRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT
                intake_case_id, intake_entry_id, file_id, status,
                confirmed_case_id, created_at, updated_at, resolved_at
            FROM case_bootstraps
            WHERE intake_case_id = ?
            """,
            (intake_case_id,),
        ).fetchone()
        return self._bootstrap(row) if row is not None else None

    def list_bootstraps(self, *, pending_only: bool = False) -> tuple[CaseBootstrapRecord, ...]:
        where = "WHERE status <> 'confirmed'" if pending_only else ""
        rows = self._repository._conn.execute(
            f"""
            SELECT
                intake_case_id, intake_entry_id, file_id, status,
                confirmed_case_id, created_at, updated_at, resolved_at
            FROM case_bootstraps
            {where}
            ORDER BY created_at, intake_case_id
            """
        ).fetchall()
        return tuple(self._bootstrap(row) for row in rows)

    def list_candidates(self, intake_case_id: str) -> tuple[CaseCandidateRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT
                id, intake_case_id, case_id, raw_value, normalized_value, detection_source,
                source_location, confidence, review_status, evidence_basis,
                tool_name, tool_version, external_reference_system,
                external_reference_kind, external_reference_value,
                decided_by, decided_at, created_at
            FROM case_number_candidates
            WHERE intake_case_id = ?
            ORDER BY created_at, id
            """,
            (intake_case_id,),
        ).fetchall()
        return tuple(self._candidate(row) for row in rows)

    def add_candidate(self, candidate: CaseCandidateRecord) -> bool:
        existing = self._repository._conn.execute(
            """
            SELECT id
            FROM case_number_candidates
            WHERE intake_case_id = ?
              AND raw_value = ?
              AND normalized_value IS ?
              AND detection_source = ?
              AND source_location IS ?
              AND evidence_basis IS ?
              AND tool_name IS ?
              AND tool_version IS ?
            LIMIT 1
            """,
            (
                candidate.intake_case_id,
                candidate.raw_value,
                candidate.normalized_value,
                candidate.detection_source,
                candidate.source_location,
                candidate.evidence_basis,
                candidate.tool_name,
                candidate.tool_version,
            ),
        ).fetchone()
        if existing is not None:
            return False
        self._repository._conn.execute(
            """
            INSERT INTO case_number_candidates(
                id, intake_case_id, case_id, raw_value, normalized_value,
                detection_source, source_location, confidence, review_status,
                decided_by, decided_at, created_at, candidate_kind,
                evidence_basis, tool_name, tool_version,
                external_reference_system, external_reference_kind,
                external_reference_value
            )
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'case_number', ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.intake_case_id,
                candidate.raw_value,
                candidate.normalized_value,
                candidate.detection_source,
                candidate.source_location,
                candidate.confidence,
                candidate.review_status,
                candidate.decided_by,
                candidate.decided_at.isoformat() if candidate.decided_at else None,
                candidate.created_at.isoformat(),
                candidate.evidence_basis,
                candidate.tool_name,
                candidate.tool_version,
                candidate.external_reference_system,
                candidate.external_reference_kind,
                candidate.external_reference_value,
            ),
        )
        self._repository._record_audit_event(
            "add_case_number_candidate",
            "case_number_candidates",
            candidate.candidate_id,
            {
                "intake_case_id": candidate.intake_case_id,
                "detection_source": candidate.detection_source,
                "has_normalized_value": candidate.normalized_value is not None,
            },
        )
        return True

    def decide_candidates(
        self,
        intake_case_id: str,
        *,
        selected_normalized_value: str | None,
        case_id: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> None:
        occurred = occurred_at.isoformat()
        if selected_normalized_value is None:
            self._repository._conn.execute(
                """
                UPDATE case_number_candidates
                SET review_status = 'rejected', case_id = NULL,
                    decided_by = ?, decided_at = ?
                WHERE intake_case_id = ?
                """,
                (actor_id, occurred, intake_case_id),
            )
        else:
            self._repository._conn.execute(
                """
                UPDATE case_number_candidates
                SET
                    review_status = CASE
                        WHEN normalized_value = ? THEN 'confirmed'
                        ELSE 'rejected'
                    END,
                    case_id = CASE
                        WHEN normalized_value = ? THEN ?
                        ELSE NULL
                    END,
                    decided_by = ?,
                    decided_at = ?
                WHERE intake_case_id = ?
                """,
                (
                    selected_normalized_value,
                    selected_normalized_value,
                    case_id,
                    actor_id,
                    occurred,
                    intake_case_id,
                ),
            )
        self._repository._record_audit_event(
            "decide_case_number_candidates",
            "case_bootstraps",
            intake_case_id,
            {"actor_id": actor_id, "selected": selected_normalized_value is not None},
        )

    def set_bootstrap_status(
        self,
        intake_case_id: str,
        *,
        status: str,
        occurred_at: datetime,
        candidate_id: str | None = None,
        case_id: str | None = None,
        actor_id: str | None = None,
        note: str | None = None,
    ) -> None:
        bootstrap = self.get_bootstrap(intake_case_id)
        if bootstrap is None:
            raise NotFoundError("Case bootstrap не знайдено", {"resource": "case_bootstrap"})
        if status not in {"manual_review_required", "candidate_ready", "confirmed"}:
            raise ValidationError("Некоректний bootstrap status")
        if status == "confirmed" and case_id is None:
            raise ValidationError("Confirmed bootstrap потребує case_id")
        if status != "confirmed" and case_id is not None:
            raise ValidationError("Pending bootstrap не може мати confirmed case")
        if bootstrap.status == status and bootstrap.confirmed_case_id == case_id:
            return
        occurred = occurred_at.isoformat()
        self._repository._conn.execute(
            """
            UPDATE case_bootstraps
            SET status = ?, confirmed_case_id = ?, updated_at = ?, resolved_at = ?
            WHERE intake_case_id = ?
            """,
            (
                status,
                case_id,
                occurred,
                occurred if status == "confirmed" else None,
                intake_case_id,
            ),
        )
        self._repository._conn.execute(
            """
            INSERT INTO case_bootstrap_status_history(
                intake_case_id, from_status, to_status, candidate_id,
                case_id, actor_id, note, occurred_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intake_case_id,
                bootstrap.status,
                status,
                candidate_id,
                case_id,
                actor_id,
                note,
                occurred,
            ),
        )
        self._repository._record_audit_event(
            "transition_case_bootstrap",
            "case_bootstraps",
            intake_case_id,
            {"from": bootstrap.status, "to": status, "case_id": case_id},
        )

    def list_cases(self) -> tuple[WorkspaceCaseRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT id, case_number, name, status, created_at, updated_at
            FROM cases
            ORDER BY COALESCE(case_number, ''), COALESCE(name, ''), id
            """
        ).fetchall()
        return tuple(self._case(row) for row in rows)

    def get_case(self, case_id: str) -> WorkspaceCaseRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, case_number, name, status, created_at, updated_at
            FROM cases
            WHERE id = ?
            """,
            (case_id,),
        ).fetchone()
        return self._case(row) if row is not None else None

    def add_case(self, case: WorkspaceCaseRecord, *, actor_id: str) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO cases(
                    id, case_number, name, status, created_at, updated_at, legacy_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, '{}')
                """,
                (
                    case.case_id,
                    case.case_number,
                    case.name,
                    case.status,
                    case.created_at.isoformat(),
                    case.updated_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Case identity conflict", {"resource": "case"}) from exc
        self._repository._record_audit_event(
            "create_workspace_case",
            "cases",
            case.case_id,
            {"actor_id": actor_id, "has_case_number": case.case_number is not None},
        )

    def register_case_number(
        self,
        *,
        registry_id: str,
        case_id: str,
        raw_value: str,
        normalized_value: str,
        source_kind: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> None:
        existing = self._repository._conn.execute(
            """
            SELECT case_id
            FROM case_number_registry
            WHERE normalized_value = ?
            """,
            (normalized_value,),
        ).fetchone()
        if existing is not None:
            if str(existing["case_id"]) != case_id:
                raise ConflictError(
                    "Normalized case number уже належить іншій справі",
                    {"resource": "case_number"},
                )
            return
        try:
            self._repository._conn.execute(
                """
                INSERT INTO case_number_registry(
                    id, case_id, raw_value, normalized_value,
                    source_kind, actor_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    registry_id,
                    case_id,
                    raw_value,
                    normalized_value,
                    source_kind,
                    actor_id,
                    occurred_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "Case number registration conflict",
                {"resource": "case_number"},
            ) from exc
        self._repository._conn.execute(
            """
            UPDATE cases
            SET case_number = COALESCE(case_number, ?), updated_at = ?
            WHERE id = ?
            """,
            (raw_value, occurred_at.isoformat(), case_id),
        )
        self._repository._record_audit_event(
            "register_case_number",
            "cases",
            case_id,
            {"actor_id": actor_id, "source_kind": source_kind},
        )

    def get_external_reference_case(
        self,
        *,
        system: str,
        kind: str,
        normalized_value: str,
    ) -> str | None:
        row = self._repository._conn.execute(
            """
            SELECT case_id
            FROM case_external_references
            WHERE system = ? AND kind = ? AND normalized_value = ?
            """,
            (system, kind, normalized_value),
        ).fetchone()
        return str(row["case_id"]) if row is not None else None

    def add_external_reference(
        self,
        *,
        reference_id: str,
        case_id: str,
        system: str,
        kind: str,
        raw_value: str,
        normalized_value: str,
        evidence_basis: str,
        source_location: str | None,
        occurred_at: datetime,
    ) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO case_external_references(
                    id, case_id, system, kind, raw_value, normalized_value,
                    evidence_basis, source_location, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference_id,
                    case_id,
                    system,
                    kind,
                    raw_value,
                    normalized_value,
                    evidence_basis,
                    source_location,
                    occurred_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "External reference conflict",
                {"resource": "case_external_reference"},
            ) from exc
        self._repository._record_audit_event(
            "add_case_external_reference",
            "case_external_references",
            reference_id,
            {"case_id": case_id, "system": system, "kind": kind},
        )

    def list_proceedings(self) -> tuple[WorkspaceProceedingRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT id, proceeding_number, name, status, created_at, updated_at
            FROM proceedings
            ORDER BY COALESCE(proceeding_number, ''), COALESCE(name, ''), id
            """
        ).fetchall()
        return tuple(self._proceeding(row) for row in rows)

    def get_proceeding(self, proceeding_id: str) -> WorkspaceProceedingRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, proceeding_number, name, status, created_at, updated_at
            FROM proceedings
            WHERE id = ?
            """,
            (proceeding_id,),
        ).fetchone()
        return self._proceeding(row) if row is not None else None

    def add_proceeding(
        self,
        proceeding: WorkspaceProceedingRecord,
        *,
        actor_id: str,
    ) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO proceedings(
                    id, proceeding_number, name, status,
                    created_at, updated_at, legacy_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, '{}')
                """,
                (
                    proceeding.proceeding_id,
                    proceeding.proceeding_number,
                    proceeding.name,
                    proceeding.status,
                    proceeding.created_at.isoformat(),
                    proceeding.updated_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "Proceeding identity conflict",
                {"resource": "proceeding"},
            ) from exc
        self._repository._record_audit_event(
            "create_workspace_proceeding",
            "proceedings",
            proceeding.proceeding_id,
            {"actor_id": actor_id},
        )

    def link_case_proceeding(
        self,
        *,
        case_id: str,
        proceeding_id: str,
        relationship_kind: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> None:
        cursor = self._repository._conn.execute(
            """
            INSERT OR IGNORE INTO case_proceedings(
                case_id, proceeding_id, relationship_kind, origin, created_at
            )
            VALUES (?, ?, ?, 'local', ?)
            """,
            (case_id, proceeding_id, relationship_kind, occurred_at.isoformat()),
        )
        if cursor.rowcount:
            self._repository._record_audit_event(
                "link_case_proceeding",
                "case_proceedings",
                proceeding_id,
                {
                    "case_id": case_id,
                    "relationship_kind": relationship_kind,
                    "actor_id": actor_id,
                },
            )

    def file_exists(self, file_id: str) -> bool:
        return (
            self._repository._conn.execute(
                "SELECT 1 FROM file_objects WHERE id = ?",
                (file_id,),
            ).fetchone()
            is not None
        )

    def add_file_membership(self, membership: FileContextMembershipRecord) -> bool:
        existing = self._repository._conn.execute(
            """
            SELECT id
            FROM file_context_memberships
            WHERE file_id = ? AND context_type = ? AND context_id = ? AND role = ?
            """,
            (
                membership.file_id,
                membership.context_type,
                membership.context_id,
                membership.role,
            ),
        ).fetchone()
        if existing is not None:
            return False
        try:
            self._repository._conn.execute(
                """
                INSERT INTO file_context_memberships(
                    id, file_id, context_type, context_id, role,
                    origin, actor_id, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    membership.membership_id,
                    membership.file_id,
                    membership.context_type,
                    membership.context_id,
                    membership.role,
                    membership.origin,
                    membership.actor_id,
                    membership.note,
                    membership.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(
                "File membership порушує context contract",
                {"resource": "file_membership"},
            ) from exc
        self._repository._record_audit_event(
            "add_file_context_membership",
            "file_context_memberships",
            membership.membership_id,
            {
                "file_id": membership.file_id,
                "context_type": membership.context_type,
                "context_id": membership.context_id,
                "actor_id": membership.actor_id,
            },
        )
        return True

    def list_file_memberships(self, file_id: str) -> tuple[FileContextMembershipRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT
                id, file_id, context_type, context_id, role,
                origin, actor_id, note, created_at
            FROM file_context_memberships
            WHERE file_id = ?
            ORDER BY context_type, context_id, role, id
            """,
            (file_id,),
        ).fetchall()
        return tuple(self._membership(row) for row in rows)

    def document_exists(self, document_id: str) -> bool:
        return (
            self._repository._conn.execute(
                "SELECT 1 FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            is not None
        )

    def add_document_membership(self, membership: DocumentContextMembershipRecord) -> bool:
        existing = self._repository._conn.execute(
            """
            SELECT id
            FROM entity_memberships
            WHERE entity_type = 'document'
              AND entity_id = ?
              AND context_type = ?
              AND context_id = ?
              AND role = ?
            """,
            (
                membership.document_id,
                membership.context_type,
                membership.context_id,
                membership.role,
            ),
        ).fetchone()
        if existing is not None:
            return False
        self._repository._conn.execute(
            """
            INSERT INTO entity_memberships(
                id, entity_type, entity_id, context_type, context_id,
                role, is_primary, source_reference_id, review_status,
                valid_from, valid_to, note, created_at, updated_at,
                origin, actor_id
            )
            VALUES (
                ?, 'document', ?, ?, ?, ?, 0, NULL, 'confirmed',
                NULL, NULL, ?, ?, ?, 'manual_command', ?
            )
            """,
            (
                membership.membership_id,
                membership.document_id,
                membership.context_type,
                membership.context_id,
                membership.role,
                membership.note,
                membership.created_at.isoformat(),
                membership.created_at.isoformat(),
                membership.actor_id,
            ),
        )
        self._repository._record_audit_event(
            "add_document_context_membership",
            "entity_memberships",
            membership.membership_id,
            {
                "document_id": membership.document_id,
                "context_type": membership.context_type,
                "context_id": membership.context_id,
                "actor_id": membership.actor_id,
            },
        )
        return True

    def list_document_memberships(
        self,
        document_id: str,
    ) -> tuple[DocumentContextMembershipRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT id, entity_id, context_type, context_id, role,
                   actor_id, note, created_at
            FROM entity_memberships
            WHERE entity_type = 'document' AND entity_id = ?
            ORDER BY context_type, context_id, role, id
            """,
            (document_id,),
        ).fetchall()
        return tuple(self._document_membership(row) for row in rows)

    def get_active_case(self, preference_id: str) -> ActiveCasePreferenceRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT preference_id, active_case_id, updated_by, updated_at
            FROM workspace_case_preferences
            WHERE preference_id = ?
            """,
            (preference_id,),
        ).fetchone()
        return self._preference(row) if row is not None else None

    def set_active_case(self, preference: ActiveCasePreferenceRecord) -> None:
        self._repository._conn.execute(
            """
            INSERT INTO workspace_case_preferences(
                preference_id, active_case_id, updated_by, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(preference_id) DO UPDATE SET
                active_case_id = excluded.active_case_id,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (
                preference.preference_id,
                preference.active_case_id,
                preference.updated_by,
                preference.updated_at.isoformat(),
            ),
        )
        self._repository._record_audit_event(
            "select_active_case",
            "workspace_case_preferences",
            preference.preference_id,
            {
                "active_case_id": preference.active_case_id,
                "actor_id": preference.updated_by,
                "scope": "presentation_preference",
            },
        )

    def add_review_decision(
        self,
        *,
        decision_id: str,
        file_id: str,
        previous_status: str,
        new_status: str,
        actor_id: str,
        occurred_at: datetime,
        note: str | None,
    ) -> None:
        self._repository._conn.execute(
            """
            INSERT INTO review_decisions(
                id, subject_type, subject_id, decision, previous_status,
                new_status, actor_id, decided_at, note
            )
            VALUES (?, 'file', ?, 'confirm', ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                file_id,
                previous_status,
                new_status,
                actor_id,
                occurred_at.isoformat(),
                note,
            ),
        )
        self._repository._record_audit_event(
            "confirm_case_bootstrap",
            "review_decisions",
            decision_id,
            {"file_id": file_id, "actor_id": actor_id},
        )

    def _case(self, row: sqlite3.Row) -> WorkspaceCaseRecord:
        case_id = str(row["id"])
        registry = self._repository._conn.execute(
            """
            SELECT normalized_value
            FROM case_number_registry
            WHERE case_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        proceeding_rows = self._repository._conn.execute(
            """
            SELECT DISTINCT proceeding_id
            FROM case_proceedings
            WHERE case_id = ?
            ORDER BY proceeding_id
            """,
            (case_id,),
        ).fetchall()
        file_rows = self._repository._conn.execute(
            """
            SELECT DISTINCT file_id
            FROM file_context_memberships
            WHERE context_type = 'case' AND context_id = ?
            ORDER BY file_id
            """,
            (case_id,),
        ).fetchall()
        return WorkspaceCaseRecord(
            case_id=case_id,
            case_number=str(row["case_number"]) if row["case_number"] is not None else None,
            name=str(row["name"]) if row["name"] is not None else None,
            status=str(row["status"]) if row["status"] is not None else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            normalized_case_number=(
                str(registry["normalized_value"]) if registry is not None else None
            ),
            proceeding_ids=tuple(str(item["proceeding_id"]) for item in proceeding_rows),
            file_ids=tuple(str(item["file_id"]) for item in file_rows),
        )

    def _proceeding(self, row: sqlite3.Row) -> WorkspaceProceedingRecord:
        proceeding_id = str(row["id"])
        case_rows = self._repository._conn.execute(
            """
            SELECT DISTINCT case_id
            FROM case_proceedings
            WHERE proceeding_id = ?
            ORDER BY case_id
            """,
            (proceeding_id,),
        ).fetchall()
        return WorkspaceProceedingRecord(
            proceeding_id=proceeding_id,
            proceeding_number=(
                str(row["proceeding_number"])
                if row["proceeding_number"] is not None
                else None
            ),
            name=str(row["name"]) if row["name"] is not None else None,
            status=str(row["status"]) if row["status"] is not None else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            case_ids=tuple(str(item["case_id"]) for item in case_rows),
        )

    @staticmethod
    def _bootstrap(row: sqlite3.Row) -> CaseBootstrapRecord:
        return CaseBootstrapRecord(
            intake_case_id=str(row["intake_case_id"]),
            intake_entry_id=str(row["intake_entry_id"]),
            file_id=str(row["file_id"]),
            status=str(row["status"]),
            confirmed_case_id=(
                str(row["confirmed_case_id"])
                if row["confirmed_case_id"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            resolved_at=(
                datetime.fromisoformat(str(row["resolved_at"]))
                if row["resolved_at"] is not None
                else None
            ),
        )

    @staticmethod
    def _candidate(row: sqlite3.Row) -> CaseCandidateRecord:
        return CaseCandidateRecord(
            candidate_id=str(row["id"]),
            intake_case_id=str(row["intake_case_id"]),
            case_id=str(row["case_id"]) if row["case_id"] is not None else None,
            raw_value=str(row["raw_value"]),
            normalized_value=(
                str(row["normalized_value"]) if row["normalized_value"] is not None else None
            ),
            detection_source=str(row["detection_source"]),
            source_location=(
                str(row["source_location"]) if row["source_location"] is not None else None
            ),
            confidence=float(row["confidence"]) if row["confidence"] is not None else None,
            review_status=str(row["review_status"]),
            evidence_basis=(
                str(row["evidence_basis"]) if row["evidence_basis"] is not None else None
            ),
            tool_name=str(row["tool_name"]) if row["tool_name"] is not None else None,
            tool_version=(
                str(row["tool_version"]) if row["tool_version"] is not None else None
            ),
            external_reference_system=(
                str(row["external_reference_system"])
                if row["external_reference_system"] is not None
                else None
            ),
            external_reference_kind=(
                str(row["external_reference_kind"])
                if row["external_reference_kind"] is not None
                else None
            ),
            external_reference_value=(
                str(row["external_reference_value"])
                if row["external_reference_value"] is not None
                else None
            ),
            decided_by=str(row["decided_by"]) if row["decided_by"] is not None else None,
            decided_at=(
                datetime.fromisoformat(str(row["decided_at"]))
                if row["decided_at"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _membership(row: sqlite3.Row) -> FileContextMembershipRecord:
        return FileContextMembershipRecord(
            membership_id=str(row["id"]),
            file_id=str(row["file_id"]),
            context_type=str(row["context_type"]),
            context_id=str(row["context_id"]),
            role=str(row["role"]),
            origin=str(row["origin"]),
            actor_id=str(row["actor_id"]),
            note=str(row["note"]) if row["note"] is not None else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _document_membership(row: sqlite3.Row) -> DocumentContextMembershipRecord:
        return DocumentContextMembershipRecord(
            membership_id=str(row["id"]),
            document_id=str(row["entity_id"]),
            context_type=str(row["context_type"]),
            context_id=str(row["context_id"]),
            role=str(row["role"]),
            actor_id=(
                str(row["actor_id"])
                if row["actor_id"] is not None
                else "system:legacy-membership"
            ),
            note=str(row["note"]) if row["note"] is not None else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _preference(row: sqlite3.Row) -> ActiveCasePreferenceRecord:
        return ActiveCasePreferenceRecord(
            preference_id=str(row["preference_id"]),
            active_case_id=(
                str(row["active_case_id"]) if row["active_case_id"] is not None else None
            ),
            updated_by=str(row["updated_by"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
