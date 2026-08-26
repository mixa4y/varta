from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path
from typing import cast

from case_docket.application import SetCompatibilityReviewCommand
from caseflow.server import CaseFlowState, Handler, ThreadingHTTPServer


SYNTHETIC_REVIEWER = "user:synthetic-c08-api-reviewer"


class RunningVarta:
    def __init__(self, root: Path):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.server.server_address[1])
        self.state = CaseFlowState(root, "127.0.0.1", self.port)
        self.state.prepare_database()
        self.server.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            assert isinstance(payload, dict)
            return response.status, payload
        finally:
            connection.close()

    def json_command(
        self,
        path: str,
        payload: dict[str, object],
    ) -> tuple[int, dict[str, object]]:
        return self.request(
            "POST",
            path,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Caseflow-Token": self.state.csrf_token,
            },
        )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.state.close()


def _entity(response: dict[str, object], key: str) -> dict[str, object]:
    value = response[key]
    assert isinstance(value, dict)
    return value


def _entities(response: dict[str, object], key: str) -> list[dict[str, object]]:
    value = response[key]
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return cast(list[dict[str, object]], value)


def test_evidence_http_vertical_slice_conflict_and_restart(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-c08-api"
    root.mkdir()
    first = RunningVarta(root)
    try:
        status, response = first.json_command(
            "/api/v1/workspace/cases",
            {
                "actorId": SYNTHETIC_REVIEWER,
                "caseNumber": "000/0000/00",
                "name": "Синтетична C08 API справа",
            },
        )
        assert status == 201
        case_id = str(_entity(response, "case")["caseId"])

        status, response = first.json_command(
            "/api/v1/workspace/proceedings",
            {
                "actorId": SYNTHETIC_REVIEWER,
                "caseIds": [case_id],
                "proceedingNumber": "synthetic-c08-api-proceeding",
                "name": "Синтетичне C08 API провадження",
            },
        )
        assert status == 201
        proceeding_id = str(_entity(response, "proceeding")["proceedingId"])
        memberships = [
            {
                "contextType": "case",
                "contextId": case_id,
                "role": "evidence",
                "isPrimary": True,
            },
            {
                "contextType": "proceeding",
                "contextId": proceeding_id,
                "role": "evidence",
            },
        ]

        status, response = first.json_command(
            "/api/v1/evidence/actors",
            {
                "createdBy": SYNTHETIC_REVIEWER,
                "actorType": "organization",
                "displayName": "Синтетична C08 API організація",
                "memberships": memberships,
            },
        )
        assert status == 201
        actor_id = str(_entity(response, "actor")["id"])

        status, response = first.json_command(
            "/api/v1/evidence/documents",
            {
                "createdBy": SYNTHETIC_REVIEWER,
                "title": "Синтетичний C08 API документ",
                "documentType": "synthetic_notice",
                "classification": "unverified",
                "memberships": memberships,
            },
        )
        assert status == 201
        document_id = str(_entity(response, "document")["id"])

        status, response = first.json_command(
            "/api/v1/evidence/events",
            {
                "createdBy": SYNTHETIC_REVIEWER,
                "title": "Синтетична C08 API подія",
                "eventType": "synthetic_event",
                "eventAt": "2026-01-03T10:00:00+00:00",
                "memberships": memberships,
                "actorIds": [actor_id],
                "documentIds": [document_id],
            },
        )
        assert status == 201
        event_id = str(_entity(response, "event")["id"])

        status, response = first.json_command(
            "/api/v1/evidence/source-references",
            {
                "createdBy": SYNTHETIC_REVIEWER,
                "sourceEntity": {"type": "document", "id": document_id},
                "locationType": "document",
                "note": "Синтетичне джерело",
            },
        )
        assert status == 201
        source_id = str(_entity(response, "sourceReference")["id"])

        status, response = first.json_command(
            "/api/v1/evidence/claims",
            {
                "createdBy": SYNTHETIC_REVIEWER,
                "subject": {"type": "event", "id": event_id},
                "text": "Синтетичне C08 API твердження",
                "classification": "confirmed_fact",
                "assertedByActorIds": [actor_id],
                "basisDocumentIds": [document_id],
                "sourceReferenceIds": [source_id],
                "memberships": memberships,
            },
        )
        assert status == 201
        claim_id = str(_entity(response, "claim")["id"])

        status, response = first.json_command(
            "/api/v1/evidence/relations",
            {
                "createdBy": SYNTHETIC_REVIEWER,
                "from": {"type": "event", "id": event_id},
                "to": {"type": "claim", "id": claim_id},
                "relationType": "supports",
                "classification": "confirmed_fact",
                "basisDocumentIds": [document_id],
                "sourceReferenceIds": [source_id],
            },
        )
        assert status == 201
        relation_id = str(_entity(response, "relation")["id"])

        status, response = first.json_command(
            "/api/v1/evidence/findings",
            {
                "fingerprint": "C" * 64,
                "findingType": "synthetic_consistency_check",
                "title": "Синтетична C08 API перевірка",
                "description": "Автоматичне синтетичне спостереження",
                "severity": "info",
                "confidence": 0.75,
                "detector": {"name": "synthetic-c08-api", "version": "1.0"},
                "subjects": [{"type": "claim", "id": claim_id}],
                "sourceReferenceIds": [source_id],
            },
        )
        assert status == 201
        finding_id = str(_entity(response, "finding")["id"])

        status, response = first.json_command(
            "/api/v1/evidence/reviews",
            {
                "subject": {"type": "claim", "id": claim_id},
                "decision": "confirm",
                "newStatus": "confirmed",
                "actorId": SYNTHETIC_REVIEWER,
                "expectedVersion": 1,
                "sourceReferenceIds": [source_id],
            },
        )
        assert status == 201
        assert _entity(response, "reviewDecision")["subjectVersion"] == 2

        status, response = first.json_command(
            f"/api/v1/evidence/findings/{finding_id}/reviews",
            {
                "decision": "resolve",
                "newStatus": "resolved",
                "actorId": SYNTHETIC_REVIEWER,
                "expectedVersion": 0,
                "sourceReferenceIds": [source_id],
            },
        )
        assert status == 201
        assert _entity(response, "finding")["reviewVersion"] == 1

        status, response = first.request(
            "GET", f"/api/v1/evidence/cases/{case_id}?limit=100&offset=0"
        )
        assert status == 200
        case_evidence = _entity(response, "evidence")
        assert case_evidence["authority"] == "sqlite"
        assert case_evidence["caseId"] == case_id
        assert [item["id"] for item in _entities(case_evidence, "actors")] == [actor_id]
        assert [item["id"] for item in _entities(case_evidence, "documents")] == [document_id]
        assert [item["id"] for item in _entities(case_evidence, "events")] == [event_id]
        assert [item["id"] for item in _entities(case_evidence, "claims")] == [claim_id]
        assert [item["id"] for item in _entities(case_evidence, "relations")] == [relation_id]
        assert [item["id"] for item in _entities(case_evidence, "findings")] == [finding_id]

        status, response = first.request(
            "GET", f"/api/v1/evidence/timeline?caseId={case_id}&limit=1&offset=0"
        )
        assert status == 200
        assert response["authority"] == "sqlite"
        assert response["page"] == {"limit": 1, "offset": 0}
        assert len(_entities(response, "timeline")) == 1

        status, response = first.request("GET", f"/api/v1/evidence/source-references/{source_id}")
        assert status == 200
        source_context = _entity(response, "sourceContext")
        assert source_context["subjectExists"] is True
        assert source_context["linkedClaimIds"] == [claim_id]
        assert source_context["linkedRelationIds"] == [relation_id]
        assert source_context["linkedFindingIds"] == [finding_id]

        status, response = first.request(
            "GET",
            f"/api/v1/evidence/reviews?subjectType=claim&subjectId={claim_id}",
        )
        assert status == 200
        assert response["authority"] == "sqlite"
        assert len(_entities(response, "reviewDecisions")) == 1

        status, response = first.json_command(
            "/api/v1/evidence/reviews",
            {
                "subject": {"type": "claim", "id": claim_id},
                "decision": "confirm",
                "newStatus": "confirmed",
                "actorId": SYNTHETIC_REVIEWER,
                "expectedVersion": 1,
            },
        )
        assert status == 409
        assert _entity(response, "error")["code"] == "conflict"

        status, response = first.json_command(
            "/api/v1/evidence/actors",
            {
                "createdBy": SYNTHETIC_REVIEWER,
                "actorType": "person",
                "displayName": "Синтетична особа",
                "unknownField": True,
            },
        )
        assert status == 422
        assert _entity(response, "error")["code"] == "request_validation_error"
    finally:
        first.close()

    second = RunningVarta(root)
    try:
        status, response = second.request(
            "GET", f"/api/v1/evidence/cases/{case_id}?limit=100&offset=0"
        )
        assert status == 200
        case_evidence = _entity(response, "evidence")
        claims = _entities(case_evidence, "claims")
        findings = _entities(case_evidence, "findings")
        assert [item["id"] for item in claims] == [claim_id]
        assert claims[0]["reviewStatus"] == "confirmed"
        assert findings[0]["reviewStatus"] == "resolved"
    finally:
        second.close()


def test_legacy_review_json_is_import_only_and_sqlite_survives_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-c08-compatibility"
    state_directory = root / ".caseflow"
    state_directory.mkdir(parents=True)
    document_path = state_directory / "document_status.json"
    anomaly_path = state_directory / "anomaly_status.json"
    document_bytes = json.dumps(
        {
            "DOC_SYNTHETIC_C08": {
                "status": "needs_review",
                "note": "Синтетичний legacy document review",
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    anomaly_id = "D" * 24
    anomaly_bytes = json.dumps(
        {
            anomaly_id: {
                "status": "open",
                "note": "Синтетичний legacy finding review",
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    document_path.write_bytes(document_bytes)
    anomaly_path.write_bytes(anomaly_bytes)

    first = RunningVarta(root)
    try:
        documents = first.state.evidence_service.list_compatibility_reviews("legacy_document")
        findings = first.state.evidence_service.list_compatibility_reviews("legacy_finding")
        assert [(item.record.external_id, item.record.current_status) for item in documents] == [
            ("DOC_SYNTHETIC_C08", "needs_review")
        ]
        assert [(item.record.external_id, item.record.current_status) for item in findings] == [
            (anomaly_id, "open")
        ]

        document_review = first.state.evidence_service.set_compatibility_review(
            SetCompatibilityReviewCommand(
                subject_type="legacy_document",
                external_id="DOC_SYNTHETIC_C08",
                status="completed",
                actor_id=SYNTHETIC_REVIEWER,
                expected_version=1,
            )
        )
        finding_review = first.state.evidence_service.set_compatibility_review(
            SetCompatibilityReviewCommand(
                subject_type="legacy_finding",
                external_id=anomaly_id,
                status="resolved",
                actor_id=SYNTHETIC_REVIEWER,
                expected_version=1,
            )
        )
        assert document_review.record.version == 2
        assert finding_review.record.version == 2
        assert document_path.read_bytes() == document_bytes
        assert anomaly_path.read_bytes() == anomaly_bytes
    finally:
        first.close()

    second = RunningVarta(root)
    try:
        documents = second.state.evidence_service.list_compatibility_reviews("legacy_document")
        findings = second.state.evidence_service.list_compatibility_reviews("legacy_finding")
        assert [(item.record.current_status, item.record.version) for item in documents] == [
            ("completed", 2)
        ]
        assert [(item.record.current_status, item.record.version) for item in findings] == [
            ("resolved", 2)
        ]
        assert document_path.read_bytes() == document_bytes
        assert anomaly_path.read_bytes() == anomaly_bytes
    finally:
        second.close()
