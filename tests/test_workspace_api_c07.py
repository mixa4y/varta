from __future__ import annotations

import http.client
import json
import os
import stat
import threading
from pathlib import Path

from caseflow.server import CaseFlowState, Handler, ThreadingHTTPServer


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


def _multipart(filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "----VartaC07SyntheticBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        "Content-Type: text/plain\r\n"
        "\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def _restore_original_permissions(root: Path) -> None:
    for original in (root / ".varta" / "originals").rglob("original.bin"):
        try:
            os.chmod(original, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass


def test_workspace_api_contract_bootstrap_confirm_active_case_and_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-api-workspace"
    root.mkdir()
    first = RunningVarta(root)
    try:
        body, content_type = _multipart(
            "synthetic-c07.txt",
            "Синтетичні API bytes".encode("utf-8"),
        )
        status, intake = first.request(
            "POST",
            "/api/v1/intake",
            body=body,
            headers={
                "Content-Type": content_type,
                "Idempotency-Key": "c07-api-synthetic-001",
                "X-Caseflow-Token": first.state.csrf_token,
            },
        )
        assert status == 201
        batch = intake["batch"]
        assert isinstance(batch, dict)
        entry = batch["entries"][0]
        assert isinstance(entry, dict)
        intake_case_id = str(entry["intakeCaseId"])
        file_id = str(entry["fileId"])
        assert entry["bootstrapStatus"] == "manual_review_required"

        status, pending = first.request("GET", "/api/v1/workspace/bootstrap-reviews")
        assert status == 200
        assert pending["authority"] == "sqlite"
        assert pending["count"] == 1
        zero_review = pending["reviews"][0]
        assert isinstance(zero_review, dict)
        assert zero_review["distinctCandidateCount"] == 0
        assert zero_review["manualConfirmationRequired"] is True

        status, proposed = first.json_command(
            f"/api/v1/workspace/bootstrap-reviews/{intake_case_id}/candidates",
            {
                "actorId": "system:synthetic-api-detector",
                "sources": [
                    {
                        "text": "Синтетичний документ у справі № 999/9100/99.",
                        "detectionSource": "document_text",
                        "sourceLocation": "page:1/paragraph:api-synthetic",
                        "evidenceBasis": "synthetic API extracted span",
                        "confidence": 0.95,
                        "tool": {
                            "name": "varta-synthetic-api-detector",
                            "version": "1.0-test",
                        },
                    }
                ],
            },
        )
        assert status == 200
        review = proposed["review"]
        assert isinstance(review, dict)
        assert review["status"] == "candidate_ready"
        assert review["distinctCandidateCount"] == 1
        candidates = review["candidates"]
        assert isinstance(candidates, list)
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        assert candidate["normalizedValue"] == "999/9100/99"
        assert candidate["tool"] == {
            "name": "varta-synthetic-api-detector",
            "version": "1.0-test",
        }

        status, confirmed = first.json_command(
            f"/api/v1/workspace/bootstrap-reviews/{intake_case_id}/confirm",
            {
                "actorId": "user:synthetic-api-reviewer",
                "candidateId": candidate["candidateId"],
                "createCaseName": "Синтетична API справа",
                "note": "Explicit synthetic confirmation",
            },
        )
        assert status == 200
        confirmed_review = confirmed["review"]
        assert isinstance(confirmed_review, dict)
        case_id = str(confirmed_review["confirmedCaseId"])
        assert confirmed_review["status"] == "confirmed"

        status, cases_response = first.request("GET", "/api/v1/workspace/cases")
        assert status == 200
        assert cases_response["authority"] == "sqlite"
        assert cases_response["count"] == 1
        case = cases_response["cases"][0]
        assert isinstance(case, dict)
        assert case["caseId"] == case_id
        assert case["fileIds"] == [file_id]

        status, selected = first.json_command(
            "/api/v1/workspace/active-case",
            {
                "preferenceId": "browser-session-api-synthetic",
                "actorId": "user:synthetic-api-reviewer",
                "activeCaseId": case_id,
            },
        )
        assert status == 200
        active = selected["activeCase"]
        assert isinstance(active, dict)
        assert active["scope"] == "presentation_preference"
        assert active["activeCase"]["caseId"] == case_id  # type: ignore[index]

        status, invalid = first.json_command(
            "/api/v1/workspace/cases",
            {
                "actorId": "user:synthetic-api-reviewer",
                "name": "Синтетична справа",
                "unknownField": True,
            },
        )
        assert status == 422
        assert invalid["error"]["code"] == "request_validation_error"  # type: ignore[index]
    finally:
        first.close()

    second = RunningVarta(root)
    try:
        status, pending = second.request("GET", "/api/v1/workspace/bootstrap-reviews")
        assert status == 200
        assert pending["count"] == 0
        status, active_response = second.request(
            "GET",
            "/api/v1/workspace/active-case?preferenceId=browser-session-api-synthetic",
        )
        assert status == 200
        active = active_response["activeCase"]
        assert isinstance(active, dict)
        assert active["activeCase"]["caseId"] == case_id  # type: ignore[index]
    finally:
        second.close()
        _restore_original_permissions(root)
