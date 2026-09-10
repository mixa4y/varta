from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path
from case_docket.application.case_read_models import (
    AttachmentReferenceDTO,
    CaseChronologyDTO,
    ChronologyItemDTO,
    ContactCardDTO,
    ContactIdentifierDTO,
    ContactRoleDTO,
    DocumentCardDTO,
    DocumentFileDTO,
    EntityNeighborhoodDTO,
    NeighborhoodEdgeDTO,
    NeighborhoodNodeDTO,
)

from .sqlite_connection import SQLiteConnectionFactory, SQLiteConnectionPolicy


class CaseReadModelIntegrityError(RuntimeError):
    """Raised when a case-scoped read model would hide invalid or leaking data."""


class SQLiteCaseReadModelRepository:
    def __init__(
        self,
        database_path: Path,
        *,
        connection_policy: SQLiteConnectionPolicy | None = None,
    ):
        self._database_path = Path(database_path)
        self._policy = connection_policy or SQLiteConnectionPolicy()

    def get_contact_card(
        self, case_id: str, profile_version: str, contact_id: str
    ) -> ContactCardDTO | None:
        connection = self._connect()
        try:
            if not self._is_scoped(connection, case_id, "contact", contact_id):
                return None
            contact = connection.execute(
                "SELECT * FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            if contact is None:
                return None
            identifiers = tuple(
                ContactIdentifierDTO(
                    identifier_id=str(row["id"]),
                    identifier_type=str(row["identifier_type"]),
                    normalized_value=str(row["normalized_value"]),
                    display_value=str(row["display_value"]),
                    source_reference_id=(
                        str(row["source_reference_id"])
                        if row["source_reference_id"] is not None
                        else None
                    ),
                    review_status=str(row["review_status"]),
                )
                for row in connection.execute(
                    """
                    SELECT * FROM contact_identifiers
                    WHERE contact_id = ?
                    ORDER BY identifier_type, normalized_value, id
                    """,
                    (contact_id,),
                ).fetchall()
            )
            roles = tuple(
                ContactRoleDTO(
                    role_id=str(row["id"]),
                    role=str(row["role"]) if row["role"] is not None else None,
                    proceeding_id=(
                        str(row["proceeding_id"]) if row["proceeding_id"] is not None else None
                    ),
                    active=bool(row["active"]),
                    review_status="unreviewed",
                )
                for row in connection.execute(
                    """
                    SELECT id, role, proceeding_id, active
                    FROM case_participants
                    WHERE case_id = ? AND contact_id = ?
                    ORDER BY id
                    """,
                    (case_id, contact_id),
                ).fetchall()
            )
            proceeding_ids = self._values(
                connection,
                """
                SELECT proceeding_id AS id FROM contact_proceedings
                WHERE contact_id = ? AND proceeding_id IN (
                    SELECT proceeding_id FROM case_proceedings WHERE case_id = ?
                )
                UNION
                SELECT proceeding_id AS id FROM case_participants
                WHERE contact_id = ? AND case_id = ? AND proceeding_id IS NOT NULL
                ORDER BY id
                """,
                (contact_id, case_id, contact_id, case_id),
            )
            event_ids = self._values(
                connection,
                """
                SELECT ec.event_id AS id FROM event_contacts ec
                JOIN case_events ce ON ce.event_id = ec.event_id
                WHERE ec.contact_id = ? AND ce.case_id = ?
                ORDER BY id
                """,
                (contact_id, case_id),
            )
            document_ids = self._values(
                connection,
                """
                SELECT DISTINCT ed.document_id AS id
                FROM event_contacts ec
                JOIN case_events ce ON ce.event_id = ec.event_id
                JOIN event_documents ed ON ed.event_id = ec.event_id
                JOIN case_documents cd ON cd.document_id = ed.document_id AND cd.case_id = ce.case_id
                WHERE ec.contact_id = ? AND ce.case_id = ?
                ORDER BY id
                """,
                (contact_id, case_id),
            )
            actor_ids = self._values(
                connection,
                """
                SELECT actor_id AS id FROM contact_actor_links
                WHERE case_id = ? AND contact_id = ? ORDER BY actor_id
                """,
                (case_id, contact_id),
            )
            source_ids = self._values(
                connection,
                """
                SELECT id FROM source_references
                WHERE source_entity_type = 'contact' AND source_entity_id = ? ORDER BY id
                """,
                (contact_id,),
            )
            merge_split = self._values(
                connection,
                """
                SELECT id FROM review_decisions
                WHERE subject_type = 'contact' AND subject_id = ?
                  AND decision IN ('merge', 'split')
                ORDER BY decided_at, id
                """,
                (contact_id,),
            )
            link_statuses = self._values(
                connection,
                """
                SELECT DISTINCT review_status AS id FROM contact_actor_links
                WHERE case_id = ? AND contact_id = ? ORDER BY id
                """,
                (case_id, contact_id),
            )
            review_status = link_statuses[0] if len(link_statuses) == 1 else "unreviewed"
            return ContactCardDTO(
                case_id=case_id,
                profile_version=profile_version,
                contact_id=contact_id,
                full_name=str(contact["full_name"]),
                short_name=str(contact["short_name"]) if contact["short_name"] else None,
                participant_type=str(contact["participant_type"]),
                identifiers=identifiers,
                roles=roles,
                proceeding_ids=proceeding_ids,
                event_ids=event_ids,
                document_ids=document_ids,
                actor_ids=actor_ids,
                source_reference_ids=source_ids,
                review_status=review_status,
                version=1,
                merge_split_review_ids=merge_split,
            )
        finally:
            connection.close()

    def get_document_card(
        self, case_id: str, profile_version: str, document_id: str
    ) -> DocumentCardDTO | None:
        connection = self._connect()
        try:
            if not self._is_scoped(connection, case_id, "document", document_id):
                return None
            document = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if document is None:
                return None
            files = tuple(
                DocumentFileDTO(
                    file_id=str(row["id"]),
                    document_file_id=(
                        str(row["document_file_id"])
                        if row["document_file_id"] is not None
                        else None
                    ),
                    role=str(row["role"]) if row["role"] is not None else None,
                    sequence_number=(
                        int(row["sequence_number"]) if row["sequence_number"] is not None else None
                    ),
                    size_bytes=int(row["size_bytes"]) if row["size_bytes"] is not None else None,
                    sha256=str(row["sha256"]) if row["sha256"] is not None else None,
                    integrity_status=str(row["integrity_status"]),
                    review_status=str(row["review_status"]),
                )
                for row in connection.execute(
                    """
                    SELECT f.*, df.role, df.sequence_number
                    FROM file_objects f
                    LEFT JOIN document_files df ON df.id = f.document_file_id
                    WHERE f.document_id = ?
                    ORDER BY COALESCE(df.sequence_number, 2147483647), f.id
                    """,
                    (document_id,),
                ).fetchall()
            )
            attachments = tuple(
                AttachmentReferenceDTO(
                    attachment_reference_id=str(row["id"]),
                    attachment_id=str(row["attachment_id"]),
                    file_id=str(row["file_id"]) if row["file_id"] is not None else None,
                    match_status=str(row["match_status"]),
                    match_method=str(row["match_method"]) if row["match_method"] else None,
                )
                for row in connection.execute(
                    """
                    SELECT ar.*
                    FROM airtable_attachment_references ar
                    JOIN airtable_record_map rm
                      ON rm.airtable_table_id = ar.source_table_id
                     AND rm.airtable_record_id = ar.source_record_id
                    WHERE rm.local_id = ?
                    ORDER BY ar.id
                    """,
                    (document_id,),
                ).fetchall()
            )
            proceeding_ids = self._values(
                connection,
                """
                SELECT pd.proceeding_id AS id FROM proceeding_documents pd
                JOIN case_proceedings cp ON cp.proceeding_id = pd.proceeding_id
                WHERE pd.document_id = ? AND cp.case_id = ? ORDER BY id
                """,
                (document_id, case_id),
            )
            event_ids = self._values(
                connection,
                """
                SELECT ed.event_id AS id FROM event_documents ed
                JOIN case_events ce ON ce.event_id = ed.event_id
                WHERE ed.document_id = ? AND ce.case_id = ? ORDER BY id
                """,
                (document_id, case_id),
            )
            actor_ids = self._values(
                connection,
                """
                SELECT DISTINCT eal.actor_id AS id FROM event_documents ed
                JOIN case_events ce ON ce.event_id = ed.event_id
                JOIN event_actor_links eal ON eal.event_id = ed.event_id
                WHERE ed.document_id = ? AND ce.case_id = ? ORDER BY id
                """,
                (document_id, case_id),
            )
            incoming = self._values(
                connection,
                "SELECT source_document_id AS id FROM document_links WHERE target_document_id = ? ORDER BY id",
                (document_id,),
            )
            outgoing = self._values(
                connection,
                "SELECT target_document_id AS id FROM document_links WHERE source_document_id = ? ORDER BY id",
                (document_id,),
            )
            claim_ids = self._values(
                connection,
                "SELECT id FROM claims WHERE subject_type = 'document' AND subject_id = ? ORDER BY id",
                (document_id,),
            )
            relation_ids = self._values(
                connection,
                """
                SELECT id FROM evidence_relations
                WHERE (from_type = 'document' AND from_id = ?)
                   OR (to_type = 'document' AND to_id = ?)
                ORDER BY id
                """,
                (document_id, document_id),
            )
            flags = self._values(
                connection,
                "SELECT id FROM compliance_flags WHERE document_id = ? ORDER BY id",
                (document_id,),
            )
            matches = self._values(
                connection,
                """
                SELECT id FROM document_version_match
                WHERE user_document_id = ? OR court_document_id = ? ORDER BY id
                """,
                (document_id, document_id),
            )
            sources = self._values(
                connection,
                """
                SELECT id FROM source_references
                WHERE source_entity_type = 'document' AND source_entity_id = ? ORDER BY id
                """,
                (document_id,),
            )
            reviews = self._values(
                connection,
                """
                SELECT id FROM review_decisions
                WHERE subject_type = 'document' AND subject_id = ? ORDER BY decided_at, id
                """,
                (document_id,),
            )
            reconciliation = tuple(
                sorted(
                    {
                        *(item.integrity_status for item in files),
                        *(item.match_status for item in attachments),
                    }
                )
            )
            return DocumentCardDTO(
                case_id=case_id,
                profile_version=profile_version,
                document_id=document_id,
                title=str(document["title"]) if document["title"] else None,
                document_type=str(document["doc_type"]) if document["doc_type"] else None,
                classification=str(document["classification"]),
                review_status=str(document["review_status"]),
                version=int(document["version"]),
                files=files,
                attachments=attachments,
                proceeding_ids=proceeding_ids,
                event_ids=event_ids,
                actor_ids=actor_ids,
                incoming_document_ids=incoming,
                outgoing_document_ids=outgoing,
                claim_ids=claim_ids,
                relation_ids=relation_ids,
                compliance_flag_ids=flags,
                version_match_ids=matches,
                source_reference_ids=sources,
                review_decision_ids=reviews,
                reconciliation_statuses=reconciliation,
            )
        finally:
            connection.close()

    def list_chronology(self, case_id: str, profile_version: str) -> CaseChronologyDTO:
        connection = self._connect()
        try:
            dated: list[ChronologyItemDTO] = []
            scoped_types = ("case", "proceeding", "document", "event")
            for entity_type in scoped_types:
                entity_ids = self._scoped_ids(connection, case_id, entity_type)
                for entity_id in entity_ids:
                    rows = connection.execute(
                        """
                        SELECT * FROM entity_dates
                        WHERE entity_type = ? AND entity_id = ?
                        ORDER BY COALESCE(date_value, ''), date_role, id
                        """,
                        (entity_type, entity_id),
                    ).fetchall()
                    for row in rows:
                        dated.append(
                            self._chronology_item(
                                connection,
                                case_id,
                                entity_type,
                                entity_id,
                                date_role=str(row["date_role"]),
                                occurred=(str(row["date_value"]) if row["date_value"] else None),
                                precision=str(row["precision"]),
                                timezone=(str(row["timezone"]) if row["timezone"] else None),
                                review_status=str(row["review_status"]),
                            )
                        )
            dated.sort(key=lambda item: item.ordering_key)
            dated_keys = {(item.entity_type, item.entity_id) for item in dated}
            undated = [
                self._chronology_item(
                    connection,
                    case_id,
                    entity_type,
                    entity_id,
                    date_role="unknown",
                    occurred=None,
                    precision="unknown",
                    timezone=None,
                    review_status="unreviewed",
                )
                for entity_type in scoped_types
                for entity_id in self._scoped_ids(connection, case_id, entity_type)
                if (entity_type, entity_id) not in dated_keys
            ]
            undated.sort(key=lambda item: item.ordering_key)
            return CaseChronologyDTO(case_id, profile_version, tuple(dated), tuple(undated))
        finally:
            connection.close()

    def get_neighborhood(
        self,
        case_id: str,
        profile_version: str,
        entity_type: str,
        entity_id: str,
        depth: int,
    ) -> EntityNeighborhoodDTO | None:
        connection = self._connect()
        try:
            if not self._is_scoped(connection, case_id, entity_type, entity_id):
                return None
            edges = self._case_edges(connection, case_id)
            root_key = (entity_type, entity_id)
            distance = {root_key: 0}
            queue = deque([root_key])
            selected: dict[str, NeighborhoodEdgeDTO] = {}
            while queue:
                current = queue.popleft()
                current_distance = distance[current]
                if current_distance >= depth:
                    continue
                for edge in edges:
                    endpoints = ((edge.from_type, edge.from_id), (edge.to_type, edge.to_id))
                    if current not in endpoints:
                        continue
                    selected[edge.edge_id] = edge
                    other = endpoints[1] if endpoints[0] == current else endpoints[0]
                    if other not in distance:
                        distance[other] = current_distance + 1
                        queue.append(other)
            nodes = tuple(
                NeighborhoodNodeDTO(kind, identifier)
                for kind, identifier in sorted(distance, key=lambda item: (item[0], item[1]))
            )
            return EntityNeighborhoodDTO(
                case_id=case_id,
                profile_version=profile_version,
                root=NeighborhoodNodeDTO(entity_type, entity_id),
                depth=depth,
                nodes=nodes,
                edges=tuple(selected[key] for key in sorted(selected)),
            )
        finally:
            connection.close()

    def _case_edges(
        self, connection: sqlite3.Connection, case_id: str
    ) -> tuple[NeighborhoodEdgeDTO, ...]:
        edges: list[NeighborhoodEdgeDTO] = []
        structural = (
            ("case_proceedings", "proceeding", "proceeding_id", "case", "case_id", "member_of"),
            ("case_documents", "document", "document_id", "case", "case_id", "member_of"),
            ("case_events", "event", "event_id", "case", "case_id", "member_of"),
            ("contact_cases", "contact", "contact_id", "case", "case_id", "member_of"),
        )
        for table, from_type, from_column, to_type, to_column, relation_type in structural:
            rows = connection.execute(
                f"SELECT {from_column} AS from_id, {to_column} AS to_id FROM {table} WHERE case_id = ?",
                (case_id,),
            ).fetchall()
            for row in rows:
                edges.append(
                    self._structural_edge(
                        table,
                        from_type,
                        str(row["from_id"]),
                        to_type,
                        str(row["to_id"]),
                        relation_type,
                    )
                )
        for row in connection.execute(
            "SELECT contact_id, actor_id FROM contact_actor_links WHERE case_id = ?",
            (case_id,),
        ).fetchall():
            edges.append(
                self._structural_edge(
                    "contact_actor_links",
                    "contact",
                    str(row["contact_id"]),
                    "actor",
                    str(row["actor_id"]),
                    "represents",
                )
            )
        for row in connection.execute(
            """
            SELECT eal.event_id, eal.actor_id, eal.role FROM event_actor_links eal
            JOIN case_events ce ON ce.event_id = eal.event_id WHERE ce.case_id = ?
            """,
            (case_id,),
        ).fetchall():
            relation_type = (
                "sender_of"
                if row["role"] == "sender"
                else ("recipient_of" if row["role"] == "recipient" else "participant_in")
            )
            edges.append(
                self._structural_edge(
                    "event_actor_links",
                    "actor",
                    str(row["actor_id"]),
                    "event",
                    str(row["event_id"]),
                    relation_type,
                )
            )
        for row in connection.execute(
            """
            SELECT ed.event_id, ed.document_id FROM event_documents ed
            JOIN case_events ce ON ce.event_id = ed.event_id
            JOIN case_documents cd ON cd.document_id = ed.document_id AND cd.case_id = ce.case_id
            WHERE ce.case_id = ?
            """,
            (case_id,),
        ).fetchall():
            edges.append(
                self._structural_edge(
                    "event_documents",
                    "event",
                    str(row["event_id"]),
                    "document",
                    str(row["document_id"]),
                    "documented_by",
                )
            )
        for row in connection.execute("SELECT * FROM evidence_relations ORDER BY id").fetchall():
            from_type, from_id = str(row["from_type"]), str(row["from_id"])
            to_type, to_id = str(row["to_type"]), str(row["to_id"])
            from_scoped = self._is_scoped(connection, case_id, from_type, from_id)
            to_scoped = self._is_scoped(connection, case_id, to_type, to_id)
            if from_scoped != to_scoped:
                raise CaseReadModelIntegrityError("Cross-case evidence relation detected")
            if not from_scoped:
                continue
            relation_type = str(row["relation_type"])
            self._validate_relation_type(connection, relation_type, from_type, to_type)
            basis = self._values(
                connection,
                "SELECT document_id AS id FROM relation_basis_documents WHERE relation_id = ? ORDER BY id",
                (str(row["id"]),),
            )
            sources = self._values(
                connection,
                "SELECT source_reference_id AS id FROM relation_source_references WHERE relation_id = ? ORDER BY id",
                (str(row["id"]),),
            )
            if str(row["classification"]) == "confirmed_fact" and not (basis or sources):
                raise CaseReadModelIntegrityError("Confirmed relation has no source basis")
            edges.append(
                NeighborhoodEdgeDTO(
                    edge_id=str(row["id"]),
                    edge_kind="semantic",
                    from_type=from_type,
                    from_id=from_id,
                    to_type=to_type,
                    to_id=to_id,
                    relation_type=relation_type,
                    classification=str(row["classification"]),
                    review_status=str(row["review_status"]),
                    basis_document_ids=basis,
                    source_reference_ids=sources,
                )
            )
        return tuple(sorted(edges, key=lambda item: item.edge_id))

    def _chronology_item(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        entity_type: str,
        entity_id: str,
        *,
        date_role: str,
        occurred: str | None,
        precision: str,
        timezone: str | None,
        review_status: str,
    ) -> ChronologyItemDTO:
        title, description, classification = self._entity_text(connection, entity_type, entity_id)
        proceedings = self._related_proceedings(connection, case_id, entity_type, entity_id)
        actors = self._related_actors(connection, case_id, entity_type, entity_id)
        documents = self._related_documents(connection, case_id, entity_type, entity_id)
        sources = self._values(
            connection,
            """
            SELECT id FROM source_references
            WHERE source_entity_type = ? AND source_entity_id = ? ORDER BY id
            """,
            (entity_type, entity_id),
        )
        precision_order = {
            "exact_datetime": "0",
            "exact_date": "1",
            "month": "2",
            "year": "3",
            "approximate": "4",
            "unknown": "9",
        }.get(precision, "8")
        ordering = f"{occurred or '~'}|{precision_order}|{entity_type}|{entity_id}|{date_role}"
        return ChronologyItemDTO(
            entity_type=entity_type,
            entity_id=entity_id,
            occurred=occurred,
            date_role=date_role,
            precision=precision,
            timezone=timezone,
            title=title,
            description=description,
            proceeding_ids=proceedings,
            actor_ids=actors,
            document_ids=documents,
            source_reference_ids=sources,
            classification=classification,
            review_status=review_status,
            ordering_key=ordering,
        )

    @staticmethod
    def _entity_text(
        connection: sqlite3.Connection, entity_type: str, entity_id: str
    ) -> tuple[str | None, str | None, str]:
        specs = {
            "case": ("cases", "name", "short_description", "'unverified'"),
            "proceeding": ("proceedings", "name", "notes", "'unverified'"),
            "document": ("documents", "title", "summary", "classification"),
            "event": ("events", "title", "description", "classification"),
        }
        if entity_type not in specs:
            return None, None, "unverified"
        table, title_column, description_column, classification_column = specs[entity_type]
        row = connection.execute(
            f"SELECT {title_column} AS title, {description_column} AS description, "
            f"{classification_column} AS classification FROM {table} WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            raise CaseReadModelIntegrityError("Chronology entity endpoint is missing")
        return (
            str(row["title"]) if row["title"] is not None else None,
            str(row["description"]) if row["description"] is not None else None,
            str(row["classification"]),
        )

    def _related_proceedings(
        self, connection: sqlite3.Connection, case_id: str, entity_type: str, entity_id: str
    ) -> tuple[str, ...]:
        if entity_type == "proceeding":
            return (entity_id,)
        if entity_type == "document":
            return self._values(
                connection,
                """
                SELECT pd.proceeding_id AS id FROM proceeding_documents pd
                JOIN case_proceedings cp ON cp.proceeding_id = pd.proceeding_id
                WHERE pd.document_id = ? AND cp.case_id = ? ORDER BY id
                """,
                (entity_id, case_id),
            )
        if entity_type == "event":
            return self._values(
                connection,
                """
                SELECT pe.proceeding_id AS id FROM proceeding_events pe
                JOIN case_proceedings cp ON cp.proceeding_id = pe.proceeding_id
                WHERE pe.event_id = ? AND cp.case_id = ? ORDER BY id
                """,
                (entity_id, case_id),
            )
        return ()

    def _related_actors(
        self, connection: sqlite3.Connection, case_id: str, entity_type: str, entity_id: str
    ) -> tuple[str, ...]:
        if entity_type == "event":
            return self._values(
                connection,
                "SELECT actor_id AS id FROM event_actor_links WHERE event_id = ? ORDER BY id",
                (entity_id,),
            )
        if entity_type == "document":
            return self._values(
                connection,
                """
                SELECT DISTINCT eal.actor_id AS id FROM event_documents ed
                JOIN event_actor_links eal ON eal.event_id = ed.event_id
                JOIN case_events ce ON ce.event_id = ed.event_id
                WHERE ed.document_id = ? AND ce.case_id = ? ORDER BY id
                """,
                (entity_id, case_id),
            )
        return ()

    def _related_documents(
        self, connection: sqlite3.Connection, case_id: str, entity_type: str, entity_id: str
    ) -> tuple[str, ...]:
        if entity_type == "document":
            return (entity_id,)
        if entity_type == "event":
            return self._values(
                connection,
                """
                SELECT ed.document_id AS id FROM event_documents ed
                JOIN case_documents cd ON cd.document_id = ed.document_id
                WHERE ed.event_id = ? AND cd.case_id = ? ORDER BY id
                """,
                (entity_id, case_id),
            )
        return ()

    def _scoped_ids(
        self, connection: sqlite3.Connection, case_id: str, entity_type: str
    ) -> tuple[str, ...]:
        if entity_type == "case":
            return (case_id,) if self._is_scoped(connection, case_id, "case", case_id) else ()
        tables = {
            "proceeding": ("case_proceedings", "proceeding_id"),
            "document": ("case_documents", "document_id"),
            "event": ("case_events", "event_id"),
            "contact": ("contact_cases", "contact_id"),
        }
        if entity_type in tables:
            table, column = tables[entity_type]
            return self._values(
                connection,
                f"SELECT {column} AS id FROM {table} WHERE case_id = ? ORDER BY id",
                (case_id,),
            )
        return self._values(
            connection,
            """
            SELECT entity_id AS id FROM entity_memberships
            WHERE context_type = 'case' AND context_id = ? AND entity_type = ? ORDER BY id
            """,
            (case_id, entity_type),
        )

    def _is_scoped(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        entity_type: str,
        entity_id: str,
    ) -> bool:
        if entity_type == "case":
            return (
                entity_id == case_id
                and connection.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone()
                is not None
            )
        return entity_id in self._scoped_ids(connection, case_id, entity_type)

    @staticmethod
    def _validate_relation_type(
        connection: sqlite3.Connection,
        relation_type: str,
        from_type: str,
        to_type: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT allowed_from_types_json, allowed_to_types_json
            FROM relation_type_catalog
            WHERE relation_type = ? AND active = 1
            ORDER BY catalog_version DESC LIMIT 1
            """,
            (relation_type,),
        ).fetchone()
        if row is None:
            raise CaseReadModelIntegrityError("Relation type is absent from active catalog")
        from_types = json.loads(str(row["allowed_from_types_json"]))
        to_types = json.loads(str(row["allowed_to_types_json"]))
        if from_type not in from_types or to_type not in to_types:
            raise CaseReadModelIntegrityError("Relation endpoint type violates catalog")

    @staticmethod
    def _structural_edge(
        source: str,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        relation_type: str,
    ) -> NeighborhoodEdgeDTO:
        edge_id = f"structural:{source}:{from_type}:{from_id}:{to_type}:{to_id}:{relation_type}"
        return NeighborhoodEdgeDTO(
            edge_id=edge_id,
            edge_kind="structural",
            from_type=from_type,
            from_id=from_id,
            to_type=to_type,
            to_id=to_id,
            relation_type=relation_type,
            classification="unverified",
            review_status="unreviewed",
            basis_document_ids=(),
            source_reference_ids=(),
        )

    def _connect(self) -> sqlite3.Connection:
        return SQLiteConnectionFactory(self._database_path, self._policy).connect()

    @staticmethod
    def _values(
        connection: sqlite3.Connection, sql: str, parameters: tuple[object, ...]
    ) -> tuple[str, ...]:
        return tuple(str(row["id"]) for row in connection.execute(sql, parameters).fetchall())
