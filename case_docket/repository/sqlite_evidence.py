from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Mapping

from case_docket.application.errors import ConflictError, NotFoundError, ValidationError
from case_docket.application.evidence_ports import (
    ClaimRecord,
    CompatibilityReviewRecord,
    EntityReferenceRecord,
    EvidenceActorRecord,
    EvidenceDocumentRecord,
    EvidenceEventRecord,
    EvidenceMembershipRecord,
    EvidenceRelationRecord,
    EvidenceRepositoryPort,
    FindingRecord,
    ReviewDecisionRecord,
    SourceContextRecord,
    SourceReferenceRecord,
    TimelineRecord,
)

from .sqlite_repository import SQLiteRepository


_ENTITY_TABLES = {
    "case": "cases",
    "proceeding": "proceedings",
    "actor": "actors",
    "file": "file_objects",
    "document": "documents",
    "event": "events",
    "claim": "claims",
    "relation": "evidence_relations",
    "source_reference": "source_references",
}
_REVIEW_TABLES = {
    "actor": "actors",
    "document": "documents",
    "event": "events",
    "claim": "claims",
    "relation": "evidence_relations",
    "source_reference": "source_references",
}


class SQLiteEvidenceRepository(EvidenceRepositoryPort):
    """C08 SQLite adapter; all polymorphic checks are called through the service."""

    def __init__(self, repository: SQLiteRepository):
        self._repository = repository

    def entity_exists(self, entity_type: str, entity_id: str) -> bool:
        table = _ENTITY_TABLES.get(entity_type)
        if table is None:
            return False
        row = self._repository._conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (entity_id,)
        ).fetchone()
        return row is not None

    def processing_run_exists(self, processing_run_id: str) -> bool:
        return (
            self._repository._conn.execute(
                "SELECT 1 FROM processing_runs WHERE id = ?", (processing_run_id,)
            ).fetchone()
            is not None
        )

    def file_sha256(self, file_id: str) -> str | None:
        row = self._repository._conn.execute(
            "SELECT sha256 FROM file_objects WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return None
        return self._optional_text(row["sha256"])

    def add_actor(
        self,
        actor: EvidenceActorRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        created_by: str,
    ) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO actors(
                    id, created_at, updated_at, legacy_payload,
                    actor_type, display_name, normalized_name,
                    review_status, notes, version
                ) VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)
                """,
                (
                    actor.actor_id,
                    actor.created_at.isoformat(),
                    actor.updated_at.isoformat(),
                    actor.actor_type,
                    actor.display_name,
                    actor.normalized_name,
                    actor.review_status,
                    actor.notes,
                    actor.version,
                ),
            )
            self._insert_memberships(memberships, actor_id=created_by)
            self._audit(
                "create_evidence_actor",
                "actors",
                actor.actor_id,
                {"actor_type": actor.actor_type, "membership_count": len(memberships)},
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "actor") from exc

    def add_document(
        self,
        document: EvidenceDocumentRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        file_ids: tuple[str, ...],
        created_by: str,
    ) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO documents(
                    id, title, doc_type, category, source, origin_format,
                    file_attachments_json, requires_manual_review,
                    created_at, updated_at, legacy_payload,
                    label, summary, process_role, classification,
                    review_status, is_key, version
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    document.title,
                    document.document_type,
                    document.category,
                    document.source,
                    document.origin_format,
                    int(document.review_status == "manual_review_required"),
                    document.created_at.isoformat(),
                    document.updated_at.isoformat(),
                    document.label,
                    document.summary,
                    document.process_role,
                    document.classification,
                    document.review_status,
                    int(document.is_key),
                    document.version,
                ),
            )
            self._insert_memberships(memberships, actor_id=created_by)
            for file_id in file_ids:
                current = self._repository._conn.execute(
                    "SELECT document_id FROM file_objects WHERE id = ?", (file_id,)
                ).fetchone()
                if current is None:
                    raise NotFoundError("File не знайдено", {"resource": "file"})
                existing_document = self._optional_text(current["document_id"])
                if existing_document is not None and existing_document != document.document_id:
                    raise ConflictError(
                        "File уже пов’язаний з іншим document",
                        {"resource": "file_document_link"},
                    )
                self._repository._conn.execute(
                    """
                    UPDATE file_objects
                    SET document_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (document.document_id, document.updated_at.isoformat(), file_id),
                )
            self._audit(
                "create_evidence_document",
                "documents",
                document.document_id,
                {
                    "classification": document.classification,
                    "file_count": len(file_ids),
                    "membership_count": len(memberships),
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "document") from exc

    def add_event(
        self,
        event: EvidenceEventRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        actor_ids: tuple[str, ...],
        document_ids: tuple[str, ...],
        created_by: str,
    ) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO events(
                    id, title, interaction_type, event_at, description,
                    workflow_status, attachments_json, created_at, updated_at,
                    legacy_payload, classification, review_status,
                    process_consequence, next_action, deadline, version
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, '{}', ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.title,
                    event.event_type,
                    event.event_at,
                    event.description,
                    event.workflow_status,
                    event.created_at.isoformat(),
                    event.updated_at.isoformat(),
                    event.classification,
                    event.review_status,
                    event.process_consequence,
                    event.next_action,
                    event.deadline,
                    event.version,
                ),
            )
            self._insert_memberships(memberships, actor_id=created_by)
            for actor_id in actor_ids:
                self._repository._conn.execute(
                    """
                    INSERT INTO event_actor_links(event_id, actor_id, role)
                    VALUES (?, ?, 'participant')
                    """,
                    (event.event_id, actor_id),
                )
            for document_id in document_ids:
                self._repository._conn.execute(
                    """
                    INSERT INTO event_documents(event_id, document_id, origin, created_at)
                    VALUES (?, ?, 'local', ?)
                    """,
                    (event.event_id, document_id, event.created_at.isoformat()),
                )
            self._audit(
                "create_evidence_event",
                "events",
                event.event_id,
                {
                    "actor_count": len(actor_ids),
                    "document_count": len(document_ids),
                    "membership_count": len(memberships),
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "event") from exc

    def add_source_reference(self, source: SourceReferenceRecord) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO source_references(
                    id, source_entity_type, source_entity_id, source_file_id,
                    location_type, location_value, excerpt, source_sha256,
                    review_status, created_by, created_at, note, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_reference_id,
                    source.source_entity_type,
                    source.source_entity_id,
                    source.source_file_id,
                    source.location_type,
                    source.location_value,
                    source.excerpt,
                    source.source_sha256,
                    source.review_status,
                    source.created_by,
                    source.created_at.isoformat(),
                    source.note,
                    source.version,
                ),
            )
            self._audit(
                "create_source_reference",
                "source_references",
                source.source_reference_id,
                {
                    "source_entity_type": source.source_entity_type,
                    "location_type": source.location_type,
                    "has_file": source.source_file_id is not None,
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "source_reference") from exc

    def add_claim(
        self,
        claim: ClaimRecord,
        *,
        memberships: tuple[EvidenceMembershipRecord, ...],
        created_by: str,
    ) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO claims(
                    id, subject_type, subject_id, claim_text, classification,
                    review_status, uncertainty_note, process_consequence,
                    created_at, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.claim_id,
                    claim.subject_type,
                    claim.subject_id,
                    claim.claim_text,
                    claim.classification,
                    claim.review_status,
                    claim.uncertainty_note,
                    claim.process_consequence,
                    claim.created_at.isoformat(),
                    claim.updated_at.isoformat(),
                    claim.version,
                ),
            )
            for actor_id in claim.asserted_by_actor_ids:
                self._repository._conn.execute(
                    "INSERT INTO claim_assertors(claim_id, actor_id) VALUES (?, ?)",
                    (claim.claim_id, actor_id),
                )
            for document_id in claim.basis_document_ids:
                self._repository._conn.execute(
                    "INSERT INTO claim_basis_documents(claim_id, document_id) VALUES (?, ?)",
                    (claim.claim_id, document_id),
                )
            for source_id in claim.source_reference_ids:
                self._repository._conn.execute(
                    """
                    INSERT INTO claim_source_references(claim_id, source_reference_id)
                    VALUES (?, ?)
                    """,
                    (claim.claim_id, source_id),
                )
            self._insert_memberships(memberships, actor_id=created_by)
            self._audit(
                "create_claim",
                "claims",
                claim.claim_id,
                {
                    "classification": claim.classification,
                    "basis_document_count": len(claim.basis_document_ids),
                    "source_reference_count": len(claim.source_reference_ids),
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "claim") from exc

    def add_relation(
        self,
        relation: EvidenceRelationRecord,
        *,
        created_by: str,
    ) -> None:
        try:
            self._repository._conn.execute(
                """
                INSERT INTO evidence_relations(
                    id, from_type, from_id, to_type, to_id, relation_type,
                    label, classification, review_status, uncertainty_note,
                    valid_from, valid_to, created_at, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relation.relation_id,
                    relation.from_type,
                    relation.from_id,
                    relation.to_type,
                    relation.to_id,
                    relation.relation_type,
                    relation.label,
                    relation.classification,
                    relation.review_status,
                    relation.uncertainty_note,
                    relation.valid_from,
                    relation.valid_to,
                    relation.created_at.isoformat(),
                    relation.updated_at.isoformat(),
                    relation.version,
                ),
            )
            for document_id in relation.basis_document_ids:
                self._repository._conn.execute(
                    """
                    INSERT INTO relation_basis_documents(relation_id, document_id)
                    VALUES (?, ?)
                    """,
                    (relation.relation_id, document_id),
                )
            for source_id in relation.source_reference_ids:
                self._repository._conn.execute(
                    """
                    INSERT INTO relation_source_references(relation_id, source_reference_id)
                    VALUES (?, ?)
                    """,
                    (relation.relation_id, source_id),
                )
            self._audit(
                "create_evidence_relation",
                "evidence_relations",
                relation.relation_id,
                {
                    "relation_type": relation.relation_type,
                    "classification": relation.classification,
                    "created_by": created_by,
                    "basis_document_count": len(relation.basis_document_ids),
                    "source_reference_count": len(relation.source_reference_ids),
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "relation") from exc

    def get_actor(self, actor_id: str) -> EvidenceActorRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, actor_type, display_name, normalized_name, review_status,
                   notes, version, created_at, updated_at
            FROM actors WHERE id = ?
            """,
            (actor_id,),
        ).fetchone()
        return self._actor(row) if row is not None else None

    def get_document(self, document_id: str) -> EvidenceDocumentRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, title, label, doc_type, category, source, origin_format,
                   summary, process_role, classification, review_status,
                   is_key, version, created_at, updated_at
            FROM documents WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        return self._document(row) if row is not None else None

    def get_event(self, event_id: str) -> EvidenceEventRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, title, interaction_type, event_at, description,
                   workflow_status, classification, review_status,
                   process_consequence, next_action, deadline, version,
                   created_at, updated_at
            FROM events WHERE id = ?
            """,
            (event_id,),
        ).fetchone()
        return self._event(row) if row is not None else None

    def get_source_reference(self, source_reference_id: str) -> SourceReferenceRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, source_entity_type, source_entity_id, source_file_id,
                   location_type, location_value, excerpt, source_sha256,
                   review_status, created_by, created_at, note, version
            FROM source_references WHERE id = ?
            """,
            (source_reference_id,),
        ).fetchone()
        return self._source(row) if row is not None else None

    def get_claim(self, claim_id: str) -> ClaimRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, subject_type, subject_id, claim_text, classification,
                   review_status, uncertainty_note, process_consequence,
                   version, created_at, updated_at
            FROM claims WHERE id = ?
            """,
            (claim_id,),
        ).fetchone()
        return self._claim(row) if row is not None else None

    def get_relation(self, relation_id: str) -> EvidenceRelationRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, from_type, from_id, to_type, to_id, relation_type,
                   label, classification, review_status, uncertainty_note,
                   valid_from, valid_to, version, created_at, updated_at
            FROM evidence_relations WHERE id = ?
            """,
            (relation_id,),
        ).fetchone()
        return self._relation(row) if row is not None else None

    def list_actors_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceActorRecord, ...]:
        ids = self._context_entity_ids("actor", case_id, limit=limit, offset=offset)
        return tuple(record for item in ids if (record := self.get_actor(item)) is not None)

    def list_documents_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceDocumentRecord, ...]:
        ids = self._context_entity_ids("document", case_id, limit=limit, offset=offset)
        return tuple(record for item in ids if (record := self.get_document(item)) is not None)

    def list_events_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceEventRecord, ...]:
        ids = self._context_entity_ids("event", case_id, limit=limit, offset=offset)
        return tuple(record for item in ids if (record := self.get_event(item)) is not None)

    def list_sources_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[SourceReferenceRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT DISTINCT sr.id, sr.created_at
            FROM source_references AS sr
            WHERE (sr.source_entity_type = 'case' AND sr.source_entity_id = ?)
               OR EXISTS (
                    SELECT 1 FROM entity_memberships AS m
                    WHERE m.context_type = 'case' AND m.context_id = ?
                      AND m.entity_type = sr.source_entity_type
                      AND m.entity_id = sr.source_entity_id
               )
               OR EXISTS (
                    SELECT 1 FROM file_context_memberships AS fm
                    WHERE sr.source_entity_type = 'file'
                      AND fm.file_id = sr.source_entity_id
                      AND fm.context_type = 'case' AND fm.context_id = ?
               )
               OR EXISTS (
                    SELECT 1
                    FROM claim_source_references AS csr
                    JOIN entity_memberships AS cm
                      ON cm.entity_type = 'claim' AND cm.entity_id = csr.claim_id
                    WHERE csr.source_reference_id = sr.id
                      AND cm.context_type = 'case' AND cm.context_id = ?
               )
               OR EXISTS (
                    SELECT 1
                    FROM relation_source_references AS rsr
                    JOIN evidence_relations AS er ON er.id = rsr.relation_id
                    WHERE rsr.source_reference_id = sr.id
                      AND (
                        (er.from_type = 'case' AND er.from_id = ?)
                        OR (er.to_type = 'case' AND er.to_id = ?)
                        OR EXISTS (
                            SELECT 1 FROM entity_memberships AS rm
                            WHERE rm.context_type = 'case' AND rm.context_id = ?
                              AND (
                                (rm.entity_type = er.from_type AND rm.entity_id = er.from_id)
                                OR
                                (rm.entity_type = er.to_type AND rm.entity_id = er.to_id)
                              )
                        )
                      )
               )
            ORDER BY sr.created_at, sr.id
            LIMIT ? OFFSET ?
            """,
            (
                case_id,
                case_id,
                case_id,
                case_id,
                case_id,
                case_id,
                case_id,
                limit,
                offset,
            ),
        ).fetchall()
        return tuple(
            record
            for row in rows
            if (record := self.get_source_reference(str(row["id"]))) is not None
        )

    def list_claims_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[ClaimRecord, ...]:
        ids = self._context_entity_ids("claim", case_id, limit=limit, offset=offset)
        return tuple(record for item in ids if (record := self.get_claim(item)) is not None)

    def list_relations_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[EvidenceRelationRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT er.id, er.created_at
            FROM evidence_relations AS er
            WHERE (er.from_type = 'case' AND er.from_id = ?)
               OR (er.to_type = 'case' AND er.to_id = ?)
               OR EXISTS (
                    SELECT 1 FROM entity_memberships AS m
                    WHERE m.context_type = 'case' AND m.context_id = ?
                      AND (
                        (m.entity_type = er.from_type AND m.entity_id = er.from_id)
                        OR
                        (m.entity_type = er.to_type AND m.entity_id = er.to_id)
                      )
               )
               OR EXISTS (
                    SELECT 1 FROM file_context_memberships AS fm
                    WHERE fm.context_type = 'case' AND fm.context_id = ?
                      AND (
                        (er.from_type = 'file' AND fm.file_id = er.from_id)
                        OR
                        (er.to_type = 'file' AND fm.file_id = er.to_id)
                      )
               )
            ORDER BY er.created_at, er.id
            LIMIT ? OFFSET ?
            """,
            (case_id, case_id, case_id, case_id, limit, offset),
        ).fetchall()
        return tuple(
            record for row in rows if (record := self.get_relation(str(row["id"]))) is not None
        )

    def list_findings_for_case(
        self, case_id: str, *, limit: int, offset: int
    ) -> tuple[FindingRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT DISTINCT ef.id, ef.last_observed_at
            FROM evidence_findings AS ef
            JOIN finding_subjects AS fs ON fs.finding_id = ef.id
            WHERE (fs.subject_type = 'case' AND fs.subject_id = ?)
               OR EXISTS (
                    SELECT 1 FROM entity_memberships AS m
                    WHERE m.context_type = 'case' AND m.context_id = ?
                      AND m.entity_type = fs.subject_type AND m.entity_id = fs.subject_id
               )
               OR EXISTS (
                    SELECT 1 FROM file_context_memberships AS fm
                    WHERE fs.subject_type = 'file' AND fm.file_id = fs.subject_id
                      AND fm.context_type = 'case' AND fm.context_id = ?
               )
            ORDER BY ef.last_observed_at DESC, ef.id
            LIMIT ? OFFSET ?
            """,
            (case_id, case_id, case_id, limit, offset),
        ).fetchall()
        return tuple(
            record for row in rows if (record := self.get_finding(str(row["id"]))) is not None
        )

    def list_timeline(self, case_id: str, *, limit: int, offset: int) -> tuple[TimelineRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT entity_type, entity_id, title, occurred_at, review_status
            FROM (
                SELECT
                    'event' AS entity_type,
                    e.id AS entity_id,
                    COALESCE(e.title, e.id) AS title,
                    COALESCE(e.event_at, e.sent_at, e.delivered_at, e.created_at) AS occurred_at,
                    e.review_status AS review_status
                FROM events AS e
                JOIN entity_memberships AS em
                  ON em.entity_type = 'event' AND em.entity_id = e.id
                WHERE em.context_type = 'case' AND em.context_id = ?
                UNION ALL
                SELECT
                    'document' AS entity_type,
                    d.id AS entity_id,
                    COALESCE(d.title, d.label, d.id) AS title,
                    COALESCE(d.registered_on, d.sent_on, d.created_at) AS occurred_at,
                    d.review_status AS review_status
                FROM documents AS d
                JOIN entity_memberships AS dm
                  ON dm.entity_type = 'document' AND dm.entity_id = d.id
                WHERE dm.context_type = 'case' AND dm.context_id = ?
            ) AS timeline
            ORDER BY occurred_at, entity_type, entity_id
            LIMIT ? OFFSET ?
            """,
            (case_id, case_id, limit, offset),
        ).fetchall()
        return tuple(
            TimelineRecord(
                entity_type=str(row["entity_type"]),
                entity_id=str(row["entity_id"]),
                title=str(row["title"]),
                occurred_at=str(row["occurred_at"]),
                review_status=str(row["review_status"]),
            )
            for row in rows
        )

    def get_source_context(self, source_reference_id: str) -> SourceContextRecord | None:
        source = self.get_source_reference(source_reference_id)
        if source is None:
            return None
        claim_ids = self._column_values(
            """
            SELECT claim_id AS id FROM claim_source_references
            WHERE source_reference_id = ? ORDER BY claim_id
            """,
            (source_reference_id,),
        )
        relation_ids = self._column_values(
            """
            SELECT relation_id AS id FROM relation_source_references
            WHERE source_reference_id = ? ORDER BY relation_id
            """,
            (source_reference_id,),
        )
        finding_ids = self._column_values(
            """
            SELECT finding_id AS id FROM finding_source_references
            WHERE source_reference_id = ? ORDER BY finding_id
            """,
            (source_reference_id,),
        )
        subject_exists = source.source_entity_type == "manual_note" or self.entity_exists(
            source.source_entity_type, source.source_entity_id
        )
        return SourceContextRecord(
            source=source,
            subject_exists=subject_exists,
            linked_claim_ids=claim_ids,
            linked_relation_ids=relation_ids,
            linked_finding_ids=finding_ids,
        )

    def add_review_decision(
        self,
        decision: ReviewDecisionRecord,
        *,
        expected_version: int,
    ) -> ReviewDecisionRecord:
        table = _REVIEW_TABLES.get(decision.subject_type)
        if table is None:
            raise ValidationError("Непідтримуваний review subject type")
        timestamp_column = "" if table == "source_references" else ", updated_at = ?"
        params: tuple[object, ...]
        if table == "source_references":
            params = (
                decision.new_status,
                decision.subject_id,
                expected_version,
            )
        else:
            params = (
                decision.new_status,
                decision.decided_at.isoformat(),
                decision.subject_id,
                expected_version,
            )
        cursor = self._repository._conn.execute(
            f"""
            UPDATE {table}
            SET review_status = ?, version = version + 1{timestamp_column}
            WHERE id = ? AND version = ?
            """,
            params,
        )
        if cursor.rowcount != 1:
            actual = self._repository._conn.execute(
                f"SELECT version FROM {table} WHERE id = ?", (decision.subject_id,)
            ).fetchone()
            if actual is None:
                raise NotFoundError(
                    "Review subject не знайдено", {"resource": decision.subject_type}
                )
            raise ConflictError(
                "Optimistic concurrency conflict",
                {"expectedVersion": expected_version, "actualVersion": int(actual[0])},
            )
        try:
            self._repository._conn.execute(
                """
                INSERT INTO review_decisions(
                    id, subject_type, subject_id, decision, previous_status,
                    new_status, actor_id, decided_at, note,
                    subject_version, decision_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.subject_type,
                    decision.subject_id,
                    decision.decision,
                    decision.previous_status,
                    decision.new_status,
                    decision.actor_id,
                    decision.decided_at.isoformat(),
                    decision.note,
                    decision.subject_version,
                    decision.decision_origin,
                ),
            )
            for source_id in decision.source_reference_ids:
                self._repository._conn.execute(
                    """
                    INSERT INTO review_decision_sources(
                        review_decision_id, source_reference_id
                    ) VALUES (?, ?)
                    """,
                    (decision.decision_id, source_id),
                )
            self._audit(
                "review_evidence_subject",
                "review_decisions",
                decision.decision_id,
                {
                    "subject_type": decision.subject_type,
                    "subject_id": decision.subject_id,
                    "decision": decision.decision,
                    "subject_version": decision.subject_version,
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "review_decision") from exc
        return decision

    def list_review_decisions(
        self,
        subject_type: str,
        subject_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[ReviewDecisionRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT id, subject_type, subject_id, decision, previous_status,
                   new_status, actor_id, decided_at, note,
                   subject_version, decision_origin
            FROM review_decisions
            WHERE subject_type = ? AND subject_id = ?
            ORDER BY decided_at, id
            LIMIT ? OFFSET ?
            """,
            (subject_type, subject_id, limit, offset),
        ).fetchall()
        return tuple(self._review_decision(row) for row in rows)

    def record_finding_observation(
        self,
        finding: FindingRecord,
        *,
        observation_status: str,
        details: Mapping[str, object],
    ) -> FindingRecord:
        current = self.get_finding_by_fingerprint(finding.fingerprint)
        try:
            if current is None:
                self._repository._conn.execute(
                    """
                    INSERT INTO evidence_findings(
                        id, fingerprint, finding_type, title, description,
                        severity, confidence, detector_name, detector_version,
                        processing_run_id, automatic_status, automatic_version,
                        review_status, review_version, first_observed_at,
                        last_observed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding.finding_id,
                        finding.fingerprint,
                        finding.finding_type,
                        finding.title,
                        finding.description,
                        finding.severity,
                        finding.confidence,
                        finding.detector_name,
                        finding.detector_version,
                        finding.processing_run_id,
                        finding.automatic_status,
                        finding.automatic_version,
                        finding.review_status,
                        finding.review_version,
                        finding.first_observed_at.isoformat(),
                        finding.last_observed_at.isoformat(),
                        finding.created_at.isoformat(),
                        finding.updated_at.isoformat(),
                    ),
                )
            else:
                cursor = self._repository._conn.execute(
                    """
                    UPDATE evidence_findings
                    SET finding_type = ?, title = ?, description = ?, severity = ?,
                        confidence = ?, detector_name = ?, detector_version = ?,
                        processing_run_id = ?, automatic_status = ?,
                        automatic_version = automatic_version + 1,
                        last_observed_at = ?, updated_at = ?
                    WHERE id = ? AND automatic_version = ?
                    """,
                    (
                        finding.finding_type,
                        finding.title,
                        finding.description,
                        finding.severity,
                        finding.confidence,
                        finding.detector_name,
                        finding.detector_version,
                        finding.processing_run_id,
                        finding.automatic_status,
                        finding.last_observed_at.isoformat(),
                        finding.updated_at.isoformat(),
                        current.finding_id,
                        current.automatic_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConflictError(
                        "Automatic finding було recompute-нуто паралельно",
                        {"resource": "finding"},
                    )
            finding_id = current.finding_id if current is not None else finding.finding_id
            self._repository._conn.execute(
                """
                INSERT INTO finding_observations(
                    finding_id, processing_run_id, observation_status,
                    detector_name, detector_version, severity, confidence,
                    details_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    finding.processing_run_id,
                    observation_status,
                    finding.detector_name,
                    finding.detector_version,
                    finding.severity,
                    finding.confidence,
                    json.dumps(dict(details), ensure_ascii=False, sort_keys=True),
                    finding.last_observed_at.isoformat(),
                ),
            )
            for subject in finding.subjects:
                self._repository._conn.execute(
                    """
                    INSERT OR IGNORE INTO finding_subjects(
                        finding_id, subject_type, subject_id
                    ) VALUES (?, ?, ?)
                    """,
                    (finding_id, subject.entity_type, subject.entity_id),
                )
            for source_id in finding.source_reference_ids:
                self._repository._conn.execute(
                    """
                    INSERT OR IGNORE INTO finding_source_references(
                        finding_id, source_reference_id
                    ) VALUES (?, ?)
                    """,
                    (finding_id, source_id),
                )
            self._audit(
                "record_finding_observation",
                "evidence_findings",
                finding_id,
                {
                    "finding_type": finding.finding_type,
                    "automatic_status": finding.automatic_status,
                    "detector_version": finding.detector_version,
                    "subject_count": len(finding.subjects),
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "finding") from exc
        saved = self.get_finding(finding_id)
        if saved is None:
            raise RuntimeError("Finding disappeared after insert")
        return saved

    def get_finding(self, finding_id: str) -> FindingRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT id, fingerprint, finding_type, title, description, severity,
                   confidence, detector_name, detector_version, processing_run_id,
                   automatic_status, automatic_version, review_status, review_version,
                   first_observed_at, last_observed_at, created_at, updated_at
            FROM evidence_findings WHERE id = ?
            """,
            (finding_id,),
        ).fetchone()
        return self._finding(row) if row is not None else None

    def get_finding_by_fingerprint(self, fingerprint: str) -> FindingRecord | None:
        row = self._repository._conn.execute(
            "SELECT id FROM evidence_findings WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return self.get_finding(str(row["id"])) if row is not None else None

    def review_finding(
        self,
        decision: ReviewDecisionRecord,
        *,
        expected_version: int,
    ) -> FindingRecord:
        cursor = self._repository._conn.execute(
            """
            UPDATE evidence_findings
            SET review_status = ?, review_version = review_version + 1,
                updated_at = ?
            WHERE id = ? AND review_version = ?
            """,
            (
                decision.new_status,
                decision.decided_at.isoformat(),
                decision.subject_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            row = self._repository._conn.execute(
                "SELECT review_version FROM evidence_findings WHERE id = ?",
                (decision.subject_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("Finding не знайдено", {"resource": "finding"})
            raise ConflictError(
                "Optimistic concurrency conflict",
                {"expectedVersion": expected_version, "actualVersion": int(row[0])},
            )
        try:
            self._repository._conn.execute(
                """
                INSERT INTO finding_review_decisions(
                    id, finding_id, decision, previous_status, new_status,
                    actor_id, subject_version, decided_at, note, decision_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.subject_id,
                    decision.decision,
                    decision.previous_status,
                    decision.new_status,
                    decision.actor_id,
                    decision.subject_version,
                    decision.decided_at.isoformat(),
                    decision.note,
                    decision.decision_origin,
                ),
            )
            for source_id in decision.source_reference_ids:
                self._repository._conn.execute(
                    """
                    INSERT INTO finding_review_decision_sources(
                        finding_review_decision_id, source_reference_id
                    ) VALUES (?, ?)
                    """,
                    (decision.decision_id, source_id),
                )
            self._audit(
                "review_finding",
                "finding_review_decisions",
                decision.decision_id,
                {
                    "finding_id": decision.subject_id,
                    "decision": decision.decision,
                    "review_version": decision.subject_version,
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "finding_review") from exc
        saved = self.get_finding(decision.subject_id)
        if saved is None:
            raise RuntimeError("Finding disappeared after review")
        return saved

    def list_finding_reviews(
        self,
        finding_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[ReviewDecisionRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT id, finding_id, decision, previous_status, new_status,
                   actor_id, subject_version, decided_at, note, decision_origin
            FROM finding_review_decisions
            WHERE finding_id = ?
            ORDER BY decided_at, id
            LIMIT ? OFFSET ?
            """,
            (finding_id, limit, offset),
        ).fetchall()
        return tuple(self._finding_review(row) for row in rows)

    def compatibility_import_seen(self, source_token: str) -> bool:
        return (
            self._repository._conn.execute(
                "SELECT 1 FROM compatibility_review_imports WHERE source_token = ?",
                (source_token,),
            ).fetchone()
            is not None
        )

    def record_compatibility_import(
        self,
        *,
        source_token: str,
        subject_type: str,
        imported_count: int,
        imported_at: datetime,
    ) -> None:
        self._repository._conn.execute(
            """
            INSERT INTO compatibility_review_imports(
                source_token, subject_type, imported_count, imported_at
            ) VALUES (?, ?, ?, ?)
            """,
            (source_token, subject_type, imported_count, imported_at.isoformat()),
        )
        self._audit(
            "import_compatibility_review",
            "compatibility_review_imports",
            source_token,
            {"subject_type": subject_type, "imported_count": imported_count},
        )

    def set_compatibility_review(
        self,
        review: CompatibilityReviewRecord,
        *,
        decision_id: str,
        actor_id: str,
        expected_version: int | None,
        decision_origin: str,
    ) -> CompatibilityReviewRecord:
        current = self._compatibility_review(review.subject_type, review.external_id)
        previous_status = current.current_status if current is not None else None
        try:
            if current is None:
                if expected_version is not None:
                    raise ConflictError(
                        "Compatibility review не існує для expected version",
                        {"expectedVersion": expected_version, "actualVersion": 0},
                    )
                self._repository._conn.execute(
                    """
                    INSERT INTO compatibility_review_states(
                        subject_type, external_id, current_status,
                        note, version, updated_at
                    ) VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (
                        review.subject_type,
                        review.external_id,
                        review.current_status,
                        review.note,
                        review.updated_at.isoformat(),
                    ),
                )
                version = 1
            else:
                if expected_version is None:
                    expected_version = current.version
                cursor = self._repository._conn.execute(
                    """
                    UPDATE compatibility_review_states
                    SET current_status = ?, note = ?, version = version + 1,
                        updated_at = ?
                    WHERE subject_type = ? AND external_id = ? AND version = ?
                    """,
                    (
                        review.current_status,
                        review.note,
                        review.updated_at.isoformat(),
                        review.subject_type,
                        review.external_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    actual = self._compatibility_review(review.subject_type, review.external_id)
                    raise ConflictError(
                        "Optimistic concurrency conflict",
                        {
                            "expectedVersion": expected_version,
                            "actualVersion": actual.version if actual is not None else 0,
                        },
                    )
                version = expected_version + 1
            self._repository._conn.execute(
                """
                INSERT INTO compatibility_review_decisions(
                    id, subject_type, external_id, previous_status, new_status,
                    actor_id, subject_version, decided_at, note, decision_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    review.subject_type,
                    review.external_id,
                    previous_status,
                    review.current_status,
                    actor_id,
                    version,
                    review.updated_at.isoformat(),
                    review.note,
                    decision_origin,
                ),
            )
            self._audit(
                "review_compatibility_subject",
                "compatibility_review_decisions",
                decision_id,
                {
                    "subject_type": review.subject_type,
                    "external_id": review.external_id,
                    "subject_version": version,
                    "decision_origin": decision_origin,
                },
            )
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, "compatibility_review") from exc
        saved = self._compatibility_review(review.subject_type, review.external_id)
        if saved is None:
            raise RuntimeError("Compatibility review disappeared after save")
        return saved

    def list_compatibility_reviews(
        self,
        subject_type: str,
    ) -> tuple[CompatibilityReviewRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT subject_type, external_id, current_status, note, version, updated_at
            FROM compatibility_review_states
            WHERE subject_type = ?
            ORDER BY external_id
            """,
            (subject_type,),
        ).fetchall()
        return tuple(self._compatibility_review_row(row) for row in rows)

    def _actor(self, row: sqlite3.Row) -> EvidenceActorRecord:
        actor_id = str(row["id"])
        return EvidenceActorRecord(
            actor_id=actor_id,
            actor_type=str(row["actor_type"]),
            display_name=self._optional_text(row["display_name"]) or actor_id,
            normalized_name=self._optional_text(row["normalized_name"]),
            review_status=str(row["review_status"]),
            notes=self._optional_text(row["notes"]),
            version=int(row["version"]),
            created_at=self._datetime(row["created_at"]),
            updated_at=self._datetime(row["updated_at"]),
            memberships=self._memberships("actor", actor_id),
            source_reference_ids=self._source_ids_for_entity("actor", actor_id),
        )

    def _document(self, row: sqlite3.Row) -> EvidenceDocumentRecord:
        document_id = str(row["id"])
        return EvidenceDocumentRecord(
            document_id=document_id,
            title=self._optional_text(row["title"]) or document_id,
            label=self._optional_text(row["label"])
            or self._optional_text(row["title"])
            or document_id,
            document_type=self._optional_text(row["doc_type"]),
            category=self._optional_text(row["category"]),
            source=self._optional_text(row["source"]),
            origin_format=self._optional_text(row["origin_format"]),
            summary=self._optional_text(row["summary"]),
            process_role=self._optional_text(row["process_role"]),
            classification=str(row["classification"]),
            review_status=str(row["review_status"]),
            is_key=bool(row["is_key"]),
            version=int(row["version"]),
            created_at=self._datetime(row["created_at"]),
            updated_at=self._datetime(row["updated_at"]),
            memberships=self._memberships("document", document_id),
            file_ids=self._column_values(
                "SELECT id FROM file_objects WHERE document_id = ? ORDER BY created_at, id",
                (document_id,),
            ),
            actor_ids=self._relation_endpoint_ids(document_id, "document", "actor"),
            event_ids=self._column_values(
                "SELECT event_id AS id FROM event_documents WHERE document_id = ? ORDER BY event_id",
                (document_id,),
            ),
            attachment_document_ids=self._column_values(
                """
                SELECT target_document_id AS id FROM document_links
                WHERE source_document_id = ? AND target_document_id IS NOT NULL
                ORDER BY target_document_id
                """,
                (document_id,),
            ),
            claim_ids=self._column_values(
                """
                SELECT id FROM claims WHERE subject_type = 'document' AND subject_id = ?
                UNION
                SELECT claim_id AS id FROM claim_basis_documents WHERE document_id = ?
                ORDER BY id
                """,
                (document_id, document_id),
            ),
            relation_ids=self._column_values(
                """
                SELECT id FROM evidence_relations
                WHERE (from_type = 'document' AND from_id = ?)
                   OR (to_type = 'document' AND to_id = ?)
                UNION
                SELECT relation_id AS id FROM relation_basis_documents WHERE document_id = ?
                ORDER BY id
                """,
                (document_id, document_id, document_id),
            ),
            source_reference_ids=self._source_ids_for_entity("document", document_id),
        )

    def _event(self, row: sqlite3.Row) -> EvidenceEventRecord:
        event_id = str(row["id"])
        return EvidenceEventRecord(
            event_id=event_id,
            title=self._optional_text(row["title"]) or event_id,
            event_type=self._optional_text(row["interaction_type"]),
            event_at=self._optional_text(row["event_at"]),
            description=self._optional_text(row["description"]),
            workflow_status=self._optional_text(row["workflow_status"]),
            classification=str(row["classification"]),
            review_status=str(row["review_status"]),
            process_consequence=self._optional_text(row["process_consequence"]),
            next_action=self._optional_text(row["next_action"]),
            deadline=self._optional_text(row["deadline"]),
            version=int(row["version"]),
            created_at=self._datetime(row["created_at"]),
            updated_at=self._datetime(row["updated_at"]),
            memberships=self._memberships("event", event_id),
            actor_ids=self._column_values(
                "SELECT actor_id AS id FROM event_actor_links WHERE event_id = ? ORDER BY actor_id",
                (event_id,),
            ),
            document_ids=self._column_values(
                "SELECT document_id AS id FROM event_documents WHERE event_id = ? ORDER BY document_id",
                (event_id,),
            ),
            claim_ids=self._column_values(
                "SELECT id FROM claims WHERE subject_type = 'event' AND subject_id = ? ORDER BY id",
                (event_id,),
            ),
            relation_ids=self._column_values(
                """
                SELECT id FROM evidence_relations
                WHERE (from_type = 'event' AND from_id = ?)
                   OR (to_type = 'event' AND to_id = ?)
                ORDER BY id
                """,
                (event_id, event_id),
            ),
            source_reference_ids=self._source_ids_for_entity("event", event_id),
        )

    def _source(self, row: sqlite3.Row) -> SourceReferenceRecord:
        return SourceReferenceRecord(
            source_reference_id=str(row["id"]),
            source_entity_type=str(row["source_entity_type"]),
            source_entity_id=str(row["source_entity_id"]),
            source_file_id=self._optional_text(row["source_file_id"]),
            location_type=str(row["location_type"]),
            location_value=self._optional_text(row["location_value"]),
            excerpt=self._optional_text(row["excerpt"]),
            source_sha256=self._optional_text(row["source_sha256"]),
            review_status=str(row["review_status"]),
            created_by=str(row["created_by"]),
            created_at=self._datetime(row["created_at"]),
            note=self._optional_text(row["note"]),
            version=int(row["version"]),
        )

    def _claim(self, row: sqlite3.Row) -> ClaimRecord:
        claim_id = str(row["id"])
        return ClaimRecord(
            claim_id=claim_id,
            subject_type=str(row["subject_type"]),
            subject_id=str(row["subject_id"]),
            claim_text=str(row["claim_text"]),
            classification=str(row["classification"]),
            review_status=str(row["review_status"]),
            uncertainty_note=self._optional_text(row["uncertainty_note"]),
            process_consequence=self._optional_text(row["process_consequence"]),
            version=int(row["version"]),
            created_at=self._datetime(row["created_at"]),
            updated_at=self._datetime(row["updated_at"]),
            asserted_by_actor_ids=self._column_values(
                "SELECT actor_id AS id FROM claim_assertors WHERE claim_id = ? ORDER BY actor_id",
                (claim_id,),
            ),
            basis_document_ids=self._column_values(
                """
                SELECT document_id AS id FROM claim_basis_documents
                WHERE claim_id = ? ORDER BY document_id
                """,
                (claim_id,),
            ),
            source_reference_ids=self._column_values(
                """
                SELECT source_reference_id AS id FROM claim_source_references
                WHERE claim_id = ? ORDER BY source_reference_id
                """,
                (claim_id,),
            ),
            review_decision_ids=self._column_values(
                """
                SELECT id FROM review_decisions
                WHERE subject_type = 'claim' AND subject_id = ?
                ORDER BY decided_at, id
                """,
                (claim_id,),
            ),
            memberships=self._memberships("claim", claim_id),
        )

    def _relation(self, row: sqlite3.Row) -> EvidenceRelationRecord:
        relation_id = str(row["id"])
        return EvidenceRelationRecord(
            relation_id=relation_id,
            from_type=str(row["from_type"]),
            from_id=str(row["from_id"]),
            to_type=str(row["to_type"]),
            to_id=str(row["to_id"]),
            relation_type=str(row["relation_type"]),
            label=self._optional_text(row["label"]),
            classification=str(row["classification"]),
            review_status=str(row["review_status"]),
            uncertainty_note=self._optional_text(row["uncertainty_note"]),
            valid_from=self._optional_text(row["valid_from"]),
            valid_to=self._optional_text(row["valid_to"]),
            version=int(row["version"]),
            created_at=self._datetime(row["created_at"]),
            updated_at=self._datetime(row["updated_at"]),
            basis_document_ids=self._column_values(
                """
                SELECT document_id AS id FROM relation_basis_documents
                WHERE relation_id = ? ORDER BY document_id
                """,
                (relation_id,),
            ),
            source_reference_ids=self._column_values(
                """
                SELECT source_reference_id AS id FROM relation_source_references
                WHERE relation_id = ? ORDER BY source_reference_id
                """,
                (relation_id,),
            ),
            review_decision_ids=self._column_values(
                """
                SELECT id FROM review_decisions
                WHERE subject_type = 'relation' AND subject_id = ?
                ORDER BY decided_at, id
                """,
                (relation_id,),
            ),
        )

    def _finding(self, row: sqlite3.Row) -> FindingRecord:
        finding_id = str(row["id"])
        subjects = self._repository._conn.execute(
            """
            SELECT subject_type, subject_id FROM finding_subjects
            WHERE finding_id = ? ORDER BY subject_type, subject_id
            """,
            (finding_id,),
        ).fetchall()
        return FindingRecord(
            finding_id=finding_id,
            fingerprint=str(row["fingerprint"]),
            finding_type=str(row["finding_type"]),
            title=str(row["title"]),
            description=str(row["description"]),
            severity=str(row["severity"]),
            confidence=float(row["confidence"]) if row["confidence"] is not None else None,
            detector_name=str(row["detector_name"]),
            detector_version=str(row["detector_version"]),
            processing_run_id=self._optional_text(row["processing_run_id"]),
            automatic_status=str(row["automatic_status"]),
            automatic_version=int(row["automatic_version"]),
            review_status=str(row["review_status"]),
            review_version=int(row["review_version"]),
            first_observed_at=self._datetime(row["first_observed_at"]),
            last_observed_at=self._datetime(row["last_observed_at"]),
            created_at=self._datetime(row["created_at"]),
            updated_at=self._datetime(row["updated_at"]),
            subjects=tuple(
                EntityReferenceRecord(str(item["subject_type"]), str(item["subject_id"]))
                for item in subjects
            ),
            source_reference_ids=self._column_values(
                """
                SELECT source_reference_id AS id FROM finding_source_references
                WHERE finding_id = ? ORDER BY source_reference_id
                """,
                (finding_id,),
            ),
            review_decision_ids=self._column_values(
                """
                SELECT id FROM finding_review_decisions
                WHERE finding_id = ? ORDER BY decided_at, id
                """,
                (finding_id,),
            ),
        )

    def _review_decision(self, row: sqlite3.Row) -> ReviewDecisionRecord:
        decision_id = str(row["id"])
        return ReviewDecisionRecord(
            decision_id=decision_id,
            subject_type=str(row["subject_type"]),
            subject_id=str(row["subject_id"]),
            decision=str(row["decision"]),
            previous_status=self._optional_text(row["previous_status"]),
            new_status=str(row["new_status"]),
            actor_id=str(row["actor_id"]),
            decided_at=self._datetime(row["decided_at"]),
            note=self._optional_text(row["note"]),
            subject_version=int(row["subject_version"]),
            decision_origin=str(row["decision_origin"]),
            source_reference_ids=self._column_values(
                """
                SELECT source_reference_id AS id FROM review_decision_sources
                WHERE review_decision_id = ? ORDER BY source_reference_id
                """,
                (decision_id,),
            ),
        )

    def _finding_review(self, row: sqlite3.Row) -> ReviewDecisionRecord:
        decision_id = str(row["id"])
        return ReviewDecisionRecord(
            decision_id=decision_id,
            subject_type="finding",
            subject_id=str(row["finding_id"]),
            decision=str(row["decision"]),
            previous_status=self._optional_text(row["previous_status"]),
            new_status=str(row["new_status"]),
            actor_id=str(row["actor_id"]),
            decided_at=self._datetime(row["decided_at"]),
            note=self._optional_text(row["note"]),
            subject_version=int(row["subject_version"]),
            decision_origin=str(row["decision_origin"]),
            source_reference_ids=self._column_values(
                """
                SELECT source_reference_id AS id FROM finding_review_decision_sources
                WHERE finding_review_decision_id = ? ORDER BY source_reference_id
                """,
                (decision_id,),
            ),
        )

    def _memberships(
        self, entity_type: str, entity_id: str
    ) -> tuple[EvidenceMembershipRecord, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT id, entity_type, entity_id, context_type, context_id,
                   role, is_primary, source_reference_id, review_status,
                   note, created_at, updated_at
            FROM entity_memberships
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY context_type, context_id, role, id
            """,
            (entity_type, entity_id),
        ).fetchall()
        return tuple(
            EvidenceMembershipRecord(
                membership_id=str(row["id"]),
                entity_type=str(row["entity_type"]),
                entity_id=str(row["entity_id"]),
                context_type=str(row["context_type"]),
                context_id=str(row["context_id"]),
                role=str(row["role"]),
                is_primary=bool(row["is_primary"]),
                source_reference_id=self._optional_text(row["source_reference_id"]),
                review_status=str(row["review_status"]),
                note=self._optional_text(row["note"]),
                created_at=self._datetime(row["created_at"]),
                updated_at=self._datetime(row["updated_at"]),
            )
            for row in rows
        )

    def _insert_memberships(
        self,
        memberships: tuple[EvidenceMembershipRecord, ...],
        *,
        actor_id: str,
    ) -> None:
        for membership in memberships:
            self._repository._conn.execute(
                """
                INSERT INTO entity_memberships(
                    id, entity_type, entity_id, context_type, context_id,
                    role, is_primary, source_reference_id, review_status,
                    valid_from, valid_to, note, created_at, updated_at,
                    origin, actor_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, 'manual_command', ?)
                """,
                (
                    membership.membership_id,
                    membership.entity_type,
                    membership.entity_id,
                    membership.context_type,
                    membership.context_id,
                    membership.role,
                    int(membership.is_primary),
                    membership.source_reference_id,
                    membership.review_status,
                    membership.note,
                    membership.created_at.isoformat(),
                    membership.updated_at.isoformat(),
                    actor_id,
                ),
            )

    def _context_entity_ids(
        self,
        entity_type: str,
        case_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[str, ...]:
        rows = self._repository._conn.execute(
            """
            SELECT entity_id AS id, MIN(created_at) AS first_created
            FROM entity_memberships
            WHERE entity_type = ? AND context_type = 'case' AND context_id = ?
            GROUP BY entity_id
            ORDER BY first_created, entity_id
            LIMIT ? OFFSET ?
            """,
            (entity_type, case_id, limit, offset),
        ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def _source_ids_for_entity(self, entity_type: str, entity_id: str) -> tuple[str, ...]:
        return self._column_values(
            """
            SELECT id FROM source_references
            WHERE source_entity_type = ? AND source_entity_id = ?
            ORDER BY created_at, id
            """,
            (entity_type, entity_id),
        )

    def _relation_endpoint_ids(
        self, source_id: str, source_type: str, target_type: str
    ) -> tuple[str, ...]:
        return self._column_values(
            """
            SELECT to_id AS id FROM evidence_relations
            WHERE from_type = ? AND from_id = ? AND to_type = ?
            UNION
            SELECT from_id AS id FROM evidence_relations
            WHERE to_type = ? AND to_id = ? AND from_type = ?
            ORDER BY id
            """,
            (source_type, source_id, target_type, source_type, source_id, target_type),
        )

    def _compatibility_review(
        self, subject_type: str, external_id: str
    ) -> CompatibilityReviewRecord | None:
        row = self._repository._conn.execute(
            """
            SELECT subject_type, external_id, current_status, note, version, updated_at
            FROM compatibility_review_states
            WHERE subject_type = ? AND external_id = ?
            """,
            (subject_type, external_id),
        ).fetchone()
        return self._compatibility_review_row(row) if row is not None else None

    def _compatibility_review_row(self, row: sqlite3.Row) -> CompatibilityReviewRecord:
        return CompatibilityReviewRecord(
            subject_type=str(row["subject_type"]),
            external_id=str(row["external_id"]),
            current_status=str(row["current_status"]),
            note=self._optional_text(row["note"]),
            version=int(row["version"]),
            updated_at=self._datetime(row["updated_at"]),
        )

    def _column_values(self, query: str, params: tuple[object, ...]) -> tuple[str, ...]:
        return tuple(
            str(row["id"]) for row in self._repository._conn.execute(query, params).fetchall()
        )

    def _audit(
        self,
        action: str,
        entity_table: str,
        entity_id: str,
        details: Mapping[str, object],
    ) -> None:
        self._repository._record_audit_event(
            action,
            entity_table,
            entity_id,
            dict(details),
        )

    @staticmethod
    def _datetime(value: object) -> datetime:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _integrity_error(
        error: sqlite3.IntegrityError, resource: str
    ) -> ConflictError | ValidationError:
        message = str(error)
        if "FOREIGN KEY" in message:
            return ValidationError("Пов’язану evidence entity не знайдено", {"resource": resource})
        if "CHECK" in message:
            return ValidationError("Evidence value порушує SQLite contract", {"resource": resource})
        if "UNIQUE" in message:
            return ConflictError("Evidence entity уже існує", {"resource": resource})
        return ConflictError("Конфлікт збереження evidence entity", {"resource": resource})
