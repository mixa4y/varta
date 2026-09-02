"""Deterministic Evidence Map projection from the typed R02 source query."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from jsonschema import Draft202012Validator

from .evidence import (
    ClaimDTO, EvidenceActorDTO, EvidenceDocumentDTO, EvidenceEventDTO,
    EvidenceRelationDTO, ReviewDecisionDTO, SourceReferenceDTO,
)
from .evidence_map_export import RecordEvidenceMapExportCommand
from .evidence_map_source import EvidenceMapSourceDTO, EvidenceMapSourceQuery, EvidenceMapSourceQueryService


class EvidenceMapProjectionError(ValueError):
    pass


class EvidenceMapExportRecorder(Protocol):
    def record_validated(self, command: RecordEvidenceMapExportCommand) -> object: ...


class EvidenceMapProjectionService:
    def __init__(self, source: EvidenceMapSourceQueryService, audit: EvidenceMapExportRecorder,
                 *, schema_path: Path | None = None, generated_by: str = "varta-c11") -> None:
        self._source = source
        self._audit = audit
        self._schema_path = schema_path or Path(__file__).parents[2] / "config" / "schemas" / "map-data.schema.json"
        self._generated_by = generated_by

    def project(self, request: EvidenceMapSourceQuery, *, export_id: str) -> dict[str, object]:
        source = self._source.query(request)
        result = self._build(source, export_id)
        schema = json.loads(self._schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(result)
        digest = self.snapshot_sha256(result)
        command = RecordEvidenceMapExportCommand(
            export_id=export_id, case_id=source.case_id,
            case_profile_id=f"profile-{source.case_id}-{source.profile_version}",
            schema_version="1.1.0", product_version="0.1.0",
            export_profile=source.export_profile, source_revision=source.source_revision,
            source_snapshot_sha256=digest, generated_by=self._generated_by,
            generated_at=source.data_cutoff, data_cutoff=source.data_cutoff,
            limitations=(), sealed=True,
        )
        self._audit.record_validated(command)
        result["export"]["sourceSnapshotSha256"] = digest  # type: ignore[index]
        return result

    @staticmethod
    def _build(source: EvidenceMapSourceDTO, export_id: str) -> dict[str, object]:
        def scoped(items):
            if any(item.case_id != source.case_id for item in items):
                raise EvidenceMapProjectionError("Source returned a cross-case item")
            return items

        actors = [EvidenceActorDTO(x.record).to_dict() for x in scoped(source.evidence.actors)]
        documents = [EvidenceDocumentDTO(x.record).to_dict() for x in scoped(source.evidence.documents)]
        events = [EvidenceEventDTO(x.record).to_dict() for x in scoped(source.evidence.events)]
        claims = [ClaimDTO(x.record).to_dict() for x in scoped(source.evidence.claims)]
        relations = [EvidenceRelationDTO(x.record).to_dict() for x in scoped(source.evidence.relations)]
        sources = [SourceReferenceDTO(x.record).to_dict() for x in scoped(source.evidence.source_references)]
        reviews = [ReviewDecisionDTO(x.record).to_dict() for x in scoped(source.reviews)
                   if x.record.subject_type != "finding"]
        known = {"case": {source.case_id}, "proceeding": {x.record.proceeding_id for x in source.proceedings},
                 "actor": {x["id"] for x in actors}, "document": {x["id"] for x in documents},
                 "event": {x["id"] for x in events}, "claim": {x["id"] for x in claims},
                 "relation": {x["id"] for x in relations}, "source_reference": {x["id"] for x in sources},
                 "file": {x.record.file_id for x in source.files}}
        errors = []
        for item in claims:
            ref = item["subject"]
            if ref["id"] not in known.get(ref["type"], set()):
                errors.append(f"claim:{item['id']}")
            if item["reviewStatus"] == "confirmed" and not item["sourceReferenceIds"] and not item["basisDocumentIds"]:
                errors.append(f"claim-basis:{item['id']}")
        for item in relations:
            for typ, ident in ((item["fromType"], item["fromId"]), (item["toType"], item["toId"])):
                if ident not in known.get(typ, set()):
                    errors.append(f"relation:{item['id']}")
            if item["reviewStatus"] == "confirmed" and not item["sourceReferenceIds"] and not item["basisDocumentIds"]:
                errors.append(f"relation-basis:{item['id']}")
        for item in sources:
            ref = item["sourceEntity"]
            if ref["id"] not in known.get(ref["type"], set()):
                errors.append(f"source:{item['id']}" )
        if errors:
            raise EvidenceMapProjectionError("Invalid Evidence Map references/basis: " + ", ".join(errors))
        case = source.case
        profile = source.profile.profile
        case_data = profile.get("case", {}) if isinstance(profile, dict) else {}
        files = [{"id": x.record.file_id, "documentId": None, "kind": x.record.kind, "originalName": x.record.original_name, "managedName": x.record.managed_name, "sourceRelativePath": x.record.source_relative_path, "storageReference": x.record.storage_reference, "extension": None, "mediaType": None, "sizeBytes": x.record.bytes, "sha256": x.record.sha256, "signatureFileIds": [], "derivedFileIds": [], "processingRunIds": [], "integrityStatus": x.record.integrity_status, "sourceReferenceIds": [], "reviewStatus": "unreviewed", "manualReviewReason": None} for x in source.files]
        proceedings = [{"id": x.record.proceeding_id, "caseId": source.case_id, "number": x.record.proceeding_number or x.record.proceeding_id, "folderKey": x.record.proceeding_id, "aliases": [], "title": x.record.name or x.record.proceeding_id, "label": x.record.name or x.record.proceeding_id, "subtitle": None, "kind": None, "courtActorIds": [], "instance": None, "status": x.record.status, "result": None, "summary": None, "dates": [], "applicantActorIds": [], "participantActorIds": [], "judgeActorIds": [], "originDocumentIds": [], "originEventIds": [], "documentIds": [], "eventIds": [], "claimIds": [], "relatedProceedingIds": [], "sourceReferenceIds": [], "reviewStatus": "unreviewed"} for x in source.proceedings]
        result = {"schemaVersion": "1.1.0", "export": {"exportId": export_id, "generatedAt": None, "profile": source.export_profile, "productVersion": "0.1.0", "profileVersion": source.profile_version, "sourceRevision": source.source_revision, "sourceSnapshotSha256": None, "dataCutoff": source.data_cutoff, "language": "uk", "sealed": True, "redactionPolicyId": None, "knownLimitations": []}, "case": {"id": case.case_id, "number": case.case_number, "numberStatus": "confirmed" if case.case_number else "unknown", "folderKey": case.case_id, "title": case.name or case.case_id, "aliases": case_data.get("aliases", []), "caseType": case_data.get("caseType"), "jurisdiction": case_data.get("jurisdiction"), "primaryCourtActorId": case_data.get("primaryCourtActorId"), "dates": [], "actorIds": sorted(known["actor"]), "proceedingIds": sorted(known["proceeding"]), "claimIds": sorted(known["claim"]), "sourceReferenceIds": sorted(known["source_reference"]), "reviewStatus": "unreviewed", "tags": []}, "proceedings": proceedings, "actors": actors, "files": files, "documents": documents, "events": events, "claims": claims, "relations": relations, "sourceReferences": sources, "reviewDecisions": reviews, "inventory": {"proceedingCount": len(source.proceedings), "actorCount": len(actors), "logicalDocumentCount": len(documents), "physicalFileCount": len(files), "uniqueSha256Count": len({x["sha256"] for x in files}), "eventCount": len(events), "claimCount": len(claims), "relationCount": len(relations), "sourceReferenceCount": len(sources), "reviewDecisionCount": len(reviews), "manualReviewRequiredCount": 0, "missingSourceCount": 0, "unregisteredFileCount": 0, "duplicateSignalCount": 0, "countsByProceeding": {}, "historicalClaims": []}, "exclusions": []}
        EvidenceMapProjectionService._strip_internal_metadata(result)
        return result

    @staticmethod
    def _strip_internal_metadata(value: object) -> None:
        if isinstance(value, dict):
            value.pop("version", None)
            value.pop("origin", None)
            value.pop("subjectVersion", None)
            if "subject" in value and "text" in value:
                value.pop("memberships", None)
            if "contextType" in value and "contextId" in value:
                value.pop("id", None)
            for child in value.values():
                EvidenceMapProjectionService._strip_internal_metadata(child)
        elif isinstance(value, list):
            for child in value:
                EvidenceMapProjectionService._strip_internal_metadata(child)

    @staticmethod
    def canonical_json(snapshot: dict[str, object]) -> bytes:
        value = json.loads(json.dumps(snapshot, ensure_ascii=False))
        value["export"].update({"exportId": None, "generatedAt": None, "sourceSnapshotSha256": None})
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def snapshot_sha256(cls, snapshot: dict[str, object]) -> str:
        return hashlib.sha256(cls.canonical_json(snapshot)).hexdigest()
