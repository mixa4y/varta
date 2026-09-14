"""C11: deterministic, read-only projection; explicit, transaction-owned audit."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .evidence import (
    ClaimDTO,
    EvidenceActorDTO,
    EvidenceDocumentDTO,
    EvidenceEventDTO,
    EvidenceRelationDTO,
    FindingDTO,
    ReviewDecisionDTO,
    SourceReferenceDTO,
)
from .evidence_map_export import EvidenceMapExportAuditPort, RecordEvidenceMapExportCommand
from .evidence_map_source import (
    EvidenceMapSourceDTO,
    EvidenceMapSourceQuery,
    EvidenceMapSourceQueryService,
    JsonValue,
)

SCHEMA_VERSION = "1.2.0"
PRODUCT_VERSION = "0.1.0"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config/schemas/map-data-v1.2.schema.json"
_TIMESTAMPS = {
    "generatedAt",
    "dataCutoff",
    "createdAt",
    "decidedAt",
    "firstObservedAt",
    "lastObservedAt",
}


class EvidenceMapProjectionError(ValueError):
    """No valid snapshot can be produced; callers must not silently replace it."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
        raise EvidenceMapProjectionError("Expected a JSON object")
    return {str(k): v for k, v in value.items()}


def _normal(value: object, key: str = "") -> JsonValue:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        if key in _TIMESTAMPS or (key in {"date", "validFrom", "validTo"} and "T" in value):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise EvidenceMapProjectionError("Invalid projection timestamp") from exc
            if parsed.tzinfo is None:
                raise EvidenceMapProjectionError("Projection timestamp requires a timezone")
            return parsed.astimezone(timezone.utc).isoformat()
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        return {k: _normal(v, k) for k, v in sorted(_object(value).items())}
    if isinstance(value, (list, tuple)):
        # All arrays in the 1.2 projection are sets/multisets, never processing sequences.
        return sorted((_normal(v) for v in value), key=_encoded)
    raise EvidenceMapProjectionError("Unsupported or non-finite JSON value")


def _encoded(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class EvidenceMapProjectionService:
    def __init__(
        self, source: EvidenceMapSourceQueryService, *, schema_path: Path = SCHEMA_PATH
    ) -> None:
        self._source = source
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def project(self, request: EvidenceMapSourceQuery, *, export_id: str) -> dict[str, object]:
        """UI/read caller: no audit port and no database writes."""
        source = self._source.query(request)
        return self._project(source, export_id)

    def export(
        self,
        request: EvidenceMapSourceQuery,
        *,
        export_id: str,
        generated_by: str,
        audit: EvidenceMapExportAuditPort,
    ) -> dict[str, object]:
        """Export caller supplies the transaction/commit boundary; no filesystem writes.

        Returning this object does not certify a sealed offline package (C14).
        """
        source = self._source.query(request)
        snapshot = self._project(source, export_id)
        metadata = _object(snapshot["export"])
        audit.record_validated(
            RecordEvidenceMapExportCommand(
                export_id=export_id,
                case_id=source.case_id,
                case_profile_id=source.profile.case_profile_id,
                schema_version=SCHEMA_VERSION,
                product_version=PRODUCT_VERSION,
                export_profile=source.export_profile,
                source_revision=source.source_revision,
                source_snapshot_sha256=str(metadata["sourceSnapshotSha256"]),
                generated_by=generated_by,
                generated_at=str(metadata["generatedAt"]),
                data_cutoff=str(metadata["dataCutoff"]),
                limitations=tuple(self._limitations(source.export_profile)),
                sealed=False,
            )
        )
        return snapshot

    @staticmethod
    def _limitations(profile: str) -> list[str]:
        result = [
            "Projection only: original bytes/signatures and sealed packaging are not verified.",
            "File associations absent from the typed source are not inferred.",
        ]
        if profile == "metadata_only":
            result.append("Content fields omitted; metadata and identifiers are not anonymized.")
        return result

    def _project(self, source: EvidenceMapSourceDTO, export_id: str) -> dict[str, object]:
        if not export_id.strip() or not source.profile.case_profile_id.strip():
            raise EvidenceMapProjectionError("Export ID and persisted profile ID are required")
        if source.export_profile == "redacted":
            raise EvidenceMapProjectionError("Redacted export requires a reviewed redaction policy")
        if source.export_profile not in {"full_local", "metadata_only"}:
            raise EvidenceMapProjectionError("Unsupported export profile")
        snapshot = self._build(source, export_id)
        normalized = _object(_normal(snapshot))
        self.validate(normalized, verify_hash=False)
        metadata = _object(normalized["export"])
        metadata["sourceSnapshotSha256"] = self.snapshot_sha256(normalized)
        normalized["export"] = metadata
        self.validate(normalized)
        return normalized

    def validate(self, snapshot: dict[str, object], *, verify_hash: bool = True) -> None:
        try:
            self._validator.validate(snapshot)
        except ValidationError as exc:
            # No instance/excerpt in exceptions: caller logs may be public.
            raise EvidenceMapProjectionError(
                "Schema validation failed at " + "/".join(map(str, exc.absolute_path))
            ) from None
        _normal(snapshot)  # Reject non-finite numbers even if a validator accepts them.
        self._validate_links(snapshot)
        if verify_hash:
            actual = _object(snapshot["export"])["sourceSnapshotSha256"]
            if actual != self.snapshot_sha256(snapshot):
                raise EvidenceMapProjectionError("Snapshot hash mismatch")

    @staticmethod
    def canonical_json(snapshot: dict[str, object]) -> bytes:
        value = _object(_normal(snapshot))
        metadata = _object(value["export"])
        for key in ("exportId", "generatedAt", "sourceSnapshotSha256"):
            metadata[key] = None
        value["export"] = metadata
        return _encoded(value).encode("utf-8")

    @classmethod
    def snapshot_sha256(cls, snapshot: dict[str, object]) -> str:
        return hashlib.sha256(cls.canonical_json(snapshot)).hexdigest()

    @staticmethod
    def _build(source: EvidenceMapSourceDTO, export_id: str) -> dict[str, object]:
        actors = [EvidenceActorDTO(x.record).to_dict() for x in source.evidence.actors]
        documents = [EvidenceDocumentDTO(x.record).to_dict() for x in source.evidence.documents]
        events = [EvidenceEventDTO(x.record).to_dict() for x in source.evidence.events]
        claims = [ClaimDTO(x.record).to_dict() for x in source.evidence.claims]
        relations = [EvidenceRelationDTO(x.record).to_dict() for x in source.evidence.relations]
        references = [
            SourceReferenceDTO(x.record).to_dict() for x in source.evidence.source_references
        ]
        file_hashes = {item.record.file_id: item.record.sha256 for item in source.files}
        for source_item in source.evidence.source_references:
            reference = source_item.record
            if (
                reference.source_file_id is not None
                and reference.source_sha256 is not None
                and reference.source_sha256 != file_hashes[reference.source_file_id]
            ):
                raise EvidenceMapProjectionError(
                    "Source reference hash differs from registered file"
                )
        reviews = [ReviewDecisionDTO(x.record).to_dict() for x in source.reviews]
        findings = [FindingDTO(x.record).to_dict() for x in source.findings]
        exclusions: list[dict[str, object]] = [
            {
                "entity": {"type": x.record.entity_type, "id": x.record.entity_id},
                "reasonCode": x.record.reason_code,
                "reason": x.record.reason,
                "sourceReferenceIds": list(x.record.source_reference_ids),
                "reviewStatus": x.record.review_status,
            }
            for x in source.exclusions
        ]
        files: list[dict[str, object]] = []
        for x in source.files:
            record = x.record
            owners = [
                d.record.document_id
                for d in source.evidence.documents
                if record.file_id in d.record.file_ids
            ]
            files.append(
                {
                    "id": record.file_id,
                    "documentId": owners[0] if len(owners) == 1 else None,
                    "kind": record.kind,
                    "originalName": record.original_name,
                    "managedName": record.managed_name,
                    "sourceRelativePath": record.source_relative_path,
                    "storageReference": record.storage_reference,
                    "extension": Path(record.original_name).suffix or None,
                    "mediaType": None,
                    "sizeBytes": record.bytes,
                    "sha256": record.sha256,
                    "signatureFileIds": [],
                    "derivedFileIds": [],
                    "processingRunIds": [],
                    "integrityStatus": record.integrity_status,
                    "sourceReferenceIds": [
                        r.record.source_reference_id
                        for r in source.evidence.source_references
                        if r.record.source_file_id == record.file_id
                    ],
                    "reviewStatus": "unreviewed",
                    "manualReviewReason": None,
                }
            )
        proceedings: list[dict[str, object]] = []
        for proceeding_item in source.proceedings:
            p = proceeding_item.record

            def linked(records: list[dict[str, object]]) -> list[str]:
                result = []
                for record in records:
                    memberships = record.get("memberships", [])
                    if isinstance(memberships, list) and any(
                        _object(m)["contextType"] == "proceeding"
                        and _object(m)["contextId"] == p.proceeding_id
                        for m in memberships
                    ):
                        result.append(str(record["id"]))
                return result

            proceedings.append(
                {
                    "id": p.proceeding_id,
                    "caseId": source.case_id,
                    "number": p.proceeding_number,
                    "folderKey": p.proceeding_id,
                    "aliases": [],
                    "title": p.name or p.proceeding_id,
                    "label": p.name or p.proceeding_id,
                    "subtitle": None,
                    "kind": None,
                    "courtActorIds": [],
                    "instance": None,
                    "status": p.status,
                    "result": None,
                    "summary": None,
                    "dates": [],
                    "applicantActorIds": [],
                    "participantActorIds": [],
                    "judgeActorIds": [],
                    "originDocumentIds": [],
                    "originEventIds": [],
                    "documentIds": linked(documents),
                    "eventIds": linked(events),
                    "claimIds": linked(claims),
                    "relatedProceedingIds": [],
                    "sourceReferenceIds": [],
                    "reviewStatus": "unreviewed",
                }
            )
        case = source.case
        profile_case = _object(source.profile.profile["case"])
        if profile_case["id"] != source.case_id or profile_case["number"] != case.case_number:
            raise EvidenceMapProjectionError(
                "Case profile identity/number differs from case record"
            )
        case_data = {
            "id": case.case_id,
            "number": case.case_number,
            "numberStatus": profile_case["numberStatus"],
            "folderKey": profile_case["folderKey"],
            "title": case.name or case.case_id,
            "aliases": profile_case["aliases"],
            "caseType": profile_case.get("caseType"),
            "jurisdiction": profile_case.get("jurisdiction"),
            "primaryCourtActorId": profile_case.get("primaryCourtActorId"),
            "status": case.status,
            "dates": [],
            "actorIds": [a["id"] for a in actors],
            "proceedingIds": [p["id"] for p in proceedings],
            "claimIds": [c["id"] for c in claims],
            "sourceReferenceIds": [r["id"] for r in references],
            "reviewStatus": "unreviewed",
        }
        groups = [actors, documents, events, claims, relations, references, findings, exclusions]
        manual = sum(
            r.get("reviewStatus") in {"manual_review_required", "in_review", "open"}
            for group in groups
            for r in group
        )
        missing = sum(
            not r.get("sourceReferenceIds") and not r.get("basisDocumentIds")
            for group in (claims, relations)
            for r in group
        )
        inventory = {
            "proceedingCount": len(proceedings),
            "actorCount": len(actors),
            "logicalDocumentCount": len(documents),
            "physicalFileCount": len(files),
            "uniqueSha256Count": len({f["sha256"] for f in files if f["sha256"] is not None}),
            "eventCount": len(events),
            "claimCount": len(claims),
            "relationCount": len(relations),
            "sourceReferenceCount": len(references),
            "reviewDecisionCount": len(reviews),
            "findingCount": len(findings),
            "manualReviewRequiredCount": manual,
            "missingSourceCount": missing,
            "unregisteredFileCount": sum(
                not any(f["id"] in d.record.file_ids for d in source.evidence.documents)
                for f in files
            ),
            "duplicateSignalCount": sum(f["findingType"] == "duplicate" for f in findings),
        }
        snapshot: dict[str, object] = {
            "schemaVersion": SCHEMA_VERSION,
            "export": {
                "exportId": export_id,
                "generatedAt": source.data_cutoff,
                "caseProfileId": source.profile.case_profile_id,
                "profile": source.export_profile,
                "productVersion": PRODUCT_VERSION,
                "profileVersion": source.profile_version,
                "sourceRevision": source.source_revision,
                "sourceSnapshotSha256": None,
                "dataCutoff": source.data_cutoff,
                "language": "uk",
                "sealed": False,
                "redactionPolicyId": None,
                "knownLimitations": EvidenceMapProjectionService._limitations(
                    source.export_profile
                ),
            },
            "case": case_data,
            "proceedings": proceedings,
            "actors": actors,
            "files": files,
            "documents": documents,
            "events": events,
            "claims": claims,
            "relations": relations,
            "sourceReferences": references,
            "reviewDecisions": reviews,
            "findings": findings,
            "exclusions": exclusions,
            "inventory": inventory,
        }
        if source.export_profile == "metadata_only":

            def omit_nested_notes(value: object) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in {"note", "notes"}:
                            value[key] = None
                        else:
                            omit_nested_notes(child)
                elif isinstance(value, list):
                    for child in value:
                        omit_nested_notes(child)

            omit_nested_notes(snapshot)
            for group in [*groups, reviews, proceedings]:
                for item in group:
                    for key in (
                        "excerpt",
                        "summary",
                        "description",
                        "notes",
                        "note",
                        "uncertaintyNote",
                        "processConsequence",
                        "nextAction",
                    ):
                        if key in item:
                            item[key] = None
                    if "text" in item:
                        item["text"] = "[content omitted]"
            for file in files:
                file["storageReference"] = None
                file["sourceRelativePath"] = None
        return snapshot

    @staticmethod
    def _validate_links(snapshot: dict[str, object]) -> None:
        tables = {
            "proceeding": "proceedings",
            "actor": "actors",
            "file": "files",
            "document": "documents",
            "event": "events",
            "claim": "claims",
            "relation": "relations",
            "source_reference": "sourceReferences",
            "review_decision": "reviewDecisions",
            "finding": "findings",
        }
        known = {"case": {str(_object(snapshot["case"])["id"])}}
        for kind, name in tables.items():
            values = snapshot[name]
            if not isinstance(values, list):
                raise EvidenceMapProjectionError("Invalid entity collection")
            ids = [str(_object(v)["id"]) for v in values]
            if len(ids) != len(set(ids)):
                raise EvidenceMapProjectionError("Duplicate entity ID")
            known[kind] = set(ids)
        array_types = {
            "caseIds": "case",
            "proceedingIds": "proceeding",
            "actorIds": "actor",
            "documentIds": "document",
            "fileIds": "file",
            "eventIds": "event",
            "claimIds": "claim",
            "relationIds": "relation",
            "sourceReferenceIds": "source_reference",
            "basisSourceReferenceIds": "source_reference",
            "reviewDecisionIds": "review_decision",
            "basisDocumentIds": "document",
            "assertedByActorIds": "actor",
            "attachmentDocumentIds": "document",
            "signatureFileIds": "file",
            "derivedFileIds": "file",
            "courtActorIds": "actor",
            "applicantActorIds": "actor",
            "participantActorIds": "actor",
            "judgeActorIds": "actor",
            "originDocumentIds": "document",
            "originEventIds": "event",
            "relatedProceedingIds": "proceeding",
        }

        def require(kind: str, identifier: object) -> None:
            if identifier is not None and identifier not in known.get(kind, set()):
                raise EvidenceMapProjectionError("Broken projection reference: " + kind)

        def walk(value: object) -> None:
            if isinstance(value, list):
                for child in value:
                    walk(child)
            elif isinstance(value, Mapping):
                obj = _object(value)
                if "type" in obj and "id" in obj and obj["type"] != "manual_note":
                    require(str(obj["type"]), obj["id"])
                if "contextType" in obj:
                    require(str(obj["contextType"]), obj["contextId"])
                for side in ("from", "to"):
                    if side + "Type" in obj:
                        require(str(obj[side + "Type"]), obj[side + "Id"])
                if (
                    obj.get("classification") == "confirmed_fact"
                    and ("text" in obj or "relationType" in obj)
                    and not obj.get("sourceReferenceIds")
                    and not obj.get("basisDocumentIds")
                ):
                    raise EvidenceMapProjectionError("Confirmed fact has no source basis")
                for key, child in obj.items():
                    if key in array_types and isinstance(child, list):
                        for identifier in child:
                            require(array_types[key], identifier)
                    if key in {"documentId", "sourceFileId", "caseId", "primaryCourtActorId"}:
                        require(
                            {
                                "documentId": "document",
                                "sourceFileId": "file",
                                "caseId": "case",
                                "primaryCourtActorId": "actor",
                            }[key],
                            child,
                        )
                    walk(child)

        walk(snapshot)
