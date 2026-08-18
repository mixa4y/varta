from __future__ import annotations

import http.client
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from case_docket.repository import SQLiteRepository
from caseflow.server import CaseFlowState, Handler, ThreadingHTTPServer


class RunningVarta:
    def __init__(self, root: Path):
        self.root = root
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = int(self.server.server_address[1])
        self.state = CaseFlowState(root, "127.0.0.1", port)
        self.state.prepare_database()
        self.server.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = port

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.state.close()

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        *,
        csrf: bool = False,
    ) -> tuple[int, dict[str, object]]:
        headers: dict[str, str] = {}
        body: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if csrf:
            headers["X-Caseflow-Token"] = self.state.csrf_token
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            decoded = json.loads(response.read().decode("utf-8"))
            return response.status, decoded
        finally:
            connection.close()


def test_api_v1_status_success_and_contacts_crud(tmp_path: Path) -> None:
    running = RunningVarta(tmp_path)
    try:
        status, status_body = running.request("GET", "/api/v1/status")
        assert status == 200
        assert status_body["apiVersion"] == "v1"
        assert status_body["server"] == {"product": "VARTA", "version": "0.1.0"}

        status, created = running.request(
            "POST",
            "/api/v1/contacts",
            {
                "full_name": "Синтетична Особа",
                "participant_type": "person",
                "email": "contact@example.invalid",
            },
            csrf=True,
        )
        assert status == 201
        assert created["apiVersion"] == "v1"
        contact = created["contact"]
        assert isinstance(contact, dict)
        contact_id = str(contact["id"])

        status, updated = running.request(
            "PATCH",
            f"/api/v1/contacts/{contact_id}",
            {"short_name": "Синтетичний контакт"},
            csrf=True,
        )
        assert status == 200
        assert updated["contact"]["short_name"] == "Синтетичний контакт"  # type: ignore[index]

        status, listed = running.request("GET", "/api/v1/contacts?q=example.invalid")
        assert status == 200
        assert listed["count"] == 1
        assert listed["contacts"][0]["id"] == contact_id  # type: ignore[index]
    finally:
        running.close()


def test_fresh_server_boot_allows_parallel_status_and_contacts_context(tmp_path: Path) -> None:
    running = RunningVarta(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            status_future = executor.submit(running.request, "GET", "/api/status")
            context_future = executor.submit(running.request, "GET", "/api/v1/contacts/context")
            status_result = status_future.result(timeout=15)
            context_result = context_future.result(timeout=15)

        assert status_result[0] == 200
        assert context_result[0] == 200
        assert context_result[1]["apiVersion"] == "v1"
        assert isinstance(context_result[1]["roles"], list)
    finally:
        running.close()


def test_api_v1_separates_request_and_domain_validation(tmp_path: Path) -> None:
    running = RunningVarta(tmp_path)
    try:
        status, request_error = running.request(
            "POST",
            "/api/v1/contacts",
            {"participant_type": "person"},
            csrf=True,
        )
        assert status == 422
        assert request_error["error"]["code"] == "request_validation_error"  # type: ignore[index]
        assert request_error["error"]["details"] == {"field": "full_name"}  # type: ignore[index]

        status, domain_error = running.request(
            "POST",
            "/api/v1/contacts",
            {
                "full_name": "Синтетична Особа",
                "participant_type": "person",
                "email": "invalid-email",
            },
            csrf=True,
        )
        assert status == 422
        assert domain_error["error"]["code"] == "validation_error"  # type: ignore[index]
        assert "invalid-email" not in json.dumps(domain_error, ensure_ascii=False)
    finally:
        running.close()


def test_api_v1_not_found_and_unknown_route_envelopes(tmp_path: Path) -> None:
    running = RunningVarta(tmp_path)
    try:
        status, missing = running.request("GET", "/api/v1/contacts/missing-contact")
        assert status == 404
        assert missing["error"]["code"] == "not_found"  # type: ignore[index]

        status, route = running.request("GET", "/api/v1/unknown")
        assert status == 404
        assert route["error"]["code"] == "route_not_found"  # type: ignore[index]
    finally:
        running.close()


def test_api_v1_duplicate_role_returns_conflict(tmp_path: Path) -> None:
    database = tmp_path / ".caseflow" / "varta.sqlite3"
    database.parent.mkdir(parents=True)
    repository = SQLiteRepository(database)
    repository.insert(
        "cases",
        {"id": "case-synthetic", "case_number": "SYNTHETIC-CASE", "name": "Синтетична справа"},
    )
    repository.insert(
        "proceedings",
        {
            "id": "proceeding-synthetic",
            "proceeding_number": "SYNTHETIC-PROCEEDING",
            "name": "Синтетичне провадження",
        },
    )
    repository.close()

    running = RunningVarta(tmp_path)
    try:
        _, created = running.request(
            "POST",
            "/api/v1/contacts",
            {"full_name": "Синтетична Особа", "participant_type": "person"},
            csrf=True,
        )
        contact_id = created["contact"]["id"]  # type: ignore[index]
        role = {
            "case_id": "case-synthetic",
            "proceeding_id": "proceeding-synthetic",
            "role": "Синтетична роль",
        }
        first_status, _ = running.request(
            "POST",
            f"/api/v1/contacts/{contact_id}/roles",
            role,
            csrf=True,
        )
        second_status, conflict = running.request(
            "POST",
            f"/api/v1/contacts/{contact_id}/roles",
            role,
            csrf=True,
        )

        assert first_status == 201
        assert second_status == 409
        assert conflict["error"]["code"] == "conflict"  # type: ignore[index]
    finally:
        running.close()


def test_legacy_contacts_adapter_and_restart_persistence(tmp_path: Path) -> None:
    first = RunningVarta(tmp_path)
    try:
        status, created = first.request(
            "POST",
            "/api/contacts",
            {
                "full_name": "Синтетична Особа",
                "participant_type": "person",
                "email": "contact@example.invalid",
            },
            csrf=True,
        )
        assert status == 201
        assert "apiVersion" not in created
        contact_id = created["contact"]["id"]  # type: ignore[index]
    finally:
        first.close()

    second = RunningVarta(tmp_path)
    try:
        status, fetched = second.request("GET", f"/api/v1/contacts/{contact_id}")
        assert status == 200
        assert fetched["contact"]["email"] == "contact@example.invalid"  # type: ignore[index]

        legacy_status, legacy = second.request("GET", "/api/contacts")
        assert legacy_status == 200
        assert "apiVersion" not in legacy
        assert legacy["count"] == 1
    finally:
        second.close()
